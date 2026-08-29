"""
Unified Auto-Detection & Legacy Compatibility Adapter.

Bridges legacy /detect endpoints and task handlers directly into the authoritative
Phase 5 Detection Engine (detection_rules.py) and Signal Correlation Service (signal_correlation_service.py).
Prevents duplicate incident creation and ensures single-source-of-truth anomaly evaluation.
"""

import asyncio
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db, SessionLocal
from app.core.auth import get_current_user
from app.core.permissions import get_active_membership, require_role
from app.models.incident import (
    Incident, Service, Environment, TelemetrySignal,
    User, Organization, UserOrganizationMembership, MembershipRole,
    IncidentStatus, IncidentSeverity, IncidentSource, SignalProvider, SignalType,
)
from app.services.detection_rules import (
    evaluate_all_rules, ALL_RULES, RULE_REGISTRY,
    ErrorRateRule as Phase5ErrorRateRule,
    LatencySpikeRule as Phase5LatencyRule,
    CrashLoopRule as Phase5CrashLoopRule,
    DatabaseSaturationRule as Phase5DbSatRule,
    RepeatedExceptionRule as Phase5ExceptionRule,
)
from app.services.signal_correlation_service import (
    process_telemetry_signal,
    sanitize_payload,
)

router = APIRouter(tags=["Auto-Detection Adapter"])


# ============================================================================
# LEGACY COMPATIBILITY CLASSES (Forwarding to Phase 5 Detection Rules)
# ============================================================================

class DetectionRule:
    """Base detection rule compatibility wrapper."""
    def __init__(self, name: str, description: str, severity: str = "SEV-3"):
        self.name = name
        self.description = description
        self.severity = severity

    def evaluate(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        raise NotImplementedError


class ErrorRateRule(DetectionRule):
    """Compatibility wrapper for Error Rate detection."""
    def __init__(self, threshold: float = 0.05, window_minutes: int = 5):
        super().__init__("error_rate_spike", "Error rate exceeded threshold", "SEV-2")
        self.threshold = threshold
        self.window_minutes = window_minutes
        self._engine_rule = Phase5ErrorRateRule()

    def evaluate(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        res = self._engine_rule.evaluate(context, custom_threshold=self.threshold)
        if res:
            return {
                "triggered": True,
                "value": res.metric_value,
                "threshold": res.threshold_value,
                "message": res.description,
            }
        return None


class LatencyRule(DetectionRule):
    """Compatibility wrapper for Latency Spike detection."""
    def __init__(self, threshold_ms: float = 1000.0, percentile: float = 99.0):
        super().__init__("latency_spike", "Latency exceeded threshold", "SEV-2")
        self.threshold_ms = threshold_ms
        self.percentile = percentile
        self._engine_rule = Phase5LatencyRule()

    def evaluate(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        res = self._engine_rule.evaluate(context, custom_threshold=self.threshold_ms)
        if res:
            return {
                "triggered": True,
                "value": res.metric_value,
                "threshold": res.threshold_value,
                "message": res.description,
            }
        return None


class CrashLoopRule(DetectionRule):
    """Compatibility wrapper for Crash Loop detection."""
    def __init__(self, restart_threshold: int = 3, window_minutes: int = 30):
        super().__init__("crash_loop", "Service restart loop detected", "SEV-1")
        self.restart_threshold = restart_threshold
        self.window_minutes = window_minutes
        self._engine_rule = Phase5CrashLoopRule()

    def evaluate(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        res = self._engine_rule.evaluate(context, custom_threshold=float(self.restart_threshold))
        if res:
            return {
                "triggered": True,
                "value": res.metric_value,
                "threshold": res.threshold_value,
                "message": res.description,
            }
        return None


class DependentFailureRule(DetectionRule):
    """Compatibility wrapper for Dependent Service Failure detection."""
    def __init__(self, min_failures: int = 2):
        super().__init__("dependent_failure", "Multiple dependent services failing", "SEV-1")
        self.min_failures = min_failures
        self._engine_rule = Phase5DbSatRule()

    def evaluate(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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
    """Compatibility wrapper for Log Anomaly & Repeated Exception detection."""
    def __init__(self, pattern: str = None, threshold: int = 10):
        super().__init__("log_anomaly", "Error log pattern spike detected", "SEV-3")
        self.pattern = pattern or r"(?i)(exception|error|fatal|panic|oom|killed)"
        self.threshold = threshold
        self._engine_rule = Phase5ExceptionRule()

    def evaluate(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        res = self._engine_rule.evaluate(context, custom_threshold=float(self.threshold))
        if res:
            return {
                "triggered": True,
                "value": res.metric_value,
                "threshold": res.threshold_value,
                "message": res.description,
            }
        return None


# Default rules alias pointing to Phase 5 engine
DEFAULT_RULES = [
    ErrorRateRule(threshold=0.05),
    LatencyRule(threshold_ms=1000.0),
    CrashLoopRule(restart_threshold=3),
    DependentFailureRule(min_failures=2),
    LogAnomalyRule(threshold=10),
]


def evaluate_rules(context: Dict[str, Any], rules: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
    """
    Evaluates detection rules against incoming context using the unified 12-rule registry.
    """
    triggered_evals = evaluate_all_rules(context)
    return [
        {
            "rule": r.rule_name,
            "description": r.title,
            "severity": r.severity,
            "triggered": True,
            "value": r.metric_value,
            "threshold": r.threshold_value,
            "message": r.description,
        }
        for r in triggered_evals
    ]


async def _run_auto_investigation(incident_id: str):
    """Asynchronous background task triggering the automated root-cause investigation."""
    from app.services.task_queue import submit_task
    try:
        await submit_task("investigate_incident", {"incident_id": incident_id})
    except Exception:
        pass


def auto_create_incident(
    triggered_rules: List[Dict[str, Any]],
    service_name: str,
    db: Session,
    organization_id: Optional[Any] = None,
) -> Optional[Incident]:
    """
    Forward legacy auto-detection triggers directly into the unified Phase 5 Signal Correlation Engine.
    Ensures single source of incident creation with concurrency-safe claim locks.
    """
    if not triggered_rules:
        return None

    # Resolve Service & Environment
    service = None
    if organization_id:
        service = db.query(Service).filter(
            Service.organization_id == organization_id,
            Service.name == service_name,
        ).first()
    else:
        service = db.query(Service).filter(Service.name == service_name).first()
        if service:
            organization_id = service.organization_id

    if not organization_id:
        org = db.query(Organization).first()
        if org:
            organization_id = org.id

    if not organization_id:
        return None

    environment = None
    if organization_id:
        environment = db.query(Environment).filter(
            Environment.organization_id == organization_id,
            Environment.env_type == "production",
        ).first() or db.query(Environment).filter(
            Environment.organization_id == organization_id
        ).first()

    first_rule = triggered_rules[0]
    rule_name = first_rule.get("rule", "error_rate")

    # Map to SignalType
    rule_cls = RULE_REGISTRY.get(rule_name)
    signal_type = rule_cls.signal_type if rule_cls else SignalType.ERROR_RATE

    import uuid
    event_id = f"auto-detect:{service_name}:{rule_name}:{uuid.uuid4().hex}"

    _, incident, _ = process_telemetry_signal(
        db=db,
        organization_id=organization_id,
        provider=SignalProvider.GENERIC,
        provider_event_id=event_id,
        signal_type=signal_type,
        service=service,
        environment=environment,
        region=None,
        metric_name=rule_name,
        metric_value=first_rule.get("value"),
        threshold_value=first_rule.get("threshold"),
        title=f"Auto-detected: {rule_name} on {service_name}",
        description="\n".join([r.get("message", "") for r in triggered_rules]),
        error_signature=f"auto:{rule_name}:{service_name}",
        raw_payload={"triggered_rules": triggered_rules, "service": service_name},
    )

    return incident


# ============================================================================
# API ENDPOINTS (Unified with Permissions & Phase 5 Engine)
# ============================================================================

@router.post("/detect")
async def run_detection(
    service_name: str,
    context: Dict[str, Any],
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """
    Run the unified detection engine against a service context.
    Automatically correlates anomalies, checks active releases, and routes through Signal Correlation.
    """
    org, _ = auth_ctx
    triggered = evaluate_rules(context)
    incident = None

    if triggered:
        incident = auto_create_incident(triggered, service_name, db, organization_id=org.id)

    return {
        "service": service_name,
        "rules_evaluated": len(ALL_RULES),
        "rules_triggered": len(triggered),
        "triggered_rules": triggered,
        "incident_created": str(incident.id) if incident else None,
        "incident_number": incident.number if incident else None,
    }


@router.get("/detect/rules")
async def list_detection_rules(
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
):
    """List all 12 production detection rules and their configurations."""
    return {
        "rules": [
            {
                "name": rule.rule_name,
                "description": rule.description,
                "signal_type": rule.signal_type.value,
                "severity": rule.default_severity,
                "default_threshold": rule.default_threshold,
            }
            for rule in ALL_RULES
        ]
    }


@router.get("/detect/status")
async def get_detection_status(
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """Get active detection status and metrics across the organization."""
    org, _ = auth_ctx
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(hours=24)

    total_signals = db.query(TelemetrySignal).filter(
        TelemetrySignal.organization_id == org.id,
        TelemetrySignal.observed_at >= lookback,
    ).count()

    auto_incidents = db.query(Incident).filter(
        Incident.organization_id == org.id,
        Incident.source.in_([IncidentSource.AUTO_DETECTION, IncidentSource.HEALTH_CHECK]),
        Incident.created_at >= lookback,
    ).count()

    return {
        "status": "active",
        "engine": "Phase 5 Autonomous Production Detection",
        "rules_count": len(ALL_RULES),
        "total_signals_24h": total_signals,
        "auto_incidents_24h": auto_incidents,
        "last_check": now.isoformat(),
    }
