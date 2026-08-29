"""
Catalog REST API routes for Organizations, Teams, Regions, Environments,
Repositories, Services, Multi-Repo Topologies, Dependencies, Ownership, and Deployments.
"""

import re
import uuid
from typing import List, Optional, Tuple
from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.permissions import (
    get_active_membership, require_viewer, require_member, require_admin, require_owner,
    validate_org_entity, ROLE_HIERARCHY
)
from app.models.incident import (
    User, Organization, Environment, Service, Repository,
    MembershipRole, UserOrganizationMembership, Team, TeamMember, Region,
    ServiceRepositoryRole, ServiceRepository, ServiceDependencyType,
    ServiceCriticality, ServiceDependency, OwnershipType, ServiceOwnership,
    ServiceDeploymentConfig, ServiceHealth
)
from app.schemas.catalog import (
    OrganizationCreate, OrganizationResponse, OrganizationActivateResponse,
    MembershipCreate, MembershipUpdateRole, MembershipResponse,
    TeamCreate, TeamUpdate, TeamResponse, TeamMemberAdd, TeamMemberResponse,
    RegionCreate, RegionResponse, EnvironmentCreate, EnvironmentResponse,
    RepositoryCreate, RepositoryResponse,
    ServiceCreate, ServiceUpdate, ServiceResponse, ServiceDetailResponse,
    ServiceRepositoryCreate, ServiceRepositoryResponse,
    ServiceDependencyCreate, ServiceDependencyResponse, ServiceGraphResponse,
    ServiceGraphNode, ServiceGraphEdge,
    ServiceOwnershipCreate, ServiceOwnershipResponse,
    ServiceDeploymentConfigCreate, ServiceDeploymentConfigResponse
)

router = APIRouter(tags=["Catalog & Organization Topology"])

# SSRF Protection regex
FORBIDDEN_HOSTS_REGEX = re.compile(
    r"^(https?://)?(localhost|127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2[0-9]|3[0-1])\.\d+\.\d+|169\.254\.\d+\.\d+|0\.0\.0\.0)",
    re.IGNORECASE,
)


def _validate_ssrf_url(url: Optional[str]) -> None:
    """Ensure health check URL does not point to internal metadata/loopback IPs."""
    if not url:
        return
    if FORBIDDEN_HOSTS_REGEX.search(url.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Health check URL must point to a public or non-loopback address (SSRF Protection).",
        )


# ============================================================================
# 1. ORGANIZATIONS & MEMBERSHIPS
# ============================================================================

@router.post("/organizations", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
def create_organization(
    data: OrganizationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Bootstrap a new organization.
    Assigns the creator MembershipRole.OWNER and creates default environments in one atomic transaction.
    """
    slug = data.slug or re.sub(r"[^a-z0-9]+", "-", data.name.lower()).strip("-")
    
    # Check duplicate slug
    existing = db.query(Organization).filter(Organization.slug == slug).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Organization with slug '{slug}' already exists.")

    org = Organization(name=data.name, slug=slug)
    db.add(org)
    db.flush()

    # 1. Create OWNER membership
    membership = UserOrganizationMembership(
        user_id=current_user.id,
        organization_id=org.id,
        role=MembershipRole.OWNER,
    )
    db.add(membership)

    # 2. Update user's active context pointer
    current_user.organization_id = org.id

    # 3. Create default environments
    db.add(Environment(name="production", env_type="production", organization_id=org.id))
    db.add(Environment(name="staging", env_type="staging", organization_id=org.id))
    db.add(Environment(name="development", env_type="development", organization_id=org.id))

    db.commit()
    db.refresh(org)
    return org


@router.post("/organizations/{organization_id}/activate", response_model=OrganizationActivateResponse)
def activate_organization(
    organization_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Switch user's active organization context after validating membership.
    """
    membership = (
        db.query(UserOrganizationMembership)
        .filter(
            UserOrganizationMembership.user_id == current_user.id,
            UserOrganizationMembership.organization_id == organization_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this organization.",
        )

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

    current_user.organization_id = org.id
    db.commit()

    return OrganizationActivateResponse(
        organization_id=org.id,
        organization_name=org.name,
        organization_slug=org.slug,
        role=membership.role,
        activated_at=datetime.now(timezone.utc),
    )


@router.get("/organizations/me", response_model=OrganizationResponse)
def get_active_org(
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
):
    """Get active organization details."""
    org, _ = context
    return org


@router.get("/organizations/memberships", response_model=List[MembershipResponse])
def list_memberships(
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """List all members of the active organization."""
    org, _ = context
    memberships = (
        db.query(UserOrganizationMembership, User.username, User.email)
        .join(User, UserOrganizationMembership.user_id == User.id)
        .filter(UserOrganizationMembership.organization_id == org.id)
        .all()
    )
    res = []
    for m, username, email in memberships:
        res.append(MembershipResponse(
            id=m.id,
            user_id=m.user_id,
            organization_id=m.organization_id,
            role=m.role,
            username=username,
            email=email,
            created_at=m.created_at,
        ))
    return res


@router.post("/organizations/memberships", response_model=MembershipResponse, status_code=status.HTTP_201_CREATED)
def add_membership(
    data: MembershipCreate,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Add or invite a user to the active organization (Admin/Owner only)."""
    org, _ = context

    # Find user by ID, email, or username
    user = None
    if data.user_id:
        user = db.query(User).filter(User.id == data.user_id).first()
    elif data.email:
        user = db.query(User).filter(User.email == data.email).first()
    elif data.username:
        user = db.query(User).filter(User.username == data.username).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    existing = (
        db.query(UserOrganizationMembership)
        .filter(
            UserOrganizationMembership.user_id == user.id,
            UserOrganizationMembership.organization_id == org.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is already a member of this organization.")

    membership = UserOrganizationMembership(
        user_id=user.id,
        organization_id=org.id,
        role=data.role,
    )
    db.add(membership)
    if not user.organization_id:
        user.organization_id = org.id
    db.commit()
    db.refresh(membership)

    return MembershipResponse(
        id=membership.id,
        user_id=membership.user_id,
        organization_id=membership.organization_id,
        role=membership.role,
        username=user.username,
        email=user.email,
        created_at=membership.created_at,
    )


@router.patch("/organizations/memberships/{membership_id}/role", response_model=MembershipResponse)
def update_membership_role(
    membership_id: UUID,
    data: MembershipUpdateRole,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Update member role with Last-Owner protection (Owner only)."""
    org, caller_membership = context
    membership = (
        db.query(UserOrganizationMembership)
        .filter(
            UserOrganizationMembership.id == membership_id,
            UserOrganizationMembership.organization_id == org.id,
        )
        .first()
    )
    validate_org_entity(membership, org.id, "Membership")

    # Last Owner Protection: Cannot demote the last owner
    if membership.role == MembershipRole.OWNER and data.role != MembershipRole.OWNER:
        owner_count = (
            db.query(UserOrganizationMembership)
            .filter(
                UserOrganizationMembership.organization_id == org.id,
                UserOrganizationMembership.role == MembershipRole.OWNER,
            )
            .count()
        )
        if owner_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot demote the last remaining owner of the organization.",
            )

    membership.role = data.role
    db.commit()
    db.refresh(membership)
    user = db.query(User).filter(User.id == membership.user_id).first()

    return MembershipResponse(
        id=membership.id,
        user_id=membership.user_id,
        organization_id=membership.organization_id,
        role=membership.role,
        username=user.username if user else None,
        email=user.email if user else None,
        created_at=membership.created_at,
    )


@router.delete("/organizations/memberships/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_membership(
    membership_id: UUID,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Remove member with Last-Owner protection (Owner only)."""
    org, _ = context
    membership = (
        db.query(UserOrganizationMembership)
        .filter(
            UserOrganizationMembership.id == membership_id,
            UserOrganizationMembership.organization_id == org.id,
        )
        .first()
    )
    validate_org_entity(membership, org.id, "Membership")

    # Last Owner Protection: Cannot remove the last owner
    if membership.role == MembershipRole.OWNER:
        owner_count = (
            db.query(UserOrganizationMembership)
            .filter(
                UserOrganizationMembership.organization_id == org.id,
                UserOrganizationMembership.role == MembershipRole.OWNER,
            )
            .count()
        )
        if owner_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the last remaining owner of the organization.",
            )

    db.delete(membership)
    db.commit()
    return None


# ============================================================================
# 2. TEAMS & MEMBERS
# ============================================================================

@router.get("/teams", response_model=List[TeamResponse])
def list_teams(
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """List teams in the active organization."""
    org, _ = context
    teams = db.query(Team).filter(Team.organization_id == org.id).all()
    res = []
    for t in teams:
        res.append(TeamResponse(
            id=t.id,
            organization_id=t.organization_id,
            name=t.name,
            slug=t.slug,
            description=t.description,
            member_count=len(t.members) if t.members else 0,
            created_at=t.created_at,
        ))
    return res


@router.post("/teams", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
def create_team(
    data: TeamCreate,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create team in the active organization (Admin/Owner only)."""
    org, _ = context
    slug = data.slug or re.sub(r"[^a-z0-9]+", "-", data.name.lower()).strip("-")

    existing = db.query(Team).filter(Team.organization_id == org.id, Team.slug == slug).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Team with slug '{slug}' already exists.")

    team = Team(organization_id=org.id, name=data.name, slug=slug, description=data.description)
    db.add(team)
    db.commit()
    db.refresh(team)
    return TeamResponse(
        id=team.id,
        organization_id=team.organization_id,
        name=team.name,
        slug=team.slug,
        description=team.description,
        member_count=0,
        created_at=team.created_at,
    )


@router.post("/teams/{team_id}/members", response_model=TeamMemberResponse, status_code=status.HTTP_201_CREATED)
def add_team_member(
    team_id: UUID,
    data: TeamMemberAdd,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Add user to team (Admin/Owner only). Validates cross-tenant user ownership."""
    org, _ = context
    team = db.query(Team).filter(Team.id == team_id, Team.organization_id == org.id).first()
    validate_org_entity(team, org.id, "Team")

    # Verify user belongs to the same organization
    user_membership = (
        db.query(UserOrganizationMembership)
        .filter(
            UserOrganizationMembership.user_id == data.user_id,
            UserOrganizationMembership.organization_id == org.id,
        )
        .first()
    )
    if not user_membership:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User does not belong to your organization.")

    existing = db.query(TeamMember).filter(TeamMember.team_id == team.id, TeamMember.user_id == data.user_id).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is already a member of this team.")

    tm = TeamMember(team_id=team.id, user_id=data.user_id, role=data.role)
    db.add(tm)
    db.commit()
    db.refresh(tm)

    user = db.query(User).filter(User.id == data.user_id).first()
    return TeamMemberResponse(
        id=tm.id,
        team_id=tm.team_id,
        user_id=tm.user_id,
        role=tm.role,
        username=user.username if user else None,
        created_at=tm.created_at,
    )


# ============================================================================
# 3. REGIONS & ENVIRONMENTS
# ============================================================================

@router.get("/regions", response_model=List[RegionResponse])
def list_regions(
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """List regions for the active organization."""
    org, _ = context
    return db.query(Region).filter(Region.organization_id == org.id).all()


@router.post("/regions", response_model=RegionResponse, status_code=status.HTTP_201_CREATED)
def create_region(
    data: RegionCreate,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create region (Admin/Owner only)."""
    org, _ = context
    existing = db.query(Region).filter(Region.organization_id == org.id, Region.code == data.code).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Region code '{data.code}' already exists.")

    region = Region(
        organization_id=org.id,
        name=data.name,
        code=data.code,
        cloud_provider=data.cloud_provider,
    )
    db.add(region)
    db.commit()
    db.refresh(region)
    return region


@router.get("/environments", response_model=List[EnvironmentResponse])
def list_environments(
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """List environments for the active organization."""
    org, _ = context
    return db.query(Environment).filter(Environment.organization_id == org.id).all()


@router.post("/environments", response_model=EnvironmentResponse, status_code=status.HTTP_201_CREATED)
def create_environment(
    data: EnvironmentCreate,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create environment (Admin/Owner only)."""
    org, _ = context
    env = Environment(
        organization_id=org.id,
        name=data.name,
        env_type=data.env_type,
        region=data.region,
    )
    db.add(env)
    db.commit()
    db.refresh(env)
    return env


# ============================================================================
# 4. REPOSITORIES
# ============================================================================

@router.get("/repositories", response_model=List[RepositoryResponse])
def list_repositories(
    search: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """List repositories for the active organization with search & pagination."""
    org, _ = context
    query = db.query(Repository).filter(Repository.organization_id == org.id)
    if search:
        query = query.filter(Repository.full_name.ilike(f"%{search}%"))
    return query.order_by(Repository.name.asc()).offset(offset).limit(limit).all()


@router.post("/repositories", response_model=RepositoryResponse, status_code=status.HTTP_201_CREATED)
def create_repository(
    data: RepositoryCreate,
    current_user: User = Depends(get_current_user),
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Register repository in active organization (Admin/Owner only)."""
    org, _ = context
    existing = db.query(Repository).filter(Repository.organization_id == org.id, Repository.full_name == data.full_name).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Repository '{data.full_name}' already exists in your organization.")

    repo = Repository(
        organization_id=org.id,
        name=data.name,
        full_name=data.full_name,
        owner_id=current_user.id,
        default_branch=data.default_branch,
        language=data.language,
        github_url=data.github_url,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return repo


# ============================================================================
# 5. SERVICES & MULTI-REPO TOPOLOGY
# ============================================================================

@router.get("/services", response_model=List[ServiceResponse])
def list_services(
    search: Optional[str] = None,
    tier: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """List services for active organization with search, tier filtering and primary repository resolution."""
    org, _ = context
    query = db.query(Service).filter(Service.organization_id == org.id)
    if search:
        query = query.filter(Service.name.ilike(f"%{search}%"))
    if tier:
        query = query.filter(Service.tier == tier)

    services = query.order_by(Service.name.asc()).offset(offset).limit(limit).all()
    res = []
    for s in services:
        primary_repo_name = None
        for sr in (s.service_repositories or []):
            if sr.is_primary and sr.repository:
                primary_repo_name = sr.repository.full_name
                break
        res.append(ServiceResponse(
            id=s.id,
            organization_id=s.organization_id,
            name=s.name,
            slug=s.slug,
            description=s.description,
            tier=s.tier,
            health=s.health,
            primary_repository=primary_repo_name,
            created_at=s.created_at,
            updated_at=s.updated_at,
        ))
    return res


@router.post("/services", response_model=ServiceResponse, status_code=status.HTTP_201_CREATED)
def create_service(
    data: ServiceCreate,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create service in active organization (Admin/Owner only)."""
    org, _ = context
    existing = db.query(Service).filter(Service.organization_id == org.id, Service.name == data.name).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Service '{data.name}' already exists in your organization.")

    slug = data.slug or re.sub(r"[^a-z0-9]+", "-", data.name.lower()).strip("-")
    svc = Service(
        organization_id=org.id,
        name=data.name,
        slug=slug,
        description=data.description,
        tier=data.tier,
    )
    db.add(svc)
    db.commit()
    db.refresh(svc)

    return ServiceResponse(
        id=svc.id,
        organization_id=svc.organization_id,
        name=svc.name,
        slug=svc.slug,
        description=svc.description,
        tier=svc.tier,
        health=svc.health,
        primary_repository=None,
        created_at=svc.created_at,
        updated_at=svc.updated_at,
    )


@router.get("/services/{service_id}", response_model=ServiceDetailResponse)
def get_service_detail(
    service_id: UUID,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """Get full service topology detail: repositories, dependencies, ownership, and deployments."""
    org, _ = context
    svc = db.query(Service).filter(Service.id == service_id, Service.organization_id == org.id).first()
    validate_org_entity(svc, org.id, "Service")

    # 1. Repositories
    repos = []
    for sr in svc.service_repositories:
        repos.append(ServiceRepositoryResponse(
            id=sr.id,
            organization_id=sr.organization_id,
            service_id=sr.service_id,
            repository_id=sr.repository_id,
            role=sr.role,
            is_primary=sr.is_primary,
            confidence=sr.confidence,
            source=sr.source,
            selection_reason=sr.selection_reason,
            repository_name=sr.repository.name if sr.repository else None,
            repository_full_name=sr.repository.full_name if sr.repository else None,
            created_at=sr.created_at,
        ))

    # 2. Upstream dependencies (services this service calls / depends on)
    upstreams = []
    for dep in svc.dependencies_out:
        upstreams.append(ServiceDependencyResponse(
            id=dep.id,
            organization_id=dep.organization_id,
            service_id=dep.service_id,
            depends_on_service_id=dep.depends_on_service_id,
            dependent_service_name=svc.name,
            upstream_service_name=dep.depends_on_service.name if dep.depends_on_service else None,
            dependency_type=dep.dependency_type,
            criticality=dep.criticality,
            description=dep.description,
            created_at=dep.created_at,
        ))

    # 3. Downstream dependents (services that call / depend on this service)
    downstreams = []
    for dep in svc.dependencies_in:
        downstreams.append(ServiceDependencyResponse(
            id=dep.id,
            organization_id=dep.organization_id,
            service_id=dep.service_id,
            depends_on_service_id=dep.depends_on_service_id,
            dependent_service_name=dep.service.name if dep.service else None,
            upstream_service_name=svc.name,
            dependency_type=dep.dependency_type,
            criticality=dep.criticality,
            description=dep.description,
            created_at=dep.created_at,
        ))

    # 4. Ownerships
    ownerships = []
    for own in svc.ownerships:
        ownerships.append(ServiceOwnershipResponse(
            id=own.id,
            organization_id=own.organization_id,
            service_id=own.service_id,
            team_id=own.team_id,
            user_id=own.user_id,
            team_name=own.team.name if own.team else None,
            username=own.user.username if own.user else None,
            ownership_type=own.ownership_type,
            escalation_policy=own.escalation_policy,
            created_at=own.created_at,
        ))

    # 5. Deployments
    deployments = []
    for dep in svc.deployment_configs:
        deployments.append(ServiceDeploymentConfigResponse(
            id=dep.id,
            organization_id=dep.organization_id,
            service_id=dep.service_id,
            environment_id=dep.environment_id,
            region_id=dep.region_id,
            environment_name=dep.environment.name if dep.environment else None,
            region_code=dep.region.code if dep.region else None,
            health_check_url=dep.health_check_url,
            health_check_interval_seconds=dep.health_check_interval_seconds,
            observability_identifiers=dep.observability_identifiers,
            current_commit_sha=dep.current_commit_sha,
            current_version=dep.current_version,
            is_active=dep.is_active,
            created_at=dep.created_at,
            updated_at=dep.updated_at,
        ))

    return ServiceDetailResponse(
        id=svc.id,
        organization_id=svc.organization_id,
        name=svc.name,
        slug=svc.slug,
        description=svc.description,
        tier=svc.tier,
        health=svc.health,
        repositories=repos,
        upstream_dependencies=upstreams,
        downstream_dependents=downstreams,
        ownerships=ownerships,
        deployments=deployments,
        created_at=svc.created_at,
        updated_at=svc.updated_at,
    )


@router.delete("/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_service(
    service_id: UUID,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Delete service (Admin/Owner only)."""
    org, _ = context
    svc = db.query(Service).filter(Service.id == service_id, Service.organization_id == org.id).first()
    validate_org_entity(svc, org.id, "Service")
    db.delete(svc)
    db.commit()
    return None


# ============================================================================
# 6. SERVICE-REPOSITORY MAPPINGS
# ============================================================================

@router.get("/service-repositories", response_model=List[ServiceRepositoryResponse])
def list_service_repositories(
    service_id: Optional[UUID] = None,
    repository_id: Optional[UUID] = None,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """List service-repository topology bindings."""
    org, _ = context
    query = db.query(ServiceRepository).filter(ServiceRepository.organization_id == org.id)
    if service_id:
        query = query.filter(ServiceRepository.service_id == service_id)
    if repository_id:
        query = query.filter(ServiceRepository.repository_id == repository_id)

    srs = query.all()
    res = []
    for sr in srs:
        res.append(ServiceRepositoryResponse(
            id=sr.id,
            organization_id=sr.organization_id,
            service_id=sr.service_id,
            repository_id=sr.repository_id,
            role=sr.role,
            is_primary=sr.is_primary,
            confidence=sr.confidence,
            source=sr.source,
            selection_reason=sr.selection_reason,
            repository_name=sr.repository.name if sr.repository else None,
            repository_full_name=sr.repository.full_name if sr.repository else None,
            created_at=sr.created_at,
        ))
    return res


@router.post("/service-repositories", response_model=ServiceRepositoryResponse, status_code=status.HTTP_201_CREATED)
def create_service_repository(
    data: ServiceRepositoryCreate,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Map repository to service with role, selection reason, and primary repository validation.
    Enforces that:
    1. Both service and repository belong to caller's organization.
    2. is_primary=True requires role == APPLICATION.
    3. At most one primary repository exists per service (SQLite + Postgres dual enforcement).
    """
    org, _ = context

    svc = db.query(Service).filter(Service.id == data.service_id, Service.organization_id == org.id).first()
    validate_org_entity(svc, org.id, "Service")

    repo = db.query(Repository).filter(Repository.id == data.repository_id, Repository.organization_id == org.id).first()
    validate_org_entity(repo, org.id, "Repository")

    # Cross-tenant validation
    if svc.organization_id != org.id or repo.organization_id != org.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Entities must belong to the active organization.")

    # Primary repository constraints
    if data.is_primary:
        if data.role != ServiceRepositoryRole.APPLICATION:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A primary repository must have role 'application'.",
            )
        # Check if service already has a primary repository
        existing_primary = (
            db.query(ServiceRepository)
            .filter(
                ServiceRepository.service_id == svc.id,
                ServiceRepository.is_primary == True,
            )
            .first()
        )
        if existing_primary:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Service already has a primary repository. Only one primary repository is allowed per service.",
            )

    # Check duplicate mapping for same role
    existing_mapping = (
        db.query(ServiceRepository)
        .filter(
            ServiceRepository.service_id == svc.id,
            ServiceRepository.repository_id == repo.id,
            ServiceRepository.role == data.role,
        )
        .first()
    )
    if existing_mapping:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Service is already linked to this repository under role '{data.role.value}'.",
        )

    sr = ServiceRepository(
        organization_id=org.id,
        service_id=svc.id,
        repository_id=repo.id,
        role=data.role,
        is_primary=data.is_primary,
        confidence=data.confidence,
        source=data.source,
        selection_reason=data.selection_reason,
    )
    db.add(sr)
    db.commit()
    db.refresh(sr)

    return ServiceRepositoryResponse(
        id=sr.id,
        organization_id=sr.organization_id,
        service_id=sr.service_id,
        repository_id=sr.repository_id,
        role=sr.role,
        is_primary=sr.is_primary,
        confidence=sr.confidence,
        source=sr.source,
        selection_reason=sr.selection_reason,
        repository_name=repo.name,
        repository_full_name=repo.full_name,
        created_at=sr.created_at,
    )


@router.delete("/service-repositories/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_service_repository(
    id: UUID,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Delete service-repository mapping (Admin/Owner only)."""
    org, _ = context
    sr = db.query(ServiceRepository).filter(ServiceRepository.id == id, ServiceRepository.organization_id == org.id).first()
    validate_org_entity(sr, org.id, "ServiceRepository")
    db.delete(sr)
    db.commit()
    return None


# ============================================================================
# 7. SERVICE DEPENDENCIES & GRAPH TRAVERSAL
# ============================================================================

@router.get("/dependencies", response_model=List[ServiceDependencyResponse])
def list_dependencies(
    service_id: Optional[UUID] = None,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """List service dependencies in active organization."""
    org, _ = context
    query = db.query(ServiceDependency).filter(ServiceDependency.organization_id == org.id)
    if service_id:
        query = query.filter((ServiceDependency.service_id == service_id) | (ServiceDependency.depends_on_service_id == service_id))

    deps = query.all()
    res = []
    for d in deps:
        res.append(ServiceDependencyResponse(
            id=d.id,
            organization_id=d.organization_id,
            service_id=d.service_id,
            depends_on_service_id=d.depends_on_service_id,
            dependent_service_name=d.service.name if d.service else None,
            upstream_service_name=d.depends_on_service.name if d.depends_on_service else None,
            dependency_type=d.dependency_type,
            criticality=d.criticality,
            description=d.description,
            created_at=d.created_at,
        ))
    return res


@router.post("/dependencies", response_model=ServiceDependencyResponse, status_code=status.HTTP_201_CREATED)
def create_dependency(
    data: ServiceDependencyCreate,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Create service dependency.
    dependent_service_id: Caller / downstream dependent
    upstream_service_id: Provider / upstream dependency
    Enforces self-dependency and cross-tenant checks.
    """
    org, _ = context

    # 1. Self-dependency guard
    if data.dependent_service_id == data.upstream_service_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A service cannot depend on itself (Self-dependency rejected).",
        )

    # 2. Scope validation
    caller = db.query(Service).filter(Service.id == data.dependent_service_id, Service.organization_id == org.id).first()
    validate_org_entity(caller, org.id, "Dependent Service")

    provider = db.query(Service).filter(Service.id == data.upstream_service_id, Service.organization_id == org.id).first()
    validate_org_entity(provider, org.id, "Upstream Service")

    # 3. Duplicate check
    existing = (
        db.query(ServiceDependency)
        .filter(
            ServiceDependency.service_id == caller.id,
            ServiceDependency.depends_on_service_id == provider.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This service dependency link already exists.")

    dep = ServiceDependency(
        organization_id=org.id,
        service_id=caller.id,
        depends_on_service_id=provider.id,
        dependency_type=data.dependency_type,
        criticality=data.criticality,
        description=data.description,
    )
    db.add(dep)
    db.commit()
    db.refresh(dep)

    return ServiceDependencyResponse(
        id=dep.id,
        organization_id=dep.organization_id,
        service_id=dep.service_id,
        depends_on_service_id=dep.depends_on_service_id,
        dependent_service_name=caller.name,
        upstream_service_name=provider.name,
        dependency_type=dep.dependency_type,
        criticality=dep.criticality,
        description=dep.description,
        created_at=dep.created_at,
    )


@router.delete("/dependencies/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dependency(
    id: UUID,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Delete service dependency link (Admin/Owner only)."""
    org, _ = context
    dep = db.query(ServiceDependency).filter(ServiceDependency.id == id, ServiceDependency.organization_id == org.id).first()
    validate_org_entity(dep, org.id, "ServiceDependency")
    db.delete(dep)
    db.commit()
    return None


@router.get("/services/{service_id}/graph", response_model=ServiceGraphResponse)
def get_service_graph(
    service_id: UUID,
    max_depth: int = Query(5, ge=1, le=10),
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """
    Cycle-safe dependency graph traversal.
    Returns upstream dependencies and downstream dependents up to max_depth.
    """
    org, _ = context
    root_svc = db.query(Service).filter(Service.id == service_id, Service.organization_id == org.id).first()
    validate_org_entity(root_svc, org.id, "Service")

    visited_nodes = {}
    edges = []
    upstream_list = []
    downstream_list = []

    # Queue of (service_id, depth, direction)
    visited_nodes[str(root_svc.id)] = ServiceGraphNode(
        id=str(root_svc.id),
        name=root_svc.name,
        tier=root_svc.tier,
        health=root_svc.health.value,
    )

    # 1. Upstream Traversal (Services root calls)
    queue = [(root_svc.id, 0)]
    visited_upstream = {root_svc.id}

    while queue:
        curr_id, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        deps = db.query(ServiceDependency).filter(ServiceDependency.service_id == curr_id, ServiceDependency.organization_id == org.id).all()
        for d in deps:
            target = d.depends_on_service
            if not target:
                continue
            edges.append(ServiceGraphEdge(
                id=f"{d.service_id}->{d.depends_on_service_id}",
                source=str(d.service_id),
                target=str(d.depends_on_service_id),
                dependency_type=d.dependency_type.value,
                criticality=d.criticality.value,
            ))
            if str(target.id) not in visited_nodes:
                visited_nodes[str(target.id)] = ServiceGraphNode(
                    id=str(target.id),
                    name=target.name,
                    tier=target.tier,
                    health=target.health.value,
                )
            upstream_list.append({
                "service_id": str(target.id),
                "name": target.name,
                "tier": target.tier,
                "criticality": d.criticality.value,
                "dependency_type": d.dependency_type.value,
                "depth": depth + 1,
            })
            if target.id not in visited_upstream:
                visited_upstream.add(target.id)
                queue.append((target.id, depth + 1))

    # 2. Downstream Traversal (Services calling root)
    queue = [(root_svc.id, 0)]
    visited_downstream = {root_svc.id}

    while queue:
        curr_id, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        deps = db.query(ServiceDependency).filter(ServiceDependency.depends_on_service_id == curr_id, ServiceDependency.organization_id == org.id).all()
        for d in deps:
            caller = d.service
            if not caller:
                continue
            edges.append(ServiceGraphEdge(
                id=f"{d.service_id}->{d.depends_on_service_id}",
                source=str(d.service_id),
                target=str(d.depends_on_service_id),
                dependency_type=d.dependency_type.value,
                criticality=d.criticality.value,
            ))
            if str(caller.id) not in visited_nodes:
                visited_nodes[str(caller.id)] = ServiceGraphNode(
                    id=str(caller.id),
                    name=caller.name,
                    tier=caller.tier,
                    health=caller.health.value,
                )
            downstream_list.append({
                "service_id": str(caller.id),
                "name": caller.name,
                "tier": caller.tier,
                "criticality": d.criticality.value,
                "dependency_type": d.dependency_type.value,
                "depth": depth + 1,
            })
            if caller.id not in visited_downstream:
                visited_downstream.add(caller.id)
                queue.append((caller.id, depth + 1))

    # Deduplicate edges
    unique_edges = {}
    for e in edges:
        unique_edges[e.id] = e

    return ServiceGraphResponse(
        service_id=str(root_svc.id),
        service_name=root_svc.name,
        upstream_dependencies=upstream_list,
        downstream_dependents=downstream_list,
        nodes=list(visited_nodes.values()),
        edges=list(unique_edges.values()),
    )


# ============================================================================
# 8. SERVICE OWNERSHIP
# ============================================================================

@router.get("/ownership", response_model=List[ServiceOwnershipResponse])
def list_ownerships(
    service_id: Optional[UUID] = None,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """List service ownership records."""
    org, _ = context
    query = db.query(ServiceOwnership).filter(ServiceOwnership.organization_id == org.id)
    if service_id:
        query = query.filter(ServiceOwnership.service_id == service_id)

    owns = query.all()
    res = []
    for o in owns:
        res.append(ServiceOwnershipResponse(
            id=o.id,
            organization_id=o.organization_id,
            service_id=o.service_id,
            team_id=o.team_id,
            user_id=o.user_id,
            team_name=o.team.name if o.team else None,
            username=o.user.username if o.user else None,
            ownership_type=o.ownership_type,
            escalation_policy=o.escalation_policy,
            created_at=o.created_at,
        ))
    return res


@router.post("/ownership", response_model=ServiceOwnershipResponse, status_code=status.HTTP_201_CREATED)
def create_ownership(
    data: ServiceOwnershipCreate,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Assign service ownership.
    Enforces:
    1. Exactly one of team_id or user_id must be set.
    2. Single primary owner per service.
    3. Escalation policy required for ONCALL.
    4. Cross-tenant verification.
    """
    org, _ = context

    # 1. Exclusive owner rule
    if bool(data.team_id) == bool(data.user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Exactly one of 'team_id' or 'user_id' must be specified for service ownership.",
        )

    # 2. Service scope
    svc = db.query(Service).filter(Service.id == data.service_id, Service.organization_id == org.id).first()
    validate_org_entity(svc, org.id, "Service")

    # 3. Team or User scope
    if data.team_id:
        team = db.query(Team).filter(Team.id == data.team_id, Team.organization_id == org.id).first()
        validate_org_entity(team, org.id, "Team")
    if data.user_id:
        user_m = db.query(UserOrganizationMembership).filter(UserOrganizationMembership.user_id == data.user_id, UserOrganizationMembership.organization_id == org.id).first()
        if not user_m:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User does not belong to your organization.")

    # 4. Primary owner uniqueness rule
    if data.ownership_type == OwnershipType.PRIMARY_OWNER:
        existing_primary = (
            db.query(ServiceOwnership)
            .filter(
                ServiceOwnership.service_id == svc.id,
                ServiceOwnership.ownership_type == OwnershipType.PRIMARY_OWNER,
            )
            .first()
        )
        if existing_primary:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Service already has a primary owner. Only one primary owner is allowed per service.",
            )

    # 5. On-call escalation policy requirement
    if data.ownership_type == OwnershipType.ONCALL and not data.escalation_policy:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An escalation policy is mandatory for ONCALL ownership.",
        )

    own = ServiceOwnership(
        organization_id=org.id,
        service_id=svc.id,
        team_id=data.team_id,
        user_id=data.user_id,
        ownership_type=data.ownership_type,
        escalation_policy=data.escalation_policy,
    )
    db.add(own)
    db.commit()
    db.refresh(own)

    return ServiceOwnershipResponse(
        id=own.id,
        organization_id=own.organization_id,
        service_id=own.service_id,
        team_id=own.team_id,
        user_id=own.user_id,
        team_name=own.team.name if own.team else None,
        username=own.user.username if own.user else None,
        ownership_type=own.ownership_type,
        escalation_policy=own.escalation_policy,
        created_at=own.created_at,
    )


@router.delete("/ownership/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ownership(
    id: UUID,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Delete service ownership record (Admin/Owner only)."""
    org, _ = context
    own = db.query(ServiceOwnership).filter(ServiceOwnership.id == id, ServiceOwnership.organization_id == org.id).first()
    validate_org_entity(own, org.id, "ServiceOwnership")
    db.delete(own)
    db.commit()
    return None


# ============================================================================
# 9. DEPLOYMENT CONFIGURATIONS
# ============================================================================

@router.get("/services/{service_id}/deployment-configs", response_model=List[ServiceDeploymentConfigResponse])
def list_service_deployments(
    service_id: UUID,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """List deployment configurations for a service."""
    org, _ = context
    svc = db.query(Service).filter(Service.id == service_id, Service.organization_id == org.id).first()
    validate_org_entity(svc, org.id, "Service")

    configs = db.query(ServiceDeploymentConfig).filter(ServiceDeploymentConfig.service_id == svc.id).all()
    res = []
    for c in configs:
        res.append(ServiceDeploymentConfigResponse(
            id=c.id,
            organization_id=c.organization_id,
            service_id=c.service_id,
            environment_id=c.environment_id,
            region_id=c.region_id,
            environment_name=c.environment.name if c.environment else None,
            region_code=c.region.code if c.region else None,
            health_check_url=c.health_check_url,
            health_check_interval_seconds=c.health_check_interval_seconds,
            observability_identifiers=c.observability_identifiers,
            current_commit_sha=c.current_commit_sha,
            current_version=c.current_version,
            is_active=c.is_active,
            created_at=c.created_at,
            updated_at=c.updated_at,
        ))
    return res


@router.post("/services/{service_id}/deployment-configs", response_model=ServiceDeploymentConfigResponse, status_code=status.HTTP_201_CREATED)
def create_service_deployment(
    service_id: UUID,
    data: ServiceDeploymentConfigCreate,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Create deployment & observability configuration for a service.
    Enforces SSRF URL protection and regional/global uniqueness.
    """
    org, _ = context
    svc = db.query(Service).filter(Service.id == service_id, Service.organization_id == org.id).first()
    validate_org_entity(svc, org.id, "Service")

    env = db.query(Environment).filter(Environment.id == data.environment_id, Environment.organization_id == org.id).first()
    validate_org_entity(env, org.id, "Environment")

    if data.region_id:
        reg = db.query(Region).filter(Region.id == data.region_id, Region.organization_id == org.id).first()
        validate_org_entity(reg, org.id, "Region")

    # SSRF Guard
    _validate_ssrf_url(data.health_check_url)

    # Uniqueness check (regional vs global)
    existing = (
        db.query(ServiceDeploymentConfig)
        .filter(
            ServiceDeploymentConfig.service_id == svc.id,
            ServiceDeploymentConfig.environment_id == env.id,
            ServiceDeploymentConfig.region_id == data.region_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Deployment configuration already exists for this service, environment, and region combination.",
        )

    config = ServiceDeploymentConfig(
        organization_id=org.id,
        service_id=svc.id,
        environment_id=env.id,
        region_id=data.region_id,
        health_check_url=data.health_check_url,
        health_check_interval_seconds=data.health_check_interval_seconds,
        observability_identifiers=data.observability_identifiers,
        current_commit_sha=data.current_commit_sha,
        current_version=data.current_version,
    )
    db.add(config)
    db.commit()
    db.refresh(config)

    return ServiceDeploymentConfigResponse(
        id=config.id,
        organization_id=config.organization_id,
        service_id=config.service_id,
        environment_id=config.environment_id,
        region_id=config.region_id,
        environment_name=env.name,
        region_code=config.region.code if config.region else None,
        health_check_url=config.health_check_url,
        health_check_interval_seconds=config.health_check_interval_seconds,
        observability_identifiers=config.observability_identifiers,
        current_commit_sha=config.current_commit_sha,
        current_version=config.current_version,
        is_active=config.is_active,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )
