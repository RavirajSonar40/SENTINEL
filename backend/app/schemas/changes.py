import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator
from app.models.incident import ChangeType, ChangeRiskLevel, CorrelationStatus


class ChangeEventCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    change_type: ChangeType
    provider: str = Field("manual", max_length=50)
    provider_event_id: Optional[str] = Field(None, max_length=255)
    service_id: Optional[uuid.UUID] = None
    environment_id: Optional[uuid.UUID] = None
    repository_id: Optional[uuid.UUID] = None
    deployment_id: Optional[uuid.UUID] = None
    external_id: Optional[str] = Field(None, max_length=255)
    commit_sha: Optional[str] = Field(None, max_length=100)
    author: Optional[str] = Field(None, max_length=255)
    risk_level: ChangeRiskLevel = ChangeRiskLevel.LOW
    effective_at: Optional[datetime] = None
    source_url: Optional[str] = Field(None, max_length=500)
    affected_components: Optional[List[str]] = Field(default_factory=list)
    diff_summary: Optional[Dict[str, Any]] = Field(default_factory=dict)
    metadata_json: Optional[Dict[str, Any]] = Field(default_factory=dict)

    @field_validator("change_type", mode="before")
    @classmethod
    def normalize_change_type(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.upper()
        return v

    @field_validator("risk_level", mode="before")
    @classmethod
    def normalize_risk_level(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.upper()
        return v


class ChangeEventBatchCreate(BaseModel):
    changes: List[ChangeEventCreate] = Field(..., min_length=1, max_length=100)


class ChangeEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    service_id: Optional[uuid.UUID] = None
    environment_id: Optional[uuid.UUID] = None
    repository_id: Optional[uuid.UUID] = None
    deployment_id: Optional[uuid.UUID] = None

    provider: str
    provider_event_id: Optional[str] = None
    auth_source: Optional[str] = None
    integration_id: Optional[uuid.UUID] = None

    change_type: ChangeType
    title: str
    description: Optional[str] = None
    external_id: str
    commit_sha: Optional[str] = None
    author: Optional[str] = None
    risk_level: ChangeRiskLevel

    effective_at: datetime
    observed_at: datetime
    source_url: Optional[str] = None

    affected_components: Optional[List[Any]] = Field(default_factory=list)
    diff_summary: Optional[Dict[str, Any]] = Field(default_factory=dict)
    metadata_json: Optional[Dict[str, Any]] = Field(default_factory=dict)
    created_at: datetime


class IncidentChangeCorrelationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    incident_id: uuid.UUID
    change_event_id: uuid.UUID

    time_delta_seconds: int
    topological_distance: int
    correlation_score: float
    rank: int

    is_causal_candidate: bool
    triage_status: CorrelationStatus
    triage_reason: Optional[str] = None
    triaged_by_user_id: Optional[uuid.UUID] = None
    triaged_at: Optional[datetime] = None
    previous_status: Optional[str] = None

    reasoning: Optional[str] = None
    change_event: Optional[ChangeEventResponse] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class ChangeCorrelationReport(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[uuid.UUID] = None
    organization_id: Optional[uuid.UUID] = None
    incident_id: uuid.UUID
    version: int = 1
    is_current: bool = True
    snapshot_hash: Optional[str] = None
    calculated_at: datetime
    lookback_window_minutes: int = 120
    causal_candidates_count: int = 0
    top_suspect: Optional[IncidentChangeCorrelationResponse] = None
    summary: str = ""
    correlations: List[IncidentChangeCorrelationResponse] = Field(default_factory=list)


class CorrelationTriageRequest(BaseModel):
    triage_status: CorrelationStatus
    reason: Optional[str] = Field(None, max_length=1000)

    @field_validator("triage_status", mode="before")
    @classmethod
    def normalize_triage_status(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.upper()
        return v
