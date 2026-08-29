"""Signal correlation, deduplication, and autonomous incident creation engine."""

import hashlib
import json
import uuid
import re
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text, and_

from app.models.incident import (
    Incident, TelemetrySignal, AlertRuleConfig, ActiveIncidentCorrelationClaim,
    Service, Environment, Region, RepositoryScope, ServiceRepository,
    IncidentStatus, IncidentSeverity, IncidentSource, SignalProvider, SignalType, SignalStatus,
    AuditEvent, Deployment,
)
from app.services.detection_rules import (
    evaluate_all_rules, TriggeredRuleResult, RULE_REGISTRY, SIGNAL_TYPE_TO_RULE
)
from app.services.deployment_service import get_deployments_in_window
from app.services.task_queue import submit_task
from app.services.blast_radius_service import calculate_blast_radius, enqueue_blast_radius_recalculation
import asyncio


SENSITIVE_KEYS = {
    "authorization", "cookie", "token", "secret", "password",
    "api_key", "access_token", "private_key", "client_secret",
    "x-sentinel-signature", "x-hub-signature-256", "sentry-hook-signature",
}

MAX_RAW_PAYLOAD_BYTES = 32 * 1024  # 32 KB


def sanitize_payload(payload: Any) -> Any:
    """Recursively redact sensitive credentials and truncate large values."""
    if isinstance(payload, dict):
        sanitized = {}
        for k, v in payload.items():
            if any(sens in k.lower() for sens in SENSITIVE_KEYS):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_payload(v)
        return sanitized
    elif isinstance(payload, list):
        return [sanitize_payload(x) for x in payload[:100]]  # limit list items
    elif isinstance(payload, str):
        if len(payload) > 1000:
            return payload[:1000] + "... [truncated]"
        return payload
    return payload


def compute_signal_fingerprint(
    provider: str,
    signal_type: str,
    service_id: Optional[uuid.UUID],
    environment_id: Optional[uuid.UUID],
    region_id: Optional[uuid.UUID],
    error_signature: Optional[str],
) -> str:
    """Compute deterministic fingerprint hash for a signal."""
    parts = [
        str(provider).lower().strip(),
        str(signal_type).lower().strip(),
        str(service_id or "none"),
        str(environment_id or "none"),
        str(region_id or "none"),
        str(error_signature or "none").lower().strip(),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def compute_correlation_key(
    organization_id: uuid.UUID,
    service_id: Optional[uuid.UUID],
    environment_id: Optional[uuid.UUID],
    region_id: Optional[uuid.UUID],
    signal_class: str,
    error_signature: Optional[str] = None,
) -> str:
    """Compute correlation key for clustering related signals."""
    parts = [
        str(organization_id),
        str(service_id or "global"),
        str(environment_id or "global"),
        str(region_id or "global"),
        str(signal_class).lower().strip(),
        str(error_signature or "general").lower().strip(),
    ]
    return ":".join(parts)


def severity_to_order(sev: str) -> int:
    mapping = {"SEV-1": 1, "SEV-2": 2, "SEV-3": 3, "SEV-4": 4}
    return mapping.get(sev, 3)


def get_highest_severity(sev1: str, sev2: str) -> str:
    return sev1 if severity_to_order(sev1) <= severity_to_order(sev2) else sev2


def resolve_incident_severity(sev_str: str) -> IncidentSeverity:
    mapping = {
        "SEV-1": IncidentSeverity.SEV1,
        "SEV-2": IncidentSeverity.SEV2,
        "SEV-3": IncidentSeverity.SEV3,
        "SEV-4": IncidentSeverity.SEV4,
    }
    return mapping.get(sev_str, IncidentSeverity.SEV2)


def process_telemetry_signal(
    db: Session,
    organization_id: uuid.UUID,
    provider: SignalProvider,
    provider_event_id: str,
    signal_type: SignalType,
    service: Optional[Service],
    environment: Optional[Environment],
    region: Optional[Region],
    metric_name: Optional[str],
    metric_value: Optional[float],
    threshold_value: Optional[float],
    title: str,
    description: Optional[str] = None,
    error_signature: Optional[str] = None,
    raw_payload: Optional[Dict[str, Any]] = None,
    observed_at: Optional[datetime] = None,
) -> Tuple[TelemetrySignal, Optional[Incident], bool]:
    """
    Core pipeline:
    1. Idempotency check.
    2. Payload sanitization.
    3. Detection rule evaluation & threshold overrides.
    4. Production scoping.
    5. Deployment regression correlation.
    6. Concurrency-safe incident deduplication & claim management.
    7. Autonomous incident creation & background task dispatch.
    """
    observed_at = observed_at or datetime.now(timezone.utc)
    service_id = service.id if service else None
    service_name = service.name if service else "unknown"
    environment_id = environment.id if environment else None
    environment_name = environment.name if environment else "unknown"
    region_id = region.id if region else None

    # 1. Delivery Idempotency Check
    existing_signal = db.query(TelemetrySignal).filter(
        TelemetrySignal.organization_id == organization_id,
        TelemetrySignal.provider == provider,
        TelemetrySignal.provider_event_id == provider_event_id,
    ).first()
    if existing_signal:
        incident = existing_signal.incident
        return existing_signal, incident, False

    # 2. Sanitize Raw Payload
    sanitized_raw = sanitize_payload(raw_payload) if raw_payload else None

    # 3. Load Org AlertRuleConfigs
    org_rules = db.query(AlertRuleConfig).filter(
        AlertRuleConfig.organization_id == organization_id
    ).all()
    custom_thresholds = {r.rule_name: r.threshold_value for r in org_rules if r.threshold_value is not None}
    enabled_rules = {r.rule_name: r.is_enabled for r in org_rules}

    # 4. Check Recent Deployments (Incident Window Correlation)
    recent_deployments: List[Deployment] = []
    if service_id and environment_id:
        window_start = observed_at - timedelta(minutes=30)
        recent_deployments = get_deployments_in_window(
            db=db,
            org_id=organization_id,
            service_id=service_id,
            environment_id=environment_id,
            window_start=window_start,
            window_end=observed_at,
            region_id=region_id,
        )

    has_recent_deploy = len(recent_deployments) > 0
    latest_deploy = recent_deployments[0] if has_recent_deploy else None

    # 5. Build Evaluation Context & Evaluate 12 Detection Rules
    eval_context = {
        "service_name": service_name,
        "environment_name": environment_name,
        "metric_name": metric_name,
        "metric_value": metric_value,
        "value": metric_value,
        "error_rate": metric_value if signal_type == SignalType.ERROR_RATE else None,
        "p99_latency_ms": metric_value if signal_type == SignalType.LATENCY_SPIKE else None,
        "cpu_usage_pct": metric_value if signal_type == SignalType.CPU_THRESHOLD else None,
        "memory_usage_pct": metric_value if signal_type == SignalType.MEMORY_THRESHOLD else None,
        "disk_usage_pct": metric_value if signal_type == SignalType.DISK_THRESHOLD else None,
        "queue_lag": metric_value if signal_type == SignalType.QUEUE_BACKLOG else None,
        "db_connection_pool_pct": metric_value if signal_type == SignalType.DATABASE_SATURATION else None,
        "consecutive_failures": metric_value if signal_type == SignalType.HEALTH_CHECK_FAILURE else None,
        "restart_count": metric_value if signal_type == SignalType.CRASH_LOOP else None,
        "restart_spike_count": metric_value if signal_type == SignalType.RESTART_SPIKE else None,
        "exception_count": metric_value if signal_type == SignalType.REPEATED_EXCEPTION else None,
        "exception_type": error_signature,
        "error_signature": error_signature,
        "description": description,
        "is_deployment_regression": has_recent_deploy and (signal_type in (SignalType.ERROR_RATE, SignalType.LATENCY_SPIKE, SignalType.HEALTH_CHECK_FAILURE)),
        "recent_deployment_commit": latest_deploy.commit_sha if latest_deploy else None,
        "recent_deployment_version": latest_deploy.version if latest_deploy else None,
    }

    triggered_rules = evaluate_all_rules(
        eval_context,
        custom_thresholds=custom_thresholds,
        enabled_rules=enabled_rules,
    )

    # Determine matched rule
    matched_rule = triggered_rules[0] if triggered_rules else None
    fallback_rule = SIGNAL_TYPE_TO_RULE.get(signal_type)
    rule_name = matched_rule.rule_name if matched_rule else (fallback_rule.rule_name if fallback_rule else "error_rate")
    resolved_severity = matched_rule.severity if matched_rule else "SEV-2"
    effective_error_sig = error_signature or (matched_rule.error_signature if matched_rule else f"{signal_type.value.lower()}:{service_name}")

    # Compute Fingerprint & Correlation Key
    fingerprint = compute_signal_fingerprint(
        provider.value, signal_type.value, service_id, environment_id, region_id, effective_error_sig
    )
    correlation_key = compute_correlation_key(
        organization_id, service_id, environment_id, region_id, signal_type.value, effective_error_sig
    )

    # 6. Production Scoping: If not production, record signal as SUPPRESSED_NON_PROD
    is_prod = False
    if environment:
        is_prod = (environment.env_type == "production" or environment.name.lower() == "production")

    if not is_prod:
        sig = TelemetrySignal(
            organization_id=organization_id,
            provider=provider,
            provider_event_id=provider_event_id,
            signal_type=signal_type,
            rule_name=rule_name,
            service_id=service_id,
            environment_id=environment_id,
            region_id=region_id,
            metric_name=metric_name,
            metric_value=metric_value,
            threshold_value=threshold_value or (matched_rule.threshold_value if matched_rule else None),
            fingerprint=fingerprint,
            correlation_key=correlation_key,
            title=title,
            description=description,
            error_signature=effective_error_sig,
            raw_payload=sanitized_raw,
            status=SignalStatus.SUPPRESSED_NON_PROD,
            observed_at=observed_at,
        )
        db.add(sig)
        db.commit()
        db.refresh(sig)
        return sig, None, False

    # 7. Check for Active Correlation Claim & Existing Incident within 30m
    cutoff = observed_at - timedelta(minutes=30)
    existing_claim = db.query(ActiveIncidentCorrelationClaim).filter(
        ActiveIncidentCorrelationClaim.organization_id == organization_id,
        ActiveIncidentCorrelationClaim.correlation_key == correlation_key,
    ).first()

    target_incident: Optional[Incident] = None
    if existing_claim:
        # Load active incident with row-level lock
        target_incident = db.query(Incident).filter(
            Incident.id == existing_claim.incident_id,
            Incident.status.notin_([IncidentStatus.RESOLVED, IncidentStatus.CANCELLED]),
        ).with_for_update().first()

    if not target_incident:
        # Fallback check on open incidents for this service and environment
        if service_id and environment_id:
            target_incident = db.query(Incident).filter(
                Incident.organization_id == organization_id,
                Incident.service_id == service_id,
                Incident.environment_id == environment_id,
                Incident.created_at >= cutoff,
                Incident.status.notin_([IncidentStatus.RESOLVED, IncidentStatus.CANCELLED]),
            ).with_for_update().first()

    # 8. Merge into Existing Incident (Deduplication)
    if target_incident:
        # Create signal row attached to incident
        sig = TelemetrySignal(
            organization_id=organization_id,
            provider=provider,
            provider_event_id=provider_event_id,
            signal_type=signal_type,
            rule_name=rule_name,
            service_id=service_id,
            environment_id=environment_id,
            region_id=region_id,
            metric_name=metric_name,
            metric_value=metric_value,
            threshold_value=threshold_value or (matched_rule.threshold_value if matched_rule else None),
            fingerprint=fingerprint,
            correlation_key=correlation_key,
            title=title,
            description=description,
            error_signature=effective_error_sig,
            raw_payload=sanitized_raw,
            status=SignalStatus.CORRELATED,
            incident_id=target_incident.id,
            observed_at=observed_at,
        )
        db.add(sig)

        # Atomic updates on incident
        target_incident.signal_count = (target_incident.signal_count or 0) + 1
        target_incident.last_signal_at = observed_at
        current_sev = target_incident.severity.value if target_incident.severity else "SEV-3"
        highest_sev = get_highest_severity(current_sev, resolved_severity)
        target_incident.severity = resolve_incident_severity(highest_sev)

        db.commit()
        db.refresh(sig)
        db.refresh(target_incident)
        try:
            enqueue_blast_radius_recalculation(db, target_incident.id)
        except Exception:
            pass
        return sig, target_incident, False

    # 9. Create New Auto-Detected Incident
    # Get sequential incident number
    try:
        next_number = db.execute(text("SELECT nextval('incident_number_seq')")).scalar()
    except Exception:
        db.rollback()
        max_num = db.execute(text("SELECT COALESCE(MAX(number), 0) FROM incidents")).scalar() or 0
        try:
            db.execute(text(f"CREATE SEQUENCE IF NOT EXISTS incident_number_seq START WITH {max_num + 1}"))
            db.flush()
            next_number = db.execute(text("SELECT nextval('incident_number_seq')")).scalar()
        except Exception:
            next_number = max_num + 1

    incident_title = f"Auto-detected: {title}"
    incident = Incident(
        number=next_number,
        title=incident_title,
        description=description or f"Autonomous anomaly detection triggered rule '{rule_name}' on {service_name}.",
        severity=resolve_incident_severity(resolved_severity),
        status=IncidentStatus.DETECTED,
        source=IncidentSource.AUTO_DETECTION if provider != SignalProvider.HEALTH_CHECK else IncidentSource.HEALTH_CHECK,
        organization_id=organization_id,
        service_id=service_id,
        service_name=service_name,
        environment_id=environment_id,
        region_id=region_id,
        deployment_id=latest_deploy.id if latest_deploy else None,
        error_signature=effective_error_sig,
        signal_count=1,
        first_signal_at=observed_at,
        last_signal_at=observed_at,
        detected_at=observed_at,
        started_at=observed_at,
    )
    db.add(incident)
    db.flush()

    # Link Primary Service Repository Scopes
    if service_id:
        sr_list = db.query(ServiceRepository).filter(
            ServiceRepository.service_id == service_id
        ).all()
        for sr in sr_list:
            scope = RepositoryScope(
                incident_id=incident.id,
                repository_id=sr.repository_id,
            )
            db.add(scope)

    # Create Claim for Race Protection
    claim = ActiveIncidentCorrelationClaim(
        organization_id=organization_id,
        correlation_key=correlation_key,
        incident_id=incident.id,
    )
    db.add(claim)

    # Create Signal Record
    sig = TelemetrySignal(
        organization_id=organization_id,
        provider=provider,
        provider_event_id=provider_event_id,
        signal_type=signal_type,
        rule_name=rule_name,
        service_id=service_id,
        environment_id=environment_id,
        region_id=region_id,
        metric_name=metric_name,
        metric_value=metric_value,
        threshold_value=threshold_value or (matched_rule.threshold_value if matched_rule else None),
        fingerprint=fingerprint,
        correlation_key=correlation_key,
        title=title,
        description=description,
        error_signature=effective_error_sig,
        raw_payload=sanitized_raw,
        status=SignalStatus.TRIGGERED_INCIDENT,
        incident_id=incident.id,
        observed_at=observed_at,
    )
    db.add(sig)

    # Record Audit Event
    audit = AuditEvent(
        incident_id=incident.id,
        event_type="incident_auto_created",
        description=f"Incident auto-created from {provider.value} signal: {title}",
        metadata_json={
            "provider": provider.value,
            "rule_name": rule_name,
            "signal_type": signal_type.value,
            "metric_value": metric_value,
            "deployment_id": str(latest_deploy.id) if latest_deploy else None,
        },
    )
    db.add(audit)

    db.commit()
    db.refresh(incident)
    # 10. Initial Blast Radius & Change Correlation Calculation
    if service:
        try:
            calculate_blast_radius(
                db=db,
                organization_id=organization_id,
                root_service=service,
                incident=incident,
                environment=environment,
            )
        except Exception as e:
            logger.warning(f"Initial blast radius calculation skipped: {e}")

    try:
        from app.services.change_correlation_service import correlate_incident_changes
        correlate_incident_changes(db, organization_id, incident.id, lookback_window_minutes=120)
    except Exception as e:
        logger.warning(f"Initial change correlation skipped: {e}")

    # 11. Enqueue Investigation Task with Idempotency Key
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(submit_task(
            task_type="investigation",
            payload={"incident_id": str(incident.id)},
            idempotency_key=f"investigate_incident:{incident.id}",
        ))
    except RuntimeError:
        pass
    except Exception:
        pass

    return sig, incident, True


def handle_alertmanager_resolution(
    db: Session,
    organization_id: uuid.UUID,
    alert_fingerprint: str,
    service: Optional[Service],
    environment: Optional[Environment],
) -> Optional[Incident]:
    """
    Handle Alertmanager 'resolved' alert status.
    Locates firing signals by alert fingerprint and resolves incident if all alerts have cleared.
    """
    service_id = service.id if service else None
    environment_id = environment.id if environment else None

    # Find active signals with matching fingerprint or service/env
    signals = db.query(TelemetrySignal).filter(
        TelemetrySignal.organization_id == organization_id,
        TelemetrySignal.fingerprint == alert_fingerprint,
        TelemetrySignal.incident_id.isnot(None),
    ).all()

    if not signals and service_id and environment_id:
        signals = db.query(TelemetrySignal).filter(
            TelemetrySignal.organization_id == organization_id,
            TelemetrySignal.service_id == service_id,
            TelemetrySignal.environment_id == environment_id,
            TelemetrySignal.incident_id.isnot(None),
        ).all()

    if not signals:
        return None

    incident_id = signals[-1].incident_id
    incident = db.query(Incident).filter(
        Incident.id == incident_id,
        Incident.status.notin_([IncidentStatus.RESOLVED, IncidentStatus.CANCELLED]),
    ).first()

    if not incident:
        return None

    # Transition Incident to RESOLVED
    incident.status = IncidentStatus.RESOLVED
    incident.resolved_at = datetime.now(timezone.utc)

    # Delete Correlation Claim
    db.query(ActiveIncidentCorrelationClaim).filter(
        ActiveIncidentCorrelationClaim.incident_id == incident.id
    ).delete()

    # Record Audit Event
    audit = AuditEvent(
        incident_id=incident.id,
        event_type="incident_auto_resolved",
        description=f"Incident auto-resolved by Alertmanager resolution event (fingerprint: {alert_fingerprint})",
    )
    db.add(audit)
    db.commit()
    db.refresh(incident)
    return incident
