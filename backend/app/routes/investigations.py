"""
REST API Endpoints for Phase 8 Investigation Workflows.

Implements:
- POST /investigations/{id}/stream-ticket
- GET /investigations/{id}/stream (SSE with single-use ticket or Bearer auth)
- POST /investigations/{id}/start
- GET /investigations/{id}
- GET /investigations/{id}/tasks
- POST /investigations/{id}/pause
- POST /investigations/{id}/cancel
- POST /investigations/{id}/step
"""

import uuid
import logging
from typing import List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query, Header, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_user_from_token
from app.core.permissions import require_role
from app.models.incident import (
    Organization,
    UserOrganizationMembership,
    MembershipRole,
    Investigation,
    InvestigationTask,
    InvestigationStatus,
    User,
)
from app.schemas.investigations import (
    InvestigationStartRequest,
    InvestigationStepRequest,
    StreamTicketResponse,
    InvestigationDetailResponse,
    InvestigationTaskResponse,
)
from app.services.investigation_workflow_service import (
    generate_stream_ticket,
    consume_stream_ticket,
    subscribe_workflow_stream,
    transition_investigation_status,
    run_repository_task,
    run_bug_investigation,
    run_feature_implementation,
    run_production_investigation,
    run_security_investigation,
)

logger = logging.getLogger("sentinel.routes.investigations")

router = APIRouter(prefix="/investigations", tags=["Phase 8 - Investigation Workflows"])


# ============================================================================
# 1. STREAM TICKET & SSE STREAMING
# ============================================================================

@router.post("/{investigation_id}/stream-ticket", response_model=StreamTicketResponse)
def create_stream_ticket(
    investigation_id: uuid.UUID,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """Generate a single-use, 60s stream ticket for secure EventSource connections."""
    org, membership = auth_ctx
    inv = db.query(Investigation).filter(
        Investigation.organization_id == org.id,
        Investigation.id == investigation_id,
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")

    ticket = generate_stream_ticket(investigation_id, membership.user_id)
    return StreamTicketResponse(
        stream_ticket=ticket,
        investigation_id=investigation_id,
        expires_in_seconds=60,
    )


@router.get("/{investigation_id}/stream")
async def stream_investigation_progress(
    investigation_id: uuid.UUID,
    ticket: Optional[str] = Query(None, description="Single-use secure stream ticket"),
    authorization: Optional[str] = Header(None),
    last_event_id: Optional[int] = Header(None, alias="Last-Event-ID"),
    db: Session = Depends(get_db),
):
    """
    Server-Sent Events (SSE) stream for live workflow progress tracking.
    Authenticates via Authorization header or single-use stream ticket.
    """
    # 1. Authenticate via single-use ticket OR Authorization Header
    authenticated = False
    if ticket:
        if consume_stream_ticket(ticket, investigation_id):
            authenticated = True
        else:
            raise HTTPException(status_code=401, detail="Invalid or expired stream ticket")
    elif authorization and authorization.startswith("Bearer "):
        token_str = authorization.replace("Bearer ", "").strip()
        user = get_user_from_token(token_str, db)
        if user:
            # Check tenant isolation
            inv = db.query(Investigation).filter(Investigation.id == investigation_id).first()
            if inv:
                membership = db.query(UserOrganizationMembership).filter(
                    UserOrganizationMembership.organization_id == inv.organization_id,
                    UserOrganizationMembership.user_id == user.id,
                ).first()
                if membership:
                    authenticated = True

    if not authenticated:
        raise HTTPException(status_code=401, detail="Authentication required for investigation stream")

    return StreamingResponse(
        subscribe_workflow_stream(investigation_id, last_event_id, db=db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================================
# 2. WORKFLOW CONTROL (START, PAUSE, CANCEL, STEP)
# ============================================================================

@router.post("/{investigation_id}/start", response_model=InvestigationDetailResponse)
def start_investigation(
    investigation_id: uuid.UUID,
    payload: Optional[InvestigationStartRequest] = None,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.OPERATOR)),
    db: Session = Depends(get_db),
):
    """Start or resume execution of a type-specific investigation workflow."""
    org, membership = auth_ctx
    inv = db.query(Investigation).filter(
        Investigation.organization_id == org.id,
        Investigation.id == investigation_id,
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")

    if inv.status in (InvestigationStatus.COMPLETED, InvestigationStatus.ABSTAINED):
        return inv

    inv.started_by_user_id = membership.user_id
    db.commit()

    w_type = payload.workflow_type if (payload and payload.workflow_type) else inv.workflow_type
    lookback = payload.lookback_window_minutes if payload else 120

    if w_type == "repository_task":
        run_repository_task(db, org.id, inv.work_item_id or inv.id, inv.id)
    elif w_type == "bug":
        run_bug_investigation(db, org.id, inv.work_item_id or inv.id, inv.id)
    elif w_type == "feature":
        run_feature_implementation(db, org.id, inv.work_item_id or inv.id, inv.id)
    elif w_type == "security_incident":
        run_security_investigation(db, org.id, inv.work_item_id or inv.id, inv.id)
    else:  # production_incident
        run_production_investigation(db, org.id, inv.incident_id or inv.id, inv.id, lookback)

    db.refresh(inv)
    return inv


@router.post("/{investigation_id}/pause", response_model=InvestigationDetailResponse)
def pause_investigation(
    investigation_id: uuid.UUID,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.OPERATOR)),
    db: Session = Depends(get_db),
):
    """Pause an active investigation workflow."""
    org, _ = auth_ctx
    inv = db.query(Investigation).filter(
        Investigation.organization_id == org.id,
        Investigation.id == investigation_id,
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")

    transition_investigation_status(db, inv, InvestigationStatus.PAUSED)
    return inv


@router.post("/{investigation_id}/cancel", response_model=InvestigationDetailResponse)
def cancel_investigation(
    investigation_id: uuid.UUID,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.OPERATOR)),
    db: Session = Depends(get_db),
):
    """Cancel an investigation workflow immediately."""
    org, _ = auth_ctx
    inv = db.query(Investigation).filter(
        Investigation.organization_id == org.id,
        Investigation.id == investigation_id,
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")

    transition_investigation_status(db, inv, InvestigationStatus.CANCELLED)
    return inv


# ============================================================================
# 3. DETAILS & TASK STEP INSPECTION
# ============================================================================

@router.get("/{investigation_id}", response_model=InvestigationDetailResponse)
def get_investigation_detail(
    investigation_id: uuid.UUID,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """Get full state, progress, and tasks for an investigation."""
    org, _ = auth_ctx
    inv = db.query(Investigation).filter(
        Investigation.organization_id == org.id,
        Investigation.id == investigation_id,
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return inv


@router.get("/{investigation_id}/tasks", response_model=List[InvestigationTaskResponse])
def list_investigation_tasks(
    investigation_id: uuid.UUID,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """List discrete task step executions for an investigation."""
    org, _ = auth_ctx
    inv = db.query(Investigation).filter(
        Investigation.organization_id == org.id,
        Investigation.id == investigation_id,
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")

    tasks = db.query(InvestigationTask).filter(
        InvestigationTask.investigation_id == investigation_id,
    ).order_by(InvestigationTask.order.asc()).all()
    return tasks


# ============================================================================
# 4. EVALUATION & BENCHMARK DATASET (LEGACY ADAPTER)
# ============================================================================

@router.get("/eval/benchmark")
def get_benchmark_dataset_route():
    """Get the benchmark evaluation incidents dataset."""
    from app.services.benchmark_dataset import BENCHMARK_DATASET
    return [
        {
            "id": b.id,
            "title": b.title,
            "description": b.description,
            "service": b.service,
            "expected_root_cause": b.expected_root_cause,
            "expected_files": b.expected_files,
            "expected_commits": b.expected_commits,
            "severity": b.severity,
            "category": b.category,
            "difficulty": b.difficulty,
            "error_signature": b.error_signature,
        }
        for b in BENCHMARK_DATASET
    ]
