"""Pydantic validation schemas for Phase 4 Deployment Inventory & Webhooks."""

import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class DeploymentCreate(BaseModel):
    service_id: uuid.UUID
    environment_id: uuid.UUID
    region_id: Optional[uuid.UUID] = None
    repository_id: Optional[uuid.UUID] = None
    commit_sha: str = Field(..., min_length=7, max_length=40)
    commit_message: Optional[str] = None
    version: Optional[str] = None
    provider: Optional[str] = "manual"
    provider_event_id: Optional[str] = None
    external_deployment_id: Optional[str] = None
    status: Optional[str] = "pending"
    url: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None


class DeploymentStatusUpdate(BaseModel):
    status: str
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class DeploymentResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    service_id: uuid.UUID
    environment_id: uuid.UUID
    region_id: Optional[uuid.UUID] = None
    repository_id: Optional[uuid.UUID] = None
    service_name: Optional[str] = None
    environment_name: Optional[str] = None
    region_code: Optional[str] = None
    repository_full_name: Optional[str] = None
    commit_sha: str
    commit_message: Optional[str] = None
    version: Optional[str] = None
    provider: str
    provider_event_id: Optional[str] = None
    external_deployment_id: Optional[str] = None
    status: str
    url: Optional[str] = None
    deployed_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    deployed_by: Optional[str] = None
    is_current: bool
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class GenericWebhookDeploymentPayload(BaseModel):
    service_id: Optional[uuid.UUID] = None
    service_name: Optional[str] = None
    environment_id: Optional[uuid.UUID] = None
    environment_name: Optional[str] = None
    region_id: Optional[uuid.UUID] = None
    region_code: Optional[str] = None
    repository_id: Optional[uuid.UUID] = None
    repository_full_name: Optional[str] = None
    commit_sha: str = Field(..., min_length=7, max_length=40)
    commit_message: Optional[str] = None
    version: Optional[str] = None
    status: Optional[str] = "succeeded"
    event_id: Optional[str] = None
    external_id: Optional[str] = None
    url: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    deployed_by: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class WebhookEndpointCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    provider: str = Field(default="generic", max_length=50)


class WebhookEndpointResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    provider: str = "generic"
    key_id: str
    raw_secret: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CommitSummary(BaseModel):
    sha: str
    message: str
    author: Optional[str] = None
    timestamp: Optional[str] = None


class DeploymentCommitComparisonResponse(BaseModel):
    status: str  # "available" | "unavailable"
    reason: Optional[str] = None
    repository_full_name: Optional[str] = None
    base_commit_sha: str
    head_commit_sha: str
    total_commits: int = 0
    commits: List[CommitSummary] = []
