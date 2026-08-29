"""Comprehensive test suite for Phase 6 System Service Graph & Blast Radius Analysis Engine."""

import json
import time
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.core.auth import create_access_token, hash_password
from app.core.crypto import encrypt_secret
from app.models.incident import (
    User, Organization, Environment, Service, Region,
    UserOrganizationMembership, MembershipRole, ServiceDeploymentConfig,
    ServiceRepositoryRole, ServiceRepository, ServiceDependencyType,
    ServiceCriticality, ServiceDependency, OwnershipType, ServiceOwnership,
    Repository, Team, WebhookEndpoint, TelemetrySignal, Incident, IncidentStatus,
    IncidentSeverity, IncidentSource, SignalProvider, SignalType, SignalStatus,
    GraphNode, GraphEdge, GraphNodeType, GraphEdgeType, GraphEdgeSource,
    IncidentBlastRadiusReport
)
from app.services.graph_service import (
    sync_catalog_to_graph, ingest_trace_spans, import_manifest_spec,
    apply_edge_decay, sanitize_attributes
)
from app.services.blast_radius_service import (
    calculate_blast_radius, enqueue_blast_radius_recalculation
)

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
def setup_org_and_users(db_session: Session):
    """Fixture providing multi-tenant orgs, users with different roles, and a webhook endpoint."""
    org = Organization(name="Acme Corp", slug=f"acme-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    db_session.flush()

    # Admin User
    admin_user = User(
        username=f"admin_{uuid.uuid4().hex[:6]}",
        email=f"admin_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("adminpass"),
        organization_id=org.id,
    )
    db_session.add(admin_user)
    db_session.flush()
    db_session.add(UserOrganizationMembership(user_id=admin_user.id, organization_id=org.id, role=MembershipRole.ADMIN))

    # Operator User
    operator_user = User(
        username=f"op_{uuid.uuid4().hex[:6]}",
        email=f"op_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("oppass"),
        organization_id=org.id,
    )
    db_session.add(operator_user)
    db_session.flush()
    db_session.add(UserOrganizationMembership(user_id=operator_user.id, organization_id=org.id, role=MembershipRole.OPERATOR))

    # Viewer User
    viewer_user = User(
        username=f"viewer_{uuid.uuid4().hex[:6]}",
        email=f"viewer_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("viewpass"),
        organization_id=org.id,
    )
    db_session.add(viewer_user)
    db_session.flush()
    db_session.add(UserOrganizationMembership(user_id=viewer_user.id, organization_id=org.id, role=MembershipRole.VIEWER))

    # Production Environment
    prod_env = Environment(organization_id=org.id, name="Production", env_type="production")
    db_session.add(prod_env)

    # Webhook Endpoint for trace ingestion
    raw_secret = "test-trace-secret-key-12345"
    wh = WebhookEndpoint(
        organization_id=org.id,
        name="OTel Ingestion",
        key_id=f"key_otel_{uuid.uuid4().hex[:6]}",
        provider="opentelemetry",
        auth_method="bearer",
        encrypted_secret=encrypt_secret(raw_secret),
        is_active=True,
    )
    db_session.add(wh)
    db_session.commit()

    admin_token = create_access_token({"sub": str(admin_user.id), "username": admin_user.username})
    operator_token = create_access_token({"sub": str(operator_user.id), "username": operator_user.username})
    viewer_token = create_access_token({"sub": str(viewer_user.id), "username": viewer_user.username})

    return {
        "org": org,
        "admin_user": admin_user,
        "admin_token": admin_token,
        "operator_token": operator_token,
        "viewer_token": viewer_token,
        "prod_env": prod_env,
        "raw_secret": raw_secret,
        "wh": wh,
    }


# ============================================================================
# 1. GRAPH NODES & EDGES CRUD & RBAC
# ============================================================================

def test_graph_node_and_edge_upsert_idempotency(client, setup_org_and_users, db_session: Session):
    """Verify node and edge creation, unique identifier constraints, and RBAC."""
    admin_token = setup_org_and_users["admin_token"]
    viewer_token = setup_org_and_users["viewer_token"]
    org = setup_org_and_users["org"]

    # 1. Admin creates custom database node
    db_payload = {
        "name": "payment-postgres",
        "node_type": "DATABASE",
        "identifier": "database:payment-postgres",
        "tier": "critical",
        "metadata_json": {"engine": "postgres", "version": "16"},
    }
    resp = client.post(
        "/graph/nodes",
        json=db_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    node1 = resp.json()
    assert node1["identifier"] == "database:payment-postgres"
    assert node1["tier"] == "critical"

    # Duplicate identifier creation fails with 409
    dup_resp = client.post(
        "/graph/nodes",
        json=db_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert dup_resp.status_code == 409

    # 2. Admin creates custom queue node
    q_payload = {
        "name": "payment-events-queue",
        "node_type": "QUEUE",
        "identifier": "queue:payment-events",
        "tier": "high",
        "metadata_json": {"broker": "kafka"},
    }
    resp2 = client.post(
        "/graph/nodes",
        json=q_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp2.status_code == 201
    node2 = resp2.json()

    # 3. Admin creates edge between nodes
    edge_payload = {
        "source_node_id": node1["id"],
        "target_node_id": node2["id"],
        "edge_type": "PUBLISHES_TO",
        "source": "MANUAL_CORRECTION",
        "confidence": 1.0,
        "criticality": "HARD",
        "metadata_json": {"notes": "manual link"},
    }
    edge_resp = client.post(
        "/graph/edges",
        json=edge_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert edge_resp.status_code == 201
    edge_data = edge_resp.json()
    assert edge_data["confidence"] == 1.0
    assert edge_data["source"] == "MANUAL_CORRECTION"

    # 4. Viewer can query topology
    topo_resp = client.get(
        "/graph/topology",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert topo_resp.status_code == 200
    topo_data = topo_resp.json()
    assert topo_data["node_count"] == 2
    assert topo_data["edge_count"] == 1
    assert "DATABASE" in topo_data["nodes_by_type"]

    # 5. Viewer is rejected from creating nodes (403 Forbidden)
    forbidden_resp = client.post(
        "/graph/nodes",
        json={"name": "test", "node_type": "SERVICE", "identifier": "service:test"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert forbidden_resp.status_code == 403


# ============================================================================
# 2. CATALOG SYNC & MANUAL OVERRIDE PRESERVATION
# ============================================================================

def test_catalog_to_graph_sync_preserves_manual_corrections(client, setup_org_and_users, db_session: Session):
    """Verify catalog sync bridges entities into graph and preserves manual edge corrections."""
    org = setup_org_and_users["org"]
    admin_token = setup_org_and_users["admin_token"]
    operator_token = setup_org_and_users["operator_token"]

    # 1. Create Catalog Entities
    svc1 = Service(organization_id=org.id, name="checkout-service", slug="checkout", tier="critical")
    svc2 = Service(organization_id=org.id, name="payment-service", slug="payment", tier="critical")
    repo = Repository(organization_id=org.id, name="checkout-repo", full_name="acme/checkout-repo", github_url="https://github.com/acme/checkout")
    team = Team(organization_id=org.id, name="Checkout Team", slug="checkout-team")
    db_session.add_all([svc1, svc2, repo, team])
    db_session.flush()

    sr = ServiceRepository(organization_id=org.id, service_id=svc1.id, repository_id=repo.id, role=ServiceRepositoryRole.APPLICATION, is_primary=True, selection_reason="primary application repo")
    so = ServiceOwnership(organization_id=org.id, service_id=svc1.id, team_id=team.id, ownership_type=OwnershipType.PRIMARY_OWNER)
    dep = ServiceDependency(organization_id=org.id, service_id=svc1.id, depends_on_service_id=svc2.id, dependency_type=ServiceDependencyType.SYNCHRONOUS, criticality=ServiceCriticality.HARD)
    db_session.add_all([sr, so, dep])
    db_session.commit()

    # 2. Trigger Sync via API
    sync_resp = client.post(
        "/graph/sync-catalog",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert sync_resp.status_code == 200
    stats = sync_resp.json()["stats"]
    assert stats["nodes_created"] >= 4
    assert stats["edges_created"] >= 3

    # Verify nodes have originating entity_id
    svc_node = db_session.query(GraphNode).filter(GraphNode.identifier == f"service:{svc1.id}").first()
    assert svc_node is not None
    assert svc_node.entity_id == svc1.id
    assert svc_node.tier == "critical"

    # 3. Manually edit an edge to have custom metadata & MANUAL_CORRECTION
    edge = db_session.query(GraphEdge).filter(
        GraphEdge.source_node_id == svc_node.id,
        GraphEdge.edge_type == GraphEdgeType.CALLS,
    ).first()
    assert edge is not None
    edge.source = GraphEdgeSource.MANUAL_CORRECTION
    edge.metadata_json = {"human_verified": True, "notes": "Protected human edge"}
    db_session.commit()

    # 4. Re-run sync and verify manual edge remains preserved
    sync_resp2 = client.post(
        "/graph/sync-catalog",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert sync_resp2.status_code == 200

    db_session.refresh(edge)
    assert edge.source == GraphEdgeSource.MANUAL_CORRECTION
    assert edge.metadata_json.get("human_verified") is True


# ============================================================================
# 3. SECURE TRACE INGESTION & CONFIDENCE SATURATION
# ============================================================================

def test_trace_ingestion_security_and_confidence_boost(client, setup_org_and_users, db_session: Session):
    """Verify trace ingestion redacts sensitive credentials, updates call graph, and boosts confidence."""
    raw_secret = setup_org_and_users["raw_secret"]
    org = setup_org_and_users["org"]

    trace_payload = {
        "spans": [
            {
                "trace_id": "trace-101",
                "span_id": "span-1",
                "service_name": "frontend-service",
                "peer_service": "checkout-service",
                "http_method": "POST",
                "http_url": "https://api.acme.com/api/v1/checkout",
                "http_status_code": 200,
                "duration_ms": 120.5,
                "is_error": False,
                "attributes": {
                    "authorization": "Bearer super-secret-user-token-12345",
                    "cookie": "session_id=abcdef123456",
                    "user_agent": "Mozilla/5.0",
                },
            }
        ]
    }

    # 1. Ingest via Webhook Bearer Token Auth
    ingest_resp = client.post(
        "/graph/traces/ingest",
        json=trace_payload,
        headers={"Authorization": f"Bearer {raw_secret}"},
    )
    assert ingest_resp.status_code == 200
    data = ingest_resp.json()
    assert data["spans_processed"] == 1
    assert data["edges_created"] == 1

    # Verify edge created with initial confidence = 0.5 and redacted attributes
    edge = db_session.query(GraphEdge).filter(
        GraphEdge.organization_id == org.id,
        GraphEdge.edge_type == GraphEdgeType.CALLS,
    ).first()
    assert edge is not None
    assert edge.confidence == 0.5
    assert edge.source == GraphEdgeSource.OPENTELEMETRY_TRACE
    meta = edge.metadata_json
    assert meta["sample_count"] == 1
    assert meta["attributes"]["authorization"] == "[REDACTED]"
    assert meta["attributes"]["cookie"] == "[REDACTED]"

    # 2. Ingest second span to test confidence boost formula
    client.post(
        "/graph/traces/ingest",
        json=trace_payload,
        headers={"Authorization": f"Bearer {raw_secret}"},
    )
    db_session.refresh(edge)
    assert edge.confidence > 0.5  # Boosted: 0.5 + 0.05*(1-0.5) = 0.525
    assert edge.metadata_json["sample_count"] == 2

    # 3. Test Edge Temporal Decay
    # Artificially set updated_at to 14 days ago
    edge.updated_at = datetime.now(timezone.utc) - timedelta(days=14)
    db_session.commit()

    decayed_count = apply_edge_decay(db_session, org.id, days_threshold=7)
    assert decayed_count == 1
    db_session.refresh(edge)
    assert edge.confidence < 0.525


# ============================================================================
# 4. BLAST RADIUS ACCEPTANCE TEST: Frontend -> Checkout -> Payment -> PaymentDB
# ============================================================================

def test_blast_radius_multi_hop_traversal_acceptance(client, setup_org_and_users, db_session: Session):
    """
    Acceptance Test Scenario:
    Frontend -> Checkout -> Payment -> PaymentDB (and unrelated Inventory).
    When Payment fails:
    - Payment is directly affected.
    - Checkout is downstream impact.
    - Frontend is customer entrypoint impact.
    - PaymentDB is upstream dependency.
    - Inventory is unaffected.
    """
    org = setup_org_and_users["org"]
    operator_token = setup_org_and_users["operator_token"]
    viewer_token = setup_org_and_users["viewer_token"]

    # 1. Setup Services
    frontend_svc = Service(organization_id=org.id, name="frontend-app", slug="frontend", tier="critical")
    checkout_svc = Service(organization_id=org.id, name="checkout-service", slug="checkout", tier="high")
    payment_svc = Service(organization_id=org.id, name="payment-service", slug="payment", tier="critical")
    inventory_svc = Service(organization_id=org.id, name="inventory-service", slug="inventory", tier="medium")
    db_session.add_all([frontend_svc, checkout_svc, payment_svc, inventory_svc])
    db_session.flush()

    # Repositories
    repo_payment = Repository(organization_id=org.id, name="payment-repo", full_name="acme/payment-repo", github_url="https://github.com/acme/payment")
    repo_checkout = Repository(organization_id=org.id, name="checkout-repo", full_name="acme/checkout-repo", github_url="https://github.com/acme/checkout")
    payment_db_svc = Service(organization_id=org.id, name="payment-database", slug="payment-db", tier="critical")
    db_session.add_all([repo_payment, repo_checkout, payment_db_svc])
    db_session.flush()

    db_session.add(ServiceRepository(organization_id=org.id, service_id=payment_svc.id, repository_id=repo_payment.id, role=ServiceRepositoryRole.APPLICATION, is_primary=True, selection_reason="payment app repo"))
    db_session.add(ServiceRepository(organization_id=org.id, service_id=checkout_svc.id, repository_id=repo_checkout.id, role=ServiceRepositoryRole.APPLICATION, is_primary=True, selection_reason="checkout app repo"))

    # Dependencies: Frontend -> Checkout -> Payment -> PaymentDB
    dep1 = ServiceDependency(organization_id=org.id, service_id=frontend_svc.id, depends_on_service_id=checkout_svc.id, dependency_type=ServiceDependencyType.SYNCHRONOUS, criticality=ServiceCriticality.HARD)
    dep2 = ServiceDependency(organization_id=org.id, service_id=checkout_svc.id, depends_on_service_id=payment_svc.id, dependency_type=ServiceDependencyType.SYNCHRONOUS, criticality=ServiceCriticality.HARD)
    dep3 = ServiceDependency(organization_id=org.id, service_id=payment_svc.id, depends_on_service_id=payment_db_svc.id, dependency_type=ServiceDependencyType.DATABASE, criticality=ServiceCriticality.HARD)
    db_session.add_all([dep1, dep2, dep3])
    db_session.commit()

    # 2. Sync graph topology
    sync_catalog_to_graph(db_session, org.id)

    # 3. Simulate blast radius on Payment
    sim_resp = client.post(
        "/graph/blast-radius",
        json={"service_id": str(payment_svc.id), "max_depth": 5},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert sim_resp.status_code == 200
    report = sim_resp.json()

    # Assert 1: Payment is directly affected
    assert len(report["direct_services"]) == 1
    assert report["direct_services"][0]["service_id"] == str(payment_svc.id)

    # Assert 2: Checkout and Frontend are in indirect downstream services
    indirect_names = [s["name"] for s in report["indirect_services"]]
    assert "checkout-service" in indirect_names
    assert "frontend-app" in indirect_names

    # Assert 3: PaymentDB is upstream dependency
    assert any("database" in s["name"].lower() or "db" in s["name"].lower() for s in report["indirect_services"])

    # Assert 4: Inventory is strictly UNAFFECTED (not in indirect_services)
    assert "inventory-service" not in indirect_names

    # Assert 5: Repositories - payment is remediation target, checkout is evidence only
    repos = report["affected_repositories"]
    payment_r = next((r for r in repos if r["name"] == "payment-repo"), None)
    checkout_r = next((r for r in repos if r["name"] == "checkout-repo"), None)
    assert payment_r is not None and payment_r["remediation_target"] is True and payment_r["evidence_only"] is False
    assert checkout_r is not None and checkout_r["remediation_target"] is False and checkout_r["evidence_only"] is True

    # Assert 6: Customer traffic impact estimation
    cust_impact = report["customer_impact"]
    assert cust_impact["traffic_percent"] >= 50.0
    assert cust_impact["traffic_confidence"] in ("high", "medium")
    assert len(cust_impact["calculation_basis"]) > 0


# ============================================================================
# 5. OBSERVED VS. INFERRED IMPACT CLASSIFICATION
# ============================================================================

def test_observed_vs_inferred_impact_classification(setup_org_and_users, db_session: Session):
    """Verify that services with active telemetry signals are marked OBSERVED, while others remain INFERRED."""
    org = setup_org_and_users["org"]

    svc_payment = Service(organization_id=org.id, name="payment-service", slug="payment", tier="critical")
    svc_checkout = Service(organization_id=org.id, name="checkout-service", slug="checkout", tier="high")
    svc_frontend = Service(organization_id=org.id, name="frontend-app", slug="frontend", tier="critical")
    db_session.add_all([svc_payment, svc_checkout, svc_frontend])
    db_session.flush()

    db_session.add(ServiceDependency(organization_id=org.id, service_id=svc_frontend.id, depends_on_service_id=svc_checkout.id, dependency_type=ServiceDependencyType.SYNCHRONOUS, criticality=ServiceCriticality.HARD))
    db_session.add(ServiceDependency(organization_id=org.id, service_id=svc_checkout.id, depends_on_service_id=svc_payment.id, dependency_type=ServiceDependencyType.SYNCHRONOUS, criticality=ServiceCriticality.HARD))
    db_session.commit()

    sync_catalog_to_graph(db_session, org.id)

    # Inject an active telemetry signal on checkout-service (e.g. error rate spike)
    sig = TelemetrySignal(
        organization_id=org.id,
        provider=SignalProvider.PROMETHEUS,
        provider_event_id="prom-alert-checkout-101",
        signal_type=SignalType.ERROR_RATE,
        rule_name="error_rate",
        service_id=svc_checkout.id,
        metric_name="error_rate",
        metric_value=0.15,
        fingerprint="fp-checkout-error",
        correlation_key=f"{org.id}:{svc_checkout.id}:error_rate:general",
        title="High Error Rate on checkout-service",
        status=SignalStatus.INGESTED,
        observed_at=datetime.now(timezone.utc),
    )
    db_session.add(sig)
    db_session.commit()

    # Calculate blast radius for payment failure
    report = calculate_blast_radius(db_session, org.id, root_service=svc_payment)

    # Find checkout and frontend in indirect services
    checkout_impact = next(s for s in report.indirect_services if s["name"] == "checkout-service")
    frontend_impact = next(s for s in report.indirect_services if s["name"] == "frontend-app")

    # Checkout has active telemetry -> OBSERVED
    assert checkout_impact["impact_type"] == "observed"
    assert len(checkout_impact["observed_signals"]) >= 1

    # Frontend has no telemetry -> INFERRED
    assert frontend_impact["impact_type"] == "inferred"
    assert len(frontend_impact["observed_signals"]) == 0

    # Measured mode in customer impact
    assert report.customer_impact["traffic_impact_mode"] == "measured"
    assert report.customer_impact["traffic_confidence"] == "high"


# ============================================================================
# 6. SOFT DEPENDENCY DEGRADED PROPAGATION
# ============================================================================

def test_soft_dependency_degraded_numerical_propagation(setup_org_and_users, db_session: Session):
    """Verify that SOFT dependency failure marks caller as DEGRADED instead of OUTAGE."""
    org = setup_org_and_users["org"]

    svc_checkout = Service(organization_id=org.id, name="checkout-service", slug="checkout", tier="high")
    svc_recs = Service(organization_id=org.id, name="recommendation-service", slug="recs", tier="low")
    db_session.add_all([svc_checkout, svc_recs])
    db_session.flush()

    # Soft dependency: Checkout -> Recommendations
    db_session.add(ServiceDependency(
        organization_id=org.id,
        service_id=svc_checkout.id,
        depends_on_service_id=svc_recs.id,
        dependency_type=ServiceDependencyType.SYNCHRONOUS,
        criticality=ServiceCriticality.SOFT,
    ))
    db_session.commit()

    sync_catalog_to_graph(db_session, org.id)

    report = calculate_blast_radius(db_session, org.id, root_service=svc_recs)

    checkout_impact = next(s for s in report.indirect_services if s["name"] == "checkout-service")
    assert checkout_impact["criticality"] == "soft"
    assert checkout_impact["impact_level"] == "degraded"
    assert report.criticality_summary["soft_dependencies"] >= 1


# ============================================================================
# 7. INCIDENT REPORT VERSIONING & DEBOUNCE
# ============================================================================

def test_incident_blast_radius_versioning_and_debounce(client, setup_org_and_users, db_session: Session):
    """Verify that Incident reports increment version numbers and debounce frequent recalculations."""
    org = setup_org_and_users["org"]
    operator_token = setup_org_and_users["operator_token"]
    viewer_token = setup_org_and_users["viewer_token"]

    svc = Service(organization_id=org.id, name="order-service", slug="order", tier="high")
    db_session.add(svc)
    db_session.flush()

    inc = Incident(
        number=1001,
        title="Order service degradation",
        severity=IncidentSeverity.SEV2,
        organization_id=org.id,
        service_id=svc.id,
        service_name=svc.name,
        status=IncidentStatus.DETECTED,
        source=IncidentSource.AUTO_DETECTION,
    )
    db_session.add(inc)
    db_session.commit()

    # 1. Initial report creation (Version 1)
    rep1 = calculate_blast_radius(db_session, org.id, root_service=svc, incident=inc)
    assert rep1.version == 1
    assert rep1.is_current is True

    # 2. Recalculation without force hits debounce cooldown
    rep_debounced = enqueue_blast_radius_recalculation(db_session, inc.id, force=False)
    assert rep_debounced.version == 1

    # 3. Forced recalculation increments version to 2
    recalc_resp = client.post(
        f"/graph/incidents/{inc.id}/blast-radius/recalculate",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert recalc_resp.status_code == 200
    recalc_data = recalc_resp.json()
    assert recalc_data["version"] == 2
    assert recalc_data["is_current"] is True

    # Check that Version 1 is now is_current=False
    db_session.refresh(rep1)
    assert rep1.is_current is False

    # 4. Viewer can retrieve current blast radius report
    get_resp = client.get(
        f"/graph/incidents/{inc.id}/blast-radius",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["version"] == 2


# ============================================================================
# 8. CROSS-TENANT ISOLATION
# ============================================================================

def test_cross_tenant_graph_isolation(client, setup_org_and_users, db_session: Session):
    """Verify that graph operations strictly isolate tenants and reject cross-tenant edge injection."""
    admin_token = setup_org_and_users["admin_token"]
    org_a = setup_org_and_users["org"]

    # Create Organization B
    org_b = Organization(name="Other Tenant", slug=f"other-{uuid.uuid4().hex[:6]}")
    db_session.add(org_b)
    db_session.flush()

    node_a = GraphNode(organization_id=org_a.id, node_type=GraphNodeType.SERVICE, name="svc-a", identifier="service:a")
    node_b = GraphNode(organization_id=org_b.id, node_type=GraphNodeType.SERVICE, name="svc-b", identifier="service:b")
    db_session.add_all([node_a, node_b])
    db_session.commit()

    # Attempt to create edge from Node A (Org A) to Node B (Org B) using Org A token
    resp = client.post(
        "/graph/edges",
        json={
            "source_node_id": str(node_a.id),
            "target_node_id": str(node_b.id),
            "edge_type": "CALLS",
            "source": "MANUAL_CORRECTION",
            "confidence": 1.0,
            "criticality": "HARD",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    # Must reject with 400 Bad Request
    assert resp.status_code == 400
    assert "must both exist within your organization" in resp.json()["detail"]


# ============================================================================
# 9. REAL TENANT-BOUNDARY TRACE INGESTION TEST
# ============================================================================

def test_real_tenant_boundary_trace_ingestion(client, setup_org_and_users, db_session: Session):
    """Verify that trace ingestion using Org A's token does not bleed into Org B's graph topology."""
    org_a = setup_org_and_users["org"]
    raw_secret_a = setup_org_and_users["raw_secret"]

    # Create Org B with its own webhook endpoint
    org_b = Organization(name="Isolated Org B", slug=f"orgb-{uuid.uuid4().hex[:6]}")
    db_session.add(org_b)
    db_session.flush()

    raw_secret_b = "org-b-secret-98765"
    wh_b = WebhookEndpoint(
        organization_id=org_b.id,
        name="Org B OTel",
        key_id=f"key_b_{uuid.uuid4().hex[:6]}",
        provider="opentelemetry",
        auth_method="bearer",
        encrypted_secret=encrypt_secret(raw_secret_b),
        is_active=True,
    )
    db_session.add(wh_b)
    db_session.commit()

    # Ingest traces for Org A
    client.post(
        "/graph/traces/ingest",
        json={"spans": [{"service_name": "tenant-a-ui", "peer_service": "tenant-a-api", "duration_ms": 50.0}]},
        headers={"Authorization": f"Bearer {raw_secret_a}"},
    )

    # Ingest traces for Org B
    client.post(
        "/graph/traces/ingest",
        json={"spans": [{"service_name": "tenant-b-billing", "peer_service": "tenant-b-db", "duration_ms": 35.0}]},
        headers={"Authorization": f"Bearer {raw_secret_b}"},
    )

    # Assert Org A nodes contains ONLY tenant-a services
    nodes_a = db_session.query(GraphNode).filter(GraphNode.organization_id == org_a.id).all()
    names_a = [n.name for n in nodes_a]
    assert "tenant-a-ui" in names_a
    assert "tenant-a-api" in names_a
    assert "tenant-b-billing" not in names_a
    assert "tenant-b-db" not in names_a

    # Assert Org B nodes contains ONLY tenant-b services
    nodes_b = db_session.query(GraphNode).filter(GraphNode.organization_id == org_b.id).all()
    names_b = [n.name for n in nodes_b]
    assert "tenant-b-billing" in names_b
    assert "tenant-b-db" in names_b
    assert "tenant-a-ui" not in names_b


# ============================================================================
# 10. MANIFEST OPENAPI IMPORT TEST
# ============================================================================

def test_manifest_openapi_import(client, setup_org_and_users, db_session: Session):
    """Verify importing OpenAPI specs creates ENDPOINT nodes and IMPLEMENTED_BY edges."""
    org = setup_org_and_users["org"]
    operator_token = setup_org_and_users["operator_token"]

    svc = Service(organization_id=org.id, name="auth-service", slug="auth", tier="critical")
    db_session.add(svc)
    db_session.commit()

    # Initial catalog sync
    sync_catalog_to_graph(db_session, org.id)

    openapi_spec = {
        "paths": {
            "/api/v1/login": {"post": {"summary": "Login"}},
            "/api/v1/logout": {"post": {"summary": "Logout"}},
            "/api/v1/user/me": {"get": {"summary": "Current User"}},
        }
    }

    resp = client.post(
        "/graph/manifests/import",
        json={
            "manifest_type": "openapi",
            "service_id": str(svc.id),
            "content": openapi_spec,
        },
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 200
    res = resp.json()
    assert res["nodes_created"] == 3
    assert res["edges_created"] == 3

    ep_nodes = db_session.query(GraphNode).filter(
        GraphNode.organization_id == org.id,
        GraphNode.node_type == GraphNodeType.ENDPOINT,
    ).all()
    assert len(ep_nodes) == 3
    ep_names = [ep.name for ep in ep_nodes]
    assert "POST /api/v1/login" in ep_names
    assert "GET /api/v1/user/me" in ep_names
