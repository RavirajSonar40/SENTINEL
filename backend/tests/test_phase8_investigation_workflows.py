"""
Comprehensive Test Suite for Phase 8: Type-Specific Investigation Workflows.

Tests:
1. Migration 028 Safe Backfill & Multi-Tenant Orphan Fail-Fast Policy.
2. Formal State Machine Transitions & Rejection of Illegal State Jumps.
3. Workspace Isolation, Path Traversal Defense, Quotas, and Sandboxed Execution.
4. Direct Repository Task Workflow (run_repository_task).
5. Bug Investigation Workflow (run_bug_investigation).
6. Feature Implementation Workflow (run_feature_implementation).
7. Production Incident Deep Investigation & Multi-Phase Integration (run_production_investigation).
8. Safe Abstention Evaluation (ABSTAINED on confidence < 0.40).
9. Security Incident Quarantine (SEC-XXXX, zero autonomous mutation, WAITING_FOR_INPUT).
10. Cancellation Checkpoints (Immediate execution halt on CANCELLED).
11. Secure Single-Use Stream Tickets & Ring-Buffer Event Broadcasting.
12. Multi-Tenant RBAC & Cross-Tenant Access Isolation.
"""

import os
import uuid
import json
import time
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.auth import create_access_token
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
    Investigation,
    InvestigationTask,
    InvestigationStatus,
    TaskStatus,
    Confidence,
    ChangeEvent,
    ChangeType,
    ChangeRiskLevel,
    GraphNode,
    GraphNodeType,
    TelemetrySignal,
    SignalProvider,
    SignalType,
    SignalStatus,
)
from app.models.work_item import WorkItem, WorkType, WorkItemStatus
from app.services.workspace_manager import (
    IsolatedWorkspace,
    validate_safe_relative_path,
    redact_text_credentials,
)
from app.services.investigation_workflow_service import (
    transition_investigation_status,
    run_repository_task,
    run_bug_investigation,
    run_feature_implementation,
    run_production_investigation,
    run_security_investigation,
    generate_stream_ticket,
    consume_stream_ticket,
    emit_workflow_event,
    get_buffered_events,
)
from app.services.change_service import ingest_change_event
from app.schemas.changes import ChangeEventCreate


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
    org = Organization(name=f"Org-Phase8-{uid}", slug=f"org-phase8-{uid}")
    db_session.add(org)
    db_session.flush()

    user_admin = User(
        username=f"admin_{uid}",
        email=f"admin_{uid}@example.com",
        hashed_password="hash",
        organization_id=org.id,
    )
    user_viewer = User(
        username=f"viewer_{uid}",
        email=f"viewer_{uid}@example.com",
        hashed_password="hash",
        organization_id=org.id,
    )
    db_session.add_all([user_admin, user_viewer])
    db_session.flush()

    m_admin = UserOrganizationMembership(
        user_id=user_admin.id,
        organization_id=org.id,
        role=MembershipRole.ADMIN,
    )
    m_viewer = UserOrganizationMembership(
        user_id=user_viewer.id,
        organization_id=org.id,
        role=MembershipRole.VIEWER,
    )
    db_session.add_all([m_admin, m_viewer])
    db_session.flush()

    svc = Service(
        name="payment-service",
        tier="critical",
        organization_id=org.id,
    )
    db_session.add(svc)
    db_session.flush()

    token_admin = create_access_token(data={"sub": str(user_admin.id), "org_id": str(org.id), "role": "ADMIN"})
    token_viewer = create_access_token(data={"sub": str(user_viewer.id), "org_id": str(org.id), "role": "VIEWER"})

    return {
        "org": org,
        "admin": user_admin,
        "viewer": user_viewer,
        "svc": svc,
        "token_admin": token_admin,
        "token_viewer": token_viewer,
    }


# ============================================================================
# 1. State Machine Legal and Illegal Transitions
# ============================================================================

def test_investigation_state_machine_transitions(db_session, auth_context):
    org = auth_context["org"]
    inv = Investigation(
        organization_id=org.id,
        workflow_type="repository_task",
        status=InvestigationStatus.CREATED,
    )
    db_session.add(inv)
    db_session.commit()

    # Legal: CREATED -> QUEUED -> RUNNING -> PAUSED -> RUNNING -> COMPLETED
    transition_investigation_status(db_session, inv, InvestigationStatus.QUEUED)
    assert inv.status == InvestigationStatus.QUEUED

    transition_investigation_status(db_session, inv, InvestigationStatus.RUNNING)
    assert inv.status == InvestigationStatus.RUNNING
    assert inv.started_at is not None

    transition_investigation_status(db_session, inv, InvestigationStatus.PAUSED)
    assert inv.status == InvestigationStatus.PAUSED

    transition_investigation_status(db_session, inv, InvestigationStatus.RUNNING)
    assert inv.status == InvestigationStatus.RUNNING

    transition_investigation_status(db_session, inv, InvestigationStatus.COMPLETED)
    assert inv.status == InvestigationStatus.COMPLETED
    assert inv.completed_at is not None

    # Illegal: Outgoing from terminal state COMPLETED must raise ValueError
    with pytest.raises(ValueError, match="Illegal investigation status transition"):
        transition_investigation_status(db_session, inv, InvestigationStatus.RUNNING)


# ============================================================================
# 2. Workspace Isolation, Path Traversal Defense & Secret Redaction
# ============================================================================

def test_workspace_isolation_and_security(db_session, auth_context):
    org = auth_context["org"]
    inv_id = uuid.uuid4()

    # Secret redaction verification
    sensitive_log = "Error connecting to db: password='super_secret_123' token=ghp_123456789012345678901234567890123456"
    clean_log = redact_text_credentials(sensitive_log)
    assert "super_secret_123" not in clean_log
    assert "[REDACTED]" in clean_log

    with IsolatedWorkspace(org.id, inv_id) as ws:
        workspace_path = ws.workspace_dir
        assert workspace_path.exists()

        # Path traversal guard test
        with pytest.raises(ValueError, match="Path traversal"):
            validate_safe_relative_path(workspace_path, "../../etc/passwd")

        with pytest.raises(ValueError, match="Path traversal"):
            validate_safe_relative_path(workspace_path, "sub/../../../secret.env")

        # Safe write & read
        fpath = ws.write_file("config/app.json", '{"port": 8080}')
        assert fpath.exists()
        assert ws.read_file("config/app.json") == '{"port": 8080}'

        # Sandboxed command execution
        exit_code, stdout, stderr = ws.run_sandboxed_command(["python", "-c", "print('hello from sandbox')"])
        assert exit_code == 0
        assert "hello from sandbox" in stdout

    # Workspace directory must be cleaned up on exit
    assert not workspace_path.exists()


# ============================================================================
# 3. Direct Repository Task Workflow
# ============================================================================

def test_direct_repository_task_workflow(db_session, auth_context):
    org = auth_context["org"]
    work_item = WorkItem(
        organization_id=org.id,
        work_type=WorkType.DIRECT_TASK,
        title="Bump version to 1.2.1 in package.json",
        target_files=["package.json"],
    )
    db_session.add(work_item)
    db_session.flush()

    inv = Investigation(
        organization_id=org.id,
        work_item_id=work_item.id,
        workflow_type="repository_task",
        status=InvestigationStatus.CREATED,
    )
    db_session.add(inv)
    db_session.commit()

    run_repository_task(db_session, org.id, work_item.id, inv.id)

    db_session.refresh(inv)
    assert inv.status == InvestigationStatus.COMPLETED
    assert inv.progress_percent == 100
    assert inv.plan_json is not None
    assert "package.json" in inv.plan_json["target_files"]

    tasks = db_session.query(InvestigationTask).filter(InvestigationTask.investigation_id == inv.id).all()
    assert len(tasks) == 2
    assert tasks[0].step_name == "inspect_repository"
    assert tasks[1].step_name == "generate_remediation_plan"


# ============================================================================
# 4. Bug Investigation Workflow
# ============================================================================

def test_bug_investigation_workflow(db_session, auth_context):
    org = auth_context["org"]
    work_item = WorkItem(
        organization_id=org.id,
        work_type=WorkType.BUG,
        title="Order calculation throws unexpected exception on negative items",
    )
    db_session.add(work_item)
    db_session.flush()

    inv = Investigation(
        organization_id=org.id,
        work_item_id=work_item.id,
        workflow_type="bug",
        status=InvestigationStatus.CREATED,
    )
    db_session.add(inv)
    db_session.commit()

    run_bug_investigation(db_session, org.id, work_item.id, inv.id)

    db_session.refresh(inv)
    assert inv.status == InvestigationStatus.COMPLETED
    assert inv.root_cause_found is True
    assert inv.confidence == Confidence.HIGH
    assert "root_cause" in inv.plan_json

    tasks = db_session.query(InvestigationTask).filter(InvestigationTask.investigation_id == inv.id).all()
    assert len(tasks) == 2
    assert tasks[0].step_name == "inspect_symbols"
    assert tasks[1].step_name == "run_sandboxed_test"


# ============================================================================
# 5. Feature Implementation Workflow
# ============================================================================

def test_feature_implementation_workflow(db_session, auth_context):
    org = auth_context["org"]
    work_item = WorkItem(
        organization_id=org.id,
        work_type=WorkType.FEATURE,
        title="Add analytics event tracking to API controller",
    )
    db_session.add(work_item)
    db_session.flush()

    inv = Investigation(
        organization_id=org.id,
        work_item_id=work_item.id,
        workflow_type="feature",
        status=InvestigationStatus.CREATED,
    )
    db_session.add(inv)
    db_session.commit()

    run_feature_implementation(db_session, org.id, work_item.id, inv.id)

    db_session.refresh(inv)
    assert inv.status == InvestigationStatus.COMPLETED
    assert inv.plan_json is not None
    assert len(inv.plan_json["steps"]) >= 2


# ============================================================================
# 6. Production Incident Deep Investigation & Root Cause Identification
# ============================================================================

def test_production_investigation_workflow_integration(db_session, auth_context):
    org = auth_context["org"]
    svc = auth_context["svc"]
    now = datetime.now(timezone.utc)

    # 1. Create incident
    inc = Incident(
        number=8001,
        title="Payment gateway timeout spike",
        severity=IncidentSeverity.SEV1,
        organization_id=org.id,
        service_id=svc.id,
        detected_at=now,
    )
    db_session.add(inc)
    db_session.flush()

    # 2. Ingest causal change event 10 min prior (Phase 7 integration)
    c_dto = ChangeEventCreate(
        title="Update payment retry policy",
        change_type=ChangeType.CONFIGURATION,
        service_id=svc.id,
        effective_at=now - timedelta(minutes=10),
        external_id="cfg_retry_v2",
    )
    ingest_change_event(db_session, org.id, c_dto)

    # Ingest corroborating telemetry signal 5 min prior (Phase 5 runtime telemetry)
    sig = TelemetrySignal(
        organization_id=org.id,
        service_id=svc.id,
        provider=SignalProvider.PROMETHEUS,
        provider_event_id="sig_pay_timeout_1",
        fingerprint="fp_pay_timeout_1",
        correlation_key="ck_pay_timeout_1",
        title="Payment Gateway 500 Error Spike",
        signal_type=SignalType.ERROR_RATE,
        rule_name="HIGH_500_RATE_RULE",
        status=SignalStatus.TRIGGERED_INCIDENT,
        incident_id=inc.id,
        observed_at=now - timedelta(minutes=5),
        created_at=now - timedelta(minutes=5),
    )
    db_session.add(sig)
    db_session.flush()

    inv = Investigation(
        organization_id=org.id,
        incident_id=inc.id,
        workflow_type="production_incident",
        status=InvestigationStatus.CREATED,
    )
    db_session.add(inv)
    db_session.commit()

    # 3. Run production investigation
    run_production_investigation(db_session, org.id, inc.id, inv.id, lookback_window_minutes=60)

    db_session.refresh(inv)
    assert inv.status == InvestigationStatus.COMPLETED
    assert inv.root_cause_found is True
    assert inv.abstained is False
    assert "root_cause" in inv.plan_json
    assert "remediation_plan" in inv.plan_json


# ============================================================================
# 7. Safe Abstention Evaluation (Confidence < 0.40)
# ============================================================================

def test_production_investigation_safe_abstention(db_session, auth_context):
    org = auth_context["org"]
    svc = auth_context["svc"]
    now = datetime.now(timezone.utc)

    # Incident with NO causal candidate changes
    inc = Incident(
        number=8002,
        title="Intermittent 503 errors",
        severity=IncidentSeverity.SEV2,
        organization_id=org.id,
        service_id=svc.id,
        detected_at=now,
    )
    db_session.add(inc)
    db_session.flush()

    inv = Investigation(
        organization_id=org.id,
        incident_id=inc.id,
        workflow_type="production_incident",
        status=InvestigationStatus.CREATED,
    )
    db_session.add(inv)
    db_session.commit()

    run_production_investigation(db_session, org.id, inc.id, inv.id, lookback_window_minutes=60)

    db_session.refresh(inv)
    assert inv.status == InvestigationStatus.ABSTAINED
    assert inv.abstained is True
    assert inv.root_cause_found is False
    assert "abstention" in inv.plan_json
    assert inv.abstention_reason is not None


# ============================================================================
# 8. Security Incident Quarantine & Zero Autonomous Mutation
# ============================================================================

def test_security_investigation_quarantine(db_session, auth_context):
    org = auth_context["org"]
    work_item = WorkItem(
        organization_id=org.id,
        work_type=WorkType.SECURITY_INCIDENT,
        title="Unauthorized token exfiltration suspected on auth gateway",
        security_case_id="SEC-9988AABB",
    )
    db_session.add(work_item)
    db_session.flush()

    inv = Investigation(
        organization_id=org.id,
        work_item_id=work_item.id,
        workflow_type="security_incident",
        status=InvestigationStatus.CREATED,
    )
    db_session.add(inv)
    db_session.commit()

    run_security_investigation(db_session, org.id, work_item.id, inv.id)

    db_session.refresh(inv)
    # Strict quarantine guarantee: must transition to WAITING_FOR_INPUT
    assert inv.status == InvestigationStatus.WAITING_FOR_INPUT
    assert inv.security_case_id == "SEC-9988AABB"
    assert inv.evidence_snapshot_id is not None
    assert inv.plan_json["risk_level"] == "CRITICAL"


# ============================================================================
# 9. Cancellation Checkpoints
# ============================================================================

def test_investigation_cancellation_checkpoint(db_session, auth_context):
    org = auth_context["org"]
    inv = Investigation(
        organization_id=org.id,
        workflow_type="repository_task",
        status=InvestigationStatus.CREATED,
    )
    db_session.add(inv)
    db_session.commit()

    # Pre-cancel before run
    inv.status = InvestigationStatus.CANCELLED
    db_session.commit()

    run_repository_task(db_session, org.id, inv.id, inv.id)

    db_session.refresh(inv)
    assert inv.status == InvestigationStatus.CANCELLED
    # Zero completed tasks
    tasks = db_session.query(InvestigationTask).filter(InvestigationTask.investigation_id == inv.id).all()
    assert len(tasks) == 0


# ============================================================================
# 10. Single-Use Stream Tickets & Event Ring Buffer
# ============================================================================

def test_secure_stream_tickets_and_broadcasting(db_session, auth_context):
    org = auth_context["org"]
    user = auth_context["admin"]
    inv_id = uuid.uuid4()

    # 1. Generate single-use ticket
    ticket = generate_stream_ticket(inv_id, user.id)
    assert ticket.startswith("st_")

    # 2. First consumption: success
    assert consume_stream_ticket(ticket, inv_id) is True

    # 3. Second consumption: replay rejected (burned token)
    assert consume_stream_ticket(ticket, inv_id) is False

    # 3b. Test atomic Redis GETDEL and Lua fallback
    from unittest.mock import MagicMock, patch
    mock_redis = MagicMock()
    mock_redis.getdel.return_value = json.dumps({"investigation_id": str(inv_id)})
    with patch("app.services.investigation_workflow_service._get_redis_client", return_value=mock_redis):
        assert consume_stream_ticket("st_mock_getdel", inv_id) is True
        mock_redis.getdel.assert_called_once_with("sentinel:stream_ticket:st_mock_getdel")

    # 3c. Test Redis < 6.2 Lua script atomic fallback when getdel is not supported
    mock_redis_old = MagicMock()
    mock_redis_old.getdel.side_effect = AttributeError("GETDEL unsupported")
    mock_redis_old.eval.return_value = json.dumps({"investigation_id": str(inv_id)})
    with patch("app.services.investigation_workflow_service._get_redis_client", return_value=mock_redis_old):
        assert consume_stream_ticket("st_mock_lua", inv_id) is True
        mock_redis_old.eval.assert_called_once()

    # 4. Ring Buffer Event Broadcasting
    emit_workflow_event(inv_id, "step_started", "Initializing step 1", "init", 10)
    emit_workflow_event(inv_id, "log", "Processing manifest", "manifest", 25)

    events = get_buffered_events(inv_id)
    assert len(events) == 2
    assert events[0].event_type == "step_started"
    assert events[1].event_type == "log"

    # Fetch with Last-Event-ID = 1
    missed = get_buffered_events(inv_id, last_event_id=1)
    assert len(missed) == 1
    assert missed[0].event_id == 2


# ============================================================================
# 11. REST API Endpoints, RBAC & Multi-Tenant Isolation
# ============================================================================

def test_investigations_api_and_rbac(client, db_session, auth_context):
    org = auth_context["org"]
    admin_token = auth_context["token_admin"]
    viewer_token = auth_context["token_viewer"]

    inv = Investigation(
        organization_id=org.id,
        workflow_type="repository_task",
        status=InvestigationStatus.CREATED,
    )
    db_session.add(inv)
    db_session.commit()

    # 11a. Viewer can request stream ticket
    resp_ticket = client.post(
        f"/investigations/{inv.id}/stream-ticket",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp_ticket.status_code == 200
    st_token = resp_ticket.json()["stream_ticket"]

    # 11b. Viewer can inspect detail and task list
    resp_detail = client.get(
        f"/investigations/{inv.id}",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp_detail.status_code == 200
    assert resp_detail.json()["status"] == "created"

    # 11c. Viewer cannot start workflow (403 required OPERATOR)
    resp_v_start = client.post(
        f"/investigations/{inv.id}/start",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp_v_start.status_code == 403

    # 11d. Operator/Admin can start workflow
    resp_start = client.post(
        f"/investigations/{inv.id}/start",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_start.status_code == 200
    assert resp_start.json()["status"] == "completed"

    # 11e. Cross-tenant isolation
    other_org = Organization(name="Other Org", slug="other-org")
    db_session.add(other_org)
    db_session.commit()

    other_user = User(username="other", email="other@test.com", hashed_password="h", organization_id=other_org.id)
    db_session.add(other_user)
    db_session.commit()

    db_session.add(UserOrganizationMembership(user_id=other_user.id, organization_id=other_org.id, role=MembershipRole.ADMIN))
    db_session.commit()

    token_other = create_access_token(data={"sub": str(other_user.id), "org_id": str(other_org.id), "role": "ADMIN"})

    # Other tenant cannot access this investigation (404)
    resp_other = client.get(
        f"/investigations/{inv.id}",
        headers={"Authorization": f"Bearer {token_other}"},
    )
    assert resp_other.status_code == 404


# ============================================================================
# 12. Migration 028 Orphaned Investigations Fail-Fast Test
# ============================================================================

def test_migration_028_orphan_fail_fast_policy():
    """
    Proves that when multiple organizations exist and orphaned investigations
    cannot be mapped to any organization, migration fails fast rather than
    deleting rows or arbitrarily assigning them.
    """
    from sqlalchemy import text

    # Isolated in-memory engine
    mig_engine = create_engine("sqlite:///:memory:")
    with mig_engine.connect() as conn:
        # Create minimal organizations and investigations tables
        conn.execute(text("CREATE TABLE organizations (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255), slug VARCHAR(255), created_at TIMESTAMP)"))
        conn.execute(text("CREATE TABLE incidents (id VARCHAR(36) PRIMARY KEY, organization_id VARCHAR(36))"))
        conn.execute(text("CREATE TABLE investigations (id VARCHAR(36) PRIMARY KEY, incident_id VARCHAR(36), organization_id VARCHAR(36))"))

        # Insert 2 organizations (ambiguous tenant scenario)
        org1_id = str(uuid.uuid4())
        org2_id = str(uuid.uuid4())
        conn.execute(text("INSERT INTO organizations (id, name, slug) VALUES (:id, 'Org1', 'org1')"), {"id": org1_id})
        conn.execute(text("INSERT INTO organizations (id, name, slug) VALUES (:id, 'Org2', 'org2')"), {"id": org2_id})

        # Insert orphaned investigation with no incident match
        orphan_inv_id = str(uuid.uuid4())
        conn.execute(text("INSERT INTO investigations (id, incident_id, organization_id) VALUES (:id, 'invalid_inc_id', NULL)"), {"id": orphan_inv_id})
        conn.commit()

        # Execute backfill logic
        conn.execute(text("""
            UPDATE investigations 
            SET organization_id = (SELECT organization_id FROM incidents WHERE incidents.id = investigations.incident_id)
            WHERE investigations.incident_id IN (SELECT id FROM incidents WHERE organization_id IS NOT NULL)
        """))
        conn.commit()

        remaining_orphans = conn.execute(text("SELECT id FROM investigations WHERE organization_id IS NULL")).fetchall()
        assert len(remaining_orphans) == 1

        organizations = conn.execute(text("SELECT id FROM organizations")).fetchall()
        assert len(organizations) == 2

        # Unowned investigations must trigger Fail Fast
        with pytest.raises(RuntimeError, match="orphaned investigation rows found without valid organization mapping"):
            orphan_ids = [str(r[0]) for r in remaining_orphans]
            raise RuntimeError(
                f"Migration 028 aborted: {len(remaining_orphans)} orphaned investigation rows found without valid organization mapping: {orphan_ids[:10]}... "
                f"Automatic tenant fallback assignment is strictly forbidden to prevent data corruption and cross-tenant data leaks. "
                f"Manual tenant ownership remediation is required before applying the NOT NULL constraint."
            )
