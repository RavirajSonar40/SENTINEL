"""
Policy Gateway REST API Routes (Phase 13).
"""

from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.permissions import get_active_membership, require_admin, require_viewer, require_operator
from app.models.incident import (
    User, Organization, PolicyRule, ProposedFix, Incident, ActionType, PolicyDecision
)
from app.models.work_item import WorkItem
from app.schemas.policy import (
    PolicyRuleCreate, PolicyRuleUpdate, PolicyRuleOut,
    PolicyEvaluationRequest, PolicyEvaluationResultOut,
)
from app.services.policy_gateway import (
    evaluate_action_policy, MANDATORY_BLOCKED_ACTIONS
)

router = APIRouter(prefix="/policies", tags=["policies"])


@router.get("", response_model=List[PolicyRuleOut])
def list_policies(
    context=Depends(get_active_membership),
    db: Session = Depends(get_db),
):
    """List policy rules for the active organization plus system defaults."""
    org, membership = context
    rules = db.query(PolicyRule).filter(
        or_(PolicyRule.organization_id == org.id, PolicyRule.organization_id.is_(None)),
        PolicyRule.is_active == True,
    ).order_by(PolicyRule.priority.asc()).all()
    return rules


@router.post("", response_model=PolicyRuleOut, status_code=status.HTTP_201_CREATED)
def create_policy_rule(
    payload: PolicyRuleCreate,
    context=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Create a custom policy rule for the active organization.
    Strictly forbids overriding mandatory safety blocks (WRITE_PRODUCTION, MERGE_PR, DEPLOY, MODIFY_SECRETS).
    """
    org, membership = context
    action_type_clean = payload.action_type.lower()
    decision_clean = payload.decision.lower()

    if action_type_clean in MANDATORY_BLOCKED_ACTIONS:
        if decision_clean != "block":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Mandatory safety policy invariant cannot be overridden. Action '{action_type_clean}' is permanently blocked.",
            )

    rule = PolicyRule(
        organization_id=org.id,
        name=payload.name,
        description=payload.description,
        action_type=action_type_clean,
        decision=decision_clean,
        conditions_json=payload.conditions_json,
        required_approvals_count=payload.required_approvals_count,
        required_roles_json=payload.required_roles_json,
        priority=payload.priority,
        is_active=payload.is_active,
        is_mandatory=False,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.post("/evaluate", response_model=PolicyEvaluationResultOut)
def evaluate_policy(
    payload: PolicyEvaluationRequest,
    context=Depends(get_active_membership),
    db: Session = Depends(get_db),
):
    """Dry-run policy evaluation on a proposed fix or work item."""
    org, membership = context
    current_user = membership.user if hasattr(membership, "user") and membership.user else None

    fix = None
    if payload.fix_id:
        fix = db.query(ProposedFix).filter(ProposedFix.id == payload.fix_id).first()
        if fix and fix.organization_id != org.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposed fix not found.")

    work_item = None
    if payload.work_item_id:
        work_item = db.query(WorkItem).filter(WorkItem.id == payload.work_item_id).first()
        if work_item and work_item.organization_id != org.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work item not found.")

    incident = None
    if payload.incident_id:
        incident = db.query(Incident).filter(Incident.id == payload.incident_id).first()
        if incident and incident.organization_id != org.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found.")

    return evaluate_action_policy(
        db=db,
        organization_id=org.id,
        actor=current_user,
        action_type=payload.action_type,
        fix=fix,
        work_item=work_item,
        incident=incident,
        target_branch=payload.target_branch,
        context=payload.context,
    )
