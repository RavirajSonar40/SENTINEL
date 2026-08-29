"""Pydantic Schemas for Phase 14 Multi-Repository Remediation.

Defines:
1. Candidate repository resolution and multi-factor scoring outputs.
2. Parent-child investigation fan-out requests and responses.
3. Multi-repository remediation plan creation, topological items, and status tracking.
4. Coordinated Draft PR publishing requests and per-repository partial-failure results.
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class CandidateRepositoryOut(BaseModel):
    """Scored candidate repository resolved for an incident."""
    model_config = ConfigDict(from_attributes=True)

    repository_id: str
    name: str
    full_name: str
    role: str  # primary_defect, downstream_affected, configuration, evidence_only
    score: float = Field(..., ge=0.0, le=1.0)
    reasons: List[str] = Field(default_factory=list)
    requires_code_change: bool = True
    base_commit_sha: Optional[str] = None
    service_id: Optional[str] = None
    service_name: Optional[str] = None


class MultiRepoResolveRequest(BaseModel):
    """Request to resolve candidate repositories for an incident."""
    incident_id: str
    threshold: float = Field(default=0.50, ge=0.0, le=1.0)


class MultiRepoResolveResponse(BaseModel):
    """Response containing scored candidate repositories."""
    incident_id: str
    candidates: List[CandidateRepositoryOut]
    total_candidates: int


class ChildInvestigationOut(BaseModel):
    """Representation of a child investigation linked to a specific repository."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    parent_investigation_id: Optional[str] = None
    repository_id: Optional[str] = None
    repository_name: Optional[str] = None
    repository_role: Optional[str] = None
    base_commit_sha: Optional[str] = None
    status: str
    workflow_type: str
    progress_percent: int = 0
    created_at: Optional[datetime] = None


class MultiRepoFanOutRequest(BaseModel):
    """Request to fan out child investigations across resolved candidate repositories."""
    parent_investigation_id: Optional[str] = None
    candidate_repository_ids: Optional[List[str]] = None
    idempotency_key: Optional[str] = None


class MultiRepoFanOutResponse(BaseModel):
    """Response from child investigation fan-out."""
    parent_investigation_id: str
    child_investigations: List[ChildInvestigationOut]
    message: str


class RemediationPlanItemOut(BaseModel):
    """Status and metadata for an individual repository in a remediation plan."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    repository_id: str
    repository_name: Optional[str] = None
    repository_role: str
    investigation_id: Optional[str] = None
    fix_id: Optional[str] = None
    execution_order: int
    requires_code_change: bool
    validation_status: str
    approval_status: str
    patch_version: Optional[int] = None
    snapshot_hash: Optional[str] = None
    base_commit_sha: Optional[str] = None
    pr_status: str
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None
    commit_sha: Optional[str] = None
    error_message: Optional[str] = None


class RemediationPlanOut(BaseModel):
    """Coordinated multi-repository remediation plan."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    incident_id: str
    parent_investigation_id: Optional[str] = None
    status: str
    title: str
    summary: str
    dependency_order: List[str] = Field(default_factory=list)
    cycle_detected: bool = False
    cycle_details: Optional[Dict[str, Any]] = None
    cross_repo_rollback_plan: Optional[str] = None
    items: List[RemediationPlanItemOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: Optional[datetime] = None


class RemediationPlanCreateRequest(BaseModel):
    """Request to compile a coordinated multi-repository remediation plan."""
    incident_id: str
    parent_investigation_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    override_dependency_order: Optional[List[str]] = None


class MultiRepoPRPublishRequest(BaseModel):
    """Request to publish Draft PRs across all plan items."""
    plan_id: str
    idempotency_key: Optional[str] = None
    branch_name_prefix: Optional[str] = "sentinel/remediation"


class MultiRepoPRItemResult(BaseModel):
    """Per-repository result of Draft PR publishing."""
    repository_id: str
    repository_name: str
    pr_status: str  # created, failed, skipped_evidence_only
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None
    commit_sha: Optional[str] = None
    error_message: Optional[str] = None


class MultiRepoPRPublishResponse(BaseModel):
    """Response summarizing multi-repository PR publishing results."""
    plan_id: str
    overall_status: str  # completed, partially_failed, failed
    items: List[MultiRepoPRItemResult]
    rollback_instructions: Optional[str] = None
    message: str
