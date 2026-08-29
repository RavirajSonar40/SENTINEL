"""
Pydantic Schemas for Phase 9: Evidence & Root-Cause Analysis.
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid


class EvidenceItemCreate(BaseModel):
    title: str = Field(..., max_length=500, description="Short title describing the evidence")
    source_type: str = Field(default="manual", description="Origin of evidence (manual, telemetry, deployments, etc.)")
    category_type: str = Field(default="fact", description="Epistemic type: fact, inference, or conclusion")
    content: Optional[str] = Field(None, max_length=65536, description="Raw content, code snippet, or log body (max 64KB)")
    summary: Optional[str] = Field(None, max_length=2000, description="Human or AI summary of findings")
    service: Optional[str] = Field(None, max_length=255)
    environment: Optional[str] = Field(None, max_length=100)
    region: Optional[str] = Field(None, max_length=100)
    repository: Optional[str] = Field(None, max_length=255)
    commit_sha: Optional[str] = Field(None, max_length=40)
    file_path: Optional[str] = Field(None, max_length=500)
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    source_url: Optional[str] = Field(None, max_length=500)
    observed_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None


class EvidenceCorrectionRequest(BaseModel):
    supersedes_evidence_id: uuid.UUID
    title: str = Field(..., max_length=500)
    content: Optional[str] = Field(None, max_length=65536)
    summary: Optional[str] = Field(None, max_length=2000)
    correction_reason: str = Field(..., min_length=5, max_length=1000)


class EvidenceVerifyRequest(BaseModel):
    status: str = Field(..., description="'verified' or 'rejected'")
    notes: Optional[str] = Field(None, max_length=1000)


class EvidenceItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    incident_id: Optional[uuid.UUID] = None
    investigation_id: Optional[uuid.UUID] = None
    work_item_id: Optional[uuid.UUID] = None
    source_type: str
    category_type: str
    evidence_family: Optional[str] = None
    source_id: Optional[str] = None
    service: Optional[str] = None
    environment: Optional[str] = None
    region: Optional[str] = None
    repository: Optional[str] = None
    commit_sha: Optional[str] = None
    file_path: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    title: str
    content: Optional[str] = None
    summary: Optional[str] = None
    content_hash: Optional[str] = None
    is_redacted: bool = False
    payload_size_bytes: int = 0
    trust_level: str
    verification_status: str
    submitted_by_user_id: Optional[uuid.UUID] = None
    verified_by_user_id: Optional[uuid.UUID] = None
    verified_at: Optional[datetime] = None
    version: int = 1
    superseded_by_id: Optional[uuid.UUID] = None
    observed_at: Optional[datetime] = None
    timestamp: Optional[datetime] = None
    source_url: Optional[str] = None
    relevance_score: Optional[float] = None
    retrieval_method: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = None
    collected_at: datetime


class EvidenceListResponse(BaseModel):
    incident_id: uuid.UUID
    total_count: int
    facts_count: int
    inferences_count: int
    conclusions_count: int
    distinct_families: List[str]
    items: List[EvidenceItemResponse]


class HypothesisCreate(BaseModel):
    label: str = Field(..., max_length=100, description="e.g. H1, H2")
    description: str = Field(..., min_length=10, max_length=4000)
    supporting_evidence_ids: Optional[List[uuid.UUID]] = None


class HypothesisTriageRequest(BaseModel):
    status: str = Field(..., description="'supported', 'contradicted', 'disproven', 'accepted'")
    triage_notes: str = Field(..., min_length=5, max_length=2000)


class HypothesisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    incident_id: Optional[uuid.UUID] = None
    investigation_id: Optional[uuid.UUID] = None
    work_item_id: Optional[uuid.UUID] = None
    label: str
    description: str
    status: str
    confidence: str
    temporal_fit: bool
    temporal_fit_score: float
    code_path_fit: bool
    code_path_fit_score: float
    operational_fit: bool
    operational_fit_score: float
    distinct_families_count: int
    supporting_evidence_count: int
    contradicting_evidence_count: int
    missing_evidence_count: int
    supporting_evidence_ids: Optional[List[str]] = None
    contradicting_evidence_ids: Optional[List[str]] = None
    missing_evidence_json: Optional[List[str]] = None
    disproof_attempt_notes: Optional[str] = None
    disproven_at: Optional[datetime] = None
    human_triaged: bool = False
    human_triage_notes: Optional[str] = None
    triaged_by_user_id: Optional[uuid.UUID] = None
    evaluation_notes: Optional[str] = None
    created_at: datetime
    evaluated_at: Optional[datetime] = None


class HypothesisEvaluationResult(BaseModel):
    incident_id: uuid.UUID
    total_hypotheses: int
    accepted_hypothesis: Optional[HypothesisResponse] = None
    hypotheses: List[HypothesisResponse]
    abstained: bool = False
    abstention_reason: Optional[str] = None
    missing_evidence: List[str] = []
    disproof_summary: Optional[str] = None


class RootCauseOverrideRequest(BaseModel):
    summary: str = Field(..., min_length=10, max_length=2000)
    affected_component: Optional[str] = Field(None, max_length=255)
    causal_explanation: str = Field(..., min_length=10, max_length=4000)
    override_notes: str = Field(..., min_length=5, max_length=2000)


class RootCauseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    incident_id: Optional[uuid.UUID] = None
    investigation_id: Optional[uuid.UUID] = None
    work_item_id: Optional[uuid.UUID] = None
    summary: str
    affected_component: Optional[str] = None
    causal_explanation: str
    confidence: str
    supporting_evidence_ids: Optional[List[str]] = None
    contradicting_evidence_ids: Optional[List[str]] = None
    evidence_sources_count: int
    distinct_families_count: int
    disproof_summary: Optional[str] = None
    timeline: Optional[List[Dict[str, Any]]] = None
    relevant_commits: Optional[List[str]] = None
    relevant_files: Optional[List[str]] = None
    abstained: bool = False
    abstention_reason: Optional[str] = None
    missing_evidence_json: Optional[List[str]] = None
    evaluation_version: int
    snapshot_hash: Optional[str] = None
    is_current: bool = True
    human_overridden: bool = False
    human_override_notes: Optional[str] = None
    identified_at: datetime
