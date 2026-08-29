from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import os
import logging

logger = logging.getLogger("sentinel.startup")

from app.core.database import engine, Base
from app.core.config import settings
from app.core.rate_limit import limiter
from app.routes import auth_router, incidents_router, repositories_router, health_router, investigations_router, github_router
from app.routes.investigation_engine import router as engine_router
from app.routes.indexing import router as indexing_router
from app.routes.webhooks import router as webhooks_router
from app.routes.health_monitor import router as health_monitor_router
from app.routes.auto_detect import router as auto_detect_router
from app.routes.remediation import router as remediation_router
from app.routes.approvals import router as approvals_router
from app.routes.websocket import router as ws_router
from app.routes.metrics import router as metrics_router
from app.routes.system import router as system_router
from app.routes.chat import router as chat_router
from app.routes.tasks import router as tasks_router
from app.routes.work_items import router as work_items_router
from app.routes.catalog import router as catalog_router
from app.routes.deployments import router as deployments_router
from app.routes.monitoring import router as monitoring_router
from app.routes.graph import router as graph_router
from app.routes.changes import router as changes_router
from app.routes.evidence import router as evidence_router
from app.routes.incident_memory import router as incident_memory_router
from app.routes.policies import router as policies_router
from app.routes.multi_repo import router as multi_repo_router
from app.routes.command_center import router as command_center_router
from app.routes.reliability import reliability_router
from app.routes.security_incidents import security_incident_router
from app.services.task_queue import start_workers





from app.services.health_check_poller import start_health_check_poller, stop_health_check_poller
from app.core.config import settings

# Database tables are created/migrated via Alembic / startup event

app = FastAPI(
    title="Sentinel API",
    description="AI Incident Response Agent — Backend",
    version="0.1.0",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — allow frontend origins
frontend_url = settings.FRONTEND_URL.rstrip("/")
extra_origins = [o.strip().rstrip("/") for o in settings.CORS_ORIGINS.split(",") if o.strip()]
allowed_origins = list({frontend_url, "http://localhost:3000", "http://127.0.0.1:3000", *extra_origins})

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    # OPTIONS is required for browser CORS preflight requests.  Without it,
    # authenticated POSTs such as registration are rejected before routing.
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Sentinel-Key-ID", "X-Sentinel-Signature", "X-Sentinel-Timestamp", "Sentry-Hook-Signature"],
)

# Routes
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(incidents_router)
app.include_router(repositories_router)
app.include_router(investigations_router)
app.include_router(github_router)
app.include_router(engine_router)
app.include_router(indexing_router)
app.include_router(webhooks_router)
app.include_router(health_monitor_router)
app.include_router(auto_detect_router)
app.include_router(remediation_router)
app.include_router(approvals_router)
app.include_router(ws_router)
app.include_router(metrics_router)
app.include_router(system_router)
app.include_router(chat_router)
app.include_router(tasks_router)
app.include_router(work_items_router)
app.include_router(catalog_router)
app.include_router(deployments_router)
app.include_router(monitoring_router)
app.include_router(graph_router)
app.include_router(changes_router)
app.include_router(evidence_router)
app.include_router(incident_memory_router)
app.include_router(policies_router)
app.include_router(multi_repo_router)
app.include_router(command_center_router)
app.include_router(reliability_router)
app.include_router(security_incident_router)







@app.on_event("startup")
async def startup_event():
    # Never use the pytest runner's environment variable as a security or
    # lifecycle switch: it is caller-controlled and can be present in a
    # deployed process. Tests must explicitly select ENVIRONMENT=testing.
    is_testing = settings.ENVIRONMENT.lower() == "testing"
    if is_testing:
        return

    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            if engine.dialect.name == "postgresql":
                conn.execute(text("ALTER TYPE membershiprole ADD VALUE IF NOT EXISTS 'OPERATOR'"))
                conn.commit()
                conn.execute(text("ALTER TABLE repositories ADD COLUMN IF NOT EXISTS sync_status VARCHAR(50) DEFAULT 'pending'"))
                conn.execute(text("ALTER TABLE repositories ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMP WITH TIME ZONE"))
                conn.execute(text("ALTER TABLE repositories ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE"))
                conn.execute(text("ALTER TABLE repositories ADD COLUMN IF NOT EXISTS language VARCHAR(100)"))
                conn.execute(text("ALTER TABLE services ADD COLUMN IF NOT EXISTS slug VARCHAR(255)"))
                conn.execute(text("ALTER TABLE services ADD COLUMN IF NOT EXISTS tier VARCHAR(50) DEFAULT 'medium'"))
                conn.execute(text("ALTER TABLE deployments ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE"))
                conn.execute(text("ALTER TABLE deployments ADD COLUMN IF NOT EXISTS environment_id UUID REFERENCES environments(id) ON DELETE CASCADE"))
                conn.execute(text("ALTER TABLE deployments ADD COLUMN IF NOT EXISTS region_id UUID REFERENCES regions(id) ON DELETE SET NULL"))
                conn.execute(text("ALTER TABLE deployments ADD COLUMN IF NOT EXISTS repository_id UUID REFERENCES repositories(id) ON DELETE SET NULL"))
                conn.execute(text("ALTER TABLE deployments ADD COLUMN IF NOT EXISTS commit_message TEXT"))
                conn.execute(text("ALTER TABLE deployments ADD COLUMN IF NOT EXISTS provider VARCHAR(50) DEFAULT 'manual'"))
                conn.execute(text("ALTER TABLE deployments ADD COLUMN IF NOT EXISTS provider_event_id VARCHAR(255)"))
                conn.execute(text("ALTER TABLE deployments ADD COLUMN IF NOT EXISTS provider_environment VARCHAR(100)"))
                conn.execute(text("ALTER TABLE deployments ADD COLUMN IF NOT EXISTS rollback_of_deployment_id UUID REFERENCES deployments(id) ON DELETE SET NULL"))
                conn.execute(text("ALTER TABLE deployments ADD COLUMN IF NOT EXISTS external_deployment_id VARCHAR(255)"))
                conn.execute(text("ALTER TABLE deployments ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'pending'"))
                conn.execute(text("ALTER TABLE deployments ADD COLUMN IF NOT EXISTS url VARCHAR(1000)"))
                conn.execute(text("ALTER TABLE deployments ADD COLUMN IF NOT EXISTS started_at TIMESTAMP WITH TIME ZONE"))
                conn.execute(text("ALTER TABLE deployments ADD COLUMN IF NOT EXISTS finished_at TIMESTAMP WITH TIME ZONE"))
                conn.execute(text("ALTER TABLE deployments ADD COLUMN IF NOT EXISTS duration_seconds FLOAT"))
                conn.execute(text("ALTER TABLE deployments ADD COLUMN IF NOT EXISTS is_current BOOLEAN DEFAULT FALSE"))
                conn.execute(text("ALTER TABLE webhook_endpoints ADD COLUMN IF NOT EXISTS provider VARCHAR(50) DEFAULT 'generic'"))
                conn.execute(text("ALTER TABLE webhook_endpoints ADD COLUMN IF NOT EXISTS auth_method VARCHAR(50) DEFAULT 'bearer'"))
                conn.execute(text("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE"))
                conn.execute(text("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS environment_id UUID REFERENCES environments(id) ON DELETE SET NULL"))
                conn.execute(text("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS region_id UUID REFERENCES regions(id) ON DELETE SET NULL"))
                conn.execute(text("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS signal_count INTEGER DEFAULT 0"))
                conn.execute(text("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS first_signal_at TIMESTAMP WITH TIME ZONE"))
                conn.execute(text("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS last_signal_at TIMESTAMP WITH TIME ZONE"))
                conn.execute(text("ALTER TABLE service_deployment_configs ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER DEFAULT 0"))
                conn.execute(text("ALTER TABLE service_deployment_configs ADD COLUMN IF NOT EXISTS last_probed_at TIMESTAMP WITH TIME ZONE"))
                conn.execute(text("ALTER TABLE service_deployment_configs ADD COLUMN IF NOT EXISTS last_probe_status_code INTEGER"))
                conn.execute(text("ALTER TABLE service_deployment_configs ADD COLUMN IF NOT EXISTS last_probe_latency_ms FLOAT"))
                conn.execute(text("ALTER TABLE service_deployment_configs ADD COLUMN IF NOT EXISTS last_probe_is_healthy BOOLEAN"))
                conn.execute(text("ALTER TABLE service_deployment_configs ADD COLUMN IF NOT EXISTS last_probe_error TEXT"))
                conn.execute(text("ALTER TABLE service_deployment_configs ADD COLUMN IF NOT EXISTS poller_lease_until TIMESTAMP WITH TIME ZONE"))
                conn.execute(text("ALTER TABLE proposed_fixes ADD COLUMN IF NOT EXISTS repository VARCHAR(500)"))
                conn.execute(text("ALTER TABLE proposed_fixes ADD COLUMN IF NOT EXISTS patch_json JSONB"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE SET NULL"))
                max_num = conn.execute(text("SELECT COALESCE(MAX(number), 0) FROM incidents")).scalar()
                conn.execute(text(f"CREATE SEQUENCE IF NOT EXISTS incident_number_seq START WITH {max_num + 1}"))
            conn.commit()
    except Exception as e:
        logger.exception("Startup schema migration failed; refusing to start with an unverified schema")
        raise

    if not is_testing:
        try:
            start_workers()
        except Exception as e:
            logger.debug(f"Workers start skipped: {e}")

        try:
            app.state.health_check_poller_task = start_health_check_poller()
        except Exception as e:
            logger.debug(f"Health check poller start skipped: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    if settings.ENVIRONMENT.lower() != "testing":
        stop_health_check_poller()
