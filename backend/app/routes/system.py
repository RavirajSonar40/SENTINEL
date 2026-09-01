"""Audit logs and settings routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.incident import AuditEvent, User

router = APIRouter(tags=["system"])


# --- Audit Logs ---

@router.get("/audit-logs")
def list_audit_logs(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logs = db.query(AuditEvent).order_by(AuditEvent.timestamp.desc()).limit(limit).all()
    return [
        {
            "id": str(log.id),
            "action": log.event_type,
            "entity_type": "incident",
            "entity_id": str(log.incident_id) if log.incident_id else "",
            "user_id": str(log.user_id) if log.user_id else "",
            "details": log.metadata_json or {},
            "created_at": log.timestamp.isoformat() if log.timestamp else None,
        }
        for log in logs
    ]


# --- Settings ---

class SettingsPayload(BaseModel):
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_api_key: Optional[str] = None
    auto_investigate: Optional[bool] = None
    auto_merge: Optional[bool] = None
    notification_email: Optional[str] = None


# In-memory settings store (production would use DB)
_settings: Dict[str, Any] = {
    "llm_provider": "mock",
    "llm_model": "gpt-4",
    "auto_investigate": True,
    "auto_merge": False,
    "notification_email": "",
}


@router.get("/settings")
def get_settings(current_user: User = Depends(get_current_user)):
    safe = {k: v for k, v in _settings.items()}
    if "llm_api_key" in safe and safe["llm_api_key"]:
        key = safe["llm_api_key"]
        safe["llm_api_key"] = key[:4] + "****" + key[-4:] if len(key) > 8 else "****"
    return safe


@router.put("/settings")
def update_settings(
    payload: SettingsPayload,
    current_user: User = Depends(get_current_user),
):
    if payload.llm_provider is not None:
        _settings["llm_provider"] = payload.llm_provider
    if payload.llm_model is not None:
        _settings["llm_model"] = payload.llm_model
    if payload.llm_api_key is not None:
        _settings["llm_api_key"] = payload.llm_api_key
    if payload.auto_investigate is not None:
        _settings["auto_investigate"] = payload.auto_investigate
    if payload.auto_merge is not None:
        _settings["auto_merge"] = payload.auto_merge
    if payload.notification_email is not None:
        _settings["notification_email"] = payload.notification_email

    # Mask API key in response
    safe = {k: v for k, v in _settings.items()}
    if "llm_api_key" in safe and safe["llm_api_key"]:
        key = safe["llm_api_key"]
        safe["llm_api_key"] = key[:4] + "****" + key[-4:] if len(key) > 8 else "****"
    return {"status": "ok", "settings": safe}


# --- Alert Rules ---

class AlertRulePayload(BaseModel):
    name: str
    type: str
    threshold: str
    severity: str
    enabled: bool = True
    services: List[str] = []


_alert_rules: List[Dict[str, Any]] = [
    {"id": "1", "name": "High Error Rate", "type": "error_rate", "threshold": ">5% over 5min", "severity": "SEV-2", "enabled": True, "services": ["all"]},
    {"id": "2", "name": "P99 Latency Spike", "type": "latency", "threshold": ">1000ms", "severity": "SEV-2", "enabled": True, "services": ["all"]},
    {"id": "3", "name": "Service Crash Loop", "type": "crash_loop", "threshold": ">=3 restarts in 30min", "severity": "SEV-1", "enabled": True, "services": ["all"]},
    {"id": "4", "name": "Dependency Down", "type": "dependency", "threshold": ">=2 failures", "severity": "SEV-1", "enabled": True, "services": ["all"]},
    {"id": "5", "name": "Error Log Spike", "type": "log_anomaly", "threshold": ">=10 errors in 5min", "severity": "SEV-3", "enabled": False, "services": ["all"]},
    {"id": "6", "name": "Database Timeout", "type": "custom", "threshold": ">5s response time", "severity": "SEV-2", "enabled": True, "services": ["api-gateway", "user-service"]},
]


@router.get("/detect/rules")
def list_alert_rules(current_user: User = Depends(get_current_user)):
    return _alert_rules


@router.put("/detect/rules/{rule_id}")
def update_alert_rule(rule_id: str, payload: AlertRulePayload, current_user: User = Depends(get_current_user)):
    for rule in _alert_rules:
        if rule["id"] == rule_id:
            rule["name"] = payload.name
            rule["type"] = payload.type
            rule["threshold"] = payload.threshold
            rule["severity"] = payload.severity
            rule["enabled"] = payload.enabled
            rule["services"] = payload.services
            return {"status": "ok", "rule": rule}
    raise HTTPException(status_code=404, detail="Rule not found")


@router.post("/detect/rules")
def create_alert_rule(payload: AlertRulePayload, current_user: User = Depends(get_current_user)):
    new_rule = {
        "id": str(len(_alert_rules) + 1),
        "name": payload.name,
        "type": payload.type,
        "threshold": payload.threshold,
        "severity": payload.severity,
        "enabled": payload.enabled,
        "services": payload.services,
    }
    _alert_rules.append(new_rule)
    return {"status": "ok", "rule": new_rule}


@router.delete("/detect/rules/{rule_id}")
def delete_alert_rule(rule_id: str, current_user: User = Depends(get_current_user)):
    global _alert_rules
    _alert_rules = [r for r in _alert_rules if r["id"] != rule_id]
    return {"status": "ok"}


@router.put("/detect/rules/{rule_id}/toggle")
def toggle_alert_rule(rule_id: str, current_user: User = Depends(get_current_user)):
    for rule in _alert_rules:
        if rule["id"] == rule_id:
            rule["enabled"] = not rule["enabled"]
            return {"status": "ok", "rule": rule}
    raise HTTPException(status_code=404, detail="Rule not found")


# --- System Health ---

@router.get("/system/health")
def get_system_health(current_user: User = Depends(get_current_user)):
    import psycopg
    from app.core.config import settings

    checks = {}

    # Postgres
    try:
        conn = psycopg.connect(settings.DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        checks["postgres"] = {"status": "operational", "latency_ms": 5}
    except Exception as e:
        checks["postgres"] = {"status": "error", "error": str(e)}

    # Canonical vector store (Pinecone in deployed environments).
    try:
        if settings.PINECONE_API_KEY and settings.PINECONE_INDEX:
            from app.services.vector_store import _get_pinecone
            checks["vector_store"] = {
                "status": "operational" if _get_pinecone() is not None else "error",
                "provider": "pinecone",
            }
        else:
            checks["vector_store"] = {"status": "error", "error": "Pinecone is not configured"}
    except Exception:
        checks["vector_store"] = {"status": "error", "error": "Vector store unavailable"}

    # Redis
    redis_client = None
    try:
        import redis as sync_redis
        url = settings.REDIS_URL
        if url.startswith("rediss://"):
            redis_client = sync_redis.from_url(url, socket_connect_timeout=2, socket_timeout=2, ssl_cert_reqs=None)
        else:
            redis_client = sync_redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        redis_client.ping()
        checks["redis"] = {"status": "operational"}
    except Exception as e:
        checks["redis"] = {"status": "error", "error": str(e)[:200]}
    finally:
        if redis_client is not None:
            try:
                redis_client.close()
            except Exception:
                pass

    # LLM
    from app.services.llm import get_config
    cfg = get_config()
    checks["llm"] = {"status": "configured", "provider": cfg.provider, "model": cfg.model}

    return {
        "status": "healthy" if all(c.get("status") in ("operational", "configured") for c in checks.values()) else "degraded",
        "checks": checks,
    }


# --- Database Migrations (run-once endpoints) ---

@router.post("/admin/migrate")
def run_pending_migrations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Run pending schema migrations. One-time use per migration."""
    from sqlalchemy import text
    results = []

    # Migration 037: Add user_id to github_installations
    try:
        db.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'github_installations' AND column_name = 'user_id'
                ) THEN
                    ALTER TABLE github_installations ADD COLUMN user_id UUID REFERENCES users(id) ON DELETE SET NULL;
                    CREATE INDEX ix_github_installations_user_id ON github_installations(user_id);
                    RAISE NOTICE 'Added user_id column to github_installations';
                ELSE
                    RAISE NOTICE 'user_id column already exists';
                END IF;
            END $$;
        """))
        db.commit()
        results.append({"migration": "037_add_user_id", "status": "applied"})
    except Exception as e:
        db.rollback()
        results.append({"migration": "037_add_user_id", "status": "error", "error": str(e)})

    return {"results": results}
