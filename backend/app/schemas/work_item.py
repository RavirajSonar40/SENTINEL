"""
Pydantic Schemas for Work Items and Intent Routing.

Implements Phase 2 Contract Envelopes and API request/response models.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from app.models.work_item import WorkType, WorkItemStatus


class WorkTypeEnvelope(BaseModel):
    """
    Contract envelope returned by Intent Router.
    Matches Section 8 of the Build Execution Plan.
    """
    work_type: WorkType
    confidence: float = Field(ge=0.0, le=1.0)
    repository_scope: List[str] = Field(default_factory=list)
    service_scope: List[str] = Field(default_factory=list)
    environment_scope: List[str] = Field(default_factory=list)
    region_scope: List[str] = Field(default_factory=list)
    target_files: List[str] = Field(default_factory=list)
    requires_runtime_evidence: bool = False
    runtime_evidence_reason: Optional[str] = None
    requires_code_change: bool = True
    workflow: str = "repository_task"
    summary: str = ""
    rationale: str = ""
    questions: Optional[List[str]] = None


class WorkItemRepositorySchema(BaseModel):
    """Repository association schema for responses."""
    repository_id: str
    repository_name: Optional[str] = None
    role: str = "primary"
    is_primary: bool = True
    selection_reason: Optional[str] = None
    confidence: float = 1.0


class WorkItemCreate(BaseModel):
    """Payload to create a new work item."""
    title: str = Field(..., min_length=3, max_length=500)
    description: Optional[str] = None
    priority: Optional[str] = "medium"
    repository_ids: Optional[List[str]] = None
    service_id: Optional[str] = None
    environment_id: Optional[str] = None
    region_id: Optional[str] = None
    target_files: Optional[List[str]] = None
    force_work_type: Optional[WorkType] = None
    idempotency_key: Optional[str] = None


class WorkItemResponse(BaseModel):
    """Standard successful work item creation/retrieval response."""
    id: str
    organization_id: str
    work_type: WorkType
    title: str
    description: Optional[str] = None
    status: WorkItemStatus
    priority: str
    target_files: List[str] = Field(default_factory=list)
    workflow: str
    confidence: float
    requires_runtime_evidence: bool
    runtime_evidence_reason: Optional[str] = None
    requires_code_change: bool
    envelope: Dict[str, Any] = Field(default_factory=dict)
    incident_id: Optional[str] = None
    job_id: Optional[str] = None
    repositories: List[WorkItemRepositorySchema] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ClarificationResponse(BaseModel):
    """Response returned when request is ambiguous or confidence < 0.70."""
    status: str = "needs_clarification"
    work_type: WorkType = WorkType.NEEDS_CLARIFICATION
    confidence: float
    reason: str
    questions: List[str]


class StatusUpdateRequest(BaseModel):
    """Payload for updating work item status."""
    status: WorkItemStatus
    clarification_answers: Optional[Dict[str, str]] = None
    reason: Optional[str] = None
