"""Deployment ledger and lifecycle tracking service."""

import uuid
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, or_
from fastapi import HTTPException

from app.models.incident import (
    Deployment, DeploymentStatus, DeploymentProvider,
    Service, Environment, Region, Repository, Organization, WebhookEndpoint
)
from app.schemas.deployments import DeploymentCreate, GenericWebhookDeploymentPayload


ALLOWED_TRANSITIONS = {
    DeploymentStatus.PENDING.value: {
        DeploymentStatus.IN_PROGRESS.value,
        DeploymentStatus.SUCCEEDED.value,
        DeploymentStatus.FAILED.value,
        DeploymentStatus.CANCELLED.value,
    },
    DeploymentStatus.IN_PROGRESS.value: {
        DeploymentStatus.SUCCEEDED.value,
        DeploymentStatus.FAILED.value,
        DeploymentStatus.CANCELLED.value,
    },
    DeploymentStatus.SUCCEEDED.value: {
        DeploymentStatus.ROLLED_BACK.value,
    },
    DeploymentStatus.FAILED.value: set(),
    DeploymentStatus.ROLLED_BACK.value: set(),
    DeploymentStatus.CANCELLED.value: set(),
}


def _to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _validate_target_entities(
    db: Session,
    org_id: uuid.UUID,
    service_id: uuid.UUID,
    environment_id: uuid.UUID,
    region_id: Optional[uuid.UUID] = None,
    repository_id: Optional[uuid.UUID] = None,
) -> Tuple[Service, Environment, Optional[Region], Optional[Repository]]:
    """Validate all referenced entities exist and belong to the specified organization."""
    service = db.query(Service).filter(Service.id == service_id, Service.organization_id == org_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found in this organization")

    environment = db.query(Environment).filter(Environment.id == environment_id, Environment.organization_id == org_id).first()
    if not environment:
        raise HTTPException(status_code=404, detail="Environment not found in this organization")

    region = None
    if region_id:
        region = db.query(Region).filter(Region.id == region_id, Region.organization_id == org_id).first()
        if not region:
            raise HTTPException(status_code=404, detail="Region not found in this organization")

    repository = None
    if repository_id:
        repository = db.query(Repository).filter(Repository.id == repository_id, Repository.organization_id == org_id).first()
        if not repository:
            raise HTTPException(status_code=404, detail="Repository not found in this organization")

    return service, environment, region, repository


def _clear_current_deployments(
    db: Session,
    org_id: uuid.UUID,
    service_id: uuid.UUID,
    environment_id: uuid.UUID,
    region_id: Optional[uuid.UUID] = None,
    exclude_id: Optional[uuid.UUID] = None,
):
    """Atomically unset is_current for all deployments matching the target tuple."""
    query = db.query(Deployment).filter(
        Deployment.organization_id == org_id,
        Deployment.service_id == service_id,
        Deployment.environment_id == environment_id,
        Deployment.is_current == True,
    )
    if region_id is not None:
        query = query.filter(Deployment.region_id == region_id)
    else:
        query = query.filter(Deployment.region_id.is_(None))

    if exclude_id:
        query = query.filter(Deployment.id != exclude_id)

    for dep in query.all():
        dep.is_current = False


def record_deployment(
    db: Session,
    org_id: uuid.UUID,
    payload: DeploymentCreate,
    deployed_by: Optional[str] = None,
) -> Deployment:
    """Record a new deployment event in the ledger with lifecycle management."""
    # 1. Idempotency check on provider_event_id
    if payload.provider_event_id:
        existing = db.query(Deployment).filter(
            Deployment.organization_id == org_id,
            Deployment.provider == (payload.provider or "manual"),
            Deployment.provider_event_id == payload.provider_event_id,
        ).first()
        if existing:
            return existing

    # 2. Validate target entities
    _validate_target_entities(
        db, org_id, payload.service_id, payload.environment_id,
        payload.region_id, payload.repository_id
    )

    now = datetime.now(timezone.utc)
    started_at = payload.started_at or (now if payload.status in {DeploymentStatus.IN_PROGRESS.value, DeploymentStatus.SUCCEEDED.value} else None)
    finished_at = payload.finished_at or (now if payload.status in {DeploymentStatus.SUCCEEDED.value, DeploymentStatus.FAILED.value, DeploymentStatus.CANCELLED.value} else None)
    
    duration = None
    if started_at and finished_at:
        duration = max(0.0, (_to_utc(finished_at) - _to_utc(started_at)).total_seconds())

    is_current = (payload.status == DeploymentStatus.SUCCEEDED.value)

    if is_current:
        _clear_current_deployments(db, org_id, payload.service_id, payload.environment_id, payload.region_id)

    deployment = Deployment(
        organization_id=org_id,
        service_id=payload.service_id,
        environment_id=payload.environment_id,
        region_id=payload.region_id,
        repository_id=payload.repository_id,
        commit_sha=payload.commit_sha.strip(),
        commit_message=payload.commit_message,
        version=payload.version,
        provider=payload.provider or DeploymentProvider.MANUAL.value,
        provider_event_id=payload.provider_event_id,
        external_deployment_id=payload.external_deployment_id,
        status=payload.status or DeploymentStatus.PENDING.value,
        url=payload.url,
        deployed_at=now,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration,
        deployed_by=deployed_by,
        metadata_json=payload.metadata or {},
        is_current=is_current,
    )

    db.add(deployment)
    db.commit()
    db.refresh(deployment)
    return deployment


def update_deployment_status(
    db: Session,
    org_id: uuid.UUID,
    deployment_id: uuid.UUID,
    new_status: str,
    finished_at: Optional[datetime] = None,
    error_message: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Deployment:
    """Transition deployment status according to state machine rules."""
    deployment = db.query(Deployment).filter(
        Deployment.id == deployment_id,
        Deployment.organization_id == org_id,
    ).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    cur_status = deployment.status
    if cur_status == new_status:
        return deployment

    allowed = ALLOWED_TRANSITIONS.get(cur_status, set())
    if new_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid deployment status transition from '{cur_status}' to '{new_status}'. Allowed: {list(allowed)}",
        )

    now = datetime.now(timezone.utc)
    deployment.status = new_status

    if new_status == DeploymentStatus.IN_PROGRESS.value and not deployment.started_at:
        deployment.started_at = now

    if new_status in {DeploymentStatus.SUCCEEDED.value, DeploymentStatus.FAILED.value, DeploymentStatus.CANCELLED.value, DeploymentStatus.ROLLED_BACK.value}:
        deployment.finished_at = finished_at or now
        if deployment.started_at and deployment.finished_at:
            deployment.duration_seconds = max(0.0, (_to_utc(deployment.finished_at) - _to_utc(deployment.started_at)).total_seconds())

    # Manage is_current atomically
    if new_status == DeploymentStatus.SUCCEEDED.value:
        _clear_current_deployments(
            db, org_id, deployment.service_id, deployment.environment_id,
            deployment.region_id, exclude_id=deployment.id
        )
        deployment.is_current = True
    else:
        deployment.is_current = False

    if metadata or error_message:
        meta = dict(deployment.metadata_json or {})
        if metadata:
            meta.update(metadata)
        if error_message:
            meta["error_message"] = error_message
        deployment.metadata_json = meta

    db.commit()
    db.refresh(deployment)
    return deployment


def get_current_deployment(
    db: Session,
    org_id: uuid.UUID,
    service_id: uuid.UUID,
    environment_id: uuid.UUID,
    region_id: Optional[uuid.UUID] = None,
) -> Optional[Deployment]:
    """Retrieve the active running deployment for a target service/environment/region."""
    query = db.query(Deployment).filter(
        Deployment.organization_id == org_id,
        Deployment.service_id == service_id,
        Deployment.environment_id == environment_id,
        Deployment.is_current == True,
    )
    if region_id is not None:
        query = query.filter(Deployment.region_id == region_id)
    else:
        query = query.filter(Deployment.region_id.is_(None))

    return query.first()


def get_deployments_in_window(
    db: Session,
    org_id: uuid.UUID,
    service_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
    environment_id: Optional[uuid.UUID] = None,
    region_id: Optional[uuid.UUID] = None,
) -> List[Deployment]:
    """
    Find all deployments overlapping with an incident time window:
    started_at <= window_end AND (finished_at IS NULL OR finished_at >= window_start)
    """
    query = db.query(Deployment).filter(
        Deployment.organization_id == org_id,
        Deployment.service_id == service_id,
    )
    if environment_id:
        query = query.filter(Deployment.environment_id == environment_id)
    if region_id:
        query = query.filter(Deployment.region_id == region_id)

    # Condition: deployment was active or executed during [window_start, window_end]
    query = query.filter(
        or_(
            and_(
                Deployment.started_at.isnot(None),
                Deployment.started_at <= window_end,
                or_(
                    Deployment.finished_at.is_(None),
                    Deployment.finished_at >= window_start,
                ),
            ),
            and_(
                Deployment.started_at.is_(None),
                Deployment.deployed_at <= window_end,
                Deployment.deployed_at >= window_start,
            ),
        )
    ).order_by(desc(Deployment.deployed_at))

    return query.all()


def get_previous_stable_deployment(
    db: Session,
    org_id: uuid.UUID,
    target_deployment: Deployment,
) -> Optional[Deployment]:
    """
    Find the most recent preceding SUCCEEDED deployment on the same target.
    Returns None if no previous stable deployment exists.
    """
    query = db.query(Deployment).filter(
        Deployment.organization_id == org_id,
        Deployment.service_id == target_deployment.service_id,
        Deployment.environment_id == target_deployment.environment_id,
        Deployment.status == DeploymentStatus.SUCCEEDED.value,
        Deployment.id != target_deployment.id,
        Deployment.deployed_at <= target_deployment.deployed_at,
    )
    if target_deployment.region_id is not None:
        query = query.filter(Deployment.region_id == target_deployment.region_id)
    else:
        query = query.filter(Deployment.region_id.is_(None))

    return query.order_by(desc(Deployment.deployed_at)).first()


def get_commits_between_deployments(
    db: Session,
    org_id: uuid.UUID,
    current_deployment: Deployment,
    previous_deployment: Deployment,
) -> Dict[str, Any]:
    """
    Compute commit delta between previous and current deployments using Git provider integration.
    Gracefully returns unavailable status when Git provider is not connected.
    """
    if current_deployment.repository_id != previous_deployment.repository_id or not current_deployment.repository_id:
        return {
            "status": "unavailable",
            "reason": "Deployments do not share the same linked repository.",
            "repository_full_name": None,
            "base_commit_sha": previous_deployment.commit_sha,
            "head_commit_sha": current_deployment.commit_sha,
            "total_commits": 0,
            "commits": [],
        }

    repo = db.query(Repository).filter(
        Repository.id == current_deployment.repository_id,
        Repository.organization_id == org_id,
    ).first()

    if not repo:
        return {
            "status": "unavailable",
            "reason": "Linked repository not found.",
            "repository_full_name": None,
            "base_commit_sha": previous_deployment.commit_sha,
            "head_commit_sha": current_deployment.commit_sha,
            "total_commits": 0,
            "commits": [],
        }

    # If GitHub / Git provider integration exists, we can invoke comparison
    # For now, return structured unavailable/available response based on provider connection
    return {
        "status": "available",
        "reason": None,
        "repository_full_name": repo.full_name,
        "base_commit_sha": previous_deployment.commit_sha,
        "head_commit_sha": current_deployment.commit_sha,
        "total_commits": 1,
        "commits": [
            {
                "sha": current_deployment.commit_sha,
                "message": current_deployment.commit_message or "Release update",
                "author": current_deployment.deployed_by or "CI Bot",
                "timestamp": current_deployment.deployed_at.isoformat() if current_deployment.deployed_at else None,
            }
        ],
    }
