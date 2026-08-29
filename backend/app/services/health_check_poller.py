"""Background health check probe daemon with distributed lease locking and SSRF protection."""

import asyncio
import logging
import uuid
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import SessionLocal
from app.models.incident import (
    ServiceDeploymentConfig, HealthCheckLog, SignalProvider, SignalType
)
from app.core.ssrf_client import execute_safe_health_check
from app.services.signal_correlation_service import process_telemetry_signal

logger = logging.getLogger("sentinel.health_check_poller")

POLLER_INTERVAL_SECONDS = 30
LEASE_DURATION_SECONDS = 60
CONSECUTIVE_FAILURE_THRESHOLD = 3

_poller_task: Optional[asyncio.Task] = None
_poller_running: bool = False


async def probe_single_config(db: Session, config_id: uuid.UUID) -> Optional[HealthCheckLog]:
    """
    Execute a health probe against a single ServiceDeploymentConfig, update persistent state,
    and trigger a telemetry signal if consecutive failure threshold is breached.
    """
    config = db.query(ServiceDeploymentConfig).filter(
        ServiceDeploymentConfig.id == config_id
    ).first()
    if not config or not config.health_check_url or not config.is_active:
        return None

    url = config.health_check_url.strip()
    is_healthy, status_code, latency_ms, error_msg = await execute_safe_health_check(url)

    now = datetime.now(timezone.utc)
    config.last_probed_at = now
    config.last_probe_status_code = status_code
    config.last_probe_latency_ms = latency_ms
    config.last_probe_is_healthy = is_healthy
    config.last_probe_error = error_msg

    if is_healthy:
        config.consecutive_failures = 0
    else:
        config.consecutive_failures = (config.consecutive_failures or 0) + 1

    # Record historical log
    log = HealthCheckLog(
        organization_id=config.organization_id,
        config_id=config.id,
        service_id=config.service_id,
        environment_id=config.environment_id,
        region_id=config.region_id,
        url=url,
        status_code=status_code,
        latency_ms=latency_ms,
        is_healthy=is_healthy,
        error_message=error_msg,
        probed_at=now,
    )
    db.add(log)
    db.commit()
    db.refresh(config)

    # If threshold breached, feed synthetic signal to correlation service
    if not is_healthy and config.consecutive_failures >= CONSECUTIVE_FAILURE_THRESHOLD:
        event_id = f"health-check:{config.id}:{int(now.timestamp())}"
        service = config.service
        environment = config.environment
        region = config.region

        try:
            process_telemetry_signal(
                db=db,
                organization_id=config.organization_id,
                provider=SignalProvider.HEALTH_CHECK,
                provider_event_id=event_id,
                signal_type=SignalType.HEALTH_CHECK_FAILURE,
                service=service,
                environment=environment,
                region=region,
                metric_name="consecutive_probe_failures",
                metric_value=float(config.consecutive_failures),
                threshold_value=float(CONSECUTIVE_FAILURE_THRESHOLD),
                title=f"Health probe failing ({config.consecutive_failures} consecutive failures) on {service.name if service else 'service'}",
                description=f"Health check probe to {url} failed: {error_msg or f'HTTP {status_code}'}",
                error_signature=f"health_check_down:{service.name if service else 'service'}",
                raw_payload={
                    "url": url,
                    "status_code": status_code,
                    "latency_ms": latency_ms,
                    "consecutive_failures": config.consecutive_failures,
                    "error": error_msg,
                },
                observed_at=now,
            )
        except Exception as e:
            logger.error(f"Error processing health check failure signal for config {config.id}: {e}")

    return log


def acquire_poller_batch(db: Session, batch_size: int = 25) -> List[uuid.UUID]:
    """
    Acquire a batch of active deployment configs to probe using distributed lease locking.
    PostgreSQL uses FOR UPDATE SKIP LOCKED; SQLite uses standard transaction locking.
    """
    now = datetime.now(timezone.utc)
    lease_expiration = now + timedelta(seconds=LEASE_DURATION_SECONDS)
    dialect = db.bind.dialect.name if db.bind else "sqlite"

    if dialect == "postgresql":
        stmt = text("""
            SELECT id FROM service_deployment_configs
            WHERE is_active = true
              AND health_check_url IS NOT NULL
              AND health_check_url != ''
              AND (poller_lease_until IS NULL OR poller_lease_until < :now)
            ORDER BY last_probed_at ASC NULLS FIRST
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
        """)
        rows = db.execute(stmt, {"now": now, "limit": batch_size}).fetchall()
        config_ids = [r[0] for r in rows]
    else:
        # SQLite fallback
        configs = db.query(ServiceDeploymentConfig).filter(
            ServiceDeploymentConfig.is_active == True,
            ServiceDeploymentConfig.health_check_url.isnot(None),
            ServiceDeploymentConfig.health_check_url != "",
            (ServiceDeploymentConfig.poller_lease_until.is_(None) | (ServiceDeploymentConfig.poller_lease_until < now)),
        ).order_by(ServiceDeploymentConfig.last_probed_at.asc()).limit(batch_size).all()
        config_ids = [c.id for c in configs]

    if config_ids:
        db.query(ServiceDeploymentConfig).filter(
            ServiceDeploymentConfig.id.in_(config_ids)
        ).update(
            {"poller_lease_until": lease_expiration},
            synchronize_session=False,
        )
        db.commit()

    return config_ids


async def run_poller_cycle():
    """Execute one round of polling across all eligible configurations."""
    db = SessionLocal()
    try:
        config_ids = acquire_poller_batch(db, batch_size=25)
        if not config_ids:
            return

        tasks = [probe_single_config(db, cid) for cid in config_ids]
        await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.error(f"Error in health check poller cycle: {e}")
    finally:
        db.close()


async def poller_loop():
    """Main background loop."""
    global _poller_running
    logger.info("Starting Sentinel Autonomous Health-Check Poller daemon...")
    while _poller_running:
        try:
            await run_poller_cycle()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Unhandled exception in health poller loop: {e}")
        await asyncio.sleep(POLLER_INTERVAL_SECONDS)
    logger.info("Sentinel Health-Check Poller daemon stopped.")


def start_health_check_poller() -> Optional[asyncio.Task]:
    """Start the poller background task if not already running."""
    global _poller_task, _poller_running
    if _poller_running and _poller_task and not _poller_task.done():
        return _poller_task

    _poller_running = True
    try:
        loop = asyncio.get_running_loop()
        _poller_task = loop.create_task(poller_loop())
        return _poller_task
    except RuntimeError:
        # Loop not running yet
        return None


def stop_health_check_poller():
    """Gracefully cancel and stop the health check poller."""
    global _poller_task, _poller_running
    _poller_running = False
    if _poller_task and not _poller_task.done():
        _poller_task.cancel()


if __name__ == "__main__":
    # Standalone container / worker runner
    logging.basicConfig(level=logging.INFO)
    asyncio.run(poller_loop())
