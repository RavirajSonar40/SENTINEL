"""Tests for API routes — with proper auth handling."""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create test client."""
    from app.main import app
    return TestClient(app)


def get_auth_header(client):
    """Login and get auth header."""
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
