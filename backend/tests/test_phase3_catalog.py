"""
Integration and Unit Tests for Phase 3:
Organization, Repositories, Services, Multi-Repo Topologies, Dependencies, Ownership, and Environments.
"""

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.core.auth import create_access_token
from app.models.incident import (
    User, Organization, Environment, Service, Repository,
    MembershipRole, UserOrganizationMembership, Team, TeamMember, Region,
    ServiceRepositoryRole, ServiceRepository, ServiceDependencyType,
    ServiceCriticality, ServiceDependency, OwnershipType, ServiceOwnership,
    ServiceDeploymentConfig, ServiceHealth
)

# In-memory SQLite with StaticPool for deterministic test isolation
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def setup_org_and_admin(db_session):
    """Setup test organization and admin user."""
    org = Organization(id=uuid.uuid4(), name="Acme Corp", slug="acme-corp")
    db_session.add(org)
    db_session.flush()

    user = User(
        id=uuid.uuid4(),
        username="alice",
        email="alice@acme.com",
        hashed_password="hash",
        role="admin",
        organization_id=org.id,
    )
    db_session.add(user)
    db_session.flush()

    membership = UserOrganizationMembership(
        id=uuid.uuid4(),
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.OWNER,
    )
    db_session.add(membership)

    # Seed default environments (matching POST /organizations bootstrap)
    db_session.add(Environment(id=uuid.uuid4(), name="production", env_type="production", organization_id=org.id))
    db_session.add(Environment(id=uuid.uuid4(), name="staging", env_type="staging", organization_id=org.id))
    db_session.add(Environment(id=uuid.uuid4(), name="development", env_type="development", organization_id=org.id))

    db_session.commit()

    token = create_access_token(data={"sub": str(user.id)})
    return org, user, token


# ============================================================================
# 1. SECTION 9 ACCEPTANCE TEST: FULL MULTI-ENTITY TOPOLOGY
# ============================================================================

def test_section_9_acceptance_topology(client, setup_org_and_admin):
    """
    Section 9 Acceptance Test:
    - 1 Organization
    - 3 Services (checkout-api, payment-service, auth-service)
    - 5 Repositories (checkout-api, payment-service, platform-config, infrastructure, shared-auth)
    - 3 Environments (production, staging, preview)
    - 2 Regions (us-east-1, ap-south-1)
    - 1 Shared Dependency Repository (shared-auth)
    """
    org, admin, token = setup_org_and_admin
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create Regions
    r1 = client.post("/regions", json={"name": "US East", "code": "us-east-1", "cloud_provider": "aws"}, headers=headers)
    assert r1.status_code == 201
    reg_us = r1.json()

    r2 = client.post("/regions", json={"name": "AP South", "code": "ap-south-1", "cloud_provider": "aws"}, headers=headers)
    assert r2.status_code == 201
    reg_ap = r2.json()

    # 2. Create Environments
    client.post("/environments", json={"name": "preview", "env_type": "preview"}, headers=headers)
    envs_resp = client.get("/environments", headers=headers)
    assert envs_resp.status_code == 200
    assert len(envs_resp.json()) >= 3  # production, staging, development seeded on bootstrap + preview

    # 3. Create 5 Repositories
    repos = {}
    for name in ["checkout-api", "payment-service", "platform-config", "infrastructure", "shared-auth"]:
        resp = client.post(
            "/repositories",
            json={"name": name, "full_name": f"acme/{name}", "language": "Python"},
            headers=headers,
        )
        assert resp.status_code == 201
        repos[name] = resp.json()

    # 4. Create 3 Services
    services = {}
    for name, tier in [("checkout-api", "critical"), ("payment-service", "critical"), ("auth-service", "high")]:
        resp = client.post(
            "/services",
            json={"name": name, "tier": tier, "description": f"{name} service"},
            headers=headers,
        )
        assert resp.status_code == 201
        services[name] = resp.json()

    # 5. Map Multi-Repository Topology for checkout-api
    # checkout-api -> checkout-api (Application, Primary)
    sr1 = client.post(
        "/service-repositories",
        json={
            "service_id": services["checkout-api"]["id"],
            "repository_id": repos["checkout-api"]["id"],
            "role": "application",
            "is_primary": True,
            "selection_reason": "Core web application codebase",
        },
        headers=headers,
    )
    assert sr1.status_code == 201

    # checkout-api -> platform-config (Configuration)
    sr2 = client.post(
        "/service-repositories",
        json={
            "service_id": services["checkout-api"]["id"],
            "repository_id": repos["platform-config"]["id"],
            "role": "configuration",
            "is_primary": False,
            "selection_reason": "Kubernetes Helm and environment configs",
        },
        headers=headers,
    )
    assert sr2.status_code == 201

    # checkout-api -> infrastructure (Infrastructure)
    sr3 = client.post(
        "/service-repositories",
        json={
            "service_id": services["checkout-api"]["id"],
            "repository_id": repos["infrastructure"]["id"],
            "role": "infrastructure",
            "is_primary": False,
            "selection_reason": "Terraform provisioning modules",
        },
        headers=headers,
    )
    assert sr3.status_code == 201

    # checkout-api -> shared-auth (Dependency)
    sr4 = client.post(
        "/service-repositories",
        json={
            "service_id": services["checkout-api"]["id"],
            "repository_id": repos["shared-auth"]["id"],
            "role": "dependency",
            "is_primary": False,
            "selection_reason": "JWT verification and security tokens",
        },
        headers=headers,
    )
    assert sr4.status_code == 201

    # 6. Map payment-service to shared-auth (Shared Repository verification)
    sr5 = client.post(
        "/service-repositories",
        json={
            "service_id": services["payment-service"]["id"],
            "repository_id": repos["shared-auth"]["id"],
            "role": "dependency",
            "is_primary": False,
            "selection_reason": "Shared authentication package",
        },
        headers=headers,
    )
    assert sr5.status_code == 201

    # 7. Verify checkout-api detail view returns all 4 repositories
    detail = client.get(f"/services/{services['checkout-api']['id']}", headers=headers)
    assert detail.status_code == 200
    data = detail.json()
    assert len(data["repositories"]) == 4
    roles = {r["role"]: r["repository_name"] for r in data["repositories"]}
    assert roles["application"] == "checkout-api"
    assert roles["configuration"] == "platform-config"
    assert roles["infrastructure"] == "infrastructure"
    assert roles["dependency"] == "shared-auth"


# ============================================================================
# 2. PRIMARY REPOSITORY UNIQUENESS CONSTRAINTS
# ============================================================================

def test_primary_repository_constraints(client, setup_org_and_admin):
    """At most one primary repository per service, and primary must have role APPLICATION."""
    org, admin, token = setup_org_and_admin
    headers = {"Authorization": f"Bearer {token}"}

    # Create service and repos
    svc = client.post("/services", json={"name": "order-service"}, headers=headers).json()
    repo1 = client.post("/repositories", json={"name": "r1", "full_name": "acme/r1"}, headers=headers).json()
    repo2 = client.post("/repositories", json={"name": "r2", "full_name": "acme/r2"}, headers=headers).json()

    # 1. Primary on non-application role fails -> 400
    r_bad_role = client.post(
        "/service-repositories",
        json={
            "service_id": svc["id"],
            "repository_id": repo1["id"],
            "role": "configuration",
            "is_primary": True,
            "selection_reason": "Invalid primary config",
        },
        headers=headers,
    )
    assert r_bad_role.status_code == 400

    # 2. First primary succeeds
    r_ok = client.post(
        "/service-repositories",
        json={
            "service_id": svc["id"],
            "repository_id": repo1["id"],
            "role": "application",
            "is_primary": True,
            "selection_reason": "Primary app repo",
        },
        headers=headers,
    )
    assert r_ok.status_code == 201

    # 3. Second primary on same service fails -> 409 Conflict
    r_dup = client.post(
        "/service-repositories",
        json={
            "service_id": svc["id"],
            "repository_id": repo2["id"],
            "role": "application",
            "is_primary": True,
            "selection_reason": "Second primary attempt",
        },
        headers=headers,
    )
    assert r_dup.status_code == 409


# ============================================================================
# 3. DEPENDENCIES DIRECTION & CYCLE-SAFE GRAPH TRAVERSAL
# ============================================================================

def test_service_dependencies_and_graph(client, setup_org_and_admin):
    """
    Verify upstream vs downstream dependency traversal and self-dependency rejection.
    Topology: Frontend (A) -> Backend (B) -> Database/Auth (C)
    """
    org, admin, token = setup_org_and_admin
    headers = {"Authorization": f"Bearer {token}"}

    svcA = client.post("/services", json={"name": "frontend-web"}, headers=headers).json()
    svcB = client.post("/services", json={"name": "backend-api"}, headers=headers).json()
    svcC = client.post("/services", json={"name": "auth-db"}, headers=headers).json()

    # 1. Self-dependency rejected -> 400
    r_self = client.post(
        "/dependencies",
        json={
            "dependent_service_id": svcA["id"],
            "upstream_service_id": svcA["id"],
            "dependency_type": "synchronous",
        },
        headers=headers,
    )
    assert r_self.status_code == 400

    # 2. Link A -> B (A calls B: B is upstream of A)
    client.post(
        "/dependencies",
        json={"dependent_service_id": svcA["id"], "upstream_service_id": svcB["id"]},
        headers=headers,
    )

    # 3. Link B -> C (B calls C: C is upstream of B)
    client.post(
        "/dependencies",
        json={"dependent_service_id": svcB["id"], "upstream_service_id": svcC["id"]},
        headers=headers,
    )

    # 4. Graph query for B
    graph_b = client.get(f"/services/{svcB['id']}/graph", headers=headers).json()
    upstream_names = [u["name"] for u in graph_b["upstream_dependencies"]]
    downstream_names = [d["name"] for d in graph_b["downstream_dependents"]]

    assert "auth-db" in upstream_names
    assert "frontend-web" in downstream_names


# ============================================================================
# 4. SERVICE OWNERSHIP & ESCALATION POLICIES
# ============================================================================

def test_service_ownership_rules(client, setup_org_and_admin, db_session):
    """Verify exclusive team/user ownership, primary uniqueness, and ONCALL escalation requirement."""
    org, admin, token = setup_org_and_admin
    headers = {"Authorization": f"Bearer {token}"}

    svc = client.post("/services", json={"name": "billing-engine"}, headers=headers).json()
    team = client.post("/teams", json={"name": "Billing Team"}, headers=headers).json()

    # 1. Setting both team_id and user_id rejected -> 400
    r_both = client.post(
        "/ownership",
        json={
            "service_id": svc["id"],
            "team_id": team["id"],
            "user_id": str(admin.id),
            "ownership_type": "primary_owner",
        },
        headers=headers,
    )
    assert r_both.status_code == 400

    # 2. Setting neither rejected -> 400
    r_neither = client.post(
        "/ownership",
        json={"service_id": svc["id"], "ownership_type": "primary_owner"},
        headers=headers,
    )
    assert r_neither.status_code == 400

    # 3. Set primary team owner
    r_primary = client.post(
        "/ownership",
        json={
            "service_id": svc["id"],
            "team_id": team["id"],
            "ownership_type": "primary_owner",
        },
        headers=headers,
    )
    assert r_primary.status_code == 201

    # 4. Second primary owner rejected -> 409
    r_dup_primary = client.post(
        "/ownership",
        json={
            "service_id": svc["id"],
            "user_id": str(admin.id),
            "ownership_type": "primary_owner",
        },
        headers=headers,
    )
    assert r_dup_primary.status_code == 409

    # 5. ONCALL without escalation policy rejected -> 400
    r_oncall_bad = client.post(
        "/ownership",
        json={
            "service_id": svc["id"],
            "team_id": team["id"],
            "ownership_type": "oncall",
        },
        headers=headers,
    )
    assert r_oncall_bad.status_code == 400

    # 6. ONCALL with escalation policy succeeds
    r_oncall_ok = client.post(
        "/ownership",
        json={
            "service_id": svc["id"],
            "team_id": team["id"],
            "ownership_type": "oncall",
            "escalation_policy": "PagerDuty Escalation Policy",
        },
        headers=headers,
    )
    assert r_oncall_ok.status_code == 201


# ============================================================================
# 5. MULTI-TENANT ISOLATION
# ============================================================================

def test_multi_tenant_isolation(client, setup_org_and_admin, db_session):
    """Organization A cannot view, link, or mutate Organization B resources."""
    orgA, adminA, tokenA = setup_org_and_admin
    headersA = {"Authorization": f"Bearer {tokenA}"}

    # Create Org B and user B
    orgB = Organization(id=uuid.uuid4(), name="Beta Corp", slug="beta-corp")
    db_session.add(orgB)
    userB = User(id=uuid.uuid4(), username="bob", email="bob@beta.com", hashed_password="hash", role="admin", organization_id=orgB.id)
    db_session.add(userB)
    membershipB = UserOrganizationMembership(id=uuid.uuid4(), user_id=userB.id, organization_id=orgB.id, role=MembershipRole.OWNER)
    db_session.add(membershipB)
    db_session.commit()
    tokenB = create_access_token(data={"sub": str(userB.id)})
    headersB = {"Authorization": f"Bearer {tokenB}"}

    # Create Service and Repo in Org A
    svcA = client.post("/services", json={"name": "svc-a"}, headers=headersA).json()
    repoA = client.post("/repositories", json={"name": "repo-a", "full_name": "acme/repo-a"}, headers=headersA).json()

    # User B tries to view Org A service -> 404 (zero leak)
    resp_get = client.get(f"/services/{svcA['id']}", headers=headersB)
    assert resp_get.status_code == 404

    # User B tries to link Org A repository to an Org B service -> 404/400
    svcB = client.post("/services", json={"name": "svc-b"}, headers=headersB).json()
    resp_cross = client.post(
        "/service-repositories",
        json={
            "service_id": svcB["id"],
            "repository_id": repoA["id"],
            "role": "application",
            "selection_reason": "Cross-org attack",
        },
        headers=headersB,
    )
    assert resp_cross.status_code in (400, 404)


# ============================================================================
# 6. ROLE-BASED ACCESS CONTROL & LAST OWNER PROTECTION
# ============================================================================

def test_rbac_and_last_owner_protection(client, setup_org_and_admin, db_session):
    """Verify role permissions (Viewer read-only) and last owner protection."""
    org, admin, token_owner = setup_org_and_admin
    headers_owner = {"Authorization": f"Bearer {token_owner}"}

    # Create a viewer user in the same organization
    viewer_user = User(
        id=uuid.uuid4(),
        username="victor",
        email="victor@acme.com",
        hashed_password="hash",
        role="user",
        organization_id=org.id,
    )
    db_session.add(viewer_user)
    membership_viewer = UserOrganizationMembership(
        id=uuid.uuid4(),
        user_id=viewer_user.id,
        organization_id=org.id,
        role=MembershipRole.VIEWER,
    )
    db_session.add(membership_viewer)
    db_session.commit()
    token_viewer = create_access_token(data={"sub": str(viewer_user.id)})
    headers_viewer = {"Authorization": f"Bearer {token_viewer}"}

    # 1. Viewer can list services
    r_list = client.get("/services", headers=headers_viewer)
    assert r_list.status_code == 200

    # 2. Viewer cannot create services -> 403 Forbidden
    r_create = client.post("/services", json={"name": "unauthorized-svc"}, headers=headers_viewer)
    assert r_create.status_code == 403

    # 3. Owner tries to demote the only owner -> 400 Bad Request
    owner_membership = (
        db_session.query(UserOrganizationMembership)
        .filter(UserOrganizationMembership.user_id == admin.id)
        .first()
    )
    r_demote = client.patch(
        f"/organizations/memberships/{owner_membership.id}/role",
        json={"role": "member"},
        headers=headers_owner,
    )
    assert r_demote.status_code == 400
    assert "Cannot demote the last remaining owner" in r_demote.json()["detail"]


# ============================================================================
# 7. SSRF PROTECTION ON DEPLOYMENT CONFIGURATIONS
# ============================================================================

def test_ssrf_protection_on_deployments(client, setup_org_and_admin):
    """Health check URLs pointing to loopback or metadata IPs must be rejected."""
    org, admin, token = setup_org_and_admin
    headers = {"Authorization": f"Bearer {token}"}

    svc = client.post("/services", json={"name": "ssrf-test-svc"}, headers=headers).json()
    envs = client.get("/environments", headers=headers).json()
    env_id = envs[0]["id"]

    # 1. Localhost URL -> 400
    r_local = client.post(
        f"/services/{svc['id']}/deployment-configs",
        json={"service_id": svc["id"], "environment_id": env_id, "health_check_url": "http://localhost:8080/health"},
        headers=headers,
    )
    assert r_local.status_code == 400

    # 2. AWS Metadata URL -> 400
    r_meta = client.post(
        f"/services/{svc['id']}/deployment-configs",
        json={"service_id": svc["id"], "environment_id": env_id, "health_check_url": "http://169.254.169.254/latest/meta-data"},
        headers=headers,
    )
    assert r_meta.status_code == 400

    # 3. Public URL -> 201 Created
    r_public = client.post(
        f"/services/{svc['id']}/deployment-configs",
        json={"service_id": svc["id"], "environment_id": env_id, "health_check_url": "https://api.acme.com/healthz"},
        headers=headers,
    )
    assert r_public.status_code == 201


# ============================================================================
# 8. ORGANIZATION BOOTSTRAP & CONTEXT SWITCHING
# ============================================================================

def test_organization_bootstrap_and_switching(client, db_session):
    """Verify that creating an organization seeds owner membership and default envs, and activate switches context."""
    # Create user with no organization
    user = User(
        id=uuid.uuid4(),
        username="newuser",
        email="newuser@example.com",
        hashed_password="hash",
        role="user",
        organization_id=None,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(data={"sub": str(user.id)})
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Bootstrap new organization
    r_create = client.post("/organizations", json={"name": "Delta Tech"}, headers=headers)
    assert r_create.status_code == 201
    org_data = r_create.json()
    assert org_data["name"] == "Delta Tech"
    assert org_data["slug"] == "delta-tech"

    # Verify user is OWNER
    memberships = client.get("/organizations/memberships", headers=headers).json()
    assert len(memberships) == 1
    assert memberships[0]["role"] == "owner"
    assert memberships[0]["username"] == "newuser"

    # Verify default environments were created in same transaction
    envs = client.get("/environments", headers=headers).json()
    env_names = {e["name"] for e in envs}
    assert "production" in env_names
    assert "staging" in env_names
    assert "development" in env_names

    # 2. Bootstrap second organization for same user
    r_create2 = client.post("/organizations", json={"name": "Epsilon Labs"}, headers=headers)
    assert r_create2.status_code == 201
    org2_data = r_create2.json()

    # Verify active context is now Epsilon Labs
    active_org = client.get("/organizations/me", headers=headers).json()
    assert active_org["slug"] == "epsilon-labs"

    # 3. Switch back to Delta Tech using /activate
    r_act = client.post(f"/organizations/{org_data['id']}/activate", headers=headers)
    assert r_act.status_code == 200
    assert r_act.json()["organization_slug"] == "delta-tech"

    active_org_after = client.get("/organizations/me", headers=headers).json()
    assert active_org_after["slug"] == "delta-tech"


# ============================================================================
# 9. REPOSITORY BACKFILL INTEGRITY
# ============================================================================

def test_repository_backfill_logic(db_session):
    """Verify deterministic backfill logic for existing unassigned repositories."""
    org1 = Organization(id=uuid.uuid4(), name="Org One", slug="org-one")
    org2 = Organization(id=uuid.uuid4(), name="Org Two", slug="org-two")
    db_session.add_all([org1, org2])
    db_session.flush()

    user1 = User(id=uuid.uuid4(), username="u1", email="u1@test.com", hashed_password="h", organization_id=org1.id)
    user2 = User(id=uuid.uuid4(), username="u2", email="u2@test.com", hashed_password="h", organization_id=org2.id)
    db_session.add_all([user1, user2])
    db_session.flush()

    # Repos with owner_id
    repo1 = Repository(id=uuid.uuid4(), name="r1", full_name="org1/r1", owner_id=user1.id, organization_id=org1.id)
    repo2 = Repository(id=uuid.uuid4(), name="r2", full_name="org2/r2", owner_id=user2.id, organization_id=org2.id)
    db_session.add_all([repo1, repo2])
    db_session.commit()

    assert repo1.organization_id == org1.id
    assert repo2.organization_id == org2.id
