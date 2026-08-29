import hmac
import hashlib
import json
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.auth import create_access_token
from app.core.crypto import encrypt_secret
from app.main import app
from app.models.incident import (
    User,
    Organization,
    Environment,
    Service,
    Repository,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    MembershipRole,
    UserOrganizationMembership,
    ChangeEvent,
    ChangeType,
    ChangeRiskLevel,
    IncidentChangeCorrelation,
    IncidentChangeCorrelationReport,
    CorrelationStatus,
    WebhookEndpoint,
    GraphNode,
    GraphEdge,
    GraphNodeType,
    GraphEdgeType,
    GraphEdgeSource,
    ServiceCriticality,
)
from app.services.change_service import (
    ingest_change_event,
    batch_ingest_changes,
    redact_sensitive_data,
    generate_change_fingerprint,
)
from app.services.change_correlation_service import (
    calculate_correlation_score,
    correlate_incident_changes,
    triage_change_correlation,
)
from app.schemas.changes import ChangeEventCreate, CorrelationTriageRequest


# In-memory SQLite with StaticPool for deterministic test isolation
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
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


@pytest.fixture(scope="function")
def auth_context(db_session: Session):
    uid = uuid.uuid4().hex[:6]
    org = Organization(name=f"Org-Phase7-{uid}", slug=f"org-phase7-{uid}")
    db_session.add(org)
    db_session.flush()

    user_admin = User(
        username=f"admin_{uid}",
        email=f"admin_{uid}@example.com",
        hashed_password="hash",
        organization_id=org.id,
        is_active=True,
    )
    user_viewer = User(
        username=f"viewer_{uid}",
        email=f"viewer_{uid}@example.com",
        hashed_password="hash",
        organization_id=org.id,
        is_active=True,
    )
    db_session.add_all([user_admin, user_viewer])
    db_session.flush()

    m_admin = UserOrganizationMembership(user_id=user_admin.id, organization_id=org.id, role=MembershipRole.ADMIN)
    m_viewer = UserOrganizationMembership(user_id=user_viewer.id, organization_id=org.id, role=MembershipRole.VIEWER)
    db_session.add_all([m_admin, m_viewer])

    env = Environment(organization_id=org.id, name="production", env_type="production")
    svc_payment = Service(organization_id=org.id, name="Payment Service", slug="payment-service", tier="critical")
    svc_auth = Service(organization_id=org.id, name="Auth Service", slug="auth-service", tier="critical")
    repo = Repository(organization_id=org.id, name="payment-repo", full_name="org/payment-repo")
    db_session.add_all([env, svc_payment, svc_auth, repo])
    db_session.flush()

    # Create Graph Nodes & Edges (Payment Service -> Auth Service)
    node_payment = GraphNode(
        organization_id=org.id,
        node_type=GraphNodeType.SERVICE,
        name="Payment Service",
        identifier="service:payment-service",
        entity_id=svc_payment.id,
    )
    node_auth = GraphNode(
        organization_id=org.id,
        node_type=GraphNodeType.SERVICE,
        name="Auth Service",
        identifier="service:auth-service",
        entity_id=svc_auth.id,
    )
    db_session.add_all([node_payment, node_auth])
    db_session.flush()

    edge = GraphEdge(
        organization_id=org.id,
        source_node_id=node_payment.id,
        target_node_id=node_auth.id,
        edge_type=GraphEdgeType.CALLS,
        source=GraphEdgeSource.SERVICE_REGISTRATION,
        confidence=1.0,
        criticality=ServiceCriticality.HARD,
    )
    db_session.add(edge)
    db_session.commit()

    token_admin = create_access_token(data={"sub": str(user_admin.id), "username": user_admin.username})
    token_viewer = create_access_token(data={"sub": str(user_viewer.id), "username": user_viewer.username})

    return {
        "org": org,
        "admin": user_admin,
        "viewer": user_viewer,
        "token_admin": token_admin,
        "token_viewer": token_viewer,
        "env": env,
        "svc_payment": svc_payment,
        "svc_auth": svc_auth,
        "repo": repo,
    }


# ============================================================================
# 1. Multi-source change ingestion across types
# ============================================================================

def test_multi_source_change_ingestion(db_session, auth_context):
    org = auth_context["org"]
    svc = auth_context["svc_payment"]
    repo = auth_context["repo"]
    now = datetime.now(timezone.utc)

    types_to_test = [
        (ChangeType.FEATURE_FLAG, "launchdarkly", "flag_killswitch_v2"),
        (ChangeType.DATABASE_MIGRATION, "alembic", "027_add_phase7_changes"),
        (ChangeType.CODE_COMMIT, "github", "commit_abc123"),
        (ChangeType.INFRASTRUCTURE, "terraform", "run_tf_456"),
        (ChangeType.DEPLOYMENT, "kubernetes", "deploy_pod_789"),
    ]

    for c_type, prov, ext_id in types_to_test:
        dto = ChangeEventCreate(
            title=f"Test change for {c_type.value}",
            change_type=c_type,
            provider=prov,
            service_id=svc.id,
            repository_id=repo.id,
            external_id=ext_id,
            effective_at=now,
        )
        event, is_created = ingest_change_event(db_session, org.id, dto)
        assert is_created is True
        assert event.change_type == c_type
        assert event.provider == prov
        assert event.external_id == ext_id


# ============================================================================
# 2. Deterministic fingerprinting & deduplication / idempotency
# ============================================================================

def test_change_event_idempotency_and_fingerprinting(db_session, auth_context):
    org = auth_context["org"]
    svc = auth_context["svc_payment"]
    now = datetime.now(timezone.utc)

    # Event without external_id - should generate deterministic fingerprint
    dto1 = ChangeEventCreate(
        title="Env variable updated",
        change_type=ChangeType.ENVIRONMENT_VARIABLE,
        provider="manual",
        service_id=svc.id,
        effective_at=now,
    )
    event1, created1 = ingest_change_event(db_session, org.id, dto1)
    assert created1 is True
    assert event1.external_id is not None
    assert len(event1.external_id) > 10

    # Ingest same payload again - should update rather than duplicate
    dto2 = ChangeEventCreate(
        title="Env variable updated",
        change_type=ChangeType.ENVIRONMENT_VARIABLE,
        provider="manual",
        service_id=svc.id,
        description="Updated description",
        effective_at=now,
    )
    event2, created2 = ingest_change_event(db_session, org.id, dto2)
    assert created2 is False
    assert event1.id == event2.id
    assert event2.description == "Updated description"


# ============================================================================
# 3. Sensitive data redaction in diff summaries and metadata
# ============================================================================

def test_sensitive_data_redaction():
    raw_diff = {
        "DB_PASSWORD": "supersecretpassword",
        "API_TOKEN": "Bearer eyJhbGciOi...",
        "auth_secret": "my-key-123",
        "safe_config": {"retries": 3, "timeout": 30, "DATABASE_URL": "postgres://user:pass@host/db"},
        "items": ["safe_string", {"nested_token": "secret_xyz"}],
    }

    redacted = redact_sensitive_data(raw_diff)
    assert redacted["DB_PASSWORD"] == "[REDACTED]"
    assert redacted["API_TOKEN"] == "[REDACTED]"
    assert redacted["auth_secret"] == "[REDACTED]"
    assert redacted["safe_config"]["DATABASE_URL"] == "[REDACTED]"
    assert redacted["safe_config"]["retries"] == 3
    assert redacted["items"][1]["nested_token"] == "[REDACTED]"


# ============================================================================
# 4. Webhook ingestion with HMAC verification, replay protection, allowlist
# ============================================================================

def test_webhook_ingestion_and_security(client, db_session, auth_context):
    org = auth_context["org"]

    webhook_secret = "test-webhook-secret-999"
    endpoint = WebhookEndpoint(
        organization_id=org.id,
        name="GitHub Webhook",
        provider="github",
        key_id=f"gh-key-{uuid.uuid4().hex[:6]}",
        encrypted_secret=encrypt_secret(webhook_secret),
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()

    # 4a. Valid GitHub Push Webhook with HMAC-SHA256
    payload_dict = {
        "repository": {"full_name": auth_context["repo"].full_name},
        "head_commit": {
            "id": "c0ffee1234567890abcdef",
            "message": "Fix payment retry loop",
            "author": {"name": "Alice"},
            "url": "https://github.com/org/payment-repo/commit/c0ffee123",
            "added": ["fix.py"],
            "removed": [],
            "modified": ["main.py"],
        },
        "ref": "refs/heads/main",
    }
    raw_body = json.dumps(payload_dict).encode("utf-8")
    sig = "sha256=" + hmac.new(webhook_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    resp = client.post(
        f"/changes/webhooks/github?key_id={endpoint.key_id}",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "delivery-uuid-111",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ingested"
    assert data["created"] is True
    assert data["change_type"] == "CODE_COMMIT"

    # 4b. Replay attack rejection (same delivery ID)
    resp_replay = client.post(
        f"/changes/webhooks/github?key_id={endpoint.key_id}",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "delivery-uuid-111",
        },
    )
    assert resp_replay.status_code == 200
    assert resp_replay.json()["status"] == "ignored"
    assert resp_replay.json()["reason"] == "duplicate_delivery"

    # 4c. Invalid Signature Rejection
    resp_bad_sig = client.post(
        f"/changes/webhooks/github?key_id={endpoint.key_id}",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=invalidsignature",
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "delivery-uuid-222",
        },
    )
    assert resp_bad_sig.status_code == 401

    # 4d. Unallowlisted Provider Rejection
    resp_bad_prov = client.post(
        "/changes/webhooks/untrusted_source",
        json={},
    )
    assert resp_bad_prov.status_code == 400


# ============================================================================
# 5. Temporal decay and topological scoring formula
# ============================================================================

def test_scoring_formula_and_decay():
    # Exactly at onset, 0 hops: Score = W(FEATURE_FLAG) * 1.0 * 1.0 = 0.95
    score_immediate = calculate_correlation_score(ChangeType.FEATURE_FLAG, time_delta_seconds=0, graph_distance=0.0)
    assert score_immediate == 0.95

    # 30 min (1800s) before onset, 0 hops: Score = 0.95 * exp(-1) = 0.95 * 0.367879 = 0.3495
    score_30m = calculate_correlation_score(ChangeType.FEATURE_FLAG, time_delta_seconds=-1800, graph_distance=0.0)
    assert 0.349 <= score_30m <= 0.350

    # 1 hop away penalty: 1 / (1 + 0.4*1) = 1/1.4 = 0.714
    score_1hop = calculate_correlation_score(ChangeType.FEATURE_FLAG, time_delta_seconds=0, graph_distance=1.0)
    assert round(0.95 * (1.0 / 1.4), 4) == score_1hop


# ============================================================================
# 6. Incident change correlation ranking & causal candidate tagging
# ============================================================================

def test_incident_change_correlation_and_causal_candidate(db_session, auth_context):
    org = auth_context["org"]
    svc_payment = auth_context["svc_payment"]
    svc_auth = auth_context["svc_auth"]
    now = datetime.now(timezone.utc)

    # Create Incident on Payment Service
    incident = Incident(
        number=7001,
        title="Payment Service Latency Spike",
        severity=IncidentSeverity.SEV2,
        status=IncidentStatus.DETECTED,
        organization_id=org.id,
        service_id=svc_payment.id,
        detected_at=now,
    )
    db_session.add(incident)
    db_session.flush()

    # Change 1: High risk feature flag enabled 5 min BEFORE onset on Payment Service (delta = -300s, dist = 0)
    # Score = 0.95 * exp(-300/1800) = 0.95 * 0.8465 = 0.8042 -> is_causal = True
    c1 = ChangeEvent(
        organization_id=org.id,
        service_id=svc_payment.id,
        change_type=ChangeType.FEATURE_FLAG,
        title="Enable new payment gateway v2",
        external_id="ff_gateway_v2",
        effective_at=now - timedelta(minutes=5),
    )

    # Change 2: Deployment on Auth Service (1 hop away) 10 min BEFORE onset (delta = -600s, dist = 1)
    # Score = 0.95 * exp(-600/1800) * (1/1.4) = 0.95 * 0.7165 * 0.7142 = 0.4862 -> is_causal = True
    c2 = ChangeEvent(
        organization_id=org.id,
        service_id=svc_auth.id,
        change_type=ChangeType.DEPLOYMENT,
        title="Deploy auth-service 1.4.0",
        external_id="deploy_auth_140",
        effective_at=now - timedelta(minutes=10),
    )

    # Change 3: Scaling change on Payment Service 5 min AFTER onset (delta = +300s, dist = 0)
    # Score = 0.80 * exp(-300/1800) = 0.6772 -> BUT delta > 0, so is_causal MUST BE False
    c3 = ChangeEvent(
        organization_id=org.id,
        service_id=svc_payment.id,
        change_type=ChangeType.SCALING_CHANGE,
        title="Scale up payment pods to 10",
        external_id="scale_payment_10",
        effective_at=now + timedelta(minutes=5),
    )

    db_session.add_all([c1, c2, c3])
    db_session.commit()

    report = correlate_incident_changes(db_session, org.id, incident.id, lookback_window_minutes=60, force=True)
    assert len(report.correlations) == 3

    # Check top suspect is Change 1
    top = report.correlations[0]
    assert top.change_event_id == c1.id
    assert top.rank == 1
    assert top.is_causal_candidate is True
    assert top.correlation_score > 0.75

    # Check Change 2 (1 hop away) is causal candidate
    corr_c2 = next(c for c in report.correlations if c.change_event_id == c2.id)
    assert corr_c2.topological_distance == 1
    assert corr_c2.is_causal_candidate is True

    # Check Change 3 (after onset) is NOT a causal candidate despite high score
    corr_c3 = next(c for c in report.correlations if c.change_event_id == c3.id)
    assert corr_c3.time_delta_seconds > 0
    assert corr_c3.is_causal_candidate is False


# ============================================================================
# 7. Non-destructive upserts preserving operator human triage
# ============================================================================

def test_non_destructive_human_triage_preservation(db_session, auth_context):
    org = auth_context["org"]
    svc = auth_context["svc_payment"]
    user = auth_context["admin"]
    now = datetime.now(timezone.utc)

    incident = Incident(
        number=7002,
        title="Checkout failure",
        severity=IncidentSeverity.SEV1,
        organization_id=org.id,
        service_id=svc.id,
        detected_at=now,
    )
    c1 = ChangeEvent(
        organization_id=org.id,
        service_id=svc.id,
        change_type=ChangeType.DATABASE_MIGRATION,
        title="Add foreign key index",
        external_id="mig_fk_index",
        effective_at=now - timedelta(minutes=15),
    )
    db_session.add_all([incident, c1])
    db_session.commit()

    # 1. Run initial correlation
    report1 = correlate_incident_changes(db_session, org.id, incident.id, force=True)
    corr1 = report1.correlations[0]
    assert corr1.triage_status == CorrelationStatus.COINCIDENTAL

    # 2. Human Operator marks correlation as SUSPECTED_ROOT_CAUSE
    triaged = triage_change_correlation(
        db=db_session,
        organization_id=org.id,
        incident_id=incident.id,
        correlation_id=corr1.id,
        user_id=user.id,
        triage_status=CorrelationStatus.SUSPECTED_ROOT_CAUSE,
        reason="Lock contention during migration blocked all write connections.",
    )
    assert triaged.triage_status == CorrelationStatus.SUSPECTED_ROOT_CAUSE
    assert triaged.triaged_by_user_id == user.id
    assert len(triaged.metadata_json["triage_history"]) == 1

    # 3. Recalculate correlations - MUST NOT overwrite human triage
    report2 = correlate_incident_changes(db_session, org.id, incident.id, force=True)
    corr_recalculated = report2.correlations[0]
    assert corr_recalculated.triage_status == CorrelationStatus.SUSPECTED_ROOT_CAUSE
    assert corr_recalculated.triage_reason == "Lock contention during migration blocked all write connections."


# ============================================================================
# 8. REST API Endpoints & Role-Based Access Control
# ============================================================================

def test_change_api_rbac_and_triage_endpoints(client, db_session, auth_context):
    admin_token = auth_context["token_admin"]
    viewer_token = auth_context["token_viewer"]
    svc = auth_context["svc_payment"]

    # 8a. Operator/Admin can create change event
    resp_create = client.post(
        "/changes",
        json={
            "title": "Config map update",
            "change_type": "CONFIGURATION",
            "service_id": str(svc.id),
            "external_id": "cfg_map_001",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_create.status_code == 201
    change_id = resp_create.json()["id"]

    # 8b. Viewer cannot create change event (403)
    resp_viewer_create = client.post(
        "/changes",
        json={"title": "Unauthorized change", "change_type": "CONFIGURATION"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp_viewer_create.status_code == 403

    # 8c. Viewer can list changes
    resp_list = client.get("/changes", headers={"Authorization": f"Bearer {viewer_token}"})
    assert resp_list.status_code == 200
    assert len(resp_list.json()) >= 1

    # 8d. Batch Ingestion
    resp_batch = client.post(
        "/changes/batch",
        json={
            "changes": [
                {"title": "Batch Commit 1", "change_type": "CODE_COMMIT", "external_id": "b_1"},
                {"title": "Batch Commit 2", "change_type": "CODE_COMMIT", "external_id": "b_2"},
            ]
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_batch.status_code == 200
    assert resp_batch.json()["total"] == 2


# ============================================================================
# 9. Correlation report version incrementing and snapshot hashes
# ============================================================================

def test_correlation_report_versioning_and_snapshot_hash(db_session, auth_context):
    org = auth_context["org"]
    svc = auth_context["svc_payment"]
    now = datetime.now(timezone.utc)

    incident = Incident(
        number=7003,
        title="Payment timeouts",
        severity=IncidentSeverity.SEV1,
        organization_id=org.id,
        service_id=svc.id,
        detected_at=now,
    )
    c1 = ChangeEvent(
        organization_id=org.id,
        service_id=svc.id,
        change_type=ChangeType.FEATURE_FLAG,
        title="Toggle dark mode",
        external_id="ff_toggle_dark",
        effective_at=now - timedelta(minutes=5),
    )
    db_session.add_all([incident, c1])
    db_session.commit()

    # 1. Initial calculation: version 1, is_current=True, snapshot_hash non-null
    rep1 = correlate_incident_changes(db_session, org.id, incident.id, force=True)
    assert rep1.version == 1
    assert rep1.is_current is True
    assert rep1.snapshot_hash is not None

    db_rep1 = db_session.query(IncidentChangeCorrelationReport).filter(
        IncidentChangeCorrelationReport.id == rep1.id
    ).first()
    assert db_rep1.version == 1
    assert db_rep1.is_current is True
    assert db_rep1.snapshot_hash == rep1.snapshot_hash

    # 2. Second calculation (force=True): version 2, rep1 becomes is_current=False
    c2 = ChangeEvent(
        organization_id=org.id,
        service_id=svc.id,
        change_type=ChangeType.DEPLOYMENT,
        title="Deploy payment v2",
        external_id="deploy_payment_v2",
        effective_at=now - timedelta(minutes=10),
    )
    db_session.add(c2)
    db_session.commit()

    rep2 = correlate_incident_changes(db_session, org.id, incident.id, force=True)
    assert rep2.version == 2
    assert rep2.is_current is True
    assert rep2.snapshot_hash is not None
    assert rep2.snapshot_hash != rep1.snapshot_hash

    db_session.refresh(db_rep1)
    assert db_rep1.is_current is False

    # 3. Third calculation (force=True): version 3
    rep3 = correlate_incident_changes(db_session, org.id, incident.id, force=True)
    assert rep3.version == 3
    assert rep3.is_current is True

    # Total reports in DB for this incident: 3
    all_reports = db_session.query(IncidentChangeCorrelationReport).filter(
        IncidentChangeCorrelationReport.organization_id == org.id,
        IncidentChangeCorrelationReport.incident_id == incident.id,
    ).order_by(IncidentChangeCorrelationReport.version.asc()).all()
    assert len(all_reports) == 3
    assert [r.version for r in all_reports] == [1, 2, 3]
    assert [r.is_current for r in all_reports] == [False, False, True]
