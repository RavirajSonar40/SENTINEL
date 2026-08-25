"""Service health monitoring and deployment correlation."""
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.incident import (
    Incident, Service, Deployment, IncidentSignal,
    User, IncidentStatus, IncidentSeverity,
)

router = APIRouter()


# --- Health Scoring ---

def calculate_service_health(service_name: str, db: Session) -> Dict:
    """Calculate health score for a service based on recent incidents."""
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(hours=24)

    # Count incidents in last 24h
    recent_incidents = db.query(Incident).filter(
        Incident.service_name == service_name,
        Incident.created_at >= lookback,
    ).count()

    # Count open incidents
    open_incidents = db.query(Incident).filter(
        Incident.service_name == service_name,
        Incident.status.notin_(["resolved", "cancelled"]),
    ).count()

    # Count by severity
    severity_counts = db.query(
        Incident.severity,
        func.count(Incident.id),
    ).filter(
        Incident.service_name == service_name,
        Incident.created_at >= lookback,
    ).group_by(Incident.severity).all()

    sev_map = {s: c for s, c in severity_counts}

    # Calculate health score (100 = healthy, 0 = critical)
    score = 100
    score -= min(recent_incidents * 10, 40)  # Max -40 for incidents
    score -= min(open_incidents * 15, 30)    # Max -30 for open
    score -= min(sev_map.get(IncidentSeverity.SEV1, 0) * 25, 30)  # Max -30 for SEV1

    # Determine status
    if score >= 90:
        status = "healthy"
    elif score >= 70:
        status = "degraded"
    elif score >= 50:
        status = "unhealthy"
    else:
        status = "critical"

    return {
        "service": service_name,
        "health_score": max(score, 0),
        "status": status,
        "incidents_24h": recent_incidents,
        "open_incidents": open_incidents,
        "severity_breakdown": {
            "SEV-1": sev_map.get(IncidentSeverity.SEV1, 0),
            "SEV-2": sev_map.get(IncidentSeverity.SEV2, 0),
            "SEV-3": sev_map.get(IncidentSeverity.SEV3, 0),
            "SEV-4": sev_map.get(IncidentSeverity.SEV4, 0),
        },
        "last_incident": _get_last_incident_time(service_name, db),
    }


def _get_last_incident_time(service_name: str, db: Session) -> Optional[str]:
    last = db.query(Incident).filter(
        Incident.service_name == service_name,
    ).order_by(desc(Incident.created_at)).first()
    return last.created_at.isoformat() if last else None


# --- Deployment Correlation ---

def correlate_with_deployments(incident: Incident, db: Session) -> Dict:
    """Find deployments that may have caused an incident."""
    if not incident.detected_at:
        return {"deployments": [], "correlation": "no_timestamp"}

    lookback = incident.detected_at - timedelta(hours=24)
    recent_deployments = db.query(Deployment).filter(
        Deployment.service_name == incident.service_name,
        Deployment.deployed_at >= lookback,
        Deployment.deployed_at <= incident.detected_at,
    ).order_by(desc(Deployment.deployed_at)).all()

    correlated = []
    for dep in recent_deployments:
        time_diff = incident.detected_at - dep.deployed_at
        hours_diff = time_diff.total_seconds() / 3600

        # Higher confidence if incident happened shortly after deployment
        if hours_diff < 1:
            confidence = "high"
        elif hours_diff < 6:
            confidence = "medium"
        else:
            confidence = "low"

        correlated.append({
            "deployment_id": dep.id,
            "version": dep.version,
            "commit_sha": dep.commit_sha,
            "deployed_at": dep.deployed_at.isoformat(),
            "hours_before_incident": round(hours_diff, 1),
            "correlation_confidence": confidence,
        })

    return {
        "deployments": correlated,
        "total_deployments_24h": len(recent_deployments),
        "most_likely": correlated[0] if correlated else None,
    }


# --- API Endpoints ---

@router.get("/services/health")
async def get_all_service_health(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get health status for all services."""
    services = db.query(Service).all()
    results = []
    for svc in services:
        health = calculate_service_health(svc.name, db)
        results.append(health)

    # Sort by health score
    results.sort(key=lambda x: x["health_score"])

    overall_score = sum(r["health_score"] for r in results) / len(results) if results else 100

    return {
        "overall_health_score": round(overall_score),
        "services": results,
    }


@router.get("/services/{service_name}/health")
async def get_service_health(
    service_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get health status for a specific service."""
    return calculate_service_health(service_name, db)


@router.get("/incidents/{incident_id}/deployments")
async def get_correlated_deployments(
    incident_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get deployments correlated with an incident."""
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    return correlate_with_deployments(incident, db)


@router.post("/services/{service_name}/deployments")
async def record_deployment(
    service_name: str,
    version: str,
    commit_sha: str = "",
    deployed_by: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record a deployment event for correlation."""
    deployment = Deployment(
        service_name=service_name,
        version=version,
        commit_sha=commit_sha,
        deployed_by=deployed_by,
        deployed_at=datetime.now(timezone.utc),
    )
    db.add(deployment)
    db.commit()
    return {"status": "ok", "deployment_id": deployment.id}
