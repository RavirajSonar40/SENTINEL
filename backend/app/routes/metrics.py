"""Self-observability — metrics for Sentinel itself."""
import time
from typing import Dict, List
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.incident import (
    Incident, Investigation, Evidence, Hypothesis,
    ProposedFix, Approval, AgentRun, AuditEvent,
    User, IncidentStatus,
)

router = APIRouter()

# In-memory metrics (production would use Prometheus)
_metrics = {
    "requests_total": 0,
    "requests_by_endpoint": {},
    "llm_calls": 0,
    "llm_tokens_total": 0,
    "llm_cost_total": 0.0,
    "llm_latency_ms": [],
    "tool_calls": 0,
    "tool_failures": 0,
    "investigations_started": 0,
    "investigations_completed": 0,
    "investigations_failed": 0,
    "hypotheses_generated": 0,
    "root_causes_found": 0,
    "fixes_generated": 0,
    "prs_created": 0,
    "approvals_granted": 0,
    "approvals_rejected": 0,
    "started_at": datetime.now(timezone.utc).isoformat(),
}


def record_request(endpoint: str):
    """Record an API request."""
    _metrics["requests_total"] += 1
    _metrics["requests_by_endpoint"][endpoint] = (
        _metrics["requests_by_endpoint"].get(endpoint, 0) + 1
    )


def record_llm_call(tokens: int, cost: float = 0.0, latency_ms: int = 0):
    """Record an LLM API call."""
    _metrics["llm_calls"] += 1
    _metrics["llm_tokens_total"] += tokens
    _metrics["llm_cost_total"] += cost
    if latency_ms > 0:
        _metrics["llm_latency_ms"].append(latency_ms)
        # Keep last 1000
        if len(_metrics["llm_latency_ms"]) > 1000:
            _metrics["llm_latency_ms"] = _metrics["llm_latency_ms"][-1000:]


def record_tool_call(success: bool):
    """Record a tool execution."""
    _metrics["tool_calls"] += 1
    if not success:
        _metrics["tool_failures"] += 1


def record_investigation(completed: bool = True, failed: bool = False):
    """Record investigation outcome."""
    if completed:
        _metrics["investigations_completed"] += 1
    if failed:
        _metrics["investigations_failed"] += 1


def record_hypothesis(count: int = 1):
    _metrics["hypotheses_generated"] += count


def record_root_cause():
    _metrics["root_causes_found"] += 1


def record_fix():
    _metrics["fixes_generated"] += 1


def record_pr():
    _metrics["prs_created"] += 1


def record_approval(approved: bool):
    if approved:
        _metrics["approvals_granted"] += 1
    else:
        _metrics["approvals_rejected"] += 1


@router.get("/metrics")
async def get_metrics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get Sentinel self-observability metrics."""
    # Compute latency stats
    latencies = _metrics["llm_latency_ms"]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    p95_latency = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0

    # Compute DB-level stats
    now = datetime.now(timezone.utc)
    lookback_24h = now - timedelta(hours=24)
    lookback_7d = now - timedelta(days=7)

    total_incidents = db.query(Incident).count()
    incidents_24h = db.query(Incident).filter(Incident.created_at >= lookback_24h).count()
    open_incidents = db.query(Incident).filter(
        Incident.status.notin_([IncidentStatus.RESOLVED.value, IncidentStatus.CANCELLED.value])
    ).count()

    total_investigations = db.query(Investigation).count()
    from sqlalchemy import case as sa_case
    avg_confidence = db.query(func.avg(
        sa_case(
            (Investigation.confidence == "high", 3),
            (Investigation.confidence == "medium", 2),
            (Investigation.confidence == "low", 1),
            else_=0,
        )
    )).scalar() or 0

    total_evidence = db.query(Evidence).count()
    total_hypotheses = db.query(Hypothesis).count()
    total_fixes = db.query(ProposedFix).count()
    total_approvals = db.query(Approval).count()

    return {
        "system": {
            "uptime_since": _metrics["started_at"],
            "status": "healthy",
        },
        "requests": {
            "total": _metrics["requests_total"],
            "by_endpoint": _metrics["requests_by_endpoint"],
        },
        "llm": {
            "total_calls": _metrics["llm_calls"],
            "total_tokens": _metrics["llm_tokens_total"],
            "total_cost_usd": round(_metrics["llm_cost_total"], 4),
            "avg_latency_ms": round(avg_latency),
            "p95_latency_ms": round(p95_latency),
        },
        "tools": {
            "total_calls": _metrics["tool_calls"],
            "total_failures": _metrics["tool_failures"],
            "failure_rate": round(
                _metrics["tool_failures"] / max(_metrics["tool_calls"], 1) * 100, 1
            ),
        },
        "investigations": {
            "total": total_investigations,
            "started": _metrics["investigations_started"],
            "completed": _metrics["investigations_completed"],
            "failed": _metrics["investigations_failed"],
            "avg_confidence": round(avg_confidence, 2),
        },
        "incidents": {
            "total": total_incidents,
            "last_24h": incidents_24h,
            "open": open_incidents,
        },
        "evidence": {
            "total_items": total_evidence,
            "hypotheses_generated": _metrics["hypotheses_generated"],
            "root_causes_found": _metrics["root_causes_found"],
        },
        "remediation": {
            "fixes_generated": _metrics["fixes_generated"],
            "prs_created": _metrics["prs_created"],
            "total_fixes": total_fixes,
        },
        "approvals": {
            "total": total_approvals,
            "granted": _metrics["approvals_granted"],
            "rejected": _metrics["approvals_rejected"],
        },
    }


@router.get("/metrics/health")
async def health_check():
    """Simple health check for monitoring."""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
