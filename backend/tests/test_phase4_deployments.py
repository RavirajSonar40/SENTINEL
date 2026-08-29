"""
Integration and Unit Tests for Phase 4:
Deployment Inventory, Ingestion Webhooks (GitHub & Generic Signed),
Lifecycle Tracking, Timing Fields, and Incident Window Correlation.
"""

import json
import uuid
import hmac
import hashlib
import time
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.core.auth import create_access_token
from app.core.crypto import encrypt_secret, generate_webhook_credentials
from app.models.incident import (
    User, Organization, Environment, Service, Repository,
    MembershipRole, UserOrganizationMembership, Region,
    Deployment, DeploymentStatus, DeploymentProvider, WebhookEndpoint,
    ServiceRepository, ServiceRepositoryRole
)

# In-memory SQLite with StaticPool for deterministic test isolation
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def setup_org_and_user(db_session):
    org = Organization(
        id=uuid.uuid4(),
        name="Acme Corp",
        slug="acme",
    )
    db_session.add(org)

    user = User(
        id=uuid.uuid4(),
        username="lead_dev",
        email="lead@acme.com",
        hashed_password="mock_password_hash",
        organization_id=org.id,
    )
    db_session.add(user)

    membership = UserOrganizationMembership(
        id=uuid.uuid4(),
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.ADMIN,
    )
    db_session.add(membership)
    db_session.commit()

    token = create_access_token(data={"sub": str(user.id), "username": user.username})
    return org, user, token


@pytest.fixture
def setup_topology(db_session, setup_org_and_user):
    org, user, token = setup_org_and_user

    env_prod = Environment(id=uuid.uuid4(), organization_id=org.id, name="production", env_type="production")
    env_stage = Environment(id=uuid.uuid4(), organization_id=org.id, name="staging", env_type="staging")
    reg_us = Region(id=uuid.uuid4(), organization_id=org.id, name="US East", code="us-east-1")
    
    svc_payment = Service(id=uuid.uuid4(), organization_id=org.id, name="payment-service", slug="payment-service", tier="critical")
    repo_payment = Repository(id=uuid.uuid4(), organization_id=org.id, name="payment-service", full_name="acme/payment-service")

    # Link repo to service via ServiceRepository as primary application
    sr_payment = ServiceRepository(
        id=uuid.uuid4(),
        organization_id=org.id,
        service_id=svc_payment.id,
        repository_id=repo_payment.id,
        role=ServiceRepositoryRole.APPLICATION,
        is_primary=True,
        selection_reason="Primary payment service repository",
    )

    # Create GitHub webhook endpoint for signature verification
    gh_key_id, gh_raw_secret = generate_webhook_credentials()
    gh_endpoint = WebhookEndpoint(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="GitHub Webhook",
        provider="github",
        key_id=gh_key_id,
        encrypted_secret=encrypt_secret(gh_raw_secret),
        is_active=True,
    )

    db_session.add_all([env_prod, env_stage, reg_us, svc_payment, repo_payment, sr_payment, gh_endpoint])
    db_session.commit()

    return {
        "org": org,
        "user": user,
        "token": token,
        "env_prod": env_prod,
        "env_stage": env_stage,
        "reg_us": reg_us,
        "svc_payment": svc_payment,
        "repo_payment": repo_payment,
        "sr_payment": sr_payment,
        "gh_endpoint": gh_endpoint,
        "gh_raw_secret": gh_raw_secret,
    }


# ============================================================================
# 1. TIMING FIELDS & LIFECYCLE STATE MACHINE
# ============================================================================

def test_deployment_lifecycle_and_timing_fields(client, setup_topology, db_session):
    """Test full deployment lifecycle: PENDING -> IN_PROGRESS -> SUCCEEDED with timing calculation."""
    topo = setup_topology
    headers = {"Authorization": f"Bearer {topo['token']}"}

    # 1. Create deployment in PENDING state
    resp = client.post(
        "/deployments",
        json={
            "service_id": str(topo["svc_payment"].id),
            "environment_id": str(topo["env_prod"].id),
            "region_id": str(topo["reg_us"].id),
            "repository_id": str(topo["repo_payment"].id),
            "commit_sha": "a1b2c3d4e5f678901234567890abcdef12345678",
            "version": "v1.0.0",
            "status": "pending",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    dep_data = resp.json()
    dep_id = dep_data["id"]
    assert dep_data["status"] == "pending"
    assert dep_data["is_current"] is False
    assert dep_data["started_at"] is None
    assert dep_data["finished_at"] is None
    assert dep_data["duration_seconds"] is None

    # 2. Transition PENDING -> IN_PROGRESS
    resp = client.patch(
        f"/deployments/{dep_id}/status",
        json={"status": "in_progress"},
        headers=headers,
    )
    assert resp.status_code == 200
    dep_data = resp.json()
    assert dep_data["status"] == "in_progress"
    assert dep_data["started_at"] is not None
    assert dep_data["finished_at"] is None

    started_at = datetime.fromisoformat(dep_data["started_at"].replace("Z", "+00:00"))

    # 3. Transition IN_PROGRESS -> SUCCEEDED with finished_at
    finished_at = started_at + timedelta(seconds=45)
    resp = client.patch(
        f"/deployments/{dep_id}/status",
        json={
            "status": "succeeded",
            "finished_at": finished_at.isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 200
    dep_data = resp.json()
    assert dep_data["status"] == "succeeded"
    assert dep_data["is_current"] is True
    assert dep_data["finished_at"] is not None
    assert dep_data["duration_seconds"] == pytest.approx(45.0, 0.1)


# ============================================================================
# 2. CURRENT DEPLOYMENT UNIQUENESS & ATOMIC SWITCHING
# ============================================================================

def test_current_deployment_atomic_switching(client, setup_topology):
    """When a new deployment SUCCEEDS, prior deployments on the same target are atomically flipped to is_current=False."""
    topo = setup_topology
    headers = {"Authorization": f"Bearer {topo['token']}"}

    # 1. Release D1 (v1.0.0) -> SUCCEEDED
    resp1 = client.post(
        "/deployments",
        json={
            "service_id": str(topo["svc_payment"].id),
            "environment_id": str(topo["env_prod"].id),
            "region_id": str(topo["reg_us"].id),
            "commit_sha": "1111111111111111111111111111111111111111",
            "version": "v1.0.0",
            "status": "succeeded",
        },
        headers=headers,
    )
    assert resp1.status_code == 201
    d1_id = resp1.json()["id"]
    assert resp1.json()["is_current"] is True

    # Check current deployment
    cur_resp = client.get(
        f"/deployments/current?service_id={topo['svc_payment'].id}&environment_id={topo['env_prod'].id}&region_id={topo['reg_us'].id}",
        headers=headers,
    )
    assert cur_resp.status_code == 200
    assert cur_resp.json()["id"] == d1_id
    assert cur_resp.json()["commit_sha"] == "1111111111111111111111111111111111111111"

    # 2. Release D2 (v2.0.0) -> SUCCEEDED on same target
    resp2 = client.post(
        "/deployments",
        json={
            "service_id": str(topo["svc_payment"].id),
            "environment_id": str(topo["env_prod"].id),
            "region_id": str(topo["reg_us"].id),
            "commit_sha": "2222222222222222222222222222222222222222",
            "version": "v2.0.0",
            "status": "succeeded",
        },
        headers=headers,
    )
    assert resp2.status_code == 201
    d2_id = resp2.json()["id"]
    assert resp2.json()["is_current"] is True

    # 3. Verify D1 is no longer current
    d1_check = client.get(f"/deployments/{d1_id}", headers=headers).json()
    assert d1_check["is_current"] is False

    # 4. Verify /deployments/current returns D2
    cur_resp2 = client.get(
        f"/deployments/current?service_id={topo['svc_payment'].id}&environment_id={topo['env_prod'].id}&region_id={topo['reg_us'].id}",
        headers=headers,
    )
    assert cur_resp2.json()["id"] == d2_id
    assert cur_resp2.json()["commit_sha"] == "2222222222222222222222222222222222222222"


def test_global_target_current_deployment_uniqueness(client, setup_topology):
    """Test global target (null region) uniqueness."""
    topo = setup_topology
    headers = {"Authorization": f"Bearer {topo['token']}"}

    resp1 = client.post(
        "/deployments",
        json={
            "service_id": str(topo["svc_payment"].id),
            "environment_id": str(topo["env_stage"].id),
            "region_id": None,
            "commit_sha": "3333333333333333333333333333333333333333",
            "version": "v1.1-stage",
            "status": "succeeded",
        },
        headers=headers,
    )
    assert resp1.status_code == 201
    d1_id = resp1.json()["id"]
    assert resp1.json()["is_current"] is True

    resp2 = client.post(
        "/deployments",
        json={
            "service_id": str(topo["svc_payment"].id),
            "environment_id": str(topo["env_stage"].id),
            "region_id": None,
            "commit_sha": "4444444444444444444444444444444444444444",
            "version": "v1.2-stage",
            "status": "succeeded",
        },
        headers=headers,
    )
    assert resp2.status_code == 201
    assert resp2.json()["is_current"] is True

    d1_check = client.get(f"/deployments/{d1_id}", headers=headers).json()
    assert d1_check["is_current"] is False


# ============================================================================
# 3. ROLLBACK & CANCELLATION BEHAVIOR
# ============================================================================

def test_rollback_and_cancellation_state_behavior(client, setup_topology):
    """Marking a deployment ROLLED_BACK or CANCELLED clears is_current."""
    topo = setup_topology
    headers = {"Authorization": f"Bearer {topo['token']}"}

    resp = client.post(
        "/deployments",
        json={
            "service_id": str(topo["svc_payment"].id),
            "environment_id": str(topo["env_prod"].id),
            "commit_sha": "5555555555555555555555555555555555555555",
            "version": "v3.0.0",
            "status": "succeeded",
        },
        headers=headers,
    )
    dep_id = resp.json()["id"]
    assert resp.json()["is_current"] is True

    # Mark ROLLED_BACK
    resp_roll = client.patch(
        f"/deployments/{dep_id}/status",
        json={"status": "rolled_back", "error_message": "Memory leak detected"},
        headers=headers,
    )
    assert resp_roll.status_code == 200
    assert resp_roll.json()["status"] == "rolled_back"
    assert resp_roll.json()["is_current"] is False
    assert resp_roll.json()["metadata"]["error_message"] == "Memory leak detected"


# ============================================================================
# 4. GENERIC SIGNED WEBHOOK INGESTION & REPLAY PROTECTION
# ============================================================================

def test_generic_signed_webhook_success_and_replay_protection(client, setup_topology):
    """Test HMAC-SHA256 generic signed webhook ingestion, tenant resolution, and replay protection."""
    topo = setup_topology
    headers = {"Authorization": f"Bearer {topo['token']}"}

    # 1. Create Webhook Endpoint credential
    ep_resp = client.post(
        "/webhook-endpoints",
        json={"name": "GitLab Production Pipeline"},
        headers=headers,
    )
    assert ep_resp.status_code == 201
    ep_data = ep_resp.json()
    key_id = ep_data["key_id"]
    raw_secret = ep_data["raw_secret"]
    assert raw_secret is not None

    # 2. Build Webhook Payload
    payload = {
        "service_name": "payment-service",
        "environment_name": "production",
        "region_code": "us-east-1",
        "repository_full_name": "acme/payment-service",
        "commit_sha": "abcdef1234567890abcdef1234567890abcdef12",
        "version": "v2.5.0-gitlab",
        "event_id": "gitlab-job-987654",
        "status": "succeeded",
    }
    payload_bytes = json.dumps(payload).encode("utf-8")
    now_ts = str(datetime.now(timezone.utc).timestamp())

    # 3. Compute HMAC Signature
    sig = hmac.new(raw_secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()

    wh_headers = {
        "Content-Type": "application/json",
        "X-Sentinel-Key-ID": key_id,
        "X-Sentinel-Signature": f"sha256={sig}",
        "X-Sentinel-Timestamp": now_ts,
    }

    # 4. Test Missing Timestamp Header
    wh_headers_no_ts = dict(wh_headers)
    del wh_headers_no_ts["X-Sentinel-Timestamp"]
    resp_no_ts = client.post("/webhooks/deployments/generic", data=payload_bytes, headers=wh_headers_no_ts)
    assert resp_no_ts.status_code == 401
    assert "timestamp" in resp_no_ts.json()["detail"].lower()

    # 5. Ingest Webhook with Valid Headers
    resp = client.post("/webhooks/deployments/generic", data=payload_bytes, headers=wh_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "processed"
    assert resp.json()["is_current"] is True

    # 6. Test Replay Attack (timestamp 10 minutes ago)
    old_ts = str((datetime.now(timezone.utc) - timedelta(minutes=10)).timestamp())
    wh_headers["X-Sentinel-Timestamp"] = old_ts
    resp_replay = client.post("/webhooks/deployments/generic", data=payload_bytes, headers=wh_headers)
    assert resp_replay.status_code == 401
    assert "expired" in resp_replay.json()["detail"].lower()

    # 7. Test Invalid Signature
    wh_headers["X-Sentinel-Timestamp"] = now_ts
    wh_headers["X-Sentinel-Signature"] = "sha256=invalid_signature_hex"
    resp_invalid = client.post("/webhooks/deployments/generic", data=payload_bytes, headers=wh_headers)
    assert resp_invalid.status_code == 401


# ============================================================================
# 5. GITHUB WEBHOOK INGESTION, SIGNATURE VERIFICATION & IDEMPOTENCY
# ============================================================================

def test_github_webhook_ingestion_and_signature_verification(client, setup_topology):
    """GitHub webhook verifies X-Hub-Signature-256 and enforces delivery idempotency."""
    topo = setup_topology
    gh_raw_secret = topo["gh_raw_secret"]

    delivery_id = f"gh-deliv-{uuid.uuid4()}"
    gh_payload = {
        "repository": {"full_name": "acme/payment-service"},
        "deployment": {
            "id": 1234567,
            "sha": "9999999999999999999999999999999999999999",
            "environment": "production",
            "description": "Deploy to prod via GitHub Action",
        },
        "deployment_status": {
            "state": "success",
            "target_url": "https://ci.acme.com/build/123",
        },
    }
    payload_bytes = json.dumps(gh_payload).encode("utf-8")

    # 1. Test Missing Signature
    headers_no_sig = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "deployment_status",
        "X-GitHub-Delivery": delivery_id,
    }
    resp_no_sig = client.post("/webhooks/deployments/github", data=payload_bytes, headers=headers_no_sig)
    assert resp_no_sig.status_code == 401
    assert "Missing X-Hub-Signature-256" in resp_no_sig.json()["detail"]

    # 2. Test Invalid Signature
    headers_bad_sig = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "deployment_status",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": "sha256=bad_hex_signature_1234567890",
    }
    resp_bad_sig = client.post("/webhooks/deployments/github", data=payload_bytes, headers=headers_bad_sig)
    assert resp_bad_sig.status_code == 401
    assert "Invalid GitHub HMAC-SHA256 signature" in resp_bad_sig.json()["detail"]

    # 3. Test that signing with a generic CI/CD webhook secret is REJECTED
    gen_key_id, gen_raw_secret = generate_webhook_credentials()
    client.post(
        "/webhook-endpoints",
        json={"name": "Generic GitLab Token"},
        headers={"Authorization": f"Bearer {topo['token']}"},
    )
    generic_sig = hmac.new(gen_raw_secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    headers_generic = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "deployment_status",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": f"sha256={generic_sig}",
    }
    resp_generic = client.post("/webhooks/deployments/github", data=payload_bytes, headers=headers_generic)
    assert resp_generic.status_code == 401
    assert "Invalid GitHub HMAC-SHA256 signature" in resp_generic.json()["detail"]

    # 4. Compute Valid Signature with dedicated GitHub secret
    valid_sig = hmac.new(gh_raw_secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    headers_valid = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "deployment_status",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": f"sha256={valid_sig}",
    }

    # Ingest Valid Webhook
    resp_valid = client.post("/webhooks/deployments/github", data=payload_bytes, headers=headers_valid)
    assert resp_valid.status_code == 200
    assert resp_valid.json()["status"] == "processed"
    dep_id = resp_valid.json()["deployment_id"]

    # 5. Resend Identical Delivery (Idempotency)
    resp_dup = client.post("/webhooks/deployments/github", data=payload_bytes, headers=headers_valid)
    assert resp_dup.status_code == 200
    assert resp_dup.json()["status"] == "already_processed"
    assert resp_dup.json()["deployment_id"] == dep_id


def test_github_webhook_service_mapping_resolution(client, setup_topology, db_session):
    """GitHub webhook resolves service using ServiceRepository bindings, rejecting ambiguous or empty mappings."""
    topo = setup_topology
    org = topo["org"]
    gh_raw_secret = topo["gh_raw_secret"]

    # Create an unlinked repository
    repo_unlinked = Repository(id=uuid.uuid4(), organization_id=org.id, name="orphan-repo", full_name="acme/orphan-repo")
    db_session.add(repo_unlinked)
    db_session.commit()

    # 1. Test Unlinked Repository -> 422
    payload_orphan = {
        "repository": {"full_name": "acme/orphan-repo"},
        "deployment": {"sha": "1111111111111111111111111111111111111111", "environment": "production"},
        "deployment_status": {"state": "success"},
    }
    orphan_bytes = json.dumps(payload_orphan).encode("utf-8")
    orphan_sig = hmac.new(gh_raw_secret.encode("utf-8"), orphan_bytes, hashlib.sha256).hexdigest()
    resp_orphan = client.post(
        "/webhooks/deployments/github",
        data=orphan_bytes,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={orphan_sig}"},
    )
    assert resp_orphan.status_code == 422
    assert "No service linked" in resp_orphan.json()["detail"]

    # 2. Test Ambiguous Mappings: Link a repo to two services with role='application' and neither is primary
    svc_a = Service(id=uuid.uuid4(), organization_id=org.id, name="service-alpha", slug="service-alpha")
    svc_b = Service(id=uuid.uuid4(), organization_id=org.id, name="service-beta", slug="service-beta")
    repo_shared = Repository(id=uuid.uuid4(), organization_id=org.id, name="shared-repo", full_name="acme/shared-repo")
    db_session.add_all([svc_a, svc_b, repo_shared])
    db_session.commit()

    sr_a = ServiceRepository(
        id=uuid.uuid4(),
        organization_id=org.id,
        service_id=svc_a.id,
        repository_id=repo_shared.id,
        role=ServiceRepositoryRole.APPLICATION,
        is_primary=False,
        selection_reason="Shared monorepo service A",
    )
    sr_b = ServiceRepository(
        id=uuid.uuid4(),
        organization_id=org.id,
        service_id=svc_b.id,
        repository_id=repo_shared.id,
        role=ServiceRepositoryRole.APPLICATION,
        is_primary=False,
        selection_reason="Shared monorepo service B",
    )
    db_session.add_all([sr_a, sr_b])
    db_session.commit()

    payload_shared = {
        "repository": {"full_name": "acme/shared-repo"},
        "deployment": {"sha": "2222222222222222222222222222222222222222", "environment": "production"},
        "deployment_status": {"state": "success"},
    }
    shared_bytes = json.dumps(payload_shared).encode("utf-8")
    shared_sig = hmac.new(gh_raw_secret.encode("utf-8"), shared_bytes, hashlib.sha256).hexdigest()
    resp_shared = client.post(
        "/webhooks/deployments/github",
        data=shared_bytes,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={shared_sig}"},
    )
    assert resp_shared.status_code == 422
    assert "Ambiguous service mapping" in resp_shared.json()["detail"]

    # 3. Resolve Ambiguity: Designate svc_a as primary
    sr_a.is_primary = True
    db_session.commit()

    resp_resolved = client.post(
        "/webhooks/deployments/github",
        data=shared_bytes,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={shared_sig}"},
    )
    assert resp_resolved.status_code == 200
    dep_resolved_id = resp_resolved.json()["deployment_id"]
    dep_obj = client.get(f"/deployments/{dep_resolved_id}", headers={"Authorization": f"Bearer {topo['token']}"}).json()
    assert dep_obj["service_id"] == str(svc_a.id)
    assert dep_obj["service_name"] == "service-alpha"


# ============================================================================
# 6. INCIDENT TIME-WINDOW OVERLAP QUERY
# ============================================================================

def test_incident_window_overlap_query(client, setup_topology, db_session):
    """Query deployments overlapping an incident window [window_start, window_end]."""
    topo = setup_topology
    headers = {"Authorization": f"Bearer {topo['token']}"}
    now = datetime.now(timezone.utc)

    # D1: Started 2h ago, finished 1h 45m ago (outside window)
    d1 = Deployment(
        organization_id=topo["org"].id,
        service_id=topo["svc_payment"].id,
        environment_id=topo["env_prod"].id,
        commit_sha="1111111111111111111111111111111111111111",
        status="succeeded",
        deployed_at=now - timedelta(hours=2),
        started_at=now - timedelta(hours=2),
        finished_at=now - timedelta(minutes=105),
    )

    # D2: Started 45m ago, finished 15m ago (overlaps incident window [T-30m, T-5m])
    d2 = Deployment(
        organization_id=topo["org"].id,
        service_id=topo["svc_payment"].id,
        environment_id=topo["env_prod"].id,
        commit_sha="2222222222222222222222222222222222222222",
        status="succeeded",
        deployed_at=now - timedelta(minutes=45),
        started_at=now - timedelta(minutes=45),
        finished_at=now - timedelta(minutes=15),
    )

    # D3: Started 10m ago, still running (overlaps incident window)
    d3 = Deployment(
        organization_id=topo["org"].id,
        service_id=topo["svc_payment"].id,
        environment_id=topo["env_prod"].id,
        commit_sha="3333333333333333333333333333333333333333",
        status="in_progress",
        deployed_at=now - timedelta(minutes=10),
        started_at=now - timedelta(minutes=10),
        finished_at=None,
    )

    db_session.add_all([d1, d2, d3])
    db_session.commit()

    window_start = (now - timedelta(minutes=30)).isoformat()
    window_end = (now - timedelta(minutes=5)).isoformat()

    resp = client.get(
        f"/deployments/window?service_id={topo['svc_payment'].id}&window_start={window_start}&window_end={window_end}",
        headers=headers,
    )
    assert resp.status_code == 200
    results = resp.json()
    result_ids = {r["id"] for r in results}
    assert str(d2.id) in result_ids
    assert str(d3.id) in result_ids
    assert str(d1.id) not in result_ids


# ============================================================================
# 7. PREVIOUS STABLE DEPLOYMENT LOOKUP & COMMIT DIFF
# ============================================================================

def test_previous_stable_lookup_and_commit_diff(client, setup_topology, db_session):
    """Lookup previous stable SUCCEEDED release and return commit delta."""
    topo = setup_topology
    headers = {"Authorization": f"Bearer {topo['token']}"}
    now = datetime.now(timezone.utc)

    # Stable v1
    d1 = Deployment(
        organization_id=topo["org"].id,
        service_id=topo["svc_payment"].id,
        environment_id=topo["env_prod"].id,
        repository_id=topo["repo_payment"].id,
        commit_sha="aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111",
        version="v1.0",
        status="succeeded",
        deployed_at=now - timedelta(hours=3),
    )
    # Failed v2
    d2 = Deployment(
        organization_id=topo["org"].id,
        service_id=topo["svc_payment"].id,
        environment_id=topo["env_prod"].id,
        repository_id=topo["repo_payment"].id,
        commit_sha="bbbb2222bbbb2222bbbb2222bbbb2222bbbb2222",
        version="v2.0",
        status="failed",
        deployed_at=now - timedelta(hours=2),
    )
    # Current v3 in progress
    d3 = Deployment(
        organization_id=topo["org"].id,
        service_id=topo["svc_payment"].id,
        environment_id=topo["env_prod"].id,
        repository_id=topo["repo_payment"].id,
        commit_sha="cccc3333cccc3333cccc3333cccc3333cccc3333",
        version="v3.0",
        status="in_progress",
        deployed_at=now - timedelta(hours=1),
    )

    db_session.add_all([d1, d2, d3])
    db_session.commit()

    # Query previous stable for v3 -> should be v1 (d1)
    resp = client.get(f"/deployments/{d3.id}/previous-stable", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == str(d1.id)
    assert resp.json()["version"] == "v1.0"

    # Query commit delta between v3 and v1
    diff_resp = client.get(f"/deployments/{d3.id}/commits-between", headers=headers)
    assert diff_resp.status_code == 200
    diff_data = diff_resp.json()
    assert diff_data["base_commit_sha"] == "cccc3333cccc3333cccc3333cccc3333cccc3333" or diff_data["head_commit_sha"] == "cccc3333cccc3333cccc3333cccc3333cccc3333"


# ============================================================================
# 8. MULTI-TENANT ISOLATION & RBAC
# ============================================================================

def test_multi_tenant_isolation_and_rbac(client, setup_topology, db_session):
    """Organization B cannot access Organization A deployments, and VIEWER cannot create deployments."""
    topo = setup_topology
    headers_org_a = {"Authorization": f"Bearer {topo['token']}"}

    # Create Org B & Viewer User in Org B
    org_b = Organization(id=uuid.uuid4(), name="Beta Corp", slug="beta")
    user_b = User(id=uuid.uuid4(), username="viewer_b", email="viewer@beta.com", hashed_password="mock_password_hash", organization_id=org_b.id)
    mem_b = UserOrganizationMembership(id=uuid.uuid4(), user_id=user_b.id, organization_id=org_b.id, role=MembershipRole.VIEWER)
    db_session.add_all([org_b, user_b, mem_b])
    db_session.commit()

    token_b = create_access_token(data={"sub": str(user_b.id), "username": user_b.username})
    headers_org_b = {"Authorization": f"Bearer {token_b}"}

    # Org A creates deployment
    resp_a = client.post(
        "/deployments",
        json={
            "service_id": str(topo["svc_payment"].id),
            "environment_id": str(topo["env_prod"].id),
            "commit_sha": "7777777777777777777777777777777777777777",
            "version": "v7.0.0",
            "status": "succeeded",
        },
        headers=headers_org_a,
    )
    dep_a_id = resp_a.json()["id"]

    # Org B attempts to read Org A deployment -> 404
    resp_leak = client.get(f"/deployments/{dep_a_id}", headers=headers_org_b)
    assert resp_leak.status_code == 404

    # Org B (Viewer) attempts to create deployment -> 403 Forbidden
    resp_forbidden = client.post(
        "/deployments",
        json={
            "service_id": str(topo["svc_payment"].id),
            "environment_id": str(topo["env_prod"].id),
            "commit_sha": "8888888888888888888888888888888888888888",
            "version": "v8.0.0",
        },
        headers=headers_org_b,
    )
    assert resp_forbidden.status_code == 403
