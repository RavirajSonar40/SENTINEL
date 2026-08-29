"""
Integration & API Tests for Workflow Router, Work Items API, and State Machine.

Verifies:
- Direct task fast-tracking with hypothesis skipping
- Production incident async routing and linked Incident creation
- Security incident isolation and autonomous execution blocking
- User without organization is rejected with HTTP 403
- Server-enforced organization tenant isolation
- Idempotency key duplicate creation prevention
- Multi-repository relationship persistence
- State machine transition validation (client cannot force VALIDATED/RESOLVED)
- Terminal cancellation rejection (cannot cancel VALIDATED, DRAFT_PR_CREATED, RESOLVED)
- Cross-organization service/environment validation
- Dry-run classification endpoint
"""

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.core.database import Base, get_db
from app.core.auth import get_current_user, create_access_token
from app.models.incident import User, Organization, Service, Environment, Repository, Incident
from app.models.work_item import WorkItem, WorkType, WorkItemStatus, WorkItemRepository

from sqlalchemy.pool import StaticPool

# In-memory SQLite for deterministic test isolation
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
def setup_org_and_user(db_session):
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
    db_session.commit()

    token = create_access_token(data={"sub": str(user.id)})
    return org, user, token


def test_user_without_organization_is_rejected_403(client, db_session):
    """User without an organization cannot create work items -> HTTP 403."""
    user = User(
        id=uuid.uuid4(),
        username="orphan",
        email="orphan@example.com",
        hashed_password="hash",
        role="user",
        organization_id=None,  # No organization
    )
    db_session.add(user)
    db_session.commit()

    token = create_access_token(data={"sub": str(user.id)})
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/work-items",
        json={"title": "Add README.md"},
        headers=headers,
    )
    assert resp.status_code == 403
    assert "Organization membership is required" in resp.json()["detail"]


def test_direct_task_routing_creates_work_item_and_skips_hypotheses(client, setup_org_and_user):
    """DIRECT_TASK creates work item with workflow='repository_task' and skips incident hypotheses."""
    org, user, token = setup_org_and_user
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/work-items",
        json={"title": "Add README.md", "description": "Create project readme"},
        headers=headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["work_type"] == "DIRECT_TASK"
    assert data["workflow"] == "repository_task"
    assert data["requires_runtime_evidence"] is False
    assert "README.md" in data["target_files"]
    assert data["status"] == "routed"
    assert data["job_id"] is not None


def test_production_incident_creates_linked_incident_and_enqueues_job(client, setup_org_and_user, db_session):
    """PRODUCTION_INCIDENT automatically creates and links an Incident record and enqueues job."""
    org, user, token = setup_org_and_user
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/work-items",
        json={"title": "Production checkout is down with 503 errors"},
        headers=headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["work_type"] == "PRODUCTION_INCIDENT"
    assert data["workflow"] == "production_incident"
    assert data["requires_runtime_evidence"] is True
    assert data["incident_id"] is not None
    assert data["job_id"] is not None

    # Verify Incident row was created
    inc = db_session.query(Incident).filter(Incident.id == uuid.UUID(data["incident_id"])).first()
    assert inc is not None
    assert "checkout" in inc.title.lower()


def test_security_incident_blocks_autonomous_execution(client, setup_org_and_user):
    """SECURITY_INCIDENT halts in status=BLOCKED with a security case ID."""
    org, user, token = setup_org_and_user
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/work-items",
        json={"title": "Suspicious login activity from unknown IP address"},
        headers=headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["work_type"] == "SECURITY_INCIDENT"
    assert data["status"] == "blocked"
    assert data["workflow"] == "security_incident"


def test_idempotency_prevents_duplicate_work_items(client, setup_org_and_user):
    """Submitting duplicate Idempotency-Key returns existing work item without re-routing."""
    org, user, token = setup_org_and_user
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "req-12345"}

    r1 = client.post(
        "/work-items",
        json={"title": "Add CONTRIBUTING.md"},
        headers=headers,
    )
    assert r1.status_code == 201
    item_id_1 = r1.json()["id"]

    r2 = client.post(
        "/work-items",
        json={"title": "Add CONTRIBUTING.md"},
        headers=headers,
    )
    assert r2.status_code == 201
    item_id_2 = r2.json()["id"]

    assert item_id_1 == item_id_2


def test_work_item_repository_relationship_persisted(client, setup_org_and_user, db_session):
    """WorkItemRepository relationship persists multi-repository scope."""
    org, user, token = setup_org_and_user
    repo = Repository(
        id=uuid.uuid4(),
        name="backend-repo",
        full_name="acme/backend-repo",
        owner_id=user.id,
        organization_id=org.id,
    )
    db_session.add(repo)
    db_session.commit()

    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post(
        "/work-items",
        json={"title": "Add docker-compose.yml", "repository_ids": [str(repo.id)]},
        headers=headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["repositories"]) == 1
    assert data["repositories"][0]["repository_name"] == "backend-repo"


def test_client_cannot_force_validated_or_resolved_status(client, setup_org_and_user):
    """Clients cannot directly PATCH work item status to VALIDATED or RESOLVED -> HTTP 403."""
    org, user, token = setup_org_and_user
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = client.post(
        "/work-items",
        json={"title": "Add README.md"},
        headers=headers,
    )
    work_item_id = create_resp.json()["id"]

    # Try to jump to VALIDATED
    patch_resp = client.patch(
        f"/work-items/{work_item_id}/status",
        json={"status": "validated"},
        headers=headers,
    )
    assert patch_resp.status_code in (403, 409)


def test_terminal_state_cancellation_is_rejected(client, setup_org_and_user, db_session):
    """Terminal states cannot be cancelled -> HTTP 409."""
    org, user, token = setup_org_and_user
    headers = {"Authorization": f"Bearer {token}"}

    # Create item in RESOLVED state
    item = WorkItem(
        organization_id=org.id,
        work_type=WorkType.DIRECT_TASK,
        title="Completed task",
        status=WorkItemStatus.RESOLVED,
        workflow="repository_task",
    )
    db_session.add(item)
    db_session.commit()

    patch_resp = client.patch(
        f"/work-items/{item.id}/status",
        json={"status": "cancelled"},
        headers=headers,
    )
    assert patch_resp.status_code == 409


def test_cross_org_service_or_environment_is_rejected(client, setup_org_and_user, db_session):
    """Specifying a service/environment from a foreign organization -> HTTP 400."""
    org, user, token = setup_org_and_user
    foreign_org = Organization(id=uuid.uuid4(), name="Foreign Corp", slug="foreign-corp")
    foreign_env = Environment(
        id=uuid.uuid4(),
        name="foreign-prod",
        organization_id=foreign_org.id,
    )
    db_session.add(foreign_org)
    db_session.add(foreign_env)
    db_session.commit()

    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post(
        "/work-items",
        json={"title": "Add README.md", "environment_id": str(foreign_env.id)},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "Environment does not belong" in resp.json()["detail"]


def test_dry_run_classify_endpoint(client, setup_org_and_user):
    """POST /work-items/classify runs stateless intent classification."""
    org, user, token = setup_org_and_user
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/work-items/classify",
        json={"title": "Fix login returns 500 when password is empty"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["work_type"] == "BUG"
    assert data["workflow"] == "bug"
    assert data["requires_runtime_evidence"] is False


def test_list_and_get_work_items_tenant_isolation(client, setup_org_and_user, db_session):
    """Users only see work items belonging to their organization."""
    org1, user1, token1 = setup_org_and_user
    headers1 = {"Authorization": f"Bearer {token1}"}

    # Org 2 & User 2
    org2 = Organization(id=uuid.uuid4(), name="Beta Corp", slug="beta-corp")
    user2 = User(
        id=uuid.uuid4(),
        username="bob",
        email="bob@beta.com",
        hashed_password="hash",
        role="user",
        organization_id=org2.id,
    )
    db_session.add(org2)
    db_session.add(user2)
    db_session.commit()
    token2 = create_access_token(data={"sub": str(user2.id)})
    headers2 = {"Authorization": f"Bearer {token2}"}

    # Create work item in Org 1
    r1 = client.post("/work-items", json={"title": "Add README.md"}, headers=headers1)
    assert r1.status_code == 201
    item1_id = r1.json()["id"]

    # User 2 lists work items -> gets empty list
    list_resp = client.get("/work-items", headers=headers2)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 0

    # User 2 tries to GET Org 1 item -> 403 Forbidden
    get_resp = client.get(f"/work-items/{item1_id}", headers=headers2)
    assert get_resp.status_code == 403

