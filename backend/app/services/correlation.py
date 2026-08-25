"""Incident correlation — group related signals into single incidents."""
from typing import List, Optional, Dict
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.incident import Incident, IncidentSignal, IncidentStatus


def correlate_signals(
    signals: List[Dict],
    window_minutes: int = 15,
    db: Session = None,
) -> Dict[str, List[Dict]]:
    """Group related signals into clusters that should become one incident."""
    if not signals:
        return {}

    # Sort by timestamp
    sorted_signals = sorted(signals, key=lambda s: s.get("timestamp", ""))

    clusters: Dict[str, List[Dict]] = {}
    current_cluster = [sorted_signals[0]]
    cluster_key = _make_cluster_key(sorted_signals[0])

    for signal in sorted_signals[1:]:
        signal_key = _make_cluster_key(signal)
        signal_time = _parse_time(signal.get("timestamp", ""))

        # Check if this signal belongs to the current cluster
        if (
            signal_key == cluster_key
            or _signals_related(current_cluster[-1], signal)
        ):
            current_cluster.append(signal)
        else:
            # Start new cluster
            clusters[cluster_key] = current_cluster
            current_cluster = [signal]
            cluster_key = signal_key

    # Don't forget the last cluster
    if current_cluster:
        clusters[cluster_key] = current_cluster

    return clusters


def _make_cluster_key(signal: Dict) -> str:
    """Make a cluster key from a signal."""
    parts = []
    if signal.get("service"):
        parts.append(signal["service"].lower())
    if signal.get("error_type"):
        parts.append(signal["error_type"].lower())
    if signal.get("source"):
        parts.append(signal["source"].lower())
    return "|".join(parts) if parts else "unknown"


def _signals_related(s1: Dict, s2: Dict) -> bool:
    """Check if two signals are related enough to be in the same incident."""
    # Same service
    if s1.get("service") and s2.get("service"):
        if s1["service"].lower() == s2["service"].lower():
            return True

    # Same error signature
    if s1.get("error_signature") and s2.get("error_signature"):
        if s1["error_signature"] == s2["error_signature"]:
            return True

    # Same source and error type
    if (
        s1.get("source") == s2.get("source")
        and s1.get("error_type") == s2.get("error_type")
        and s1.get("error_type")
    ):
        return True

    return False


def _parse_time(ts: str) -> Optional[datetime]:
    """Parse ISO timestamp."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def find_or_create_correlated_incident(
    signal: Dict,
    window_minutes: int = 15,
    db: Session = None,
) -> Optional[Incident]:
    """Find an existing incident this signal correlates with, or None."""
    if not db:
        return None

    service = signal.get("service")
    error_sig = signal.get("error_signature")
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)

    # Look for open incidents matching service or error signature
    query = db.query(Incident).filter(
        Incident.created_at >= cutoff,
        Incident.status.notin_([
            IncidentStatus.RESOLVED.value,
            IncidentStatus.CANCELLED.value,
        ]),
    )

    if service:
        existing = query.filter(Incident.service_name == service).first()
        if existing:
            return existing

    if error_sig:
        existing = query.filter(Incident.error_signature == error_sig).first()
        if existing:
            return existing

    return None
