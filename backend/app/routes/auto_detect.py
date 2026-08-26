"""Auto-detection engine — creates incidents from error spikes, patterns, and anomalies."""
import re
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, text

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.incident import (
    Incident, Service, Deployment, IncidentSignal,
    User, IncidentStatus, IncidentSeverity, IncidentSource,
)

router = APIRouter()


# --- Detection Rules ---

class DetectionRule:
    """Base detection rule."""
    def __init__(self, name: str, description: str, severity: str = "SEV-3"):
        self.name = name
        self.description = description
        self.severity = severity

    def evaluate(self, context: Dict) -> Optional[Dict]:
        raise NotImplementedError


class ErrorRateRule(DetectionRule):
    """Detect error rate spikes."""
    def __init__(self, threshold: float = 0.05, window_minutes: int = 5):
        super().__init__("error_rate_spike", "Error rate exceeded threshold", "SEV-2")
        self.threshold = threshold
        self.window_minutes = window_minutes

    def evaluate(self, context: Dict) -> Optional[Dict]:
        error_rate = context.get("error_rate", 0)
        if error_rate > self.threshold:
            return {
                "triggered": True,
                "value": error_rate,
                "threshold": self.threshold,
                "message": f"Error rate {error_rate:.2%} exceeds threshold {self.threshold:.2%}",
            }
        return None


class LatencyRule(DetectionRule):
    """Detect latency spikes."""
    def __init__(self, threshold_ms: float = 1000, percentile: float = 99):
        super().__init__("latency_spike", "Latency exceeded threshold", "SEV-2")
        self.threshold_ms = threshold_ms
        self.percentile = percentile

    def evaluate(self, context: Dict) -> Optional[Dict]:
        latency = context.get("p99_latency_ms", 0)
        if latency > self.threshold_ms:
            return {
                "triggered": True,
                "value": latency,
                "threshold": self.threshold_ms,
                "message": f"P{self.percentile} latency {latency:.0f}ms exceeds {self.threshold_ms:.0f}ms",
            }
        return None


class CrashLoopRule(DetectionRule):
    """Detect crash loops (multiple restarts)."""
    def __init__(self, restart_threshold: int = 3, window_minutes: int = 30):
        super().__init__("crash_loop", "Service restart loop detected", "SEV-1")
        self.restart_threshold = restart_threshold
        self.window_minutes = window_minutes

    def evaluate(self, context: Dict) -> Optional[Dict]:
        restarts = context.get("restart_count", 0)
        if restarts >= self.restart_threshold:
            return {
                "triggered": True,
                "value": restarts,
                "threshold": self.restart_threshold,
                "message": f"Service restarted {restarts} times in {self.window_minutes} minutes",
            }
        return None


class DependentFailureRule(DetectionRule):
    """Detect when multiple dependent services fail."""
    def __init__(self, min_failures: int = 2):
        super().__init__("dependent_failure", "Multiple dependent services failing", "SEV-1")
        self.min_failures = min_failures

    def evaluate(self, context: Dict) -> Optional[Dict]:
        failed_services = context.get("failed_dependencies", [])
        if len(failed_services) >= self.min_failures:
            return {
                "triggered": True,
                "value": len(failed_services),
                "threshold": self.min_failures,
                "message": f"{len(failed_services)} dependent services failing: {', '.join(failed_services)}",
            }
        return None


class LogAnomalyRule(DetectionRule):
    """Detect error log pattern spikes."""
    def __init__(self, pattern: str = None, threshold: int = 10):
        super().__init__("log_anomaly", "Error log pattern spike detected", "SEV-3")
        self.pattern = pattern or r"(?i)(exception|error|fatal|panic|oom|killed)"
        self.threshold = threshold

    def evaluate(self, context: Dict) -> Optional[Dict]:
        error_logs = context.get("error_log_count", 0)
        if error_logs >= self.threshold:
            return {
                "triggered": True,
                "value": error_logs,
                "threshold": self.threshold,
                "message": f"Error log pattern detected {error_logs} times (threshold: {self.threshold})",
            }
        return None


# Default rule set
DEFAULT_RULES = [
    ErrorRateRule(threshold=0.05),
    LatencyRule(threshold_ms=1000),
    CrashLoopRule(restart_threshold=3),
    DependentFailureRule(min_failures=2),
    LogAnomalyRule(threshold=10),
]


async def _run_auto_investigation(incident_id: str):
    """Run the same streamed investigation used by the manual UI flow."""
    from app.core.database import SessionLocal
    from app.models.incident import Incident, Investigation
    from app.routes.investigation_engine import _stream_investigation

    db = SessionLocal()
    try:
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            return
        investigation = db.query(Investigation).filter(
            Investigation.incident_id == incident.id
        ).first()
        if not investigation:
            from datetime import datetime, timezone
            from app.models.incident import IncidentStatus, InvestigationStatus
            investigation = Investigation(
                incident_id=incident.id,
                status=InvestigationStatus.PLANNING,
                confidence="low",
                started_at=datetime.now(timezone.utc),
            )
            db.add(investigation)
            incident.status = IncidentStatus.INVESTIGATING
            db.commit()
        db.refresh(incident)
        db.refresh(investigation)
        stream = _stream_investigation(
            incident.id,
            investigation.id,
            incident.title or "Unknown",
            incident.description or "",
            incident.error_signature,
            list(incident.scopes) if incident.scopes else [],
            incident.service_name,
            None,
            incident.service_name,
        )
        async for _ in stream:
            pass
    finally:
        db.close()


# --- Detection Engine ---

def evaluate_rules(context: Dict, rules: List[DetectionRule] = None) -> List[Dict]:
    """Evaluate all detection rules against context."""
    if rules is None:
        rules = DEFAULT_RULES

    triggered = []
    for rule in rules:
        result = rule.evaluate(context)
        if result and result.get("triggered"):
            triggered.append({
                "rule": rule.name,
                "description": rule.description,
                "severity": rule.severity,
                **result,
            })
    return triggered


def auto_create_incident(
    triggered_rules: List[Dict],
    service_name: str,
    db: Session,
) -> Optional[Incident]:
    """Auto-create an incident from triggered detection rules."""
    if not triggered_rules:
        return None

    # Determine highest severity
    severity_order = {"SEV-1": 1, "SEV-2": 2, "SEV-3": 3, "SEV-4": 4}
    highest = min(triggered_rules, key=lambda r: severity_order.get(r["severity"], 5))
    severity = highest["severity"]

    # Build title from rules
    rule_names = [r["rule"] for r in triggered_rules[:3]]
    title = f"Auto-detected: {', '.join(rule_names)} — {service_name}"

    # Build description
    descriptions = [r["message"] for r in triggered_rules]
    description = "\n".join(descriptions)

    severity_map = {
        "SEV-1": IncidentSeverity.SEV1,
        "SEV-2": IncidentSeverity.SEV2,
        "SEV-3": IncidentSeverity.SEV3,
        "SEV-4": IncidentSeverity.SEV4,
    }

    incident = Incident(
        title=title,
        description=description,
        severity=severity_map.get(severity, IncidentSeverity.SEV3),
        status=IncidentStatus.DETECTED,
        source=IncidentSource.WEBHOOK,
        service_name=service_name,
        error_signature=f"auto:{rule_names[0]}:{service_name}",
        signal_count=len(triggered_rules),
        first_signal_at=datetime.now(timezone.utc),
        last_signal_at=datetime.now(timezone.utc),
        detected_at=datetime.now(timezone.utc),
    )
    db.add(incident)
    db.flush()

    # Add signals
    for rule in triggered_rules:
        signal = IncidentSignal(
            incident_id=incident.id,
            source="auto_detection",
            signal_type="rule",
            content=rule["message"],
            fingerprint=rule["rule"],
        )
        db.add(signal)

    db.commit()
    return incident


# --- API Endpoints ---

@router.post("/detect")
async def run_detection(
    service_name: str,
    context: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run detection rules against a service context."""
    triggered = evaluate_rules(context)
    incident = None

    if triggered:
        incident = auto_create_incident(triggered, service_name, db)
        if incident:
            asyncio.create_task(_run_auto_investigation(str(incident.id)))

    return {
        "service": service_name,
        "rules_evaluated": len(DEFAULT_RULES),
        "rules_triggered": len(triggered),
        "triggered_rules": triggered,
        "incident_created": incident.id if incident else None,
    }


@router.get("/detect/rules")
async def list_detection_rules(
    current_user: User = Depends(get_current_user),
):
    """List all available detection rules."""
    return {
        "rules": [
            {
                "name": rule.name,
                "description": rule.description,
                "severity": rule.severity,
                "type": rule.__class__.__name__,
            }
            for rule in DEFAULT_RULES
        ]
    }


@router.get("/detect/status")
async def get_detection_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get detection system status."""
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(hours=24)

    auto_incidents = db.query(Incident).filter(
        Incident.source == IncidentSource.WEBHOOK,
        Incident.created_at >= lookback,
    ).count()

    return {
        "status": "active",
        "rules_count": len(DEFAULT_RULES),
        "auto_incidents_24h": auto_incidents,
        "last_check": now.isoformat(),
    }
