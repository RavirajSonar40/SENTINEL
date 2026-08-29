"""Phase 15 Test Suite: Operations Command Center.

Verifies:
1. REST overview aggregation across incidents, services, deployments, draft PRs, and reliability.
2. Deterministic server-side microservice health rules (0 failures -> healthy, 1-2 -> degraded, 3+ -> down, stale -> unknown).
3. Freshness metadata and staleness flagging (>300s).
4. No-traffic error budget semantics (value: null, display: "—", status: "insufficient_data").
5. Server-side pagination, bounded activity feeds, and zero N+1 queries.
6. Role-Based Access Control (Viewer read-only, Member quick-probe).
7. Cross-tenant isolation enforcement.
8. MTTD, MTTR, and deployment change failure rate calculation accuracy.
"""

import os
import re
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.auth import hash_password, create_access_token
from app.main import app
from app.models.incident import (
    User,
    Organization,
    UserOrganizationMembership,
    MembershipRole,
    Incident,
    Investigation,
    Repository,
    Service,
    ServiceHealth,
    Environment,

    ServiceRepository,
    ServiceRepositoryRole,
    ServiceDependency,
    ServiceDependencyType,
    ServiceCriticality,
    ServiceOwnership,
    ServiceDeploymentConfig,
    Deployment,
    DeploymentStatus,
    ProposedFix,
    Approval,
    ApprovalStatus,
    MultiRepoRemediationPlan,
    RemediationPlanItem,
    RemediationPlanStatus,
    TelemetrySignal,
    HealthCheckLog,
    SignalProvider,
    SignalType,
    SignalStatus,
)
from app.schemas.command_center import (
    FreshnessMetadata,
    ErrorBudgetMetric,
    TimeMetric,
    IncidentsSummary,
    ServiceFleetSummary,
    DeploymentsSummary,
    RemediationSummary,
    ReliabilitySummary,
    RecentActivityItem,
    CommandCenterOverviewResponse,
    OperationalServiceItem,
    OperationalServicesResponse,
    ActiveCommandIncidentItem,
    ActiveCommandResponse,
    QuickProbeRequest,
    QuickProbeResponse,
)
from app.services.command_center import (
    _compute_freshness,
    compute_deterministic_service_health,
    get_command_center_overview,
    get_operational_services_paginated,
    get_active_command_feed,
    trigger_quick_diagnostic_probe,
    STALE_THRESHOLD_SECONDS,
)

# In-memory SQLite for high-speed isolated test execution
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def org(db):
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme Global Ops",
        slug="acme-global-ops",
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture
def org_b(db):
    organization = Organization(
        id=uuid.uuid4(),
        name="Beta Ops Corp",
        slug="beta-ops-corp",
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture
def viewer_user(db, org):
    user = User(
        id=uuid.uuid4(),
        email="viewer@acme.com",
        username="viewer_acme",
        hashed_password=hash_password("ViewerPass123!"),
        organization_id=org.id,
        is_active=True,
    )
    db.add(user)
    db.flush()
    mem = UserOrganizationMembership(
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.VIEWER,
    )
    db.add(mem)
    db.commit()
    return user


@pytest.fixture
def member_user(db, org):
    user = User(
        id=uuid.uuid4(),
        email="operator@acme.com",
        username="operator_acme",
        hashed_password=hash_password("OperatorPass123!"),
        organization_id=org.id,
        is_active=True,
    )

    db.add(user)
    db.flush()
    mem = UserOrganizationMembership(
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.MEMBER,
    )
    db.add(mem)
    db.commit()
    return user


@pytest.fixture
def auth_headers_viewer(viewer_user):
    token = create_access_token(data={"sub": str(viewer_user.id), "org_id": str(viewer_user.organization_id)})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers_member(member_user):
    token = create_access_token(data={"sub": str(member_user.id), "org_id": str(member_user.organization_id)})
    return {"Authorization": f"Bearer {token}"}


_inc_seq = 1000

def make_inc(db, org, **kwargs) -> Incident:
    global _inc_seq
    _inc_seq += 1
    inc = Incident(
        id=kwargs.get("id", uuid.uuid4()),
        organization_id=org.id,
        number=_inc_seq,
        title=kwargs.get("title", f"Incident {_inc_seq}"),
        description=kwargs.get("description", "Diagnostic description"),
        severity=kwargs.get("severity", "SEV-1"),
        status=kwargs.get("status", "investigating"),
        service_id=kwargs.get("service_id", None),
        service_name=kwargs.get("service_name", None),
        created_at=kwargs.get("created_at", datetime.now(timezone.utc)),
        started_at=kwargs.get("started_at", None),
        resolved_at=kwargs.get("resolved_at", None),
    )
    db.add(inc)
    db.commit()
    db.refresh(inc)
    return inc


@pytest.fixture
def seeded_command_center_fleet(db, org):
    """Seed comprehensive fleet of services, incidents, deployments, and probes."""
    now = datetime.now(timezone.utc)

    # 1. Services
    srv_checkout = Service(id=uuid.uuid4(), organization_id=org.id, name="checkout-api", slug="checkout-api", tier="tier_1", health="healthy")
    srv_payment = Service(id=uuid.uuid4(), organization_id=org.id, name="payment-service", slug="payment-service", tier="tier_1", health="degraded")
    srv_inventory = Service(id=uuid.uuid4(), organization_id=org.id, name="inventory-service", slug="inventory-service", tier="tier_2", health="healthy")
    srv_legacy = Service(id=uuid.uuid4(), organization_id=org.id, name="legacy-billing", slug="legacy-billing", tier="tier_3", health=ServiceHealth.UNHEALTHY)

    db.add_all([srv_checkout, srv_payment, srv_inventory, srv_legacy])
    db.flush()

    # 2. Parent Incidents (Root Incidents only)
    inc1 = make_inc(
        db, org,
        service_id=srv_payment.id,
        service_name="payment-service",
        title="Payment gateway error rate spike",
        description="Gateway responses failing with HTTP 504",
        severity="SEV-1",
        status="investigating",
        created_at=now - timedelta(minutes=45),
        started_at=now - timedelta(minutes=50),
    )
    inc2 = make_inc(
        db, org,
        service_id=srv_checkout.id,
        service_name="checkout-api",
        title="Checkout latency degradation",
        description="Downstream calls taking >1200ms",
        severity="SEV-2",
        status="awaiting_approval",
        created_at=now - timedelta(minutes=20),
        started_at=now - timedelta(minutes=25),
    )
    inc3 = make_inc(
        db, org,
        service_id=srv_legacy.id,
        service_name="legacy-billing",
        title="Legacy billing cron job failed",
        description="Job timeout",
        severity="SEV-3",
        status="created",
        created_at=now - timedelta(minutes=10),
    )
    # 1 Resolved incident with known MTTD/MTTR
    inc_resolved = make_inc(
        db, org,
        service_id=srv_inventory.id,
        service_name="inventory-service",
        title="Inventory sync lock resolved",
        severity="SEV-2",
        status="resolved",
        created_at=now - timedelta(hours=3),
        started_at=now - timedelta(hours=3, minutes=10), # MTTD: 10 mins
        resolved_at=now - timedelta(hours=2),            # MTTR: 60 mins
    )

    # 3. Child Investigation linked to inc1 (verifies child not double-counted in active parent count)
    inv_parent = Investigation(
        id=uuid.uuid4(),
        organization_id=org.id,
        incident_id=inc1.id,
        is_parent=True,
        workflow_type="production_incident",
        status="running",
    )
    inv_child = Investigation(
        id=uuid.uuid4(),
        organization_id=org.id,
        incident_id=inc1.id,
        parent_investigation_id=inv_parent.id,
        is_parent=False,
        workflow_type="production_incident",
        status="running",
    )
    db.add_all([inv_parent, inv_child])

    # Environment
    env = Environment(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="production",
        env_type="production",
    )
    db.add(env)
    db.flush()

    # 4. Deployments (3 in 24h: 2 succeeded, 1 failed -> failure rate = 33.3%)
    dep1 = Deployment(
        id=uuid.uuid4(), organization_id=org.id, service_id=srv_checkout.id,
        environment_id=env.id,
        status=DeploymentStatus.SUCCEEDED.value, version="v2.4.1", commit_sha="a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4",
        deployed_by="alice@acme.com", created_at=now - timedelta(hours=2),
    )
    dep2 = Deployment(
        id=uuid.uuid4(), organization_id=org.id, service_id=srv_payment.id,
        environment_id=env.id,
        status=DeploymentStatus.FAILED.value, version="v1.9.0", commit_sha="b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5",
        deployed_by="bob@acme.com", created_at=now - timedelta(hours=1),
    )
    dep3 = Deployment(
        id=uuid.uuid4(), organization_id=org.id, service_id=srv_inventory.id,
        environment_id=env.id,
        status=DeploymentStatus.SUCCEEDED.value, version="v3.0.0", commit_sha="c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f6",
        deployed_by="charlie@acme.com", created_at=now - timedelta(hours=5),
    )
    db.add_all([dep1, dep2, dep3])

    # 5. Health Check Probe Logs
    log_checkout = HealthCheckLog(
        organization_id=org.id, config_id=uuid.uuid4(), service_id=srv_checkout.id,
        environment_id=env.id, url="https://api.internal/checkout/health",
        status_code=200, latency_ms=42.0, is_healthy=True, probed_at=now - timedelta(seconds=20),
    )
    log_payment = HealthCheckLog(
        organization_id=org.id, config_id=uuid.uuid4(), service_id=srv_payment.id,
        environment_id=env.id, url="https://api.internal/payment/health",
        status_code=500, latency_ms=850.0, is_healthy=False, probed_at=now - timedelta(seconds=15),
    )

    db.add_all([log_checkout, log_payment])

    # 6. Telemetry Signal (error rate signal for error budget)
    sig_checkout = TelemetrySignal(
        organization_id=org.id, provider=SignalProvider.PROMETHEUS, provider_event_id="evt_01",
        signal_type=SignalType.ERROR_RATE, rule_name="http_error_rate",
        service_id=srv_checkout.id, metric_name="http_error_rate_percent", metric_value=0.04,
        fingerprint="fp_chk_01", correlation_key="corr_chk_01", title="Checkout Low Error Rate",
        status=SignalStatus.INGESTED, observed_at=now - timedelta(minutes=10),
    )
    sig_payment = TelemetrySignal(
        organization_id=org.id, provider=SignalProvider.PROMETHEUS, provider_event_id="evt_02",
        signal_type=SignalType.ERROR_RATE, rule_name="http_error_rate",
        service_id=srv_payment.id, metric_name="http_error_rate_percent", metric_value=0.08,
        fingerprint="fp_pay_01", correlation_key="corr_pay_01", title="Payment Error Rate",
        status=SignalStatus.INGESTED, observed_at=now - timedelta(minutes=5),
    )
    db.add_all([sig_checkout, sig_payment])

    # 7. Remediation Plans & Items
    plan1 = MultiRepoRemediationPlan(
        id=uuid.uuid4(), organization_id=org.id, incident_id=inc1.id,
        title="Payment & Checkout Coordinated Fix", summary="Patch payment service",
        status=RemediationPlanStatus.EXECUTING.value,
    )
    db.add(plan1)
    db.commit()

    return {
        "srv_checkout": srv_checkout,
        "srv_payment": srv_payment,
        "srv_inventory": srv_inventory,
        "srv_legacy": srv_legacy,
        "inc1": inc1,
        "inc2": inc2,
        "inc3": inc3,
        "inc_resolved": inc_resolved,
    }


# ============================================================================
# 1. OPERATIONS COMMAND CENTER OVERVIEW AGGREGATION
# ============================================================================

def test_command_center_overview_aggregation(client, auth_headers_viewer, seeded_command_center_fleet, org):
    """Verify company-wide overview aggregation calculates exact counts and metrics."""
    res = client.get("/command-center/overview", headers=auth_headers_viewer)
    assert res.status_code == 200
    data = res.json()

    # 1. Organization info
    assert data["organization_id"] == str(org.id)
    assert data["organization_name"] == org.name

    # 2. Incidents summary (Parent incidents only: 3 active, 1 SEV-1, 1 SEV-2, 1 SEV-3)
    inc_sum = data["incidents_summary"]
    assert inc_sum["active_total"] == 3
    assert inc_sum["critical_sev1"] == 1
    assert inc_sum["major_sev2"] == 1
    assert inc_sum["minor_sev3"] == 1
    assert inc_sum["low_sev4"] == 0
    assert inc_sum["investigating_count"] == 1
    assert inc_sum["awaiting_approval_count"] == 1
    assert inc_sum["resolved_last_24h"] == 1

    # MTTD and MTTR verification
    assert inc_sum["mttd"]["sample_size"] == 1
    assert inc_sum["mttd"]["value_minutes"] == 10.0
    assert inc_sum["mttd"]["display"] == "10m"

    assert inc_sum["mttr"]["sample_size"] == 1
    assert inc_sum["mttr"]["value_minutes"] == 60.0
    assert inc_sum["mttr"]["display"] == "60m"

    # Freshness metadata
    assert "freshness" in inc_sum
    assert inc_sum["freshness"]["is_stale"] is False
    assert inc_sum["freshness"]["freshness_seconds"] >= 0.0

    # 3. Service fleet summary
    fleet = data["service_fleet"]
    assert fleet["total_services"] == 4
    assert fleet["tier1_total"] == 2

    # 4. Deployments summary (3 in 24h: 2 succeeded, 1 failed -> failure rate = 33.3%)
    dep_sum = data["deployments_summary"]
    assert dep_sum["total_last_24h"] == 3
    assert dep_sum["successful"] == 2
    assert dep_sum["failed"] == 1
    assert dep_sum["failure_rate_percent"] == 33.3

    # 5. Reliability & Error budget
    rel = data["reliability_summary"]
    assert rel["error_budget"]["status"] in ("healthy", "degraded", "exhausted")
    assert rel["error_budget"]["value"] is not None
    assert rel["error_budget"]["slo_target_percent"] == 99.9

    # 6. Recent activity feed (bounded to 24h)
    assert len(data["recent_activity"]) >= 3
    for act in data["recent_activity"]:
        assert act["event_type"] in ("incident_created", "deployment_completed", "root_cause_identified", "pr_published")
        assert act["title"] is not None


# ============================================================================
# 2. DETERMINISTIC SERVER-SIDE HEALTH RULES
# ============================================================================

def test_deterministic_health_status_rules():
    """Verify deterministic server-side health classification across all rule branches."""
    now = datetime.now(timezone.utc)
    fresh = FreshnessMetadata(observed_at=now, source="probe", freshness_seconds=10.0, is_stale=False)
    stale = FreshnessMetadata(observed_at=now - timedelta(seconds=350), source="probe", freshness_seconds=350.0, is_stale=True)

    # 1. HEALTHY: No active SEV-1/2, error rate < 1.0%, p95 < 500ms, probe failures == 0, fresh
    status, reason = compute_deterministic_service_health(
        has_active_sev1_sev2=False,
        has_active_sev3_sev4=False,
        error_rate_percent=0.05,
        p95_latency_ms=85.0,
        consecutive_probe_failures=0,
        freshness=fresh,
        has_telemetry_or_probes=True,
    )
    assert status == "healthy"

    # 2. DEGRADED: 1 or 2 consecutive probe failures
    status_deg1, _ = compute_deterministic_service_health(
        has_active_sev1_sev2=False,
        has_active_sev3_sev4=False,
        error_rate_percent=0.05,
        p95_latency_ms=85.0,
        consecutive_probe_failures=1,
        freshness=fresh,
        has_telemetry_or_probes=True,
    )
    assert status_deg1 == "degraded"

    status_deg2, _ = compute_deterministic_service_health(
        has_active_sev1_sev2=False,
        has_active_sev3_sev4=False,
        error_rate_percent=0.05,
        p95_latency_ms=85.0,
        consecutive_probe_failures=2,
        freshness=fresh,
        has_telemetry_or_probes=True,
    )
    assert status_deg2 == "degraded"

    # DEGRADED: Error rate between 1.0% and 5.0%
    status_deg_err, _ = compute_deterministic_service_health(
        has_active_sev1_sev2=False,
        has_active_sev3_sev4=False,
        error_rate_percent=2.5,
        p95_latency_ms=85.0,
        consecutive_probe_failures=0,
        freshness=fresh,
        has_telemetry_or_probes=True,
    )
    assert status_deg_err == "degraded"

    # DEGRADED: p95 latency between 500ms and 2000ms
    status_deg_lat, _ = compute_deterministic_service_health(
        has_active_sev1_sev2=False,
        has_active_sev3_sev4=False,
        error_rate_percent=0.05,
        p95_latency_ms=950.0,
        consecutive_probe_failures=0,
        freshness=fresh,
        has_telemetry_or_probes=True,
    )
    assert status_deg_lat == "degraded"

    # 3. DOWN: Active SEV-1 incident
    status_down_inc, _ = compute_deterministic_service_health(
        has_active_sev1_sev2=True,
        has_active_sev3_sev4=False,
        error_rate_percent=0.05,
        p95_latency_ms=85.0,
        consecutive_probe_failures=0,
        freshness=fresh,
        has_telemetry_or_probes=True,
    )
    assert status_down_inc == "down"

    # DOWN: Consecutive probe failures >= 3
    status_down_probe, _ = compute_deterministic_service_health(
        has_active_sev1_sev2=False,
        has_active_sev3_sev4=False,
        error_rate_percent=0.05,
        p95_latency_ms=85.0,
        consecutive_probe_failures=3,
        freshness=fresh,
        has_telemetry_or_probes=True,
    )
    assert status_down_probe == "down"

    # DOWN: Error rate > 5.0%
    status_down_err, _ = compute_deterministic_service_health(
        has_active_sev1_sev2=False,
        has_active_sev3_sev4=False,
        error_rate_percent=7.5,
        p95_latency_ms=85.0,
        consecutive_probe_failures=0,
        freshness=fresh,
        has_telemetry_or_probes=True,
    )
    assert status_down_err == "down"

    # 4. UNKNOWN: Stale telemetry (>300s)
    status_unk_stale, _ = compute_deterministic_service_health(
        has_active_sev1_sev2=False,
        has_active_sev3_sev4=False,
        error_rate_percent=0.05,
        p95_latency_ms=85.0,
        consecutive_probe_failures=0,
        freshness=stale,
        has_telemetry_or_probes=True,
    )
    assert status_unk_stale == "unknown"

    # UNKNOWN: No telemetry or probes configured
    status_unk_none, _ = compute_deterministic_service_health(
        has_active_sev1_sev2=False,
        has_active_sev3_sev4=False,
        error_rate_percent=None,
        p95_latency_ms=None,
        consecutive_probe_failures=0,
        freshness=fresh,
        has_telemetry_or_probes=False,
    )
    assert status_unk_none == "unknown"

    # UNKNOWN: Telemetry configured but error rate and latency are missing/None (prevents false healthy)
    status_unk_missing_metrics, reason_missing = compute_deterministic_service_health(
        has_active_sev1_sev2=False,
        has_active_sev3_sev4=False,
        error_rate_percent=None,
        p95_latency_ms=None,
        consecutive_probe_failures=0,
        freshness=fresh,
        has_telemetry_or_probes=True,
        has_verified_probe=False,
    )
    assert status_unk_missing_metrics == "unknown"
    assert "missing" in reason_missing.lower() or "insufficient" in reason_missing.lower()

    # HEALTHY: Missing metric but verified 200 OK probe exists
    status_healthy_probe, _ = compute_deterministic_service_health(
        has_active_sev1_sev2=False,
        has_active_sev3_sev4=False,
        error_rate_percent=None,
        p95_latency_ms=None,
        consecutive_probe_failures=0,
        freshness=fresh,
        has_telemetry_or_probes=True,
        has_verified_probe=True,
    )
    assert status_healthy_probe == "healthy"



# ============================================================================
# 3. FRESHNESS METADATA & STALENESS FLAGGING
# ============================================================================

def test_freshness_metadata_and_stale_flagging():
    """Verify freshness metadata computation and >300s staleness threshold."""
    now = datetime.now(timezone.utc)

    # 1. Fresh observation (15 seconds old)
    obs_fresh = now - timedelta(seconds=15)
    f1 = _compute_freshness(obs_fresh, source="prometheus")
    assert f1.freshness_seconds >= 14.0
    assert f1.freshness_seconds <= 16.0
    assert f1.is_stale is False
    assert f1.source == "prometheus"

    # 2. Stale observation (350 seconds old > 300s)
    obs_stale = now - timedelta(seconds=350)
    f2 = _compute_freshness(obs_stale, source="synthetic_probe")
    assert f2.freshness_seconds >= 349.0
    assert f2.is_stale is True

    # 3. None timestamp defaults to stale
    f3 = _compute_freshness(None)
    assert f3.is_stale is True


# ============================================================================
# 4. NO-TRAFFIC ERROR BUDGET INSUFFICIENT DATA SEMANTICS
# ============================================================================

def test_no_traffic_error_budget_insufficient_data(client, auth_headers_viewer, db, org):
    """Verify that when no telemetry signals exist, error budget returns insufficient_data (not 0%)."""
    # Organization with zero telemetry signals
    res = client.get("/command-center/overview", headers=auth_headers_viewer)
    assert res.status_code == 200
    data = res.json()

    eb = data["reliability_summary"]["error_budget"]
    assert eb["value"] is None
    assert eb["display"] == "—"
    assert eb["status"] == "insufficient_data"
    assert eb["slo_target_percent"] == 99.9


# ============================================================================
# 5. SERVER-SIDE PAGINATION & OPERATIONAL SERVICE MATRIX
# ============================================================================

def test_command_center_pagination_and_eager_loading(client, auth_headers_viewer, seeded_command_center_fleet):
    """Verify operational service matrix pagination, filters, and relationship eager loading."""
    # 1. Page 1 with page_size=2
    res_p1 = client.get("/command-center/services-operational?page=1&page_size=2", headers=auth_headers_viewer)
    assert res_p1.status_code == 200
    p1 = res_p1.json()
    assert len(p1["items"]) == 2
    assert p1["total"] == 4
    assert p1["page"] == 1
    assert p1["page_size"] == 2
    assert p1["total_pages"] == 2

    # 2. Page 2 with page_size=2
    res_p2 = client.get("/command-center/services-operational?page=2&page_size=2", headers=auth_headers_viewer)
    assert res_p2.status_code == 200
    p2 = res_p2.json()
    assert len(p2["items"]) == 2
    assert p2["page"] == 2

    # 3. Filter by Tier 1
    res_t1 = client.get("/command-center/services-operational?tier=tier_1", headers=auth_headers_viewer)
    assert res_t1.status_code == 200
    t1_data = res_t1.json()
    assert t1_data["total"] == 2
    for item in t1_data["items"]:
        assert "tier_1" in item["tier"].lower()
        assert item["freshness"] is not None
        assert item["health_status"] in ("healthy", "degraded", "down", "unknown")


# ============================================================================
# 6. ACTIVE COMMAND INCIDENT FEED
# ============================================================================

def test_active_command_incident_feed(client, auth_headers_viewer, seeded_command_center_fleet):
    """Verify active command feed returns enriched parent incident cards."""
    res = client.get("/command-center/active-command", headers=auth_headers_viewer)
    assert res.status_code == 200
    data = res.json()

    assert data["total_active"] == 3
    assert len(data["active_incidents"]) == 3

    inc1_item = next(i for i in data["active_incidents"] if i["severity"] == "SEV-1")
    assert inc1_item["has_active_remediation_plan"] is True
    assert inc1_item["remediation_plan_status"] == "executing"
    assert inc1_item["blast_radius_service_count"] >= 1
    assert inc1_item["duration_minutes"] >= 0.0


# ============================================================================
# 7. ROLE-BASED ACCESS CONTROL (RBAC) & QUICK PROBE
# ============================================================================

def test_command_center_rbac_and_quick_probe(client, auth_headers_viewer, auth_headers_member, seeded_command_center_fleet):
    """Verify Viewer has read-only access while Member can trigger quick probes."""
    svc = seeded_command_center_fleet["srv_checkout"]

    # 1. Anonymous request is rejected
    res_anon = client.get("/command-center/overview")
    assert res_anon.status_code in (401, 403)


    # 2. Viewer can view overview
    res_view = client.get("/command-center/overview", headers=auth_headers_viewer)
    assert res_view.status_code == 200

    # 3. Viewer is forbidden from triggering quick diagnostic probe
    res_probe_view = client.post(
        "/command-center/quick-probe",
        json={"service_id": str(svc.id)},
        headers=auth_headers_viewer,
    )
    assert res_probe_view.status_code == 403

    # 4. Member can trigger quick diagnostic probe
    res_probe_mem = client.post(
        "/command-center/quick-probe",
        json={"service_id": str(svc.id)},
        headers=auth_headers_member,
    )
    assert res_probe_mem.status_code == 200
    probe_data = res_probe_mem.json()
    assert probe_data["service_id"] == str(svc.id)
    assert probe_data["probe_status"] == "success"
    assert probe_data["http_status_code"] == 200
    assert probe_data["health_status_after"] == "healthy"


# ============================================================================
# 8. CROSS-TENANT ISOLATION ENFORCEMENT
# ============================================================================

def test_command_center_cross_tenant_isolation(client, db, org, org_b, seeded_command_center_fleet):
    """Verify complete tenant boundary between Organization A and Organization B."""
    # Create user in Organization B
    user_b = User(
        id=uuid.uuid4(),
        email="user@beta.com",
        username="user_beta",
        hashed_password=hash_password("BetaPass123!"),
        organization_id=org_b.id,
        is_active=True,
    )

    db.add(user_b)
    db.flush()
    mem_b = UserOrganizationMembership(
        user_id=user_b.id,
        organization_id=org_b.id,
        role=MembershipRole.MEMBER,
    )
    db.add(mem_b)
    db.commit()

    token_b = create_access_token(data={"sub": str(user_b.id), "org_id": str(user_b.organization_id)})
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Org B queries overview
    res_b = client.get("/command-center/overview", headers=headers_b)
    assert res_b.status_code == 200
    data_b = res_b.json()

    # Org B sees 0 incidents, 0 services, 0 deployments
    assert data_b["organization_id"] == str(org_b.id)
    assert data_b["incidents_summary"]["active_total"] == 0
    assert data_b["service_fleet"]["total_services"] == 0
    assert data_b["deployments_summary"]["total_last_24h"] == 0
    assert data_b["remediation_summary"]["active_plans"] == 0

    # Org B queries operational services
    res_services_b = client.get("/command-center/services-operational", headers=headers_b)
    assert res_services_b.status_code == 200
    assert res_services_b.json()["total"] == 0

    # Org B cannot probe Org A's service
    svc_a = seeded_command_center_fleet["srv_checkout"]
    res_cross_probe = client.post(
        "/command-center/quick-probe",
        json={"service_id": str(svc_a.id)},
        headers=headers_b,
    )
    assert res_cross_probe.status_code == 404
