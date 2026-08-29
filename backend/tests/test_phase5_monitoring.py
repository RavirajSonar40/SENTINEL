"""Comprehensive test suite for Phase 5 Autonomous Monitoring & Production Detection."""

import json
import time
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.core.auth import create_access_token, hash_password
from app.core.crypto import encrypt_secret, generate_hmac_sha256
from app.core.ssrf_client import validate_target_ip, SSRFSecurityException
from app.models.incident import (
    User, Organization, Environment, Service, Region,
    UserOrganizationMembership, MembershipRole, ServiceDeploymentConfig,
    WebhookEndpoint, TelemetrySignal, AlertRuleConfig, ActiveIncidentCorrelationClaim,
    HealthCheckLog, Incident, IncidentStatus, IncidentSeverity, IncidentSource,
    SignalProvider, SignalType, SignalStatus, Deployment, DeploymentStatus
)
from app.services.detection_rules import evaluate_all_rules, ALL_RULES, RULE_REGISTRY
from app.services.health_check_poller import acquire_poller_batch, probe_single_config

# In-memory SQLite with StaticPool for deterministic test isolation
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
def org_and_user(db_session: Session):
    org = Organization(name="Monitoring Org", slug=f"mon-org-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    db_session.flush()

    user = User(
        username=f"mon_admin_{uuid.uuid4().hex[:6]}",
        email=f"mon_admin_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("adminpass123"),
        organization_id=org.id,
    )
    db_session.add(user)
    db_session.flush()

    membership = UserOrganizationMembership(
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.ADMIN,
    )
    db_session.add(membership)

    prod_env = Environment(
        name="production",
        env_type="production",
        organization_id=org.id,
    )
    staging_env = Environment(
        name="staging",
        env_type="staging",
        organization_id=org.id,
    )
    db_session.add_all([prod_env, staging_env])

    region = Region(
        name="US East",
        code="us-east-1",
        organization_id=org.id,
    )
    db_session.add(region)

    svc = Service(
        name="checkout-service",
        slug="checkout-service",
        tier="critical",
        organization_id=org.id,
    )
    db_session.add(svc)
    db_session.flush()

    # Create Deployment Config
    dep_cfg = ServiceDeploymentConfig(
        organization_id=org.id,
        service_id=svc.id,
        environment_id=prod_env.id,
        region_id=region.id,
        health_check_url="https://example.com/healthz",
        is_active=True,
    )
    db_session.add(dep_cfg)
    db_session.commit()

    token = create_access_token({"sub": str(user.id), "org_id": str(org.id)})

    return {
        "org": org,
        "user": user,
        "token": token,
        "prod_env": prod_env,
        "staging_env": staging_env,
        "region": region,
        "service": svc,
        "dep_cfg": dep_cfg,
    }


# ============================================================================
# 1. SSRF PROTECTION UNIT TESTS
# ============================================================================

def test_ssrf_ip_validation():
    """Verify SSRF protection strictly blocks private, loopback, and metadata ranges."""
    # Loopback
    with pytest.raises(SSRFSecurityException):
        validate_target_ip("127.0.0.1")
    with pytest.raises(SSRFSecurityException):
        validate_target_ip("127.0.1.5")
    with pytest.raises(SSRFSecurityException):
        validate_target_ip("::1")

    # RFC1918 Private
    with pytest.raises(SSRFSecurityException):
        validate_target_ip("10.0.0.1")
    with pytest.raises(SSRFSecurityException):
        validate_target_ip("172.16.5.10")
    with pytest.raises(SSRFSecurityException):
        validate_target_ip("192.168.1.1")

    # Cloud Metadata / Link-Local
    with pytest.raises(SSRFSecurityException):
        validate_target_ip("169.254.169.254")
    with pytest.raises(SSRFSecurityException):
        validate_target_ip("169.254.1.1")

    # Valid Public IP should not raise
    validate_target_ip("93.184.216.34")  # example.com
    validate_target_ip("8.8.8.8")         # Google DNS


# ============================================================================
# 2. ALL 12 DETECTION RULES UNIT TESTS
# ============================================================================

def test_all_12_detection_rules():
    """Verify all 12 explicit detection rules evaluate properly against thresholds."""
    assert len(ALL_RULES) == 12

    # 1. CPU Threshold
    res = evaluate_all_rules({"cpu_usage_pct": 95.0, "service_name": "api"})
    assert any(r.rule_name == "cpu_threshold" and r.signal_type == SignalType.CPU_THRESHOLD for r in res)

    # 2. Memory Threshold
    res = evaluate_all_rules({"memory_usage_pct": 92.0, "service_name": "api"})
    assert any(r.rule_name == "memory_threshold" and r.signal_type == SignalType.MEMORY_THRESHOLD for r in res)

    # 3. Error Rate
    res = evaluate_all_rules({"error_rate": 0.08, "service_name": "api"})
    assert any(r.rule_name == "error_rate" and r.signal_type == SignalType.ERROR_RATE for r in res)

    # 4. Latency Spike
    res = evaluate_all_rules({"p99_latency_ms": 1500.0, "service_name": "api"})
    assert any(r.rule_name == "latency_spike" and r.signal_type == SignalType.LATENCY_SPIKE for r in res)

    # 5. Health Check Failure
    res = evaluate_all_rules({"consecutive_failures": 4, "service_name": "api"})
    assert any(r.rule_name == "health_check_failure" and r.signal_type == SignalType.HEALTH_CHECK_FAILURE for r in res)

    # 6. Crash Loop
    res = evaluate_all_rules({"restart_count": 4, "service_name": "api"})
    assert any(r.rule_name == "crash_loop" and r.signal_type == SignalType.CRASH_LOOP for r in res)

    # 7. Restart Spike
    res = evaluate_all_rules({"restart_spike_count": 6, "service_name": "api"})
    assert any(r.rule_name == "restart_spike" and r.signal_type == SignalType.RESTART_SPIKE for r in res)

    # 8. Disk Threshold
    res = evaluate_all_rules({"disk_usage_pct": 94.0, "service_name": "api"})
    assert any(r.rule_name == "disk_threshold" and r.signal_type == SignalType.DISK_THRESHOLD for r in res)

    # 9. Queue Backlog
    res = evaluate_all_rules({"queue_lag": 15000, "service_name": "api"})
    assert any(r.rule_name == "queue_backlog" and r.signal_type == SignalType.QUEUE_BACKLOG for r in res)

    # 10. Database Saturation
    res = evaluate_all_rules({"db_connection_pool_pct": 88.0, "service_name": "api"})
    assert any(r.rule_name == "database_saturation" and r.signal_type == SignalType.DATABASE_SATURATION for r in res)

    # 11. Deployment Regression
    res = evaluate_all_rules({
        "is_deployment_regression": True,
        "recent_deployment_commit": "abcdef123",
        "service_name": "api"
    })
    assert any(r.rule_name == "deployment_regression" and r.signal_type == SignalType.DEPLOYMENT_REGRESSION for r in res)

    # 12. Repeated Exception
    res = evaluate_all_rules({
        "exception_count": 15,
        "exception_type": "DatabaseConnectionError",
        "service_name": "api"
    })
    assert any(r.rule_name == "repeated_exception" and r.signal_type == SignalType.REPEATED_EXCEPTION for r in res)


# ============================================================================
# 3. PROMETHEUS / ALERTMANAGER INGESTION TESTS
# ============================================================================

def test_prometheus_alert_ingestion_and_incident_creation(client, org_and_user, db_session: Session):
    """Test Prometheus Bearer token auth, firing alert ingestion, and autonomous incident creation."""
    org = org_and_user["org"]
    svc = org_and_user["service"]
    raw_secret = "prom-secret-test-token"
    key_id = f"prom_{uuid.uuid4().hex[:8]}"

    ep = WebhookEndpoint(
        organization_id=org.id,
        name="Prometheus Alertmanager",
        provider="prometheus",
        auth_method="bearer",
        key_id=key_id,
        encrypted_secret=encrypt_secret(raw_secret),
        is_active=True,
    )
    db_session.add(ep)
    db_session.commit()

    # 1. Invalid Bearer Token Fails (401)
    bad_resp = client.post(
        f"/webhooks/alerts/prometheus?key_id={key_id}",
        json={"alerts": []},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert bad_resp.status_code == 401

    # 2. Missing Environment Rejects with 422
    unenv_payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "HighCPUUsage", "service": "non-existent-svc"},
                "annotations": {"description": "CPU > 90%", "value": "95.5"},
            }
        ]
    }
    unenv_resp = client.post(
        f"/webhooks/alerts/prometheus?key_id={key_id}",
        json=unenv_payload,
        headers={"Authorization": f"Bearer {raw_secret}"},
    )
    assert unenv_resp.status_code == 422

    # 3. Valid Firing Alert in Production Auto-Creates Incident
    firing_payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "HighErrorRate",
                    "service": svc.name,
                    "environment": "production",
                    "region": "us-east-1",
                },
                "annotations": {
                    "summary": "High 5xx error rate on checkout",
                    "description": "5xx rate reached 8.5%",
                    "value": "0.085",
                },
                "startsAt": datetime.now(timezone.utc).isoformat(),
                "fingerprint": "prom-fp-101",
            }
        ]
    }

    resp = client.post(
        f"/webhooks/alerts/prometheus?key_id={key_id}",
        json=firing_payload,
        headers={"Authorization": f"Bearer {raw_secret}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processed"
    assert len(data["signals"]) == 1
    assert data["signals"][0]["incident_created"] is True
    inc_id = data["signals"][0]["incident_id"]
    assert inc_id is not None

    # Verify Incident in Database
    inc = db_session.query(Incident).filter(Incident.id == uuid.UUID(inc_id)).first()
    assert inc is not None
    assert inc.source == IncidentSource.AUTO_DETECTION
    assert inc.status == IncidentStatus.DETECTED
    assert inc.service_name == svc.name
    assert inc.signal_count == 1

    # Verify Active Correlation Claim
    claim = db_session.query(ActiveIncidentCorrelationClaim).filter(
        ActiveIncidentCorrelationClaim.incident_id == inc.id
    ).first()
    assert claim is not None

    # 4. Merging Duplicate/Subsequent Signal in Same Window
    second_alert = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "HighLatencySpike",
                    "service": svc.name,
                    "environment": "production",
                },
                "annotations": {"value": "2500", "summary": "P99 latency spike"},
                "startsAt": datetime.now(timezone.utc).isoformat(),
                "fingerprint": "prom-fp-102",
            }
        ]
    }
    resp2 = client.post(
        f"/webhooks/alerts/prometheus?key_id={key_id}",
        json=second_alert,
        headers={"Authorization": f"Bearer {raw_secret}"},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["signals"][0]["incident_created"] is False
    assert data2["signals"][0]["incident_id"] == str(inc.id)

    db_session.refresh(inc)
    assert inc.signal_count == 2

    # 5. Alertmanager Resolution Event Auto-Resolves Incident
    res_payload = {
        "status": "resolved",
        "alerts": [
            {
                "status": "resolved",
                "labels": {
                    "alertname": "HighErrorRate",
                    "service": svc.name,
                    "environment": "production",
                },
                "fingerprint": "prom-fp-101",
            }
        ]
    }
    res_resp = client.post(
        f"/webhooks/alerts/prometheus?key_id={key_id}",
        json=res_payload,
        headers={"Authorization": f"Bearer {raw_secret}"},
    )
    assert res_resp.status_code == 200
    res_data = res_resp.json()
    assert str(inc.id) in res_data["resolved_incidents"]

    db_session.refresh(inc)
    assert inc.status == IncidentStatus.RESOLVED


def test_non_prod_signals_suppressed(client, org_and_user, db_session: Session):
    """Verify non-production signals are persisted but suppressed from triggering incidents."""
    org = org_and_user["org"]
    svc = org_and_user["service"]
    raw_secret = "prom-secret-staging"
    key_id = f"prom_{uuid.uuid4().hex[:8]}"

    ep = WebhookEndpoint(
        organization_id=org.id,
        name="Prometheus Staging",
        provider="prometheus",
        key_id=key_id,
        encrypted_secret=encrypt_secret(raw_secret),
        is_active=True,
    )
    db_session.add(ep)
    db_session.commit()

    staging_payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "HighErrorRate",
                    "service": svc.name,
                    "environment": "staging",
                },
                "annotations": {"value": "0.15", "summary": "Staging error rate"},
                "fingerprint": "staging-fp-1",
            }
        ]
    }
    resp = client.post(
        f"/webhooks/alerts/prometheus?key_id={key_id}",
        json=staging_payload,
        headers={"Authorization": f"Bearer {raw_secret}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["signals"][0]["status"] == "suppressed_non_prod"
    assert data["signals"][0]["incident_id"] is None


# ============================================================================
# 4. SENTRY WEBHOOK INGESTION TESTS
# ============================================================================

def test_sentry_webhook_ingestion(client, org_and_user, db_session: Session):
    """Test Sentry HMAC signature verification and exception signal ingestion."""
    org = org_and_user["org"]
    svc = org_and_user["service"]
    raw_secret = "sentry-secret-key-12345"
    key_id = f"sentry_{uuid.uuid4().hex[:8]}"

    ep = WebhookEndpoint(
        organization_id=org.id,
        name="Sentry Webhook",
        provider="sentry",
        key_id=key_id,
        encrypted_secret=encrypt_secret(raw_secret),
        is_active=True,
    )
    db_session.add(ep)
    db_session.commit()

    sentry_body = {
        "event_id": f"sentry-{uuid.uuid4().hex}",
        "project_slug": svc.name,
        "message": "NullPointerException in payment gateway",
        "environment": "production",
        "exception": {
            "values": [{"type": "NullPointerException", "value": "Payment failed"}]
        }
    }
    body_raw = json.dumps(sentry_body).encode("utf-8")
    sig = generate_hmac_sha256(body_raw, raw_secret)

    # 1. Invalid Signature Fails (401)
    bad_resp = client.post(
        f"/webhooks/alerts/sentry?key_id={key_id}",
        content=body_raw,
        headers={
            "Content-Type": "application/json",
            "Sentry-Hook-Signature": "invalidsignature123",
        },
    )
    assert bad_resp.status_code == 401

    # 2. Valid Signature Succeeds
    ok_resp = client.post(
        f"/webhooks/alerts/sentry?key_id={key_id}",
        content=body_raw,
        headers={
            "Content-Type": "application/json",
            "Sentry-Hook-Signature": sig,
        },
    )
    assert ok_resp.status_code == 200
    data = ok_resp.json()
    assert data["status"] == "processed"
    assert data["signal_id"] is not None


# ============================================================================
# 5. GENERIC APM WEBHOOK INGESTION TESTS
# ============================================================================

def test_generic_signal_ingestion(client, org_and_user, db_session: Session):
    """Test generic webhook with HMAC-SHA256 and replay timestamp protection."""
    org = org_and_user["org"]
    svc = org_and_user["service"]
    raw_secret = "generic-apm-secret"
    key_id = f"gen_{uuid.uuid4().hex[:8]}"

    ep = WebhookEndpoint(
        organization_id=org.id,
        name="Custom APM",
        provider="generic",
        key_id=key_id,
        encrypted_secret=encrypt_secret(raw_secret),
        is_active=True,
    )
    db_session.add(ep)
    db_session.commit()

    payload = {
        "service_name": svc.name,
        "environment_name": "production",
        "signal_type": "DATABASE_SATURATION",
        "metric_name": "db_connection_pool_pct",
        "metric_value": 92.5,
        "title": "PostgreSQL pool exhaustion",
    }
    body_raw = json.dumps(payload).encode("utf-8")
    sig = generate_hmac_sha256(body_raw, raw_secret)
    now_ts = str(datetime.now(timezone.utc).timestamp())

    # 1. Expired Timestamp Fails (401)
    old_ts = str((datetime.now(timezone.utc) - timedelta(minutes=10)).timestamp())
    expired_resp = client.post(
        "/webhooks/signals/generic",
        content=body_raw,
        headers={
            "Content-Type": "application/json",
            "X-Sentinel-Key-ID": key_id,
            "X-Sentinel-Signature": sig,
            "X-Sentinel-Timestamp": old_ts,
        },
    )
    assert expired_resp.status_code == 401

    # 2. Valid Request Succeeds
    ok_resp = client.post(
        "/webhooks/signals/generic",
        content=body_raw,
        headers={
            "Content-Type": "application/json",
            "X-Sentinel-Key-ID": key_id,
            "X-Sentinel-Signature": sig,
            "X-Sentinel-Timestamp": now_ts,
        },
    )
    assert ok_resp.status_code == 200
    data = ok_resp.json()
    assert data["status"] == "processed"
    assert data["incident_created"] is True


# ============================================================================
# 6. HEALTH CHECK POLLER & LEASE LOCKING TESTS
# ============================================================================

def test_health_check_poller_leases(org_and_user, db_session: Session):
    """Test distributed lease acquisition and consecutive failure state tracking."""
    dep_cfg = org_and_user["dep_cfg"]

    # 1. Acquire Poller Batch
    batch_ids = acquire_poller_batch(db_session, batch_size=10)
    assert dep_cfg.id in batch_ids

    db_session.refresh(dep_cfg)
    assert dep_cfg.poller_lease_until is not None

    # Immediate second acquisition returns empty because lease is active
    second_batch = acquire_poller_batch(db_session, batch_size=10)
    assert dep_cfg.id not in second_batch


# ============================================================================
# 7. ALERT RULES CONFIG CRUD TESTS
# ============================================================================

def test_alert_rules_crud(client, org_and_user):
    """Test querying and updating organization detection rules."""
    token = org_and_user["token"]

    # 1. List Rules (All 12 Returned)
    resp = client.get(
        "/monitoring/rules",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    rules = resp.json()
    assert len(rules) == 12

    # 2. Update Rule Threshold
    update_resp = client.put(
        "/monitoring/rules/cpu_threshold",
        json={"threshold_value": 85.0, "is_enabled": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["threshold_value"] == 85.0
    assert updated["is_enabled"] is True


def test_monitoring_dashboard_endpoints(client, org_and_user):
    """Test signals list and correlation summary endpoints."""
    token = org_and_user["token"]

    # 1. Signals Feed
    sig_resp = client.get(
        "/monitoring/signals?limit=20",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert sig_resp.status_code == 200
    assert isinstance(sig_resp.json(), list)

    # 2. Health Checks Status
    hc_resp = client.get(
        "/monitoring/health-checks",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert hc_resp.status_code == 200
    assert len(hc_resp.json()) >= 1

    # 3. Correlation Summary
    sum_resp = client.get(
        "/monitoring/correlation-summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert sum_resp.status_code == 200
    data = sum_resp.json()
    assert "total_signals_24h" in data
    assert "auto_incidents_24h" in data


# ============================================================================
# 8. UNIFIED DETECTION ADAPTER & OPERATOR ROLE TESTS
# ============================================================================

def test_unified_auto_detect_adapter_and_deduplication(client, org_and_user, db_session: Session):
    """Verify legacy /detect router forwards seamlessly into Phase 5 unified engine and deduplicates."""
    token = org_and_user["token"]
    svc = org_and_user["service"]

    # 1. GET /detect/rules returns all 12 rules from Phase 5 engine
    rules_resp = client.get(
        "/detect/rules",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert rules_resp.status_code == 200
    rules_data = rules_resp.json()
    assert len(rules_data["rules"]) == 12

    # 2. POST /detect triggers error rate spike and creates incident via Signal Correlation
    detect_resp = client.post(
        f"/detect?service_name={svc.name}",
        json={"error_rate": 0.12, "service_name": svc.name},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detect_resp.status_code == 200
    detect_data = detect_resp.json()
    assert detect_data["rules_triggered"] >= 1
    inc_id = detect_data["incident_created"]
    assert inc_id is not None

    # Verify incident in DB
    inc = db_session.query(Incident).filter(Incident.id == uuid.UUID(inc_id)).first()
    assert inc is not None
    assert inc.source == IncidentSource.AUTO_DETECTION
    assert inc.signal_count == 1

    # 3. Duplicate event within same window dedupes without creating second incident
    detect_resp2 = client.post(
        f"/detect?service_name={svc.name}",
        json={"error_rate": 0.15, "service_name": svc.name},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detect_resp2.status_code == 200
    detect_data2 = detect_resp2.json()
    # Merges into the existing incident ID
    assert detect_data2["incident_created"] == str(inc.id)

    db_session.refresh(inc)
    assert inc.signal_count == 2

    # 4. GET /detect/status reflects unified metrics
    status_resp = client.get(
        "/detect/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["rules_count"] == 12
    assert status_data["auto_incidents_24h"] >= 1


def test_operator_role_authentication_and_permissions(client, org_and_user, db_session: Session):
    """Verify OPERATOR role is recognized in hierarchy, allows operational actions, and restricts admin mutations."""
    org = org_and_user["org"]

    operator_user = User(
        username=f"operator_{uuid.uuid4().hex[:6]}",
        email=f"operator_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("operator123"),
        organization_id=org.id,
    )
    db_session.add(operator_user)
    db_session.flush()

    operator_mem = UserOrganizationMembership(
        user_id=operator_user.id,
        organization_id=org.id,
        role=MembershipRole.OPERATOR,
    )
    db_session.add(operator_mem)
    db_session.commit()

    operator_token = create_access_token(data={"sub": str(operator_user.id), "username": operator_user.username})

    # 1. OPERATOR can query signals (requires VIEWER)
    sig_resp = client.get(
        "/monitoring/signals",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert sig_resp.status_code == 200

    # 2. OPERATOR can access health checks (requires VIEWER)
    hc_resp = client.get(
        "/monitoring/health-checks",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert hc_resp.status_code == 200

    # 3. OPERATOR can trigger probe-now (requires MEMBER)
    dep_cfg = org_and_user["dep_cfg"]
    probe_resp = client.post(
        "/monitoring/health-checks/probe-now",
        json={"config_id": str(dep_cfg.id)},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    # Probe runs (or returns result) - 200 OK or 400 for mock host, but NOT 403 Forbidden
    assert probe_resp.status_code != 403

    # 4. OPERATOR is rejected from mutating alert rules (requires ADMIN -> 403 Forbidden)
    admin_resp = client.put(
        "/monitoring/rules/cpu_threshold",
        json={"threshold_value": 80.0, "is_enabled": True},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert admin_resp.status_code == 403
    assert "Operation requires 'admin' role or higher" in admin_resp.json()["detail"]


def test_operator_role_database_persistence(org_and_user, db_session: Session):
    """Verify that MembershipRole.OPERATOR persists and round-trips correctly through database queries."""
    org = org_and_user["org"]

    op_user = User(
        username=f"db_operator_{uuid.uuid4().hex[:6]}",
        email=f"db_operator_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("db_op_pass"),
        organization_id=org.id,
    )
    db_session.add(op_user)
    db_session.flush()

    op_membership = UserOrganizationMembership(
        user_id=op_user.id,
        organization_id=org.id,
        role=MembershipRole.OPERATOR,
    )
    db_session.add(op_membership)
    db_session.commit()

    # Query back from DB
    loaded_mem = db_session.query(UserOrganizationMembership).filter(
        UserOrganizationMembership.user_id == op_user.id,
        UserOrganizationMembership.organization_id == org.id,
    ).first()

    assert loaded_mem is not None
    assert loaded_mem.role == MembershipRole.OPERATOR
    assert loaded_mem.role.value == "operator"


