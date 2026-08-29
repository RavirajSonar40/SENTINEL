"""
Pydantic Schemas for Policy Gateway & Approval Lifecycle (Phase 13).
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class PolicyRuleCreate(BaseModel):
    name: str = Field(..., max_length=255, description="Rule name")
    description: Optional[str] = None
    action_type: str = Field(..., description="Action type (e.g., create_draft_pr, modify_infrastructure, database_migration)")
    decision: str = Field(..., description="Decision: allow, block, require_human, multi_approval, security_approval")
    conditions_json: Optional[Dict[str, Any]] = None
    required_approvals_count: int = Field(1, ge=1, le=10)
    required_roles_json: Optional[List[str]] = None
    priority: int = Field(100, ge=1, le=1000)
    is_active: bool = True


class PolicyRuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    decision: Optional[str] = None
    conditions_json: Optional[Dict[str, Any]] = None
    required_approvals_count: Optional[int] = None
    required_roles_json: Optional[List[str]] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


class PolicyRuleOut(BaseModel):
    id: UUID
    organization_id: Optional[UUID] = None
    name: str
    description: Optional[str] = None
    action_type: str
    decision: str
    conditions_json: Optional[Dict[str, Any]] = None
    required_approvals_count: int = 1
    required_roles_json: Optional[List[str]] = None
    priority: int = 100
    is_active: bool = True
    is_mandatory: bool = False
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PolicyStepCheck(BaseModel):
    step_number: int
    name: str
    status: str  # passed, failed, warning, required_action
    message: str
    details: Optional[Dict[str, Any]] = None


class PolicyEvaluationRequest(BaseModel):
    action_type: str
    fix_id: Optional[UUID] = None
    work_item_id: Optional[UUID] = None
    incident_id: Optional[UUID] = None
    target_branch: Optional[str] = "main"
    context: Optional[Dict[str, Any]] = None


class PolicyEvaluationResultOut(BaseModel):
    action_type: str
    decision: str  # allow, block, require_human, multi_approval, security_approval
    allowed: bool
    requires_approval: bool
    required_approvals_count: int = 1
    required_roles: List[str] = []
    risk_level: str = "low"
    steps: List[PolicyStepCheck]
    matched_rule: Optional[str] = None
    reasons: List[str] = []
    fix_id: Optional[UUID] = None
    patch_version: Optional[int] = None
    snapshot_hash: Optional[str] = None
    base_commit_sha: Optional[str] = None
    evaluated_at: datetime = Field(default_factory=datetime.utcnow)


class ComplianceChecklistOut(BaseModel):
    scope_contained: bool = True
    ast_syntax_valid: bool = True
    secrets_clean: bool = True
    diff_bloat_acceptable: bool = True
    base_sha_verified: bool = True
    pre_patch_reproduced: bool = True
    post_patch_regressions_passed: bool = True
    details: Optional[Dict[str, Any]] = None


class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(..., description="Decision: approved, rejected, changes_requested")
    notes: Optional[str] = None


class ApprovalDecisionOut(BaseModel):
    id: UUID
    approval_id: UUID
    approver_id: UUID
    approver_name: Optional[str] = None
    approver_email: Optional[str] = None
    role: Optional[str] = None
    decision: str
    notes: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ApprovalRequestOut(BaseModel):
    id: UUID
    organization_id: UUID
    incident_id: Optional[UUID] = None
    fix_id: Optional[UUID] = None
    work_item_id: Optional[UUID] = None
    action_type: str
    status: str  # pending, approved, rejected, changes_requested, invalidated_stale, cancelled, expired
    risk_level: str
    patch_version: int = 1
    snapshot_hash: Optional[str] = None
    base_commit_sha: Optional[str] = None
    validation_run_id: Optional[UUID] = None
    required_approvals: int = 1
    approvals_received: int = 0
    compliance_checklist: Optional[ComplianceChecklistOut] = None
    decisions: List[ApprovalDecisionOut] = []
    notes: Optional[str] = None
    requested_at: datetime
    decided_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True
