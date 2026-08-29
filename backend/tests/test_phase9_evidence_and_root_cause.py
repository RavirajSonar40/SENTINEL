"""
Comprehensive Automated Test Suite for Phase 9: Evidence Ledger & Root-Cause Analysis.
"""
import uuid
import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.incident import (
    User,
    Organization,
    UserOrganizationMembership,
    MembershipRole,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    Service,
    Deployment,
    TelemetrySignal,
    Evidence,
    EvidenceSourceType,
    EvidenceCategoryType,
    EvidenceFamily,
    EvidenceTrustLevel,
    EvidenceVerificationStatus,
    Hypothesis,
    HypothesisStatus,
    Confidence,
    RootCause,
)
from app.services.evidence_harvester import (
    compute_canonical_content_hash,
    classify_evidence_family,
    sanitize_and_truncate_content,
    create_evidence_item,
    create_evidence_correction,
    harvest_incident_evidence,
)
from app.services.hypothesis_evaluator import (
    evaluate_tri_factor_fit,
    run_adversarial_disproof,
    transition_hypothesis_status,
    evaluate_incident_hypotheses,
)


from sqlalchemy.pool import StaticPool
import random


@pytest.fixture
def db_session():
    """Create in-memory SQLite DB for Phase 9 testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def org_and_user(db_session):
    """Seed test Organization and Operator User."""
    org = Organization(name="Acme Security Org", slug=f"acme-sec-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)

    user = User(
        username=f"operator_{uuid.uuid4().hex[:6]}",
        email=f"op_{uuid.uuid4().hex[:6]}@acme.com",
        hashed_password="pw",
        role="operator",
        organization_id=org.id,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    membership = UserOrganizationMembership(
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.OPERATOR,
    )
    db_session.add(membership)
    db_session.commit()

    service = Service(organization_id=org.id, name="payment-gateway", tier="tier-1")
    db_session.add(service)
    db_session.commit()
    db_session.refresh(service)

    incident = Incident(
        organization_id=org.id,
        number=random.randint(100000, 99999999),
        title="Payment Service 500 Spike",
        severity=IncidentSeverity.SEV1,
        status=IncidentStatus.INVESTIGATING,
        service_id=service.id,
        service_name="payment-gateway",
        creator_id=user.id,
        detected_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )
    db_session.add(incident)
    db_session.commit()
    db_session.refresh(incident)

    return org, user, service, incident


# ============================================================================
# 1. IMMUTABILITY & ORM LAYER TESTS
# ============================================================================

def test_evidence_append_only_immutability(db_session, org_and_user):
    """Test that modifying immutable evidence fields raises ValueError at ORM layer."""
    org, user, _, incident = org_and_user

    ev = create_evidence_item(
        db=db_session,
        organization_id=org.id,
        incident_id=incident.id,
        title="Initial Log Evidence",
        source_type=EvidenceSourceType.LOGS,
        category_type=EvidenceCategoryType.FACT,
        content="NullPointerException at PaymentProcessor.java:142",
    )
    assert ev is not None
    assert ev.version == 1

    # Attempt direct mutation of content
    with pytest.raises(ValueError, match="Evidence record is immutable"):
        ev.content = "Mutated unauthorized content!"
        db_session.commit()

    db_session.rollback()

    # Attempt direct mutation of category_type
    with pytest.raises(ValueError, match="Evidence record is immutable"):
        ev.category_type = EvidenceCategoryType.CONCLUSION
        db_session.commit()

    db_session.rollback()


def test_evidence_deletion_guard(db_session, org_and_user):
    """Test that deleting evidence without admin override raises ValueError."""
    org, _, _, incident = org_and_user

    ev = create_evidence_item(
        db=db_session,
        organization_id=org.id,
        incident_id=incident.id,
        title="Audit Evidence",
        source_type=EvidenceSourceType.TELEMETRY,
        category_type=EvidenceCategoryType.FACT,
        content="Metric spike 99.2%",
    )

    with pytest.raises(ValueError, match="Evidence records are append-only and cannot be deleted"):
        db_session.delete(ev)
        db_session.commit()

    db_session.rollback()


# ============================================================================
# 2. CANONICAL HASHING & SANITIZATION TESTS
# ============================================================================

def test_canonical_hash_determinism():
    """Test deterministic SHA-256 generation independent of dictionary key ordering."""
    payload_a = {"title": "Deploy v2.1", "source_type": "deployments", "commit_sha": "abc1234"}
    payload_b = {"commit_sha": "abc1234", "title": "Deploy v2.1", "source_type": "deployments"}

    hash_a = compute_canonical_content_hash(payload_a)
    hash_b = compute_canonical_content_hash(payload_b)
    assert hash_a == hash_b
    assert len(hash_a) == 64


def test_secret_redaction_and_truncation():
    """Test that secrets are redacted and limits are enforced."""
    raw_log = "Error connecting to db: postgresql://admin:supersecretpassword123@db.prod.com:5432/main\n" + "\n".join([f"line {i}" for i in range(300)])
    clean_text, size_bytes, is_redacted = sanitize_and_truncate_content(raw_log, EvidenceSourceType.LOGS)

    assert "[REDACTED]" in clean_text or "password" not in clean_text
    assert is_redacted is True
    assert "Truncated" in clean_text


# ============================================================================
# 3. EVIDENCE FAMILIES & CORROBORATION TESTS
# ============================================================================

def test_evidence_family_classification():
    """Test mapping of source types to orthogonal families."""
    assert classify_evidence_family(EvidenceSourceType.DEPLOYMENTS) == EvidenceFamily.FAMILY_CODE_CHANGE
    assert classify_evidence_family(EvidenceSourceType.CHANGES) == EvidenceFamily.FAMILY_CODE_CHANGE
    assert classify_evidence_family(EvidenceSourceType.TELEMETRY) == EvidenceFamily.FAMILY_RUNTIME_TELEMETRY
    assert classify_evidence_family(EvidenceSourceType.LOGS) == EvidenceFamily.FAMILY_RUNTIME_TELEMETRY
    assert classify_evidence_family(EvidenceSourceType.GRAPH) == EvidenceFamily.FAMILY_TOPOLOGY_GRAPH
    assert classify_evidence_family(EvidenceSourceType.WORKSPACE) == EvidenceFamily.FAMILY_WORKSPACE_STATIC

    # Manual evidence unverified vs verified
    assert classify_evidence_family(EvidenceSourceType.MANUAL, verification_status=EvidenceVerificationStatus.PENDING_REVIEW) is None
    assert classify_evidence_family(EvidenceSourceType.MANUAL, verification_status=EvidenceVerificationStatus.VERIFIED) == EvidenceFamily.FAMILY_VERIFIED_HUMAN


def test_corroboration_acceptance_vs_abstention(db_session, org_and_user):
    """Test that >= 2 distinct families promotes to ACCEPTED, while < 2 leads to safe abstention."""
    org, user, service, incident = org_and_user

    # Case A: Only 1 family (TELEMETRY)
    ev1 = create_evidence_item(
        db=db_session,
        organization_id=org.id,
        incident_id=incident.id,
        title="Latency Spike Alert",
        source_type=EvidenceSourceType.TELEMETRY,
        category_type=EvidenceCategoryType.FACT,
        content="p99 latency > 4000ms",
        observed_at=incident.detected_at,
    )

    res_a = evaluate_incident_hypotheses(db_session, org.id, incident.id)
    assert res_a["abstained"] is True
    assert "Root Cause Inconclusive" in res_a["root_cause"].summary
    assert len(res_a["missing_evidence"]) > 0

    # Case B: Add second distinct family (DEPLOYMENTS - CODE CHANGE)
    ev2 = create_evidence_item(
        db=db_session,
        organization_id=org.id,
        incident_id=incident.id,
        title="Deploy v1.4.2",
        source_type=EvidenceSourceType.DEPLOYMENTS,
        category_type=EvidenceCategoryType.FACT,
        content="Deploy v1.4.2 to payment-gateway completed 5m before incident",
        observed_at=incident.detected_at - timedelta(minutes=5),
    )

    res_b = evaluate_incident_hypotheses(db_session, org.id, incident.id)
    assert res_b["abstained"] is False
    assert res_b["accepted_hypothesis"] is not None
    assert res_b["accepted_hypothesis"].status == HypothesisStatus.ACCEPTED
    assert res_b["accepted_hypothesis"].distinct_families_count >= 2
    assert res_b["root_cause"].is_current is True
    assert res_b["root_cause"].evaluation_version > 1


# ============================================================================
# 4. ADVERSARIAL DISPROOF TESTS
# ============================================================================

def test_adversarial_disproof_falsification(db_session, org_and_user):
    """Test that anomaly telemetry preceding deployment disproves deployment candidate."""
    org, _, _, incident = org_and_user

    incident_time = datetime.now(timezone.utc)

    # Anomaly fired at t-45m
    ev_telemetry = create_evidence_item(
        db=db_session,
        organization_id=org.id,
        incident_id=incident.id,
        title="Pre-existing 500 error spike",
        source_type=EvidenceSourceType.TELEMETRY,
        category_type=EvidenceCategoryType.FACT,
        content="High error count active 45m ago",
        observed_at=incident_time - timedelta(minutes=45),
    )

    # Deployment at t-10m
    ev_deploy = create_evidence_item(
        db=db_session,
        organization_id=org.id,
        incident_id=incident.id,
        title="Recent Deploy",
        source_type=EvidenceSourceType.DEPLOYMENTS,
        category_type=EvidenceCategoryType.FACT,
        content="Deploy v3.0",
        observed_at=incident_time - timedelta(minutes=10),
    )

    hyp = Hypothesis(
        organization_id=org.id,
        incident_id=incident.id,
        label="H_Deploy",
        description="Recent deployment caused the error spike.",
        status=HypothesisStatus.PROPOSED,
    )
    db_session.add(hyp)
    db_session.commit()

    is_disproven, reason = run_adversarial_disproof(hyp, [ev_telemetry, ev_deploy], incident_time)
    assert is_disproven is True
    assert "Disproved" in reason


# ============================================================================
# 5. HUMAN TRIAGE & OVERRIDE PRESERVATION TESTS
# ============================================================================

def test_human_triage_preservation(db_session, org_and_user):
    """Test that automated recalculation never overwrites human triage decisions."""
    org, user, _, incident = org_and_user

    hyp = Hypothesis(
        organization_id=org.id,
        incident_id=incident.id,
        label="H_Human",
        description="Database connection exhaustion in Redis cache.",
        status=HypothesisStatus.SUPPORTED,
    )
    db_session.add(hyp)
    db_session.commit()

    # Human triages this hypothesis as ACCEPTED
    transition_hypothesis_status(
        db=db_session,
        hypothesis=hyp,
        new_status=HypothesisStatus.ACCEPTED,
        reason="Manual DBA confirmation of pool exhaustion",
        user_id=user.id,
        is_human=True,
    )
    assert hyp.human_triaged is True

    # Run automated evaluation
    evaluate_incident_hypotheses(db_session, org.id, incident.id)

    db_session.refresh(hyp)
    assert hyp.status == HypothesisStatus.ACCEPTED
    assert hyp.human_triaged is True
    assert "DBA confirmation" in hyp.human_triage_notes


# ============================================================================
# 6. FAIL-FAST MIGRATION 029 ORPHAN ABORT TEST
# ============================================================================

def test_migration_029_fails_fast_on_orphaned_evidence():
    """Verify that migration 029 aborts with RuntimeError if orphaned evidence exists."""
    import importlib.util
    from pathlib import Path
    from unittest.mock import MagicMock, patch

    mig_path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "029_add_phase9_evidence_and_root_cause.py"
    spec = importlib.util.spec_from_file_location("mig_029", str(mig_path))
    mig_029 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig_029)
    upgrade = mig_029.upgrade

    mock_conn = MagicMock()
    mock_conn.dialect.name = "postgresql"

    # Simulate finding 2 orphaned evidence rows
    mock_conn.execute.return_value.fetchall.return_value = [
        (uuid.uuid4(),),
        (uuid.uuid4(),),
    ]

    mock_inspector = MagicMock()
    mock_inspector.get_table_names.return_value = ["evidence"]
    mock_inspector.get_columns.return_value = [{"name": "id"}]

    with patch.object(mig_029, "op") as mock_op, \
         patch("sqlalchemy.inspect", return_value=mock_inspector):
        mock_op.get_bind.return_value = mock_conn
        with pytest.raises(RuntimeError, match="Migration 029 aborted.*orphaned evidence"):
            upgrade()


# ============================================================================
# 7. REST API ENDPOINT TESTS
# ============================================================================

def test_rest_api_evidence_endpoints(org_and_user, db_session):
    """Test full Phase 9 REST API lifecycle: Evidence CRUD, Verification, Correction, Hypotheses, Triage, Root Cause."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.database import get_db
    from app.core.auth import get_current_user
    from app.core.permissions import get_active_membership

    org, user, service, incident = org_and_user
    membership = db_session.query(UserOrganizationMembership).filter(
        UserOrganizationMembership.user_id == user.id,
        UserOrganizationMembership.organization_id == org.id,
    ).first()

    def override_db():
        yield db_session

    def override_user():
        return user

    def override_membership():
        return (org, membership)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_active_membership] = override_membership

    with TestClient(app) as client:
        # 1. Post manual evidence
        payload = {
            "title": "Manual Trace Observation",
            "source_type": "manual",
            "category_type": "fact",
            "content": "Operator noted DB deadlocks in thread pool dump",
            "service": "payment-gateway",
        }
        res_post = client.post(f"/incidents/{incident.id}/evidence", json=payload)
        assert res_post.status_code == 201, res_post.text
        ev_id = res_post.json()["id"]

        # 2. Get evidence list
        res_list = client.get(f"/incidents/{incident.id}/evidence")
        assert res_list.status_code == 200
        assert res_list.json()["total_count"] >= 1

        # 3. Verify manual evidence
        res_verify = client.post(f"/incidents/{incident.id}/evidence/{ev_id}/verify", json={"status": "verified"})
        assert res_verify.status_code == 200
        assert res_verify.json()["verification_status"] == "verified"
        assert res_verify.json()["evidence_family"] == "verified_human"

        # 4. Post append-only correction
        corr_payload = {
            "supersedes_evidence_id": ev_id,
            "title": "Corrected Trace Observation",
            "content": "Operator confirmed thread pool queue limit reached (not deadlocks)",
            "correction_reason": "Thread dump analysis revised by senior SRE",
        }
        res_corr = client.post(f"/incidents/{incident.id}/evidence/correction", json=corr_payload)
        assert res_corr.status_code == 201
        assert res_corr.json()["version"] == 2
        assert res_corr.json()["superseded_by_id"] is None

        # 5. Evaluate hypotheses
        res_eval = client.post(f"/incidents/{incident.id}/hypotheses/evaluate")
        assert res_eval.status_code == 200
        data_eval = res_eval.json()
        assert len(data_eval["hypotheses"]) >= 2
        h_id = data_eval["hypotheses"][0]["id"]

        # 6. Human triage override on hypothesis
        res_triage = client.post(f"/incidents/{incident.id}/hypotheses/{h_id}/triage", json={
            "status": "supported",
            "triage_notes": "SRE verified with APM flame graph",
        })
        assert res_triage.status_code == 200
        assert res_triage.json()["human_triaged"] is True

        # 7. Get root cause
        res_rc = client.get(f"/incidents/{incident.id}/root-cause")
        assert res_rc.status_code == 200

        # 8. Human override on root cause
        res_override = client.post(f"/incidents/{incident.id}/root-cause/override", json={
            "summary": "Verified Root Cause: Redis Connection Pool Starvation",
            "causal_explanation": "Connection timeout cascade triggered HTTP 500s across payment checkout",
            "override_notes": "Identified by database administrator",
        })
        assert res_override.status_code == 200
        assert res_override.json()["human_overridden"] is True
        assert "Redis Connection Pool Starvation" in res_override.json()["summary"]

    app.dependency_overrides.clear()


# ============================================================================
# 8. DIRECT DATABASE-LEVEL TRIGGER & CONSTRAINT TESTS
# ============================================================================

def test_direct_sql_update_rejected_by_db_trigger(db_session, org_and_user):
    """Verify that direct raw SQL UPDATE on evidence table is rejected by database trigger."""
    import sqlalchemy as sa
    from sqlalchemy.exc import DBAPIError, OperationalError, IntegrityError

    org, user, _, incident = org_and_user

    ev = create_evidence_item(
        db=db_session,
        organization_id=org.id,
        incident_id=incident.id,
        title="Immutable Audit Log",
        source_type=EvidenceSourceType.LOGS,
        category_type=EvidenceCategoryType.FACT,
        content="Original raw log payload",
    )
    ev_id = ev.id.hex

    # Attempt direct raw SQL UPDATE bypassing ORM layer
    with pytest.raises((DBAPIError, OperationalError, IntegrityError, Exception)) as exc_info:
        db_session.execute(
            sa.text("UPDATE evidence SET title = 'Hacked SQL Title' WHERE id = :id"),
            {"id": ev_id}
        )
        db_session.commit()

    db_session.rollback()
    err_msg = str(exc_info.value).lower()
    assert "immutable" in err_msg or "blocked" in err_msg or "abort" in err_msg

    # Verify content in DB remained completely unaltered
    fresh_ev = db_session.query(Evidence).filter(Evidence.id == ev.id).first()
    assert fresh_ev.title == "Immutable Audit Log"


def test_direct_sql_delete_rejected_by_db_trigger(db_session, org_and_user):
    """Verify that direct raw SQL DELETE on evidence table is rejected by database trigger."""
    import sqlalchemy as sa
    from sqlalchemy.exc import DBAPIError, OperationalError, IntegrityError

    org, _, _, incident = org_and_user

    ev = create_evidence_item(
        db=db_session,
        organization_id=org.id,
        incident_id=incident.id,
        title="Immutable Security Evidence",
        source_type=EvidenceSourceType.TELEMETRY,
        category_type=EvidenceCategoryType.FACT,
        content="Critical security trace",
    )
    ev_id = ev.id.hex

    # Attempt direct raw SQL DELETE bypassing ORM layer
    with pytest.raises((DBAPIError, OperationalError, IntegrityError, Exception)) as exc_info:
        db_session.execute(
            sa.text("DELETE FROM evidence WHERE id = :id"),
            {"id": ev_id}
        )
        db_session.commit()

    db_session.rollback()
    err_msg = str(exc_info.value).lower()
    assert "cannot be deleted" in err_msg or "immutable" in err_msg or "abort" in err_msg

    # Verify record still exists in DB
    fresh_ev = db_session.query(Evidence).filter(Evidence.id == ev.id).first()
    assert fresh_ev is not None
    assert fresh_ev.title == "Immutable Security Evidence"


def test_unique_current_root_cause_db_constraint(db_session, org_and_user):
    """Verify that database partial unique index prevents two active current root causes for one incident."""
    import sqlalchemy as sa
    from sqlalchemy.exc import IntegrityError, OperationalError

    org, _, _, incident = org_and_user

    # Insert first current root cause
    rc1 = RootCause(
        organization_id=org.id,
        incident_id=incident.id,
        summary="Root cause #1",
        causal_explanation="Explanation #1",
        confidence=Confidence.HIGH,
        is_current=True,
        evaluation_version=1,
    )
    db_session.add(rc1)
    db_session.commit()

    # Attempt to insert second current root cause without deactivating the first
    rc2 = RootCause(
        organization_id=org.id,
        incident_id=incident.id,
        summary="Root cause #2 (duplicate current)",
        causal_explanation="Explanation #2",
        confidence=Confidence.HIGH,
        is_current=True,
        evaluation_version=2,
    )
    db_session.add(rc2)

    with pytest.raises((IntegrityError, OperationalError)):
        db_session.commit()

    db_session.rollback()


def test_concurrent_evidence_corrections(db_session, org_and_user):
    """Test sequential chained corrections maintain immutable lineage and distinct versions."""
    org, _, _, incident = org_and_user

    # v1 original
    ev_v1 = create_evidence_item(
        db=db_session,
        organization_id=org.id,
        incident_id=incident.id,
        title="Log Anomaly v1",
        source_type=EvidenceSourceType.LOGS,
        category_type=EvidenceCategoryType.FACT,
        content="DB connection pool timeout 5000ms",
    )
    assert ev_v1.version == 1
    assert ev_v1.superseded_by_id is None

    # v2 correction
    ev_v2 = create_evidence_correction(
        db=db_session,
        organization_id=org.id,
        supersedes_evidence_id=ev_v1.id,
        title="Log Anomaly v2",
        content="DB connection pool timeout 8000ms (revised after APM analysis)",
        correction_reason="Revised after APM analysis",
    )
    assert ev_v2 is not None
    db_session.refresh(ev_v1)
    assert ev_v2.version == 2
    assert str(ev_v1.superseded_by_id) == str(ev_v2.id)

    # v3 correction
    ev_v3 = create_evidence_correction(
        db=db_session,
        organization_id=org.id,
        supersedes_evidence_id=ev_v2.id,
        title="Log Anomaly v3",
        content="DB connection pool starvation caused by unclosed cursor leak in worker",
        correction_reason="Identified leak in worker loop",
    )
    assert ev_v3 is not None
    db_session.refresh(ev_v2)
    assert ev_v3.version == 3
    assert str(ev_v2.superseded_by_id) == str(ev_v3.id)
    assert ev_v3.superseded_by_id is None

    # All three distinct version records exist immutably in DB
    all_versions = db_session.query(Evidence).filter(
        Evidence.incident_id == incident.id
    ).order_by(Evidence.version).all()
    assert len(all_versions) == 3
    assert [v.version for v in all_versions] == [1, 2, 3]


def test_real_migration_029_upgrade_and_downgrade_execution():
    """Verify that migration 029 upgrade() and downgrade() execute cleanly against a real database connection."""
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from sqlalchemy import create_engine
    import alembic.migration
    import alembic.operations
    from unittest.mock import patch

    mig_path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "029_add_phase9_evidence_and_root_cause.py"
    spec = importlib.util.spec_from_file_location("mig_029_real", str(mig_path))
    mig_029 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig_029)

    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)

    with engine.connect() as conn:
        ctx = alembic.migration.MigrationContext.configure(conn)
        real_op = alembic.operations.Operations(ctx)

        with patch.object(mig_029, "op", real_op):
            # 1. Run upgrade
            mig_029.upgrade()

            # Verify triggers exist in sqlite_master
            triggers = conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger'")).fetchall()
            trigger_names = [r[0] for r in triggers]
            assert "trg_evidence_prevent_update" in trigger_names
            assert "trg_evidence_prevent_delete" in trigger_names

            # Verify unique root cause index exists
            indexes = conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type = 'index'")).fetchall()
            index_names = [r[0] for r in indexes]
            assert "uq_root_causes_incident_current" in index_names

            # 2. Run downgrade
            mig_029.downgrade()

            # Verify triggers were dropped
            triggers_after = conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger'")).fetchall()
            trigger_names_after = [r[0] for r in triggers_after]
            assert "trg_evidence_prevent_update" not in trigger_names_after
            assert "trg_evidence_prevent_delete" not in trigger_names_after

            # Verify unique index was dropped
            indexes_after = conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type = 'index'")).fetchall()
            index_names_after = [r[0] for r in indexes_after]
            assert "uq_root_causes_incident_current" not in index_names_after

            # Verify columns were dropped in downgrade
            inspector = sa.inspect(conn)
            rc_cols_after = [c["name"] for c in inspector.get_columns("root_causes")]
            assert "human_override_notes" not in rc_cols_after
            assert "is_current" not in rc_cols_after

            hyp_cols_after = [c["name"] for c in inspector.get_columns("hypotheses")]
            assert "missing_evidence_json" not in hyp_cols_after

            ev_cols_after = [c["name"] for c in inspector.get_columns("evidence")]
            assert "superseded_by_id" not in ev_cols_after
            assert "content_hash" not in ev_cols_after


def test_root_cause_unique_index_recreated_independently():
    """Verify that uq_root_causes_incident_current index is created even when is_current column already exists."""
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from sqlalchemy import create_engine
    import alembic.migration
    import alembic.operations
    from unittest.mock import patch

    mig_path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "029_add_phase9_evidence_and_root_cause.py"
    spec = importlib.util.spec_from_file_location("mig_029_indep", str(mig_path))
    mig_029 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig_029)

    engine = create_engine("sqlite:///:memory:", echo=False)
    with engine.connect() as conn:
        # Create root_causes with is_current column pre-existing, but WITHOUT the unique index
        conn.execute(sa.text("""
            CREATE TABLE root_causes (
                id TEXT PRIMARY KEY,
                incident_id TEXT,
                organization_id TEXT,
                summary TEXT,
                is_current INTEGER DEFAULT 1
            );
        """))

        ctx = alembic.migration.MigrationContext.configure(conn)
        real_op = alembic.operations.Operations(ctx)

        with patch.object(mig_029, "op", real_op):
            # Run upgrade
            mig_029.upgrade()

            # Verify uq_root_causes_incident_current index was created independently
            indexes = conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type = 'index'")).fetchall()
            index_names = [r[0] for r in indexes]
            assert "uq_root_causes_incident_current" in index_names

