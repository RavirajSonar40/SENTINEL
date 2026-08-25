"""Feedback recording — store human feedback on investigations and fixes."""
from typing import Dict, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.incident import (
    Approval, AuditEvent, ProposedFix, Investigation,
    User, ApprovalStatus, FixStatus,
)


def record_approval_feedback(
    fix_id: str,
    action: str,
    user_id: str,
    comment: Optional[str] = None,
    modified_diff: Optional[str] = None,
    db: Session = None,
) -> Dict:
    """Record human feedback on a proposed fix."""
    if not db:
        return {"error": "No database session"}

    fix = db.query(ProposedFix).filter(ProposedFix.id == fix_id).first()
    if not fix:
        return {"error": "Fix not found"}

    # Map action to status
    status_map = {
        "approve": ApprovalStatus.APPROVED,
        "reject": ApprovalStatus.REJECTED,
        "request_changes": ApprovalStatus.MODIFIED,
    }
    approval_status = status_map.get(action, ApprovalStatus.PENDING)

    # Create approval record
    approval = Approval(
        fix_id=fix_id,
        incident_id=fix.incident_id,
        user_id=user_id,
        status=approval_status,
        notes=comment,
        modified_diff=modified_diff,
        requested_at=datetime.now(timezone.utc),
        decided_at=datetime.now(timezone.utc),
    )
    db.add(approval)

    # Update fix status
    if action == "approve":
        fix.status = FixStatus.APPROVED.value
    elif action == "reject":
        fix.status = FixStatus.REJECTED.value
    elif action == "request_changes":
        fix.status = FixStatus.CHANGES_REQUESTED.value

    # Record audit event
    audit = AuditEvent(
        incident_id=fix.incident_id,
        user_id=user_id,
        event_type=f"feedback.{action}",
        description=f"Human {action}d fix: {fix.title}",
        metadata={
            "fix_id": fix_id,
            "action": action,
            "comment": comment,
            "has_modifications": modified_diff is not None,
        },
        timestamp=datetime.now(timezone.utc),
    )
    db.add(audit)

    # Record outcome for learning
    outcome = {
        "fix_id": fix_id,
        "fix_type": fix.fix_type,
        "root_cause_category": None,
        "action": action,
        "had_comment": comment is not None,
        "had_modifications": modified_diff is not None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Get root cause category if available
    from app.models.incident import RootCause
    rc = db.query(RootCause).filter(RootCause.investigation_id == fix.investigation_id).first()
    if rc:
        outcome["root_cause_category"] = rc.category

    db.commit()

    return {
        "approval_id": approval.id,
        "outcome_recorded": True,
        "outcome": outcome,
    }


def get_feedback_stats(db: Session) -> Dict:
    """Get aggregate feedback statistics."""
    from sqlalchemy import func

    total = db.query(Approval).count()
    approved = db.query(Approval).filter(Approval.status == ApprovalStatus.APPROVED).count()
    rejected = db.query(Approval).filter(Approval.status == ApprovalStatus.REJECTED).count()
    modified = db.query(Approval).filter(Approval.status == ApprovalStatus.MODIFIED).count()

    return {
        "total_feedback": total,
        "approved": approved,
        "rejected": rejected,
        "modified": modified,
        "approval_rate": round(approved / max(total, 1) * 100, 1),
    }
