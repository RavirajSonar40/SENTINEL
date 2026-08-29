"""
Pydantic Schemas for Phase 3 Organization, Repositories, Services & Environments.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict

from app.models.incident import (
    MembershipRole, ServiceRepositoryRole, ServiceDependencyType,
    ServiceCriticality, OwnershipType, ServiceHealth
)


# ============================================================================
# ORGANIZATIONS & MEMBERSHIPS
# ============================================================================

class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: Optional[str] = Field(None, min_length=2, max_length=255)


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    slug: str
    created_at: Optional[datetime] = None


class OrganizationActivateResponse(BaseModel):
    organization_id: UUID
    organization_name: str
    organization_slug: str
    role: MembershipRole
    activated_at: datetime


class MembershipCreate(BaseModel):
    user_id: Optional[UUID] = None
    email: Optional[str] = None
    username: Optional[str] = None
    role: MembershipRole = MembershipRole.MEMBER


class MembershipUpdateRole(BaseModel):
    role: MembershipRole


class MembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    organization_id: UUID
    role: MembershipRole
    username: Optional[str] = None
    email: Optional[str] = None
    created_at: Optional[datetime] = None


# ============================================================================
# TEAMS & MEMBERS
# ============================================================================

class TeamCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = None


class TeamUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class TeamMemberAdd(BaseModel):
    user_id: UUID
    role: str = "member"


class TeamMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    team_id: UUID
    user_id: UUID
    role: str
    username: Optional[str] = None
    created_at: Optional[datetime] = None


class TeamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: Optional[str] = None
    member_count: Optional[int] = 0
    created_at: Optional[datetime] = None


# ============================================================================
# REGIONS & ENVIRONMENTS
# ============================================================================

class RegionCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    code: str = Field(..., min_length=2, max_length=50)  # us-east-1, ap-south-1
    cloud_provider: str = Field("aws", max_length=50)


class RegionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    name: str
    code: str
    cloud_provider: str
    created_at: Optional[datetime] = None


class EnvironmentCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)  # production, staging, preview
    env_type: str = Field("production", max_length=50)
    region: Optional[str] = None


class EnvironmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    name: str
    env_type: str
    region: Optional[str] = None
    created_at: Optional[datetime] = None


# ============================================================================
# REPOSITORIES
# ============================================================================

class RepositoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    full_name: str = Field(..., min_length=1, max_length=500)  # org/repo
    default_branch: str = "main"
    language: Optional[str] = None
    github_url: Optional[str] = None


class RepositoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    name: str
    full_name: str
    default_branch: str
    language: Optional[str] = None
    github_url: Optional[str] = None
    sync_status: Optional[str] = "pending"
    is_active: bool = True
    created_at: Optional[datetime] = None


# ============================================================================
# SERVICE-REPOSITORY TOPOLOGY
# ============================================================================

class ServiceRepositoryCreate(BaseModel):
    service_id: UUID
    repository_id: UUID
    role: ServiceRepositoryRole = ServiceRepositoryRole.APPLICATION
    is_primary: bool = False
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    selection_reason: str = Field(..., min_length=3, max_length=500)
    source: str = "manual"


class ServiceRepositoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    service_id: UUID
    repository_id: UUID
    role: ServiceRepositoryRole
    is_primary: bool
    confidence: float
    source: str
    selection_reason: str
    repository_name: Optional[str] = None
    repository_full_name: Optional[str] = None
    created_at: Optional[datetime] = None


# ============================================================================
# SERVICE DEPENDENCIES & GRAPH
# ============================================================================

class ServiceDependencyCreate(BaseModel):
    dependent_service_id: UUID = Field(..., description="The calling service (downstream dependent)")
    upstream_service_id: UUID = Field(..., description="The provider service (upstream dependency)")
    dependency_type: ServiceDependencyType = ServiceDependencyType.SYNCHRONOUS
    criticality: ServiceCriticality = ServiceCriticality.HARD
    description: Optional[str] = None


class ServiceDependencyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    service_id: UUID  # dependent_service_id (caller)
    depends_on_service_id: UUID  # upstream_service_id (provider)
    dependent_service_name: Optional[str] = None
    upstream_service_name: Optional[str] = None
    dependency_type: ServiceDependencyType
    criticality: ServiceCriticality
    description: Optional[str] = None
    created_at: Optional[datetime] = None


class ServiceGraphNode(BaseModel):
    id: str
    name: str
    tier: str
    health: str


class ServiceGraphEdge(BaseModel):
    id: str
    source: str  # caller (dependent)
    target: str  # provider (upstream)
    dependency_type: str
    criticality: str


class ServiceGraphResponse(BaseModel):
    service_id: str
    service_name: str
    upstream_dependencies: List[Dict[str, Any]]
    downstream_dependents: List[Dict[str, Any]]
    nodes: List[ServiceGraphNode]
    edges: List[ServiceGraphEdge]


# ============================================================================
# SERVICE OWNERSHIP
# ============================================================================

class ServiceOwnershipCreate(BaseModel):
    service_id: UUID
    team_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    ownership_type: OwnershipType = OwnershipType.PRIMARY_OWNER
    escalation_policy: Optional[str] = None


class ServiceOwnershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    service_id: UUID
    team_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    team_name: Optional[str] = None
    username: Optional[str] = None
    ownership_type: OwnershipType
    escalation_policy: Optional[str] = None
    created_at: Optional[datetime] = None


# ============================================================================
# DEPLOYMENT CONFIGURATIONS
# ============================================================================

class ServiceDeploymentConfigCreate(BaseModel):
    service_id: Optional[UUID] = None
    environment_id: UUID
    region_id: Optional[UUID] = None
    health_check_url: Optional[str] = None
    health_check_interval_seconds: int = 30
    observability_identifiers: Optional[Dict[str, Any]] = None
    current_commit_sha: Optional[str] = None
    current_version: Optional[str] = None


class ServiceDeploymentConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    service_id: UUID
    environment_id: UUID
    region_id: Optional[UUID] = None
    environment_name: Optional[str] = None
    region_code: Optional[str] = None
    health_check_url: Optional[str] = None
    health_check_interval_seconds: int
    observability_identifiers: Optional[Dict[str, Any]] = None
    current_commit_sha: Optional[str] = None
    current_version: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ============================================================================
# SERVICES
# ============================================================================

class ServiceCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: Optional[str] = None
    description: Optional[str] = None
    tier: str = "medium"  # critical, high, medium, low


class ServiceUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    tier: Optional[str] = None
    health: Optional[ServiceHealth] = None


class ServiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    name: str
    slug: Optional[str] = None
    description: Optional[str] = None
    tier: str
    health: ServiceHealth
    primary_repository: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ServiceDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    name: str
    slug: Optional[str] = None
    description: Optional[str] = None
    tier: str
    health: ServiceHealth
    repositories: List[ServiceRepositoryResponse] = []
    upstream_dependencies: List[ServiceDependencyResponse] = []
    downstream_dependents: List[ServiceDependencyResponse] = []
    ownerships: List[ServiceOwnershipResponse] = []
    deployments: List[ServiceDeploymentConfigResponse] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
