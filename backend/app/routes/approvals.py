"""Human approval workflow — approve/reject proposed fixes and PRs."""
from typing import Dict, List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.incident import (
    Incident, Investigation, ProposedFix, Approval, AuditEvent,
    User, ApprovalStatus, FixStatus, IncidentStatus,
)

router = APIRouter()


class ApprovalRequest(BaseModel):
    fix_id: str
    action: str  # approve, reject, request_changes
    comment: Optional[str] = None


class ApprovalResponse(BaseModel):
    status: str
    approval_id: str
    message: str


# --- Approval Logic ---

def process_approval(
    fix_id: str,
    action: str,
    user: User,
    comment: Optional[str],
    db: Session,
) -> Dict:
    """Process an approval/rejection for a fix."""
    fix = db.query(ProposedFix).filter(ProposedFix.id == fix_id).first()
    if not fix:
        raise HTTPException(status_code=404, detail="Fix not found")

    # Map action to status
    status_map = {
        "approve": ApprovalStatus.APPROVED,
        "reject": ApprovalStatus.REJECTED,
        "request_changes": ApprovalStatus.MODIFIED,
    }
    approval_status = status_map.get(action)
    if not approval_status:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")

    # Create approval record
    approval = Approval(
        fix_id=fix_id,
        user_id=user.id,
        incident_id=fix.incident_id,
        status=approval_status,
        notes=comment or "",
    )
    db.add(approval)

    # Update fix status
    if action == "approve":
        fix.status = FixStatus.APPROVED.value
    elif action == "reject":
        fix.status = FixStatus.REJECTED.value
    elif action == "request_changes":
        fix.status = FixStatus.CHANGES_REQUESTED.value

    # Audit event
    audit = AuditEvent(
        event_type=f"fix.{action}",
        description=f"Fix {action}: {fix.title}",
        user_id=user.id,
        incident_id=fix.incident_id,
        metadata_json={"comment": comment, "fix_id": fix_id},
    )
    db.add(audit)
    db.commit()

    return {
        "fix_id": fix_id,
        "action": action,
        "approval_id": approval.id,
        "fix_status": fix.status,
    }


def check_auto_merge_eligibility(fix: ProposedFix) -> bool:
    """Check if a fix is eligible for auto-merge."""
    if fix.fix_type not in ("dependency_update", "rollback"):
        return False

    # Check if approved
    if fix.status != FixStatus.APPROVED.value:
        return False

    return True


# --- API Endpoints ---

@router.post("/approvals")
async def submit_approval(
    request: ApprovalRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit an approval/rejection for a proposed fix."""
    result = process_approval(
        request.fix_id,
        request.action,
        current_user,
        request.comment,
        db,
    )
    return ApprovalResponse(
        status="submitted",
        approval_id=result["approval_id"],
        message=f"Fix {request.action}d successfully",
    )


@router.get("/approvals/pending")
async def list_pending_approvals(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all fixes awaiting approval."""
    fixes = db.query(ProposedFix).filter(
        ProposedFix.status == FixStatus.GENERATED.value,
    ).all()

    results = []
    for fix in fixes:
        investigation = db.query(Investigation).filter(
            Investigation.id == fix.investigation_id
        ).first()
        incident = None
        if investigation:
            incident = db.query(Incident).filter(
                Incident.id == investigation.incident_id
            ).first()

        results.append({
            "fix_id": fix.id,
            "title": fix.title,
            "description": fix.description,
            "fix_type": fix.fix_type,
            "investigation_id": fix.investigation_id,
            "incident_number": incident.number if incident else None,
            "incident_title": incident.title if incident else None,
            "auto_merge_eligible": check_auto_merge_eligibility(fix),
            "created_at": fix.generated_at.isoformat() if fix.generated_at else None,
        })

    return results


@router.get("/approvals/{fix_id}/history")
async def get_approval_history(
    fix_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get approval history for a fix."""
    approvals = db.query(Approval).filter(
        Approval.fix_id == fix_id
    ).order_by(Approval.requested_at.desc()).all()

    return [
        {
            "id": a.id,
            "user_id": a.user_id,
            "status": a.status,
            "comment": a.notes,
            "created_at": a.requested_at.isoformat() if a.requested_at else None,
        }
        for a in approvals
    ]


@router.post("/approvals/bulk")
async def bulk_approval(
    fix_ids: List[str],
    action: str,
    comment: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bulk approve/reject multiple fixes."""
    results = []
    for fix_id in fix_ids:
        try:
            result = process_approval(fix_id, action, current_user, comment, db)
            results.append({"fix_id": fix_id, "status": "success", **result})
        except HTTPException as e:
            results.append({"fix_id": fix_id, "status": "error", "message": e.detail})

    return {"results": results, "total": len(results)}
