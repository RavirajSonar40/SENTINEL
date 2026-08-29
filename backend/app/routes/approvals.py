"""
Approval Lifecycle REST API Routes (Phase 13).
Provides multi-tenant approval queries, compliance checklist inspection,
and transactional quorum decision submissions.
"""

from typing import Dict, List, Optional, Any
from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from pydantic import BaseModel
import logging

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.permissions import get_active_membership, require_operator, require_viewer
from app.models.incident import (
    Incident, Investigation, ProposedFix, Approval, ApprovalDecision,
    AuditEvent, ValidationRun, User, ApprovalStatus, FixStatus,
)
from app.schemas.policy import (
    ApprovalRequestOut, ApprovalDecisionRequest, ApprovalDecisionOut,
    ComplianceChecklistOut,
)
from app.services.approval_service import (
    create_approval_request, submit_approval_decision,
    invalidate_stale_approvals_for_fix, compile_compliance_checklist,
)

logger = logging.getLogger("sentinel.approvals")

router = APIRouter(prefix="/approvals", tags=["approvals"])


class LegacyApprovalRequest(BaseModel):
    fix_id: str
    action: str  # approve, reject, request_changes
    comment: Optional[str] = None


class LegacyApprovalResponse(BaseModel):
    status: str
    approval_id: str
    message: str


@router.get("", response_model=List[ApprovalRequestOut])
def list_approvals(
    status_filter: Optional[str] = None,
    fix_id: Optional[UUID] = None,
    incident_id: Optional[UUID] = None,
    context=Depends(get_active_membership),
    db: Session = Depends(get_db),
):
    """List approval requests for the active organization with optional filters."""
    org, membership = context
    query = db.query(Approval).filter(Approval.organization_id == org.id)

    if status_filter:
        stat_clean = status_filter.lower()
        if stat_clean == "pending":
            query = query.filter(Approval.status == ApprovalStatus.PENDING)
        elif stat_clean == "approved":
            query = query.filter(Approval.status == ApprovalStatus.APPROVED)
        elif stat_clean == "rejected":
            query = query.filter(Approval.status == ApprovalStatus.REJECTED)
        elif stat_clean == "changes_requested":
            query = query.filter(Approval.status == ApprovalStatus.CHANGES_REQUESTED)
        elif stat_clean == "stale":
            query = query.filter(Approval.status == ApprovalStatus.INVALIDATED_STALE)

    if fix_id:
        query = query.filter(Approval.fix_id == fix_id)

    if incident_id:
        query = query.filter(Approval.incident_id == incident_id)

    approvals = query.order_by(Approval.requested_at.desc()).all()
    results = []
    for app in approvals:
        results.append(_format_approval_out(app, db))
    return results


@router.get("/pending")
def list_pending_approvals_legacy(
    context=Depends(get_active_membership),
    db: Session = Depends(get_db),
):
    """Compatibility endpoint: list all pending approval requests."""
    org, membership = context
    approvals = db.query(Approval).filter(
        Approval.organization_id == org.id,
        Approval.status == ApprovalStatus.PENDING,
    ).order_by(Approval.requested_at.desc()).all()

    results = []
    for app in approvals:
        fix = app.fix
        results.append({
            "approval_id": str(app.id),
            "fix_id": str(app.fix_id) if app.fix_id else None,
            "title": fix.title if fix else "Approval Request",
            "description": fix.description if fix else "",
            "risk_level": app.risk_level,
            "required_approvals": app.required_approvals,
            "approvals_received": app.approvals_received,
            "patch_version": app.patch_version,
            "status": app.status.value if hasattr(app.status, "value") else str(app.status),
            "requested_at": app.requested_at.isoformat() if app.requested_at else None,
        })
    return results


@router.get("/{approval_id}", response_model=ApprovalRequestOut)
def get_approval_detail(
    approval_id: UUID,
    context=Depends(get_active_membership),
    db: Session = Depends(get_db),
):
    """Retrieve full details of an approval request including compliance checklist and decisions."""
    org, membership = context
    approval = db.query(Approval).filter(
        Approval.id == approval_id,
        Approval.organization_id == org.id,
    ).first()

    if not approval:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found.")

    return _format_approval_out(approval, db)


@router.post("/request/{fix_id}", response_model=ApprovalRequestOut, status_code=status.HTTP_201_CREATED)
def request_approval_for_fix(
    fix_id: UUID,
    notes: Optional[str] = None,
    context=Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Request human operator approval for a proposed fix."""
    org, membership = context
    current_user = membership.user if hasattr(membership, "user") and membership.user else None

    fix = db.query(ProposedFix).filter(
        ProposedFix.id == fix_id,
        ProposedFix.organization_id == org.id,
    ).first()

    if not fix:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposed fix not found.")

    approval = create_approval_request(
        db=db,
        organization_id=org.id,
        fix=fix,
        actor=current_user,
        action_type="create_draft_pr",
        notes=notes,
    )
    return _format_approval_out(approval, db)


@router.post("/{approval_id}/decision", response_model=ApprovalRequestOut)
@router.post("/{approval_id}/decide", response_model=ApprovalRequestOut)
def record_decision(
    approval_id: UUID,
    payload: ApprovalDecisionRequest,
    context=Depends(require_operator),
    db: Session = Depends(get_db),
):
    """
    Submit an approval decision (approved, rejected, changes_requested)
    with transactional row locking and quorum counting.
    """
    org, membership = context
    current_user = membership.user if hasattr(membership, "user") and membership.user else None
    if not current_user:
        current_user = db.query(User).filter(User.id == membership.user_id).first()

    approval, decision_rec = submit_approval_decision(
        db=db,
        approval_id=approval_id,
        approver=current_user,
        decision_type=payload.decision,
        notes=payload.notes,
    )
    return _format_approval_out(approval, db)


@router.post("", response_model=LegacyApprovalResponse)
def submit_legacy_approval(
    request: LegacyApprovalRequest,
    context=Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Legacy approval endpoint: maps action to decision."""
    org, membership = context
    current_user = membership.user if hasattr(membership, "user") and membership.user else None
    if not current_user:
        current_user = db.query(User).filter(User.id == membership.user_id).first()

    fix = db.query(ProposedFix).filter(ProposedFix.id == request.fix_id).first()
    if not fix or fix.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Fix not found")

    # Find active pending approval or create one
    approval = db.query(Approval).filter(
        Approval.fix_id == fix.id,
        Approval.status == ApprovalStatus.PENDING,
    ).first()
    if not approval:
        approval = create_approval_request(
            db=db,
            organization_id=org.id,
            fix=fix,
            actor=current_user,
            action_type="create_draft_pr",
            notes=request.comment,
        )

    action_map = {
        "approve": "approved",
        "reject": "rejected",
        "request_changes": "changes_requested",
    }
    decision_clean = action_map.get(request.action.lower(), request.action.lower())

    approval, _ = submit_approval_decision(
        db=db,
        approval_id=approval.id,
        approver=current_user,
        decision_type=decision_clean,
        notes=request.comment,
    )

    return LegacyApprovalResponse(
        status="submitted",
        approval_id=str(approval.id),
        message=f"Decision '{decision_clean}' recorded for fix",
    )


@router.get("/{fix_id}/history")
def get_fix_approval_history(
    fix_id: UUID,
    context=Depends(get_active_membership),
    db: Session = Depends(get_db),
):
    """Get all approval history and decisions for a fix."""
    org, membership = context
    approvals = db.query(Approval).filter(
        Approval.fix_id == fix_id,
        Approval.organization_id == org.id,
    ).order_by(Approval.requested_at.desc()).all()

    return [_format_approval_out(a, db) for a in approvals]


def _format_approval_out(approval: Approval, db: Session) -> ApprovalRequestOut:
    """Helper to convert Approval ORM to ApprovalRequestOut schema."""
    decisions_out = []
    if approval.decisions:
        for d in approval.decisions:
            approver = d.approver
            decisions_out.append(ApprovalDecisionOut(
                id=d.id,
                approval_id=d.approval_id,
                approver_id=d.approver_id,
                approver_name=getattr(approver, "full_name", None) or getattr(approver, "username", "Operator"),
                approver_email=getattr(approver, "email", None),
                role=d.role,
                decision=d.decision,
                notes=d.notes,
                created_at=d.created_at,
            ))

    checklist_obj = None
    if approval.compliance_checklist_json:
        checklist_obj = ComplianceChecklistOut(**approval.compliance_checklist_json)

    stat_val = approval.status.value if hasattr(approval.status, "value") else str(approval.status)

    return ApprovalRequestOut(
        id=approval.id,
        organization_id=approval.organization_id,
        incident_id=approval.incident_id,
        fix_id=approval.fix_id,
        work_item_id=approval.work_item_id,
        action_type=approval.action_type,
        status=stat_val,
        risk_level=approval.risk_level,
        patch_version=approval.patch_version or 1,
        snapshot_hash=approval.snapshot_hash,
        base_commit_sha=approval.base_commit_sha,
        validation_run_id=approval.validation_run_id,
        required_approvals=approval.required_approvals or 1,
        approvals_received=approval.approvals_received or 0,
        compliance_checklist=checklist_obj,
        decisions=decisions_out,
        notes=approval.notes,
        requested_at=approval.requested_at,
        decided_at=approval.decided_at,
        expires_at=approval.expires_at,
    )
