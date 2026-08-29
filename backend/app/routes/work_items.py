"""
REST API Endpoints for Sentinel Work Items and Intent Routing.

Implements Phase 2:
- POST /work-items: Create and route work item with tenant isolation & idempotency
- POST /work-items/classify: Dry-run stateless classification
- GET /work-items: List work items with tenant filtering
- GET /work-items/{id}: Retrieve single work item
- PATCH /work-items/{id}/status: Controlled status transition
"""

import uuid
from typing import List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Header, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.incident import User, Repository
from app.models.work_item import WorkItem, WorkType, WorkItemStatus, WorkItemRepository
from app.schemas.work_item import (
    WorkItemCreate,
    WorkItemResponse,
    ClarificationResponse,
    WorkTypeEnvelope,
    WorkItemRepositorySchema,
    StatusUpdateRequest,
)
from app.services.intent_router import classify_intent
from app.services.workflow_router import route_work_item, validate_status_transition

router = APIRouter(prefix="/work-items", tags=["work-items"])


def _serialize_work_item(item: WorkItem) -> WorkItemResponse:
    """Helper to convert WorkItem model to WorkItemResponse schema."""
    repos = [
        WorkItemRepositorySchema(
            repository_id=str(r.repository_id),
            repository_name=r.repository.name if r.repository else None,
            role=r.role,
            is_primary=r.is_primary,
            selection_reason=r.selection_reason,
            confidence=r.confidence,
        )
        for r in item.repositories
    ]
    return WorkItemResponse(
        id=str(item.id),
        organization_id=str(item.organization_id),
        work_type=item.work_type,
        title=item.title,
        description=item.description,
        status=item.status,
        priority=item.priority,
        target_files=item.target_files or [],
        workflow=item.workflow,
        confidence=item.confidence,
        requires_runtime_evidence=item.requires_runtime_evidence,
        runtime_evidence_reason=item.runtime_evidence_reason,
        requires_code_change=item.requires_code_change,
        envelope=item.envelope or {},
        incident_id=str(item.incident_id) if item.incident_id else None,
        repositories=repos,
        created_at=item.created_at.isoformat() if item.created_at else None,
        updated_at=item.updated_at.isoformat() if item.updated_at else None,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_work_item(
    payload: WorkItemCreate,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new WorkItem, classify its intent, and dispatch it to the appropriate workflow.
    Enforces non-null organization tenant isolation and server-side membership.
    """
    # 1. Enforce organization membership
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not belong to an organization. Organization membership is required to create work items.",
        )
    org_id = current_user.organization_id

    # 2. Idempotency Key check
    effective_idempotency_key = idempotency_key or payload.idempotency_key
    if effective_idempotency_key:
        existing = (
            db.query(WorkItem)
            .filter(
                WorkItem.organization_id == org_id,
                WorkItem.idempotency_key == effective_idempotency_key,
            )
            .first()
        )
        if existing:
            return _serialize_work_item(existing)

    # 3. Handle force_work_type authorization
    force_type = payload.force_work_type
    if force_type and current_user.role != "admin":
        # Non-admin users cannot force work type
        force_type = None

    # 4. Classify intent
    envelope = await classify_intent(
        title=payload.title,
        description=payload.description,
        target_files=payload.target_files,
        force_work_type=force_type,
    )

    # 5. Check if request needs clarification
    if envelope.work_type == WorkType.NEEDS_CLARIFICATION or envelope.confidence < 0.70:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=ClarificationResponse(
                status="needs_clarification",
                work_type=WorkType.NEEDS_CLARIFICATION,
                confidence=envelope.confidence,
                reason=envelope.rationale or "The request is too ambiguous to classify safely.",
                questions=envelope.questions or ["Could you provide more context on the expected change?"],
            ).model_dump(),
        )

    # 6. Parse and link services & environments
    service_uuid = None
    if payload.service_id:
        try:
            service_uuid = uuid.UUID(payload.service_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid service_id format.")

    env_uuid = None
    if payload.environment_id:
        try:
            env_uuid = uuid.UUID(payload.environment_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid environment_id format.")

    # 7. Persist WorkItem record
    work_item = WorkItem(
        organization_id=org_id,
        idempotency_key=effective_idempotency_key,
        work_type=envelope.work_type,
        title=payload.title,
        description=payload.description,
        status=WorkItemStatus.CREATED,
        priority=payload.priority or "medium",
        requester_id=current_user.id,
        service_id=service_uuid,
        environment_id=env_uuid,
        region_id=payload.region_id,
        target_files=envelope.target_files,
        workflow=envelope.workflow,
        confidence=envelope.confidence,
        requires_runtime_evidence=envelope.requires_runtime_evidence,
        runtime_evidence_reason=envelope.runtime_evidence_reason,
        requires_code_change=envelope.requires_code_change,
        envelope=envelope.model_dump(),
    )
    db.add(work_item)
    db.flush()

    # 8. Associate repositories
    if payload.repository_ids:
        for idx, repo_id_str in enumerate(payload.repository_ids):
            try:
                r_uuid = uuid.UUID(repo_id_str)
            except ValueError:
                continue
            repo_record = db.query(Repository).filter(Repository.id == r_uuid).first()
            if repo_record:
                work_item_repo = WorkItemRepository(
                    work_item_id=work_item.id,
                    repository_id=repo_record.id,
                    role="primary" if idx == 0 else "secondary",
                    is_primary=(idx == 0),
                    selection_reason="User specified repository scope",
                    confidence=1.0,
                )
                db.add(work_item_repo)

    # 9. Route work item to workflow
    decision = await route_work_item(work_item=work_item, envelope=envelope, db=db)

    db.refresh(work_item)
    resp = _serialize_work_item(work_item)
    resp.job_id = decision.job_id
    return resp


@router.post("/classify", response_model=Union[WorkTypeEnvelope, ClarificationResponse])
async def dry_run_classify(
    payload: WorkItemCreate,
    current_user: User = Depends(get_current_user),
):
    """
    Stateless dry-run intent classification endpoint.
    Returns classified WorkTypeEnvelope or ClarificationResponse without writing to the database.
    """
    force_type = payload.force_work_type if current_user.role == "admin" else None
    envelope = await classify_intent(
        title=payload.title,
        description=payload.description,
        target_files=payload.target_files,
        force_work_type=force_type,
    )
    if envelope.work_type == WorkType.NEEDS_CLARIFICATION or envelope.confidence < 0.70:
        return ClarificationResponse(
            status="needs_clarification",
            work_type=WorkType.NEEDS_CLARIFICATION,
            confidence=envelope.confidence,
            reason=envelope.rationale or "Ambiguous request",
            questions=envelope.questions or ["Please clarify your goal."],
        )
    return envelope


@router.get("", response_model=List[WorkItemResponse])
async def list_work_items(
    work_type: Optional[WorkType] = None,
    status: Optional[WorkItemStatus] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List work items for the authenticated user's organization with optional filters.
    """
    if not current_user.organization_id:
        return []

    query = db.query(WorkItem).filter(WorkItem.organization_id == current_user.organization_id)
    if work_type:
        query = query.filter(WorkItem.work_type == work_type)
    if status:
        query = query.filter(WorkItem.status == status)

    items = query.order_by(WorkItem.created_at.desc()).offset(offset).limit(limit).all()
    return [_serialize_work_item(item) for item in items]


@router.get("/{id}", response_model=WorkItemResponse)
async def get_work_item(
    id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve single work item by ID with organization tenant check.
    """
    try:
        item_uuid = uuid.UUID(id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid work item ID format.")

    item = db.query(WorkItem).filter(WorkItem.id == item_uuid).first()
    if not item:
        raise HTTPException(status_code=404, detail="Work item not found.")

    if current_user.organization_id != item.organization_id:
        raise HTTPException(status_code=403, detail="Access denied to work item in another organization.")

    return _serialize_work_item(item)


@router.patch("/{id}/status", response_model=WorkItemResponse)
async def update_work_item_status(
    id: str,
    payload: StatusUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Controlled work item status transitions (e.g. unblocking with clarification or cancelling).
    """
    try:
        item_uuid = uuid.UUID(id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid work item ID format.")

    item = db.query(WorkItem).filter(WorkItem.id == item_uuid).first()
    if not item:
        raise HTTPException(status_code=404, detail="Work item not found.")

    if current_user.organization_id != item.organization_id:
        raise HTTPException(status_code=403, detail="Access denied.")

    # Validate transition against client-permitted state machine rules
    validate_status_transition(item.status, payload.status, is_client_request=True)

    item.status = payload.status
    db.commit()
    db.refresh(item)
    return _serialize_work_item(item)
