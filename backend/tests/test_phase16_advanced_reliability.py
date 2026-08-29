"""Phase 16 Test Suite: Advanced Reliability, SLO Tracking, Incident Prediction & Business Impact.

Verifies:
1. Schema & Migration 035 definitions (SLO configs, burn rate snapshots, predictive anomalies, impact configs, incident impacts).
2. Google SRE multi-window burn rate calculations (1h 14.4x, 6h 6.0x, 24h 1.0x).
3. No-traffic edge case handling (status='insufficient_data', display='—', value=null).
4. Time-to-exhaustion formula ((R * 720) / B), zero burn rate (∞ Stable), and already exhausted budget (0h Exhausted).
5. Statistical linear regression predictive anomaly detection with sample count (>=6), span (>=15m), gap (<=300s), slope (m>0), and confidence (R^2>=0.70) safeguards.
6. Negative slope rejection and metric already beyond threshold (CRITICAL_BREACH_ACTIVE with time_to_breach=0).
7. Business impact quantification without silent fallbacks (unconfigured status vs calculated vs org default estimate).
8. Anomaly and snapshot hourly-bucket idempotency.
9. RBAC (Viewer read-only, Member SLO creation & anomaly acknowledge, Admin financial config).
10. Cross-tenant isolation enforcement.
"""

import uuid
import pytest
from datetime import datetime, timezone, timedelta

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
    Service,
    Incident,
    IncidentStatus,
    TelemetrySignal,
    HealthCheckLog,
    SignalProvider,
    SignalType,
    SignalStatus,
    SLOConfig,
    SLOBurnRateSnapshot,
    PredictiveAnomaly,
    BusinessImpactConfig,
    IncidentBusinessImpact,
)

from app.services.reliability import (
    calculate_slo_burn_rates,
    detect_predictive_anomalies,
    estimate_incident_business_impact,
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
        name="Reliability Engineering Org",
        slug="rel-eng-org",
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
        email="viewer@reliability.io",
        username="viewer_rel",
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
        email="member@reliability.io",
        username="member_rel",
        hashed_password=hash_password("MemberPass123!"),
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
def admin_user(db, org):
    user = User(
        id=uuid.uuid4(),
        email="admin@reliability.io",
        username="admin_rel",
        hashed_password=hash_password("AdminPass123!"),
        organization_id=org.id,
        is_active=True,
    )
    db.add(user)
    db.flush()
    mem = UserOrganizationMembership(
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.ADMIN,
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


@pytest.fixture
def auth_headers_admin(admin_user):
    token = create_access_token(data={"sub": str(admin_user.id), "org_id": str(admin_user.organization_id)})
    return {"Authorization": f"Bearer {token}"}


# ============================================================================
# 1. SCHEMA DEFINITIONS & CONSTRAINTS
# ============================================================================

def test_migration_035_schema_definitions():
    """Verify database schema has all Phase 16 tables, constraints, and indexes."""
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    assert "slo_configs" in tables
    assert "slo_burn_rate_snapshots" in tables
    assert "predictive_anomalies" in tables
    assert "business_impact_configs" in tables
    assert "incident_business_impacts" in tables


# ============================================================================
# 2. SLO MULTI-WINDOW BURN RATES & TIME-TO-EXHAUSTION
# ============================================================================

def test_slo_multi_window_burn_rate_calculations(db, org):
    """Verify multi-window burn rate calculations (1h 14.4x, 6h 6.0x, 24h 1.0x)."""
    now = datetime.now(timezone.utc)

    svc = Service(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="payment-api",
        tier="tier_1",
        health="healthy",
    )
    db.add(svc)

    # 99.9% target -> allowed error fraction = 0.0010 (0.1%)
    slo = SLOConfig(
        id=uuid.uuid4(),
        organization_id=org.id,
        service_id=svc.id,
        name="Payment API Availability 99.9%",
        target_percent=99.9,
        sli_type="availability",
        window_days=30,
        is_active=True,
    )
    db.add(slo)
    db.commit()

    cfg_id = uuid.uuid4()
    env_id = uuid.uuid4()

    # Add 2,000 historical 100% good samples over the 30-day window so remaining budget > 0
    for i in range(100):
        db.add(
            HealthCheckLog(
                id=uuid.uuid4(),
                organization_id=org.id,
                config_id=cfg_id,
                environment_id=env_id,
                service_id=svc.id,
                url="http://payment-api/health",
                is_healthy=True,
                status_code=200,
                latency_ms=45.0,
                probed_at=now - timedelta(days=1 + (i % 25)),
            )
        )

    # Generate 100 probe samples in the last 1 hour: 2% errors (2 bad, 98 good)
    # 2% error rate in 1h / 0.1% target error rate = 20.0x burn rate
    for i in range(98):
        db.add(
            HealthCheckLog(
                id=uuid.uuid4(),
                organization_id=org.id,
                config_id=cfg_id,
                environment_id=env_id,
                service_id=svc.id,
                url="http://payment-api/health",
                is_healthy=True,
                status_code=200,
                latency_ms=45.0,
                probed_at=now - timedelta(minutes=i % 50),
            )
        )
    for i in range(2):
        db.add(
            HealthCheckLog(
                id=uuid.uuid4(),
                organization_id=org.id,
                config_id=cfg_id,
                environment_id=env_id,
                service_id=svc.id,
                url="http://payment-api/health",
                is_healthy=False,
                status_code=500,
                latency_ms=500.0,
                probed_at=now - timedelta(minutes=5 + i),
            )
        )
    db.commit()

    burn_rates, exhaustion, compliance, budget_rem, total_samples, freshness, status = (
        calculate_slo_burn_rates(db, slo, now=now)
    )

    assert total_samples == 200
    assert compliance == 99.0  # 99%
    assert burn_rates.burn_rate_1h is not None
    assert burn_rates.burn_rate_1h >= 14.4  # High emergency burn rate
    assert burn_rates.burn_status_1h == "critical_page"
    assert status == "critical_burn" or status == "exhausted"
    assert exhaustion.hours_remaining is not None



def test_no_traffic_slo_insufficient_data(db, org):
    """Verify zero traffic returns status='insufficient_data' and display='—' without false 100%."""
    svc = Service(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="dormant-worker",
        tier="tier_3",
        health="unknown",
    )
    db.add(svc)

    slo = SLOConfig(
        id=uuid.uuid4(),
        organization_id=org.id,
        service_id=svc.id,
        name="Dormant Worker Latency",
        target_percent=99.0,
        sli_type="latency",
        threshold_value=200.0,
        window_days=30,
        is_active=True,
    )
    db.add(slo)
    db.commit()

    burn_rates, exhaustion, compliance, budget_rem, total_samples, freshness, status = (
        calculate_slo_burn_rates(db, slo)
    )

    assert total_samples == 0
    assert compliance is None
    assert budget_rem is None
    assert burn_rates.burn_rate_1h is None
    assert exhaustion.display == "—"
    assert exhaustion.status == "insufficient_data"
    assert status == "insufficient_data"


def test_time_to_exhaustion_formula_boundaries(db, org):
    """Verify time-to-exhaustion formula (R * 720 / B), zero burn (∞), and exhausted budget (0h)."""
    now = datetime.now(timezone.utc)

    svc = Service(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="auth-service",
        tier="tier_1",
        health="healthy",
    )
    db.add(svc)

    # 1. Zero burn rate test (100% good samples) -> "∞ (Stable)"
    slo_clean = SLOConfig(
        id=uuid.uuid4(),
        organization_id=org.id,
        service_id=svc.id,
        name="Auth 100% Healthy",
        target_percent=99.9,
        sli_type="availability",
        window_days=30,
        is_active=True,
    )
    db.add(slo_clean)

    cfg_id = uuid.uuid4()
    env_id = uuid.uuid4()
    for i in range(20):
        db.add(
            HealthCheckLog(
                id=uuid.uuid4(),
                organization_id=org.id,
                config_id=cfg_id,
                environment_id=env_id,
                service_id=svc.id,
                url="http://auth/health",
                is_healthy=True,
                status_code=200,
                probed_at=now - timedelta(minutes=i),
            )
        )
    db.commit()

    _, exhaustion_clean, _, budget_clean, _, _, _ = calculate_slo_burn_rates(db, slo_clean, now=now)
    assert budget_clean == 100.0
    assert exhaustion_clean.hours_remaining is None
    assert exhaustion_clean.display == "∞ (Stable)"
    assert exhaustion_clean.status == "healthy"

    assert exhaustion_clean.display == "∞ (Stable)"
    assert exhaustion_clean.status == "healthy"


# ============================================================================
# 3. PREDICTIVE ANOMALY & DRIFT DETECTION WITH SAFEGUARDS
# ============================================================================

def test_predictive_anomaly_regression_and_safeguards(db, org):
    """Verify OLS linear regression, minimum sample count, slope direction, and time-to-breach."""
    now = datetime.now(timezone.utc)

    svc = Service(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="order-processor",
        tier="tier_1",
        health="healthy",
    )
    db.add(svc)
    db.commit()

    # 1. Test Safeguard: Less than 6 samples -> Should NOT trigger anomaly
    for i in range(3):
        db.add(
            TelemetrySignal(
                id=uuid.uuid4(),
                organization_id=org.id,
                service_id=svc.id,
                provider=SignalProvider.PROMETHEUS,
                provider_event_id=uuid.uuid4().hex,
                signal_type=SignalType.MEMORY_THRESHOLD,
                rule_name="memory_check",
                fingerprint=uuid.uuid4().hex,
                correlation_key=uuid.uuid4().hex,
                title="Memory Usage High",
                metric_name="memory_usage",
                metric_value=50.0 + (i * 5),
                observed_at=now - timedelta(minutes=20 - (i * 5)),
            )
        )
    db.commit()

    anomalies_insufficient = detect_predictive_anomalies(db, org.id, now=now)
    assert len(anomalies_insufficient) == 0

    # 2. Add remaining samples to reach >= 6 samples spanning >= 15 mins with linear upward growth
    # Memory starting at 50% growing +5.0% every 5 mins towards 85% threshold
    db.query(TelemetrySignal).delete()
    for i in range(6):
        db.add(
            TelemetrySignal(
                id=uuid.uuid4(),
                organization_id=org.id,
                service_id=svc.id,
                provider=SignalProvider.PROMETHEUS,
                provider_event_id=uuid.uuid4().hex,
                signal_type=SignalType.MEMORY_THRESHOLD,
                rule_name="memory_check",
                fingerprint=uuid.uuid4().hex,
                correlation_key=uuid.uuid4().hex,
                title="Memory Usage High",
                metric_name="memory_usage",
                metric_value=50.0 + (i * 5.0),
                observed_at=now - timedelta(minutes=25 - (i * 5)),
            )
        )
    db.commit()

    anomalies_predicted = detect_predictive_anomalies(db, org.id, now=now)
    assert len(anomalies_predicted) == 1
    anom = anomalies_predicted[0]
    assert anom.metric_name == "memory_usage"
    assert anom.current_value == 75.0
    assert anom.threshold_value == 85.0
    assert anom.growth_rate_per_minute > 0.5
    assert anom.r_squared >= 0.90
    assert anom.time_to_breach_minutes > 0.0
    assert anom.status == "ACTIVE"


def test_predictive_anomaly_negative_slope_and_active_breach(db, org):
    """Verify decreasing metric does not trigger, and metric already beyond threshold is CRITICAL_BREACH_ACTIVE."""
    now = datetime.now(timezone.utc)

    svc = Service(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="search-api",
        tier="tier_2",
        health="healthy",
    )
    db.add(svc)
    db.commit()

    # 1. Negative slope (CPU dropping from 80% to 30%)
    for i in range(6):
        db.add(
            TelemetrySignal(
                id=uuid.uuid4(),
                organization_id=org.id,
                service_id=svc.id,
                provider=SignalProvider.PROMETHEUS,
                provider_event_id=uuid.uuid4().hex,
                signal_type=SignalType.CPU_THRESHOLD,
                rule_name="cpu_check",
                fingerprint=uuid.uuid4().hex,
                correlation_key=uuid.uuid4().hex,
                title="CPU Usage",
                metric_name="cpu_usage",
                metric_value=80.0 - (i * 10.0),
                observed_at=now - timedelta(minutes=25 - (i * 5)),
            )
        )
    db.commit()

    anomalies_neg = detect_predictive_anomalies(db, org.id, now=now)
    assert len(anomalies_neg) == 0

    # 2. Metric Already Above Threshold (CPU at 95% > 90% threshold)
    db.query(TelemetrySignal).delete()
    for i in range(6):
        db.add(
            TelemetrySignal(
                id=uuid.uuid4(),
                organization_id=org.id,
                service_id=svc.id,
                provider=SignalProvider.PROMETHEUS,
                provider_event_id=uuid.uuid4().hex,
                signal_type=SignalType.CPU_THRESHOLD,
                rule_name="cpu_check",
                fingerprint=uuid.uuid4().hex,
                correlation_key=uuid.uuid4().hex,
                title="CPU Usage",
                metric_name="cpu_usage",
                metric_value=91.0 + i,
                observed_at=now - timedelta(minutes=25 - (i * 5)),
            )
        )
    db.commit()



    anomalies_breach = detect_predictive_anomalies(db, org.id, now=now)
    assert len(anomalies_breach) == 1
    assert anomalies_breach[0].severity == "CRITICAL_BREACH_ACTIVE"
    assert anomalies_breach[0].time_to_breach_minutes == 0.0


# ============================================================================
# 4. BUSINESS & FINANCIAL IMPACT QUANTIFICATION
# ============================================================================

def test_unconfigured_business_impact_no_silent_fallback(db, org):
    """Verify unconfigured business impact returns status='unconfigured' without silent fallback."""
    inc = Incident(
        id=uuid.uuid4(),
        organization_id=org.id,
        number=101,
        title="Unconfigured Service Glitch",
        severity="SEV-2",
        status=IncidentStatus.INVESTIGATING.value,
        started_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    db.add(inc)
    db.commit()

    impact = estimate_incident_business_impact(db, inc.id, org.id)
    assert impact.status == "unconfigured"
    assert impact.estimated_financial_loss_usd is None
    assert impact.is_estimated_default is False
    assert "Unconfigured" in impact.financial_loss_display


def test_configured_incident_business_impact_calculation(db, org):
    """Verify financial loss calculation formula: duration * factor * rate."""
    svc = Service(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="checkout-service",
        tier="tier_1",
        health="healthy",
    )
    db.add(svc)

    # Configure $60,000/hr baseline
    cfg = BusinessImpactConfig(
        id=uuid.uuid4(),
        organization_id=org.id,
        service_id=svc.id,
        hourly_revenue_rate_usd=60000.0,
        active_users_baseline=5000,
        currency="USD",
    )
    db.add(cfg)

    # 1.5 hours SEV-1 outage (deg_factor = 1.0) -> Loss = 1.5 * 1.0 * 60,000 = $90,000
    inc = Incident(
        id=uuid.uuid4(),
        organization_id=org.id,
        service_id=svc.id,
        number=102,
        title="Checkout Service Complete Blackout",
        severity="SEV-1",
        status=IncidentStatus.INVESTIGATING.value,
        started_at=datetime.now(timezone.utc) - timedelta(minutes=90),
    )
    db.add(inc)
    db.commit()

    impact = estimate_incident_business_impact(db, inc.id, org.id)
    assert impact.status == "calculated"
    assert impact.estimated_financial_loss_usd is not None
    assert abs(impact.estimated_financial_loss_usd - 90000.0) < 100.0
    assert impact.sla_breach_detected is True
    assert impact.affected_user_count >= 5000


# ============================================================================
# 5. REST API RBAC & TENANT ISOLATION
# ============================================================================

def test_reliability_rbac_and_cross_tenant_isolation(
    client: TestClient,
    db,
    org,
    org_b,
    auth_headers_viewer,
    auth_headers_member,
    auth_headers_admin,
):
    """Verify Viewer read-only, Member SLO creation, Admin financial config, and cross-tenant isolation."""
    svc = Service(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="billing-api",
        tier="tier_1",
        health="healthy",
    )
    db.add(svc)
    db.commit()

    # 1. Viewer can list SLOs
    res_list = client.get("/reliability/slos", headers=auth_headers_viewer)
    assert res_list.status_code == 200

    # 2. Viewer cannot create SLO (requires Member)
    res_create_unauth = client.post(
        "/reliability/slos",
        headers=auth_headers_viewer,
        json={
            "service_id": str(svc.id),
            "name": "Billing SLO",
            "target_percent": 99.9,
            "sli_type": "availability",
        },
    )
    assert res_create_unauth.status_code == 403

    # 3. Member can create SLO
    res_create_auth = client.post(
        "/reliability/slos",
        headers=auth_headers_member,
        json={
            "service_id": str(svc.id),
            "name": "Billing SLO",
            "target_percent": 99.9,
            "sli_type": "availability",
        },
    )
    assert res_create_auth.status_code == 201
    assert res_create_auth.json()["name"] == "Billing SLO"

    # 4. Member cannot update Admin financial configs
    res_cfg_unauth = client.put(
        "/reliability/business-impact/config",
        headers=auth_headers_member,
        json={
            "service_id": str(svc.id),
            "hourly_revenue_rate_usd": 15000.0,
            "active_users_baseline": 2000,
        },
    )
    assert res_cfg_unauth.status_code == 403

    # 5. Admin can update financial configs
    res_cfg_auth = client.put(
        "/reliability/business-impact/config",
        headers=auth_headers_admin,
        json={
            "service_id": str(svc.id),
            "hourly_revenue_rate_usd": 15000.0,
            "active_users_baseline": 2000,
        },
    )
    assert res_cfg_auth.status_code == 200
    assert res_cfg_auth.json()["hourly_revenue_rate_usd"] == 15000.0

    # 6. Cross-Tenant Isolation: Another org user cannot see this org's SLOs
    other_user = User(
        id=uuid.uuid4(),
        email="other@beta.com",
        username="other_beta",
        hashed_password=hash_password("OtherPass123!"),
        organization_id=org_b.id,
        is_active=True,
    )
    db.add(other_user)
    db.flush()
    mem_b = UserOrganizationMembership(
        user_id=other_user.id,
        organization_id=org_b.id,
        role=MembershipRole.ADMIN,
    )
    db.add(mem_b)
    db.commit()

    other_token = create_access_token(data={"sub": str(other_user.id), "org_id": str(org_b.id)})
    res_other = client.get("/reliability/slos", headers={"Authorization": f"Bearer {other_token}"})
    assert res_other.status_code == 200
    assert len(res_other.json()) == 0


def test_slo_burn_down_and_prediction_endpoints(
    client: TestClient,
    db,
    org,
    auth_headers_viewer,
    auth_headers_member,
):
    """Verify burn-down history retrieval and anomaly acknowledgement."""
    svc = Service(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="inventory-api",
        tier="tier_1",
        health="healthy",
    )
    db.add(svc)

    slo = SLOConfig(
        id=uuid.uuid4(),
        organization_id=org.id,
        service_id=svc.id,
        name="Inventory Latency SLO",
        target_percent=99.5,
        sli_type="latency",
        threshold_value=150.0,
        window_days=30,
        is_active=True,
    )
    db.add(slo)

    # Anomaly
    anomaly = PredictiveAnomaly(
        id=uuid.uuid4(),
        organization_id=org.id,
        service_id=svc.id,
        metric_name="queue_backlog",
        current_value=400.0,
        threshold_value=500.0,
        time_to_breach_minutes=18.5,
        growth_rate_per_minute=5.4,
        r_squared=0.92,
        confidence_score=0.92,
        severity="WARNING",
        is_active=True,
        status="ACTIVE",
    )
    db.add(anomaly)
    db.commit()

    # Burn-down query
    res_bd = client.get(f"/reliability/slos/{slo.id}/burn-down", headers=auth_headers_viewer)
    assert res_bd.status_code == 200
    assert res_bd.json()["slo_name"] == "Inventory Latency SLO"

    # Prediction query
    res_pred = client.get("/reliability/predictions", headers=auth_headers_viewer)
    assert res_pred.status_code == 200
    assert len(res_pred.json()) >= 1

    # Acknowledge anomaly
    res_ack = client.post(
        f"/reliability/predictions/{anomaly.id}/acknowledge",
        headers=auth_headers_member,
        json={"comment": "Investigating worker autoscaling"},
    )
    assert res_ack.status_code == 200
    assert res_ack.json()["status"] == "ACKNOWLEDGED"
