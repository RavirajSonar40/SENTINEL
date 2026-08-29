import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.core.database import get_db, Base
from app.models.incident import User, Organization, UserOrganizationMembership, MembershipRole
from app.core.auth import hash_password
import uuid

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.create_all(bind=test_engine)
    session = TestingSessionLocal()
    try:
        org = Organization(name="Routes Org", slug=f"routes-org-{uuid.uuid4().hex[:6]}")
        session.add(org)
        session.flush()

        user = User(
            username="admin",
            email="admin@sentinel.io",
            hashed_password=hash_password("sentinel123"),
            role="admin",
            organization_id=org.id,
            is_active=True,
        )
        session.add(user)
        session.flush()

        mem = UserOrganizationMembership(
            user_id=user.id,
            organization_id=org.id,
            role=MembershipRole.ADMIN,
        )
        session.add(mem)
        session.commit()
    finally:
        session.close()

    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    from app.main import app

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def get_auth_header(client):
    resp = client.post("/auth/login", json={"username": "admin", "password": "sentinel123"})
    if resp.status_code == 200:
        token = resp.json().get("access_token", "")
        return {"Authorization": f"Bearer {token}"}
    return {}


class TestAuthRoutes:
    def test_login(self, client):
        response = client.post("/auth/login", json={"username": "admin", "password": "sentinel123"})
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data

    def test_login_wrong_password(self, client):
        response = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
        assert response.status_code in (400, 401, 422)

    def test_me(self, client):
        headers = get_auth_header(client)
        if headers:
            response = client.get("/auth/me", headers=headers)
            assert response.status_code == 200


class TestIncidentRoutes:
    def test_list_incidents(self, client):
        headers = get_auth_header(client)
        response = client.get("/incidents", headers=headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_create_incident(self, client):
        headers = get_auth_header(client)
        response = client.post("/incidents", json={
            "title": "Test incident",
            "description": "Test description",
            "severity": "SEV-2",
            "service": "test-service",
        }, headers=headers)
        assert response.status_code in (200, 201)


class TestMetricsRoutes:
    def test_health_check(self, client):
        response = client.get("/metrics/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_get_metrics(self, client):
        headers = get_auth_header(client)
        response = client.get("/metrics", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "system" in data
        assert "llm" in data


class TestEvaluationRoutes:
    def test_benchmark_dataset(self, client):
        headers = get_auth_header(client)
        response = client.get("/investigations/eval/benchmark", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 10


class TestWebhookRoutes:
    def test_generic_webhook(self, client):
        response = client.post("/webhooks/generic", json={
            "title": "Test alert",
            "severity": "critical",
            "service": "test-service",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_webhook_config(self, client):
        response = client.get("/webhooks/config")
        assert response.status_code == 200
        data = response.json()
        assert "endpoints" in data


class TestHealthRoutes:
    def test_service_health(self, client):
        headers = get_auth_header(client)
        response = client.get("/services/health", headers=headers)
        assert response.status_code == 200


class TestApprovalRoutes:
    def test_pending_approvals(self, client):
        headers = get_auth_header(client)
        response = client.get("/approvals/pending", headers=headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)
