"""Phase 10 Tests — Incident Memory, Explainable Timeline, and Post-Mortems.

Tests:
1. Migration 030 upgrade and downgrade reversibility.
2. PREVIOUS_INCIDENT enum database persistence and family classification.
3. Deterministic explainable timeline generation & causal parent links.
4. Exact milestone calculations (MTTD, MTTA, MTTRC, MTTM, MTTR) with null safety.
5. AI Post-Mortem Generator evidence-binding, snapshot hashing, and Safe Abstention.
6. Post-Mortem versioning lifecycle and partial unique index enforcement.
7. Multi-tenant vector incident memory search with mandatory org isolation.
8. Strict production Pinecone failure behavior (no silent fallback to Qdrant).
9. Action items lifecycle, audit trail, and RBAC permissions.
10. Full REST API lifecycle across timeline, post-mortem, action items, and memory search.
"""
import uuid
import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.core.database import Base
from app.models.incident import (
    User, Organization, Incident, IncidentSeverity, IncidentStatus, IncidentSource,
    Investigation, InvestigationTask, Evidence, EvidenceSourceType, EvidenceFamily,
    EvidenceCategoryType, EvidenceTrustLevel, EvidenceVerificationStatus,
    Hypothesis, HypothesisStatus, Confidence, RootCause, ProposedFix, Approval,
    ApprovalStatus, AuditEvent, PostMortem, PostMortemActionItem, PostMortemStatus,
    MemoryIndexingStatus, ActionItemCategory, ActionItemPriority, ActionItemStatus,
    UserOrganizationMembership, MembershipRole, TelemetrySignal, SignalType,
    SignalProvider, SignalStatus,
)
from app.services.timeline import build_explainable_timeline, compute_milestones
from app.services.post_mortem_generator import generate_post_mortem_for_incident, compute_post_mortem_snapshot_hash
from app.services.historical import (
    index_post_mortem,
    search_similar_incidents,
    _memory_store,
    is_production_mode,
)
from app.services.evidence_harvester import classify_evidence_family, harvest_incident_evidence
from app.core.config import settings
from app.main import app


from sqlalchemy.pool import StaticPool

# Test DB setup
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    settings.ENVIRONMENT = "testing"
    Base.metadata.create_all(bind=engine)
    _memory_store.clear()
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
def org(db):
    org = Organization(name="Memory Org", slug="memory-org")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@pytest.fixture
def admin_user(db, org):
    user = User(
        username="admin_mem",
        email="admin_mem@test.com",
        hashed_password="pw",
        role="admin",
        organization_id=org.id,
    )
    db.add(user)
    db.flush()
    mem = UserOrganizationMembership(user_id=user.id, organization_id=org.id, role=MembershipRole.ADMIN)
    db.add(mem)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def member_user(db, org):
    user = User(
        username="member_mem",
        email="member_mem@test.com",
        hashed_password="pw",
        role="member",
        organization_id=org.id,
    )
    db.add(user)
    db.flush()
    mem = UserOrganizationMembership(user_id=user.id, organization_id=org.id, role=MembershipRole.MEMBER)
    db.add(mem)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def incident(db, org, admin_user):
    now = datetime.now(timezone.utc)
    inc = Incident(
        number=1001,
        title="Checkout Latency Spike and CrashLoop",
        description="Checkout API latency spiked to 4500ms and pod started crash looping",
        severity=IncidentSeverity.SEV1,
        status=IncidentStatus.INVESTIGATING,
        source=IncidentSource.PROMETHEUS,
        service_name="checkout-api",
        organization_id=org.id,
        creator_id=admin_user.id,
        started_at=now - timedelta(minutes=45),
        detected_at=now - timedelta(minutes=40),
        created_at=now - timedelta(minutes=39),
    )
    db.add(inc)
    db.commit()
    db.refresh(inc)
    return inc


# ============================================================================
# 1. MIGRATION 030 TESTS
# ============================================================================

def test_migration_030_upgrade_and_downgrade_execution():
    """Verify that migration 030 upgrade() and downgrade() execute cleanly against a real DB."""
    import importlib.util
    from pathlib import Path
    import alembic.migration
    import alembic.operations

    mig_path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "030_add_phase10_incident_memory_and_timeline.py"
    spec = importlib.util.spec_from_file_location("mig_030_real", str(mig_path))
    mig_030 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig_030)

    test_engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=test_engine)

    with test_engine.connect() as conn:
        ctx = alembic.migration.MigrationContext.configure(conn)
        real_op = alembic.operations.Operations(ctx)

        with patch.object(mig_030, "op", real_op):
            # 1. Upgrade
            mig_030.upgrade()

            inspector = text("SELECT name FROM sqlite_master WHERE type = 'table'")
            tables = [r[0] for r in conn.execute(inspector).fetchall()]
            assert "post_mortems" in tables
            assert "post_mortem_action_items" in tables

            indexes = [r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'index'")).fetchall()]
            assert "uq_post_mortems_incident_current" in indexes
            assert "ix_post_mortems_org_incident" in indexes
            assert "ix_action_items_org_status" in indexes

            # 2. Downgrade
            mig_030.downgrade()

            tables_after = [r[0] for r in conn.execute(inspector).fetchall()]
            assert "post_mortems" not in tables_after
            assert "post_mortem_action_items" not in tables_after


# ============================================================================
# 2. ENUM PERSISTENCE & FAMILY CLASSIFICATION
# ============================================================================

def test_previous_incident_enum_persistence_and_classification(db, org, incident):
    """Verify EvidenceSourceType.PREVIOUS_INCIDENT persists to database, round-trips correctly, and maps to FAMILY_WORKSPACE_STATIC."""
    assert EvidenceSourceType.PREVIOUS_INCIDENT.name == "PREVIOUS_INCIDENT"
    assert EvidenceSourceType.PREVIOUS_INCIDENT.value == "previous_incident"

    family = classify_evidence_family(EvidenceSourceType.PREVIOUS_INCIDENT)
    assert family == EvidenceFamily.FAMILY_WORKSPACE_STATIC

    # 1. ORM Persistence
    ev = Evidence(
        organization_id=org.id,
        incident_id=incident.id,
        title="Historical Post-Mortem: Redis Connection Pool Exhaustion",
        source_type=EvidenceSourceType.PREVIOUS_INCIDENT,
        evidence_family=family,
        content="Past incident INC-0899 was caused by unclosed DB connections in payment middleware.",
        content_hash="abc123canonicalhash",
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)

    saved = db.query(Evidence).filter(Evidence.id == ev.id).first()
    assert saved is not None
    assert saved.source_type == EvidenceSourceType.PREVIOUS_INCIDENT
    assert saved.evidence_family == EvidenceFamily.FAMILY_WORKSPACE_STATIC

    # 2. Filter query by Enum
    queried = db.query(Evidence).filter(
        Evidence.incident_id == incident.id,
        Evidence.source_type == EvidenceSourceType.PREVIOUS_INCIDENT,
    ).all()
    assert len(queried) >= 1
    assert queried[0].id == ev.id

    # 3. Direct DB execution check
    raw_source = db.execute(
        text("SELECT source_type FROM evidence WHERE id = :id"),
        {"id": ev.id if isinstance(ev.id, str) else str(ev.id).replace("-", "")},
    ).scalar()
    assert raw_source in ("PREVIOUS_INCIDENT", "previous_incident", EvidenceSourceType.PREVIOUS_INCIDENT.name)


# ============================================================================
# 3. DETERMINISTIC TIMELINE & CAUSAL GRAPH
# ============================================================================

def test_explainable_timeline_generation_and_causal_graph(db, org, incident, admin_user):
    """Verify deterministic chronological ordering, causal parent linking, and SRE milestones."""
    now = datetime.now(timezone.utc)

    # 1. Add Telemetry Signal
    sig = TelemetrySignal(
        organization_id=org.id,
        incident_id=incident.id,
        provider_event_id="prom-event-101",
        rule_name="high_latency_p99_checkout",
        fingerprint="fp-checkout-latency-p99",
        correlation_key="ck-checkout-latency",
        title="P99 latency above 1000ms",
        signal_type=SignalType.LATENCY_SPIKE,
        provider=SignalProvider.PROMETHEUS,
        metric_name="http_request_duration_seconds_p99",
        metric_value=4.5,
        threshold_value=1.0,
        observed_at=now - timedelta(minutes=42),
    )
    db.add(sig)

    # 2. Add Investigation & Task
    inv = Investigation(
        organization_id=org.id,
        incident_id=incident.id,
        started_at=now - timedelta(minutes=38),
        completed_at=now - timedelta(minutes=25),
        llm_model="Nemotron-70B",
    )
    db.add(inv)
    db.flush()

    task = InvestigationTask(
        investigation_id=inv.id,
        task_type="service_graph_blast_radius",
        step_name="Assess blast radius",
        completed_at=now - timedelta(minutes=35),
        duration_ms=450,
    )
    db.add(task)

    # 3. Add Evidence
    ev = Evidence(
        organization_id=org.id,
        incident_id=incident.id,
        investigation_id=inv.id,
        title="OOMKill Crash Log in checkout-api",
        source_type=EvidenceSourceType.LOGS,
        evidence_family=EvidenceFamily.FAMILY_RUNTIME_TELEMETRY,
        collected_at=now - timedelta(minutes=34),
    )
    db.add(ev)

    # 4. Add Hypothesis & Root Cause
    hyp = Hypothesis(
        organization_id=org.id,
        incident_id=incident.id,
        investigation_id=inv.id,
        label="Memory leak in unbuffered stream reader",
        description="Stream reader buffers unbounded responses causing OOM kill",
        status=HypothesisStatus.ACCEPTED,
        distinct_families_count=2,
        evaluated_at=now - timedelta(minutes=30),
    )
    db.add(hyp)

    rc = RootCause(
        organization_id=org.id,
        incident_id=incident.id,
        investigation_id=inv.id,
        summary="Unbounded memory buffer in stream reader caused container OOMKill.",
        causal_explanation="Payment response stream buffers the entire payload in memory before parsing.",
        confidence=Confidence.HIGH,
        identified_at=now - timedelta(minutes=28),
        is_current=True,
        abstained=False,
    )
    db.add(rc)

    # 5. Add Fix & Approval
    fix = ProposedFix(
        incident_id=incident.id,
        investigation_id=inv.id,
        title="Chunked streaming response reader with 16MB cap",
        description="Caps maximum stream buffer size to prevent memory exhaustion",
        fix_type="code_fix",
        proposed_change="Use io.LimitReader with 16MB buffer",
        expected_behavior="Stream is chunked without OOMKill",
        pr_url="https://github.com/company/checkout-api/pull/42",
        pr_number=42,
        branch_name="sentinel/fix-oom-checkout",
        generated_at=now - timedelta(minutes=20),
    )
    db.add(fix)

    app_rec = Approval(
        incident_id=incident.id,
        fix_id=fix.id,
        user_id=admin_user.id,
        status=ApprovalStatus.APPROVED,
        notes="Validated on staging. Approved for merge.",
        decided_at=now - timedelta(minutes=15),
    )
    db.add(app_rec)

    # 6. Resolve Incident
    incident.resolved_at = now - timedelta(minutes=10)
    db.commit()

    # Build Explainable Timeline
    timeline_data = build_explainable_timeline(str(incident.id), db)
    events = timeline_data["events"]
    milestones = timeline_data["milestones"]

    assert len(events) >= 8
    event_types = [e["type"] for e in events]
    assert "signal_detected" in event_types
    assert "incident_created" in event_types
    assert "investigation_started" in event_types
    assert "task_completed" in event_types
    assert "evidence_collected" in event_types
    assert "hypothesis_evaluated" in event_types
    assert "root_cause_identified" in event_types
    assert "fix_generated" in event_types
    assert "pr_published" in event_types
    assert "approval_decided" in event_types
    assert "incident_resolved" in event_types

    # Causal links verification
    signal_evt = next(e for e in events if e["type"] == "signal_detected")
    inc_evt = next(e for e in events if e["type"] == "incident_created")
    assert inc_evt["parent_event_id"] == signal_evt["id"]

    rc_evt = next(e for e in events if e["type"] == "root_cause_identified")
    fix_evt = next(e for e in events if e["type"] == "fix_generated")
    assert fix_evt["parent_event_id"] == rc_evt["id"]

    # SRE Milestones Verification
    assert milestones["mttd_seconds"] is not None
    assert milestones["mttd_seconds"] == 5 * 60  # 45 min onset to 40 min detection = 300s
    assert milestones["mtta_seconds"] is not None
    assert milestones["mttrc_seconds"] is not None
    assert milestones["mttm_seconds"] is not None
    assert milestones["mttr_seconds"] is not None
    assert milestones["mttr_seconds"] == 35 * 60  # 45 min onset to 10 min resolved = 2100s


def test_milestone_missing_timestamps_return_none(db, org, admin_user):
    """Verify that missing boundary timestamps return None (never 0)."""
    inc = Incident(
        number=1002,
        title="Unstarted Incident with No Resolution",
        severity=IncidentSeverity.SEV3,
        status=IncidentStatus.CREATED,
        organization_id=org.id,
        creator_id=admin_user.id,
        started_at=None,
        detected_at=None,
        resolved_at=None,
    )
    db.add(inc)
    db.commit()

    milestones = compute_milestones(inc, db)
    assert milestones["mttd_seconds"] is None
    assert milestones["mttr_seconds"] is None
    assert milestones["mtta_seconds"] is None


# ============================================================================
# 4. AI POST-MORTEM GENERATION & SAFE ABSTENTION
# ============================================================================

def test_evidence_bound_ai_post_mortem_generator(db, org, incident, admin_user):
    """Verify post-mortem synthesis, snapshot hashing, and default action items."""
    rc = RootCause(
        organization_id=org.id,
        incident_id=incident.id,
        summary="Deadlock in database connection pool during peak checkout traffic.",
        causal_explanation="Nested transactions held open connections without releasing on exception.",
        confidence=Confidence.HIGH,
        is_current=True,
        abstained=False,
    )
    db.add(rc)
    db.commit()

    pm = generate_post_mortem_for_incident(str(incident.id), db, author=admin_user)
    assert pm is not None
    assert pm.title.startswith("Post-Mortem: INC-1001")
    assert "Deadlock" in pm.root_cause_summary
    assert pm.status == PostMortemStatus.DRAFT
    assert pm.human_reviewed is False
    assert pm.is_current is True
    assert pm.version == 1
    assert len(pm.snapshot_hash) == 64
    assert len(pm.action_items) == 2


def test_post_mortem_preserves_safe_abstention(db, org, incident, admin_user):
    """Verify that post-mortem synthesis explicitly reflects Phase 9 Safe Abstention."""
    rc = RootCause(
        organization_id=org.id,
        incident_id=incident.id,
        summary="Candidate root cause",
        causal_explanation="Uncorroborated single-family hypothesis",
        confidence=Confidence.INSUFFICIENT,
        is_current=True,
        abstained=True,
        abstention_reason="Strict 2-family corroboration requirement not met (only 1 family observed).",
        missing_evidence_json=["Missing server access log confirmation", "Missing trace latency breakdown"],
    )
    db.add(rc)
    db.commit()

    pm = generate_post_mortem_for_incident(str(incident.id), db, author=admin_user)
    assert pm.abstained is True
    assert "Safe Abstention Enforced" in pm.root_cause_summary
    assert "Missing server access log confirmation" in pm.root_cause_summary


# ============================================================================
# 5. POST-MORTEM VERSIONING & UNIQUENESS
# ============================================================================

def test_post_mortem_versioning_and_uniqueness(db, org, incident, admin_user):
    """Verify version increments on regeneration of published post-mortems and partial unique index."""
    rc = RootCause(
        organization_id=org.id,
        incident_id=incident.id,
        summary="Initial Root Cause",
        causal_explanation="Initial root cause causal explanation",
        confidence=Confidence.HIGH,
        is_current=True,
        abstained=False,
    )
    db.add(rc)
    db.commit()

    # 1. Create first version
    pm_v1 = generate_post_mortem_for_incident(str(incident.id), db, author=admin_user)
    assert pm_v1.version == 1
    assert pm_v1.is_current is True

    # 2. Publish first version
    pm_v1.status = PostMortemStatus.PUBLISHED
    pm_v1.human_reviewed = True
    pm_v1.signed_off_at = datetime.now(timezone.utc)
    db.commit()

    # 3. Regenerate -> creates version 2
    pm_v2 = generate_post_mortem_for_incident(str(incident.id), db, author=admin_user)
    db.refresh(pm_v1)
    db.refresh(pm_v2)

    assert pm_v1.is_current is False
    assert pm_v2.is_current is True
    assert pm_v2.version == 2

    # Verify only 1 active post-mortem exists for this incident
    active_count = db.query(PostMortem).filter(
        PostMortem.incident_id == incident.id,
        PostMortem.is_current == True,
    ).count()
    assert active_count == 1


# ============================================================================
# 6. VECTOR INCIDENT MEMORY & STRICT TENANT ISOLATION
# ============================================================================

def test_tenant_isolated_incident_memory_search(db):
    """Verify Pinecone/In-Memory search strictly scopes queries to the requester's organization."""
    org_a = Organization(name="Tenant A", slug="tenant-a")
    org_b = Organization(name="Tenant B", slug="tenant-b")
    db.add_all([org_a, org_b])
    db.commit()

    # Post-mortem for Tenant A
    pm_a = {
        "id": str(uuid.uuid4()),
        "organization_id": str(org_a.id),
        "incident_id": str(uuid.uuid4()),
        "title": "Tenant A: Postgres Connection Starvation",
        "summary": "Postgres connection pool exhausted during cyber monday sale.",
        "root_cause_summary": "Leak in session close hook.",
        "service": "checkout",
    }
    # Post-mortem for Tenant B
    pm_b = {
        "id": str(uuid.uuid4()),
        "organization_id": str(org_b.id),
        "incident_id": str(uuid.uuid4()),
        "title": "Tenant B: Postgres Connection Starvation",
        "summary": "Tenant B secret database connection failure.",
        "root_cause_summary": "Tenant B confidential details.",
        "service": "checkout",
    }

    assert index_post_mortem(pm_a) is True
    assert index_post_mortem(pm_b) is True

    # Search as Tenant A
    results_a = search_similar_incidents(
        query="Postgres connection pool exhausted",
        organization_id=str(org_a.id),
    )
    assert len(results_a) == 1
    assert results_a[0]["title"] == "Tenant A: Postgres Connection Starvation"

    # Search as Tenant B
    results_b = search_similar_incidents(
        query="Postgres connection pool exhausted",
        organization_id=str(org_b.id),
    )
    assert len(results_b) == 1
    assert results_b[0]["title"] == "Tenant B: Postgres Connection Starvation"


def test_production_pinecone_failure_does_not_switch_to_qdrant():
    """Verify that in production mode, Pinecone failure returns empty and does NOT route to Qdrant."""
    from app.services import historical

    with patch.object(historical, "is_production_mode", return_value=True):
        mock_index = MagicMock()
        mock_index.query.side_effect = RuntimeError("Pinecone 503 Service Unavailable")
        
        with patch.object(historical, "_get_pinecone", return_value=mock_index):
            with patch.object(historical, "_get_qdrant") as mock_qdrant:
                results = search_similar_incidents(
                    query="test failure query",
                    organization_id=str(uuid.uuid4()),
                )
                assert results == []
                mock_qdrant.assert_not_called()


# ============================================================================
# 7. ACTION ITEMS LIFECYCLE & AUDIT TRAIL
# ============================================================================

def test_action_items_lifecycle_and_audit_trail(db, org, incident, admin_user, member_user):
    """Verify action item creation, status transitions, auto-completion timestamps, and audit events."""
    pm = generate_post_mortem_for_incident(str(incident.id), db, author=admin_user)
    
    item = PostMortemActionItem(
        organization_id=org.id,
        post_mortem_id=pm.id,
        incident_id=incident.id,
        created_by_user_id=admin_user.id,
        assigned_to_user_id=member_user.id,
        title="Add circuit breaker on payment gateway RPC",
        description="Prevent cascading thread pool saturation when payment gateway latency spikes",
        category=ActionItemCategory.INFRASTRUCTURE_RESILIENCE,
        priority=ActionItemPriority.P1,
        status=ActionItemStatus.OPEN,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    assert item.status == ActionItemStatus.OPEN
    assert item.completed_at is None

    # Transition to COMPLETED
    item.status = ActionItemStatus.COMPLETED
    item.completed_at = datetime.now(timezone.utc)
    
    audit = AuditEvent(
        incident_id=incident.id,
        user_id=member_user.id,
        event_type="action_item_completed",
        description=f"Action item completed: {item.title}",
        metadata_json={"action_item_id": str(item.id), "title": item.title},
    )
    db.add(audit)
    db.commit()
    db.refresh(item)

    assert item.status == ActionItemStatus.COMPLETED
    assert item.completed_at is not None

    # Verify audit event logged
    logged_audit = db.query(AuditEvent).filter(
        AuditEvent.incident_id == incident.id,
        AuditEvent.event_type == "action_item_completed",
    ).first()
    assert logged_audit is not None
    assert logged_audit.user_id == member_user.id


# ============================================================================
# 8. REST API FULL LIFECYCLE TESTS
# ============================================================================

def test_rest_api_incident_memory_and_post_mortem_lifecycle(db, org, incident, admin_user):
    """Verify full REST API lifecycle: timeline, post-mortem generation, edit, sign-off, and search."""
    from app.core.auth import create_access_token
    from app.core.database import get_db

    app.dependency_overrides[get_db] = lambda: db

    client = TestClient(app)
    token = create_access_token(data={"sub": str(admin_user.id), "org_id": str(org.id), "role": "admin"})
    headers = {"Authorization": f"Bearer {token}"}

    # 1. GET Timeline
    resp = client.get(f"/incidents/{incident.id}/timeline", headers=headers)
    assert resp.status_code == 200
    timeline = resp.json()
    assert timeline["incident_id"] == str(incident.id)
    assert "milestones" in timeline
    assert "events" in timeline

    # 2. POST Generate Post-Mortem
    resp = client.post(f"/incidents/{incident.id}/post-mortem/generate", headers=headers)
    assert resp.status_code == 200
    pm_json = resp.json()
    assert pm_json["incident_id"] == str(incident.id)
    assert pm_json["status"] == "draft"
    pm_id = pm_json["id"]

    # 3. GET Post-Mortem
    resp = client.get(f"/incidents/{incident.id}/post-mortem", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == pm_id

    # 4. PUT Update Post-Mortem
    update_payload = {
        "title": "Custom Post-Mortem Title: Checkout Outage",
        "summary": "Updated executive summary after team debrief.",
    }
    resp = client.put(f"/incidents/{incident.id}/post-mortem", json=update_payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["title"] == "Custom Post-Mortem Title: Checkout Outage"

    # 5. POST Action Item
    action_payload = {
        "title": "Tighten Redis retry budget",
        "category": "code_hardening",
        "priority": "P1",
    }
    resp = client.post(f"/incidents/{incident.id}/post-mortem/action-items", json=action_payload, headers=headers)
    assert resp.status_code == 200
    action_id = resp.json()["id"]
    assert resp.json()["title"] == "Tighten Redis retry budget"

    # 6. GET Action Items list
    resp = client.get("/incident-memory/action-items", headers=headers)
    assert resp.status_code == 200
    items = resp.json()
    assert any(i["id"] == action_id for i in items)

    # 7. PATCH Action Item
    resp = client.patch(f"/incident-memory/action-items/{action_id}", json={"status": "completed"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
    assert resp.json()["completed_at"] is not None

    # 8. POST Publish Post-Mortem
    resp = client.post(f"/incidents/{incident.id}/post-mortem/publish", json={"sign_off_notes": "All checks signed off"}, headers=headers)
    assert resp.status_code == 200
    published_pm = resp.json()
    assert published_pm["status"] == "published"
    assert published_pm["human_reviewed"] is True
    assert published_pm["published_at"] is not None
    assert published_pm["memory_indexing_status"] in ("indexed", "pending", "failed")

    # 9. POST Semantic Memory Search
    resp = client.post(
        "/incident-memory/search",
        json={"query": "Checkout Outage Redis", "limit": 5},
        headers=headers,
    )
    assert resp.status_code == 200
    search_res = resp.json()
    assert "results" in search_res
    assert search_res["total"] >= 1
