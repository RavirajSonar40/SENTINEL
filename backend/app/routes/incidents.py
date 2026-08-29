from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID
from datetime import datetime

from app.core.database import get_db
from app.core.auth import get_current_user
from app.services.security import validate_input
from app.models.incident import (
    Incident, IncidentStatus, IncidentSeverity, IncidentSource,
    Repository, RepositoryScope, User, Service,
    Investigation, Evidence, Hypothesis, RootCause, ProposedFix, AuditEvent,
)

router = APIRouter(prefix="/incidents", tags=["incidents"])


# --- Pydantic Schemas ---

class IncidentCreate(BaseModel):
    title: str
    description: Optional[str] = None
    severity: str  # SEV-1, SEV-2, SEV-3, SEV-4
    service: str
    source: str = "manual"  # manual, alert, prometheus, sentry, webhook, deployment_regression
    started_at: Optional[datetime] = None
    repository_ids: List[str] = []


class IncidentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    service: Optional[str] = None
    status: Optional[str] = None
    source: Optional[str] = None


class RepositoryOut(BaseModel):
    id: str
    name: str
    full_name: str
    default_branch: str


class InvestigationSummary(BaseModel):
    id: str
    status: str
    progress_percent: int
    confidence: Optional[str]
    root_cause_found: bool


class IncidentOut(BaseModel):
    id: str
    number: int
    title: str
    description: Optional[str]
    severity: str
    service: Optional[str]
    status: str
    source: str
    confidence: Optional[str]
    root_cause_summary: Optional[str]
    started_at: Optional[datetime]
    detected_at: Optional[datetime]
    resolved_at: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]
    creator_id: Optional[str]
    repositories: List[RepositoryOut] = []
    investigation: Optional[InvestigationSummary] = None


# --- Endpoints ---

def _get_next_incident_number(db: Session) -> int:
    from sqlalchemy import text
    if db.bind and db.bind.dialect.name == "sqlite":
        max_num = db.execute(text("SELECT COALESCE(MAX(number), 0) FROM incidents")).scalar()
        return (max_num or 0) + 1
    try:
        result = db.execute(text("SELECT nextval('incident_number_seq')")).scalar()
        return result
    except Exception:
        db.rollback()
        max_num = db.execute(text("SELECT COALESCE(MAX(number), 0) FROM incidents")).scalar()
        db.execute(text(f"CREATE SEQUENCE IF NOT EXISTS incident_number_seq START WITH {max_num + 1}"))
        db.flush()
        return db.execute(text("SELECT nextval('incident_number_seq')")).scalar()


@router.post("", response_model=IncidentOut)
def create_incident(
    payload: IncidentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Validate inputs for prompt injection
    for field_val in [payload.title, payload.description or ""]:
        validation = validate_input(field_val)
        if not validation["safe"]:
            raise HTTPException(status_code=400, detail="Input contains potentially unsafe content. Please rephrase.")

    service_record = None
    if payload.service and current_user.organization_id:
        service_record = db.query(Service).filter(
            Service.name == payload.service,
            Service.organization_id == current_user.organization_id,
        ).first()

    incident = Incident(
        number=_get_next_incident_number(db),
        organization_id=current_user.organization_id,
        service_id=service_record.id if service_record else None,
        title=payload.title,
        description=payload.description,
        severity=payload.severity,
        service_name=payload.service,
        source=payload.source,
        started_at=payload.started_at,
        status=IncidentStatus.CREATED,
        creator_id=current_user.id,
    )
    db.add(incident)
    db.flush()


    # Attach repository scopes
    for repo_id_str in payload.repository_ids:
        repo_uuid = UUID(repo_id_str)
        scope = RepositoryScope(incident_id=incident.id, repository_id=repo_uuid)
        db.add(scope)

    # Audit event
    audit = AuditEvent(
        incident_id=incident.id,
        user_id=current_user.id,
        event_type="incident_created",
        description=f"Incident created: {incident.title}",
    )
    db.add(audit)

    db.commit()
    db.refresh(incident)
    return _incident_to_out(incident, db)


@router.get("", response_model=List[IncidentOut])
def list_incidents(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    source: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Incident)
    if current_user.role != "admin":
        query = query.filter(Incident.creator_id == current_user.id)
    if status:
        query = query.filter(Incident.status == status)
    if severity:
        query = query.filter(Incident.severity == severity)
    if source:
        query = query.filter(Incident.source == source)
    incidents = query.order_by(Incident.created_at.desc()).offset(skip).limit(limit).all()
    return [_incident_to_out(i, db) for i in incidents]


@router.get("/{incident_id}", response_model=IncidentOut)
def get_incident(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    incident = db.query(Incident).filter(Incident.id == UUID(incident_id)).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    if current_user.role != "admin" and incident.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return _incident_to_out(incident, db)


@router.patch("/{incident_id}", response_model=IncidentOut)
def update_incident(
    incident_id: str,
    payload: IncidentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    incident = db.query(Incident).filter(Incident.id == UUID(incident_id)).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    if current_user.role != "admin" and incident.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Validate user-provided fields for prompt injection
    updates = payload.model_dump(exclude_unset=True)
    for field in ["title", "description"]:
        if field in updates and updates[field]:
            validation = validate_input(str(updates[field]))
            if not validation["safe"]:
                raise HTTPException(status_code=400, detail=f"Input for '{field}' contains potentially unsafe content. Please rephrase.")

    for field, value in updates.items():
        if field == "service":
            setattr(incident, "service_name", value)
        else:
            setattr(incident, field, value)

    db.commit()
    db.refresh(incident)
    return _incident_to_out(incident, db)


@router.delete("/{incident_id}", status_code=204)
def delete_incident(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an incident and its cascaded investigation records."""
    incident = db.query(Incident).filter(Incident.id == UUID(incident_id)).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    if current_user.role != "admin" and incident.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    db.delete(incident)
    db.commit()

@router.post("/{incident_id}/investigate")
def start_investigation(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start an investigation for an incident."""
    incident = db.query(Incident).filter(Incident.id == UUID(incident_id)).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    if incident.status not in (IncidentStatus.CREATED, IncidentStatus.INVESTIGATION_QUEUED):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start investigation in status: {incident.status.value}"
        )

    investigation = Investigation(
        organization_id=incident.organization_id,
        incident_id=incident.id,
        status="planning",
    )
    db.add(investigation)

    incident.status = IncidentStatus.INVESTIGATING

    audit = AuditEvent(
        incident_id=incident.id,
        user_id=current_user.id,
        event_type="investigation_started",
        description="Investigation started",
    )
    db.add(audit)

    db.commit()
    return {"investigation_id": str(investigation.id), "status": "started"}


# --- Helpers ---

def _incident_to_out(incident: Incident, db: Session) -> dict:
    # Get repositories
    scopes = db.query(RepositoryScope).filter(
        RepositoryScope.incident_id == incident.id
    ).all()
    repos = []
    for scope in scopes:
        repo = db.query(Repository).filter(Repository.id == scope.repository_id).first()
        if repo:
            repos.append(RepositoryOut(
                id=str(repo.id),
                name=repo.name,
                full_name=repo.full_name,
                default_branch=repo.default_branch,
            ))

    # Get latest investigation summary
    investigation = db.query(Investigation).filter(
        Investigation.incident_id == incident.id
    ).order_by(Investigation.created_at.desc()).first()

    inv_summary = None
    if investigation:
        inv_summary = InvestigationSummary(
            id=str(investigation.id),
            status=investigation.status.value if hasattr(investigation.status, 'value') else investigation.status,
            progress_percent=investigation.progress_percent or 0,
            confidence=investigation.confidence.value if hasattr(investigation.confidence, 'value') else investigation.confidence,
            root_cause_found=investigation.root_cause_found or False,
        )

    return IncidentOut(
        id=str(incident.id),
        number=incident.number,
        title=incident.title,
        description=incident.description,
        severity=incident.severity if isinstance(incident.severity, str) else incident.severity.value,
        service=incident.service_name,
        status=incident.status if isinstance(incident.status, str) else incident.status.value,
        source=incident.source if isinstance(incident.source, str) else incident.source.value,
        confidence=incident.confidence.value if hasattr(incident.confidence, 'value') else incident.confidence,
        root_cause_summary=incident.root_cause_summary,
        started_at=incident.started_at,
        detected_at=incident.detected_at,
        resolved_at=incident.resolved_at,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
        creator_id=str(incident.creator_id) if incident.creator_id else None,
        repositories=repos,
        investigation=inv_summary,
    )
