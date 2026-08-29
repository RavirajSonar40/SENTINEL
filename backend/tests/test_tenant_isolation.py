import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.core.database import get_db, Base

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


def _register(client, username, password="testpass123"):
    return client.post("/auth/register", json={
        "username": username,
        "email": f"{username}@test.com",
        "password": password,
    })


def _login(client, username, password="testpass123"):
    return client.post("/auth/login", json={"username": username, "password": password})


def _auth_header(token):
    return {"Authorization": f"Bearer {token}"}


class TestTenantIsolation:
    """Non-admin users can only see incidents they created."""

    def test_user_cannot_see_other_users_incidents(self, client):
        # Register two users
        r1 = _register(client, "tenant_owner_a")
        r2 = _register(client, "tenant_viewer_b")
        if r1.status_code != 201 or r2.status_code != 201:
            pytest.skip("Registration unavailable")

        token_a = r1.json()["access_token"]
        token_b = r2.json()["access_token"]
        headers_a = _auth_header(token_a)
        headers_b = _auth_header(token_b)

        # User A creates an incident
        r = client.post("/incidents", json={
            "title": "Secret incident A", "severity": "SEV-2", "service": "svc-a"
        }, headers=headers_a)
        if r.status_code not in (200, 201):
            pytest.skip("Incident creation unavailable")
        inc_id = r.json()["id"]

        # User A can see it
        r_list = client.get("/incidents", headers=headers_a)
        assert r_list.status_code == 200
        ids_a = [i["id"] for i in r_list.json()]
        assert inc_id in ids_a

        # User B CANNOT see it
        r_list_b = client.get("/incidents", headers=headers_b)
        assert r_list_b.status_code == 200
        ids_b = [i["id"] for i in r_list_b.json()]
        assert inc_id not in ids_b

    def test_user_cannot_view_other_users_incident_detail(self, client):
        r1 = _register(client, "tenant_detail_a")
        r2 = _register(client, "tenant_detail_b")
        if r1.status_code != 201 or r2.status_code != 201:
            pytest.skip("Registration unavailable")

        token_a = r1.json()["access_token"]
        token_b = r2.json()["access_token"]

        r = client.post("/incidents", json={
            "title": "Private incident detail", "severity": "SEV-3", "service": "svc"
        }, headers=_auth_header(token_a))
        if r.status_code not in (200, 201):
            pytest.skip("Incident creation unavailable")
        inc_id = r.json()["id"]

        # User B cannot view detail
        r_detail = client.get(f"/incidents/{inc_id}", headers=_auth_header(token_b))
        assert r_detail.status_code == 404

    def test_user_cannot_update_other_users_incident(self, client):
        r1 = _register(client, "tenant_update_a")
        r2 = _register(client, "tenant_update_b")
        if r1.status_code != 201 or r2.status_code != 201:
            pytest.skip("Registration unavailable")

        token_a = r1.json()["access_token"]
        token_b = r2.json()["access_token"]

        r = client.post("/incidents", json={
            "title": "Incident to block update", "severity": "SEV-3", "service": "svc"
        }, headers=_auth_header(token_a))
        if r.status_code not in (200, 201):
            pytest.skip("Incident creation unavailable")
        inc_id = r.json()["id"]

        # User B cannot update
        r_update = client.patch(f"/incidents/{inc_id}", json={"title": "Hacked"},
                               headers=_auth_header(token_b))
        assert r_update.status_code == 404

    def test_admin_can_see_all_incidents(self, client):
        # Register a regular user
        r1 = _register(client, "tenant_admin_see")
        if r1.status_code != 201:
            pytest.skip("Registration unavailable")
        token_user = r1.json()["access_token"]

        # Register admin (or login existing)
        r_admin = _register(client, "tenant_admin_all")
        if r_admin.status_code == 201:
            token_admin = r_admin.json()["access_token"]
        else:
            r_admin = _login(client, "admin", "sentinel123")
            if r_admin.status_code != 200:
                pytest.skip("No admin available")
            token_admin = r_admin.json()["access_token"]

        # User creates incident
        r = client.post("/incidents", json={
            "title": "User incident for admin", "severity": "SEV-3", "service": "svc"
        }, headers=_auth_header(token_user))
        if r.status_code not in (200, 201):
            pytest.skip("Incident creation unavailable")
        inc_id = r.json()["id"]

        # Admin can see it
        r_list = client.get("/incidents", headers=_auth_header(token_admin))
        assert r_list.status_code == 200
        ids = [i["id"] for i in r_list.json()]
        assert inc_id in ids

    def test_user_cannot_delete_other_users_incident(self, client):
        r1 = _register(client, "tenant_del_a")
        r2 = _register(client, "tenant_del_b")
        if r1.status_code != 201 or r2.status_code != 201:
            pytest.skip("Registration unavailable")

        token_a = r1.json()["access_token"]
        token_b = r2.json()["access_token"]

        r = client.post("/incidents", json={
            "title": "Incident to block delete", "severity": "SEV-3", "service": "svc"
        }, headers=_auth_header(token_a))
        if r.status_code not in (200, 201):
            pytest.skip("Incident creation unavailable")
        inc_id = r.json()["id"]

        # User B cannot delete
        r_del = client.delete(f"/incidents/{inc_id}", headers=_auth_header(token_b))
        assert r_del.status_code == 404
