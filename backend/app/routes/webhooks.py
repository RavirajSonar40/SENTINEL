"""Webhook receiver — ingests alerts from PagerDuty, Datadog, Sentry, Slack, custom sources."""
import hashlib
import hmac
import json
import asyncio
from typing import Dict, Optional, Any, List
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, Header, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.incident import (
    Incident, IncidentStatus, IncidentSeverity, IncidentSource,
    User, Service, IncidentSignal,
)

router = APIRouter()


def _schedule_investigation(incident: Incident):
    from app.routes.auto_detect import _run_auto_investigation
    asyncio.create_task(_run_auto_investigation(str(incident.id)))


# --- Alert Schemas ---

class NormalizedAlert(BaseModel):
    title: str
    description: Optional[str] = None
    severity: str = "SEV-3"
    source: str = "webhook"
    service: Optional[str] = None
    error_signature: Optional[str] = None
    signals: List[str] = []
    metadata: Dict[str, Any] = {}
    external_id: Optional[str] = None
    external_url: Optional[str] = None
    timestamp: Optional[str] = None


# --- Source Normalizers ---

def normalize_pagerduty(payload: Dict) -> NormalizedAlert:
    """Normalize PagerDuty webhook payload."""
    event = payload.get("event", {})
    data = event.get("data", {})
    incident = data.get("incident", {})

    title = incident.get("title", "PagerDuty Incident")
    urgency = incident.get("urgency", "high")
    severity = "SEV-1" if urgency == "high" else "SEV-2"

    return NormalizedAlert(
        title=title,
        description=incident.get("description", ""),
        severity=severity,
        source="pagerduty",
        service=incident.get("service", {}).get("summary"),
        error_signature=incident.get("key"),
        external_id=incident.get("id"),
        external_url=incident.get("html_url"),
        metadata={
            "urgency": urgency,
            "status": incident.get("status"),
            "assignments": [a.get("assignee", {}).get("summary") for a in incident.get("assignments", [])],
        },
    )


def normalize_datadog(payload: Dict) -> NormalizedAlert:
    """Normalize Datadog alert webhook payload."""
    title = payload.get("title", "Datadog Alert")
    alert_type = payload.get("alert_type", "error")
    severity_map = {"error": "SEV-2", "warning": "SEV-3", "info": "SEV-4"}
    severity = severity_map.get(alert_type, "SEV-3")

    tags = payload.get("tags", {})
    service = tags.get("service") or tags.get("env")

    return NormalizedAlert(
        title=title,
        description=payload.get("body", ""),
        severity=severity,
        source="datadog",
        service=service,
        error_signature=payload.get("alert_id"),
        external_id=payload.get("alert_id"),
        metadata={
            "alert_type": alert_type,
            "org": payload.get("org", {}).get("name"),
            "tags": tags,
            "metrics": payload.get("metrics", {}),
        },
    )


def normalize_sentry(payload: Dict) -> NormalizedAlert:
    """Normalize Sentry webhook payload."""
    event = payload.get("data", {}).get("event", {})
    title = event.get("title", "Sentry Error")
    level = event.get("level", "error")
    severity_map = {"fatal": "SEV-1", "error": "SEV-2", "warning": "SEV-3", "info": "SEV-4"}
    severity = severity_map.get(level, "SEV-2")

    metadata = event.get("metadata", {})
    error_type = metadata.get("type", "")
    value = metadata.get("value", "")

    return NormalizedAlert(
        title=title,
        description=f"{error_type}: {value}" if error_type else value,
        severity=severity,
        source="sentry",
        service=event.get("tags", {}).get("server_name"),
        error_signature=event.get("exception", {}).get("values", [{}])[0].get("type") if event.get("exception") else None,
        external_id=event.get("id"),
        external_url=event.get("web_url"),
        metadata={
            "platform": event.get("platform"),
            "environment": event.get("tags", {}).get("environment"),
            "release": event.get("tags", {}).get("release"),
            "user": event.get("user", {}).get("email"),
        },
    )


def normalize_slack(payload: Dict) -> NormalizedAlert:
    """Normalize Slack alert (e.g., from monitoring bot)."""
    text = payload.get("text", "Slack Alert")
    blocks = payload.get("blocks", [])
    title = text[:200] if text else "Slack Alert"

    # Try to extract from blocks
    for block in blocks:
        if block.get("type") == "section":
            text_content = block.get("text", {})
            if text_content.get("type") == "mrkdwn":
                title = text_content.get("text", title)[:200]
                break

    return NormalizedAlert(
        title=title,
        description=text[:1000],
        severity="SEV-3",
        source="slack",
        metadata={"raw_payload": payload},
    )


def normalize_generic(payload: Dict) -> NormalizedAlert:
    """Normalize generic webhook payload."""
    title = (
        payload.get("title")
        or payload.get("name")
        or payload.get("message")
        or payload.get("summary")
        or "Alert"
    )
    severity_raw = (
        payload.get("severity")
        or payload.get("priority")
        or payload.get("level")
        or "medium"
    )

    severity_map = {
        "critical": "SEV-1", "p1": "SEV-1", "sev1": "SEV-1",
        "high": "SEV-2", "p2": "SEV-2", "sev2": "SEV-2",
        "medium": "SEV-3", "p3": "SEV-3", "sev3": "SEV-3",
        "low": "SEV-4", "p4": "SEV-4", "sev4": "SEV-4",
    }
    severity = severity_map.get(str(severity_raw).lower(), "SEV-3")

    return NormalizedAlert(
        title=str(title)[:200],
        description=str(payload.get("description") or payload.get("message") or "")[:1000],
        severity=severity,
        source="generic",
        service=payload.get("service") or payload.get("component"),
        error_signature=payload.get("error") or payload.get("error_type"),
        external_id=payload.get("id"),
        metadata={"raw_payload": payload},
    )


NORMALIZERS = {
    "pagerduty": normalize_pagerduty,
    "datadog": normalize_datadog,
    "sentry": normalize_sentry,
    "slack": normalize_slack,
    "generic": normalize_generic,
}


# --- Incident Creation ---

def create_incident_from_alert(
    alert: NormalizedAlert,
    db: Session,
) -> Incident:
    """Create or update an incident from a normalized alert (with deduplication)."""
    from app.services.dedup import find_existing_incident, add_signal_to_incident
    from app.services.correlation import find_or_create_correlated_incident

    # 1. Check for exact duplicate (same fingerprint within window)
    existing = find_existing_incident(
        title=alert.title,
        service=alert.service,
        error_signature=alert.error_signature,
        source=alert.source,
        window_minutes=30,
        db=db,
    )

    if existing:
        # Merge signal into existing incident
        add_signal_to_incident(
            existing,
            source=alert.source,
            source_id=alert.external_id or "",
            title=alert.title,
            raw_payload=alert.metadata,
            db=db,
        )
        db.commit()
        return existing

    # 2. Check for correlated incident (same service, related error)
    correlated = find_or_create_correlated_incident(
        signal={
            "service": alert.service,
            "error_signature": alert.error_signature,
            "source": alert.source,
            "error_type": alert.metadata.get("error_type"),
        },
        window_minutes=15,
        db=db,
    )

    if correlated:
        add_signal_to_incident(
            correlated,
            source=alert.source,
            source_id=alert.external_id or "",
            title=alert.title,
            raw_payload=alert.metadata,
            db=db,
        )
        db.commit()
        return correlated

    if existing:
        # Update existing incident with new signal
        existing.signal_count = (existing.signal_count or 0) + 1
        existing.last_signal_at = datetime.now(timezone.utc)

        # Add as incident signal
        fingerprint = alert.external_id or ""
        if fingerprint:
            fingerprint = f"{fingerprint}:{int(datetime.now(timezone.utc).timestamp() * 1000)}"
        signal = IncidentSignal(
            incident_id=existing.id,
            source=alert.source,
            signal_type="alert",
            content=alert.title or "",
            fingerprint=fingerprint,
        )
        db.add(signal)
        db.commit()
        return existing

    # Create new incident
    severity_map = {
        "SEV-1": IncidentSeverity.SEV1,
        "SEV-2": IncidentSeverity.SEV2,
        "SEV-3": IncidentSeverity.SEV3,
        "SEV-4": IncidentSeverity.SEV4,
    }
    source_map = {
        "pagerduty": IncidentSource.WEBHOOK,
        "datadog": IncidentSource.WEBHOOK,
        "sentry": IncidentSource.SENTRY,
        "slack": IncidentSource.WEBHOOK,
        "github": IncidentSource.WEBHOOK,
        "generic": IncidentSource.WEBHOOK,
    }

    # Auto-generate incident number
    from sqlalchemy import text
    try:
        next_number = db.execute(text("SELECT nextval('incident_number_seq')")).scalar()
    except Exception:
        db.rollback()
        max_num = db.execute(text("SELECT COALESCE(MAX(number), 0) FROM incidents")).scalar()
        db.execute(text(f"CREATE SEQUENCE IF NOT EXISTS incident_number_seq START WITH {max_num + 1}"))
        db.flush()
        next_number = db.execute(text("SELECT nextval('incident_number_seq')")).scalar()

    incident = Incident(
        number=next_number,
        title=alert.title,
        description=alert.description,
        severity=severity_map.get(alert.severity, IncidentSeverity.SEV3),
        status=IncidentStatus.DETECTED,
        source=source_map.get(alert.source, IncidentSource.WEBHOOK),
        service_name=alert.service,
        error_signature=alert.error_signature,
        external_id=alert.external_id,
        external_url=alert.external_url,
        signal_count=1,
        first_signal_at=datetime.now(timezone.utc),
        last_signal_at=datetime.now(timezone.utc),
        detected_at=datetime.now(timezone.utc),
    )
    db.add(incident)
    db.flush()

    # Add signal
    signal = IncidentSignal(
        incident_id=incident.id,
        source=alert.source,
        signal_type="alert",
        content=alert.title or "",
        fingerprint=alert.external_id or "",
    )
    db.add(signal)
    db.commit()

    return incident


# --- Webhook Endpoints ---

@router.post("/webhooks/pagerduty")
@limiter.limit("60/minute")
async def receive_pagerduty(request: Request, db: Session = Depends(get_db)):
    """Receive PagerDuty webhook."""
    payload = await request.json()
    alert = normalize_pagerduty(payload)
    incident = create_incident_from_alert(alert, db)
    _schedule_investigation(incident)
    return {"status": "ok", "incident_id": incident.id}


@router.post("/webhooks/datadog")
@limiter.limit("60/minute")
async def receive_datadog(request: Request, db: Session = Depends(get_db)):
    """Receive Datadog alert webhook."""
    payload = await request.json()
    alert = normalize_datadog(payload)
    incident = create_incident_from_alert(alert, db)
    _schedule_investigation(incident)
    return {"status": "ok", "incident_id": incident.id}


@router.post("/webhooks/sentry")
@limiter.limit("60/minute")
async def receive_sentry(request: Request, db: Session = Depends(get_db)):
    """Receive Sentry webhook."""
    payload = await request.json()
    alert = normalize_sentry(payload)
    incident = create_incident_from_alert(alert, db)
    _schedule_investigation(incident)
    return {"status": "ok", "incident_id": incident.id}


@router.post("/webhooks/slack")
@limiter.limit("60/minute")
async def receive_slack(request: Request, db: Session = Depends(get_db)):
    """Receive Slack alert."""
    payload = await request.json()
    alert = normalize_slack(payload)
    incident = create_incident_from_alert(alert, db)
    _schedule_investigation(incident)
    return {"status": "ok", "incident_id": incident.id}


@router.post("/webhooks/generic")
@limiter.limit("60/minute")
async def receive_generic(request: Request, db: Session = Depends(get_db)):
    """Receive generic webhook — auto-detects source from payload."""
    payload = await request.json()

    # Auto-detect source
    source = "generic"
    if "event" in payload and "data" in payload:
        source = "pagerduty"
    elif "alert_type" in payload:
        source = "datadog"
    elif "event" in payload and payload.get("event", {}).get("platform"):
        source = "sentry"
    elif "blocks" in payload or "text" in payload:
        source = "slack"

    normalizer = NORMALIZERS.get(source, normalize_generic)
    alert = normalizer(payload)
    incident = create_incident_from_alert(alert, db)
    _schedule_investigation(incident)
    return {"status": "ok", "incident_id": incident.id, "source_detected": source}


@router.get("/webhooks/config")
async def get_webhook_config():
    """Get webhook endpoint configuration."""
    return {
        "endpoints": {
            "pagerduty": "/webhooks/pagerduty",
            "datadog": "/webhooks/datadog",
            "sentry": "/webhooks/sentry",
            "slack": "/webhooks/slack",
            "generic": "/webhooks/generic",
        },
        "instructions": "POST JSON payloads to these endpoints. Sentinel auto-detects source format.",
    }
