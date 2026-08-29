"""REST API Routes for Phase 14 Multi-Repository Remediation.

Provides:
1. Candidate repository resolution and 9-factor scoring.
2. Parent-child investigation fan-out and tracking.
3. Multi-repository remediation plan compilation with cycle detection.
4. Coordinated Draft PR publishing with partial-failure tracking.
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.permissions import require_operator, require_viewer
from app.models.incident import (
    User,
    Incident,
    Investigation,
    Repository,
    MultiRepoRemediationPlan,
    RemediationPlanItem,
    RemediationPlanStatus,
)
from app.schemas.multi_repo import (
    MultiRepoResolveRequest,
    MultiRepoResolveResponse,
    MultiRepoFanOutRequest,
    MultiRepoFanOutResponse,
    ChildInvestigationOut,
    RemediationPlanCreateRequest,
    RemediationPlanOut,
    RemediationPlanItemOut,
    MultiRepoPRPublishRequest,
    MultiRepoPRPublishResponse,
)
from app.services.multi_repo_resolver import resolve_candidate_repositories
from app.services.multi_repo_coordinator import (
    fan_out_child_investigations,
    validate_child_base_sha_for_remediation,
)
from app.services.multi_repo_orchestrator import (
    create_multi_repo_remediation_plan,
    publish_multi_repo_draft_prs,
)

logger = logging.getLogger("sentinel.routes.multi_repo")

router = APIRouter(prefix="/multi-repo", tags=["Multi-Repository Remediation"])


def _format_plan_out(plan: MultiRepoRemediationPlan, db: Session) -> RemediationPlanOut:
    items_out = []
    for item in plan.items:
        repo = db.query(Repository).filter(Repository.id == item.repository_id).first()
        items_out.append(RemediationPlanItemOut(
            id=str(item.id),
            repository_id=str(item.repository_id),
            repository_name=repo.full_name if repo else str(item.repository_id),
            repository_role=item.repository_role,
            investigation_id=str(item.investigation_id) if item.investigation_id else None,
            fix_id=str(item.fix_id) if item.fix_id else None,
            execution_order=item.execution_order,
            requires_code_change=item.requires_code_change,
            validation_status=item.validation_status,
            approval_status=item.approval_status,
            patch_version=item.patch_version,
            snapshot_hash=item.snapshot_hash,
            base_commit_sha=item.base_commit_sha,
            pr_status=item.pr_status,
            pr_url=item.pr_url,
            pr_number=item.pr_number,
            commit_sha=item.commit_sha,
            error_message=item.error_message,
        ))

    return RemediationPlanOut(
        id=str(plan.id),
        organization_id=str(plan.organization_id),
        incident_id=str(plan.incident_id),
        parent_investigation_id=str(plan.parent_investigation_id) if plan.parent_investigation_id else None,
        status=plan.status.value if hasattr(plan.status, "value") else str(plan.status),
        title=plan.title,
        summary=plan.summary,
        dependency_order=plan.dependency_order_json or [],
        cycle_detected=plan.cycle_detected,
        cycle_details=plan.cycle_details_json,
        cross_repo_rollback_plan=plan.cross_repo_rollback_plan,
        items=items_out,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


@router.post("/resolve-candidates", response_model=MultiRepoResolveResponse)
def resolve_candidates(
    req: MultiRepoResolveRequest,
    db: Session = Depends(get_db),
    context=Depends(require_viewer),
):
    """Resolve and score candidate repositories for an incident."""
    try:
        inc_uuid = UUID(req.incident_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid incident_id format")

    org, membership = context
    org_id = org.id

    # Tenant check
    incident = db.query(Incident).filter(
        Incident.id == inc_uuid,
        Incident.organization_id == org_id,
    ).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found in organization")

    candidates = resolve_candidate_repositories(
        db=db,
        incident_id=inc_uuid,
        organization_id=org_id,
        threshold=req.threshold,
    )

    return MultiRepoResolveResponse(
        incident_id=str(inc_uuid),
        candidates=candidates,
        total_candidates=len(candidates),
    )


@router.post("/incidents/{incident_id}/fan-out", response_model=MultiRepoFanOutResponse)
def fan_out_investigations(
    incident_id: str,
    req: MultiRepoFanOutRequest,
    db: Session = Depends(get_db),
    context=Depends(require_operator),
):
    """Idempotently fan out child investigations across affected repositories."""
    try:
        inc_uuid = UUID(incident_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid incident_id format")

    org, membership = context
    org_id = org.id
    current_user = db.query(User).filter(User.id == membership.user_id).first()

    parent_inv, child_invs = fan_out_child_investigations(
        db=db,
        incident_id=inc_uuid,
        organization_id=org_id,
        actor=current_user,
        candidate_repo_ids=req.candidate_repository_ids,
        idempotency_key=req.idempotency_key,
    )

    children_out = []
    for c in child_invs:
        repo = db.query(Repository).filter(Repository.id == c.repository_id).first()
        children_out.append(ChildInvestigationOut(
            id=str(c.id),
            parent_investigation_id=str(c.parent_investigation_id) if c.parent_investigation_id else None,
            repository_id=str(c.repository_id) if c.repository_id else None,
            repository_name=repo.full_name if repo else str(c.repository_id),
            repository_role=c.repository_role,
            base_commit_sha=c.base_commit_sha,
            status=c.status.value if hasattr(c.status, "value") else str(c.status),
            workflow_type=c.workflow_type,
            progress_percent=c.progress_percent,
            created_at=c.created_at,
        ))

    return MultiRepoFanOutResponse(
        parent_investigation_id=str(parent_inv.id),
        child_investigations=children_out,
        message=f"Successfully fanned out {len(children_out)} child investigation(s).",
    )


@router.get("/incidents/{incident_id}/investigations")
def list_incident_investigations(
    incident_id: str,
    db: Session = Depends(get_db),
    context=Depends(require_viewer),
):
    """List all parent and child investigations for an incident."""
    try:
        inc_uuid = UUID(incident_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid incident_id format")

    org, membership = context
    org_id = org.id

    # Tenant check
    incident = db.query(Incident).filter(
        Incident.id == inc_uuid,
        Incident.organization_id == org_id,
    ).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    parent_inv = db.query(Investigation).filter(
        Investigation.incident_id == inc_uuid,
        Investigation.organization_id == org_id,
        Investigation.parent_investigation_id == None,
    ).first()

    children = []
    if parent_inv:
        children = db.query(Investigation).filter(
            Investigation.parent_investigation_id == parent_inv.id,
            Investigation.organization_id == org_id,
        ).all()

    return {
        "incident_id": str(inc_uuid),
        "parent_investigation": {
            "id": str(parent_inv.id) if parent_inv else None,
            "status": parent_inv.status.value if (parent_inv and hasattr(parent_inv.status, "value")) else None,
            "is_parent": True,
        } if parent_inv else None,
        "child_investigations": [
            {
                "id": str(c.id),
                "repository_id": str(c.repository_id) if c.repository_id else None,
                "repository_role": c.repository_role,
                "base_commit_sha": c.base_commit_sha,
                "status": c.status.value if hasattr(c.status, "value") else str(c.status),
                "workflow_type": c.workflow_type,
            }
            for c in children
        ],
    }


@router.post("/incidents/{incident_id}/remediation-plans", response_model=RemediationPlanOut)
def create_remediation_plan(
    incident_id: str,
    req: RemediationPlanCreateRequest,
    db: Session = Depends(get_db),
    context=Depends(require_operator),
):
    """Compile a coordinated MultiRepoRemediationPlan with cycle detection."""
    try:
        inc_uuid = UUID(incident_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid incident_id format")

    org, membership = context
    org_id = org.id

    parent_uuid = None
    if req.parent_investigation_id:
        try:
            parent_uuid = UUID(req.parent_investigation_id)
        except (ValueError, TypeError):
            pass

    plan = create_multi_repo_remediation_plan(
        db=db,
        incident_id=inc_uuid,
        organization_id=org_id,
        parent_investigation_id=parent_uuid,
        idempotency_key=req.idempotency_key,
        override_dependency_order=req.override_dependency_order,
    )

    return _format_plan_out(plan, db)


@router.get("/incidents/{incident_id}/remediation-plans", response_model=Optional[RemediationPlanOut])
def get_latest_remediation_plan(
    incident_id: str,
    db: Session = Depends(get_db),
    context=Depends(require_viewer),
):
    """Get the latest remediation plan for an incident."""
    try:
        inc_uuid = UUID(incident_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid incident_id format")

    org, membership = context
    org_id = org.id

    plan = db.query(MultiRepoRemediationPlan).filter(
        MultiRepoRemediationPlan.incident_id == inc_uuid,
        MultiRepoRemediationPlan.organization_id == org_id,
    ).order_by(MultiRepoRemediationPlan.created_at.desc()).first()

    if not plan:
        return None

    return _format_plan_out(plan, db)


@router.post("/remediation-plans/{plan_id}/generate-prs", response_model=MultiRepoPRPublishResponse)
async def publish_plan_prs(
    plan_id: str,
    req: MultiRepoPRPublishRequest,
    db: Session = Depends(get_db),
    context=Depends(require_operator),
):
    """Publish Draft PRs across all plan items in topological order."""
    try:
        p_uuid = UUID(plan_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid plan_id format")

    org, membership = context
    org_id = org.id
    current_user = db.query(User).filter(User.id == membership.user_id).first()

    res = await publish_multi_repo_draft_prs(
        db=db,
        plan_id=p_uuid,
        organization_id=org_id,
        actor=current_user,
        branch_prefix=req.branch_name_prefix or "sentinel/remediation",
    )
    return res

