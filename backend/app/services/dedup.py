"""Deduplication — prevent duplicate incidents from repeated alerts."""
import hashlib
from typing import Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from app.models.incident import Incident, IncidentSignal, IncidentStatus


def compute_fingerprint(
    title: str,
    service: Optional[str] = None,
    error_signature: Optional[str] = None,
    source: Optional[str] = None,
) -> str:
    """Compute a fingerprint for deduplication."""
    parts = []
    if title:
        parts.append(title.lower().strip())
    if service:
        parts.append(service.lower().strip())
    if error_signature:
        parts.append(error_signature.lower().strip())
    if source:
        parts.append(source.lower().strip())
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def find_existing_incident(
    title: str,
    service: Optional[str] = None,
    error_signature: Optional[str] = None,
    source: Optional[str] = None,
    window_minutes: int = 30,
    db: Session = None,
) -> Optional[Incident]:
    """Find an existing incident that matches this alert (deduplication)."""
    if not db:
        return None

    fingerprint = compute_fingerprint(title, service, error_signature, source)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)

    # Check for recent incident with same fingerprint
    existing = db.query(Incident).filter(
        Incident.created_at >= cutoff,
        Incident.status.notin_([
            IncidentStatus.RESOLVED.value,
            IncidentStatus.CANCELLED.value,
        ]),
    ).all()

    for inc in existing:
        inc_fingerprint = compute_fingerprint(
            inc.title,
            inc.service_name,
            inc.error_signature,
            inc.source.value if inc.source else None,
        )
        if inc_fingerprint == fingerprint:
            return inc

    return None


def add_signal_to_incident(
    incident: Incident,
    source: str,
    source_id: str,
    title: str,
    raw_payload: dict = None,
    db: Session = None,
) -> IncidentSignal:
    """Add a signal to an existing incident (dedup merge)."""
    base_fingerprint = compute_fingerprint(title, source=source)
    fingerprint = f"{base_fingerprint}:{int(datetime.now(timezone.utc).timestamp() * 1000)}"
    signal = IncidentSignal(
        incident_id=incident.id,
        source=source,
        signal_type="webhook",
        content={"title": title, "source_id": source_id, "raw_payload": raw_payload or {}},
        fingerprint=fingerprint,
    )
    if db:
        db.add(signal)
        incident.signal_count = (incident.signal_count or 0) + 1
        incident.last_signal_at = datetime.now(timezone.utc)
    return signal
