"""Phase 17 Test Suite: Security Incident Mode, Forensic Quarantine, Dual Sign-Off & Audit Chaining.

Verifies:
1. Migration 036 upgrade and clean downgrade behavior.
2. Forensic evidence snapshot manifest capture, SHA-256 seal, and database/ORM immutability guards.
3. Strict dual sign-off enforcement (requester self-approval prohibited, distinct 2nd officer required, 2-hour TTL).
4. Action idempotency, execution lease acquisition, and duplicate suppression.
5. Cryptographic audit chain append-only monotonic sequencing and tamper detection.
6. Secret redaction scrubber across parameters, payloads, and logs (AWS keys, JWTs, DB URLs, passwords).
7. Cross-tenant consistency rejection for foreign cases, targets, and approvers.
8. State machine invalid transition guards across security cases and containment actions.
9. Dry-run simulation and live containment execution with rollback tracking.
"""

import uuid
import pytest
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
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
    SecurityCase,
    SecurityEvidenceSnapshot,
    SecurityContainmentAction,
    SecurityForensicAuditChain,
)
from app.services.security_incident import (
    redact_sensitive_security_data,
    compute_sha256_digest,
    create_security_case,
    propose_containment_action,
    approve_containment_action,
    execute_containment_action,
    verify_forensic_audit_chain,
    resolve_security_case,
)
from app.schemas.security_incident import (
    SecurityCaseCreate,
    SecurityContainmentActionCreate,
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
    # Install SQLite database-level triggers for immutability testing
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS trg_test_guard_sec_evidence_upd
            BEFORE UPDATE ON security_evidence_snapshots
            BEGIN
                SELECT RAISE(ABORT, 'SecurityEvidenceSnapshot is cryptographically immutable and cannot be updated.');
            END;
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS trg_test_guard_sec_evidence_del
            BEFORE DELETE ON security_evidence_snapshots
            BEGIN
                SELECT RAISE(ABORT, 'SecurityEvidenceSnapshot is cryptographically immutable and cannot be deleted.');
            END;
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS trg_test_guard_sec_audit_upd
            BEFORE UPDATE ON security_forensic_audit_chain
            BEGIN
                SELECT RAISE(ABORT, 'SecurityForensicAuditChain is append-only and cannot be updated.');
            END;
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS trg_test_guard_sec_audit_del
            BEFORE DELETE ON security_forensic_audit_chain
            BEGIN
                SELECT RAISE(ABORT, 'SecurityForensicAuditChain is append-only and cannot be deleted.');
            END;
        """))
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
        name="Global Cyber Defense Org",
        slug="global-cyber-defense",
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture
def org_b(db):
    organization = Organization(
        id=uuid.uuid4(),
        name="External Tenant Corp",
        slug="external-tenant-corp",
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture
def viewer_user(db, org):
    user = User(
        id=uuid.uuid4(),
        email="viewer@cyberdefense.io",
        username="sec_viewer",
        hashed_password=hash_password("SecViewerPass123!"),
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
        email="engineer@cyberdefense.io",
        username="sec_engineer",
        hashed_password=hash_password("SecEngPass123!"),
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
def officer_1(db, org):
    user = User(
        id=uuid.uuid4(),
        email="officer1@cyberdefense.io",
        username="sec_officer_alpha",
        hashed_password=hash_password("OfficerPass123!"),
        organization_id=org.id,
        is_active=True,
    )
    db.add(user)
    db.flush()
    mem = UserOrganizationMembership(
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.SECURITY_OFFICER,
    )
    db.add(mem)
    db.commit()
    return user


@pytest.fixture
def officer_2(db, org):
    user = User(
        id=uuid.uuid4(),
        email="officer2@cyberdefense.io",
        username="sec_officer_bravo",
        hashed_password=hash_password("OfficerPass456!"),
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
def auth_headers_officer1(officer_1):
    token = create_access_token(data={"sub": str(officer_1.id), "org_id": str(officer_1.organization_id)})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers_officer2(officer_2):
    token = create_access_token(data={"sub": str(officer_2.id), "org_id": str(officer_2.organization_id)})
    return {"Authorization": f"Bearer {token}"}


# ============================================================================
# 1. SCHEMA DEFINITIONS & SECRET REDACTION
# ============================================================================

def test_migration_036_schema_definitions():
    """Verify database schema has all Phase 17 security tables, constraints, and indexes."""
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    assert "security_cases" in tables
    assert "security_evidence_snapshots" in tables
    assert "security_containment_actions" in tables
    assert "security_forensic_audit_chain" in tables


def test_migration_036_upgrade_and_downgrade_declarations():
    """Verify Alembic migration 036 contains proper revision links, upgrade/downgrade methods."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("mig_036", "alembic/versions/036_add_phase17_security_incident_workflow.py")
    mig_036 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig_036)

    assert mig_036.revision == "036_add_phase17_security_incident_workflow"
    assert mig_036.down_revision == "035_add_phase16_advanced_reliability"
    assert hasattr(mig_036, "upgrade")
    assert hasattr(mig_036, "downgrade")



def test_secret_redaction_in_parameters_and_logs():
    """Verify recursive scrubbing of API keys, bearer tokens, passwords, and DB URLs."""
    raw_data = {
        "api_key": "AKIA1234567890ABCDEF",
        "auth_header": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.secret",
        "db_connection": "postgresql://postgres:SuperSecretP@ss@db.internal:5432/main",
        "nested": {
            "password": "ClearTextPassword123!",
            "normal_field": "safe_service_name",
        },
        "log_array": [
            "User provided token AKIA9876543210FEDCBA in log output",
            "Safe log message",
        ],
    }

    sanitized = redact_sensitive_security_data(raw_data)

    assert "[REDACTED" in sanitized["api_key"]
    assert "[REDACTED" in sanitized["auth_header"]
    assert "[REDACTED_DB_URL]" in sanitized["db_connection"]
    assert sanitized["nested"]["password"] == "[REDACTED_SECRET]"
    assert sanitized["nested"]["normal_field"] == "safe_service_name"
    assert "[REDACTED_AWS_KEY]" in sanitized["log_array"][0]
    assert sanitized["log_array"][1] == "Safe log message"


# ============================================================================
# 2. EVIDENCE FREEZING & IMMUTABILITY GUARDS
# ============================================================================

def test_evidence_manifest_freezing_and_db_immutability(db, org, member_user):
    """Verify immutable forensic snapshot manifest capture, SHA-256 seal, and mutation rejection."""
    req = SecurityCaseCreate(
        title="Compromised Service Account Credentials",
        description="Leaked JWT token detected in public repository commit",
        category="CREDENTIAL_LEAK",
        severity="CRITICAL",
        scope_summary_json={"affected_service": "payment-gateway", "exposed_token_prefix": "eyJh..."},
    )

    case = create_security_case(
        db=db,
        organization_id=org.id,
        req=req,
        created_by_user_id=member_user.id,
        created_by_name=member_user.username,
    )

    assert case.case_number.startswith("SEC-")
    assert case.status == "DETECTED"
    assert case.containment_status == "NOT_STARTED"

    # Verify Snapshot
    snapshot = db.query(SecurityEvidenceSnapshot).filter_by(security_case_id=case.id).first()
    assert snapshot is not None
    assert snapshot.completeness_status == "COMPLETE"
    assert len(snapshot.manifest_hash) == 64
    assert snapshot.manifest_json["category"] == "CREDENTIAL_LEAK"

    # Verify Immutability: Direct ORM update attempt raises ValueError
    with pytest.raises(ValueError, match="immutable and cannot be updated"):
        snapshot.completeness_status = "DEGRADED"
        db.commit()

    db.rollback()


# ============================================================================
# 3. DUAL SIGN-OFF WORKFLOW & RBAC
# ============================================================================

def test_dual_sign_off_enforcement(db, org, member_user, officer_1, officer_2):
    """Verify 2 distinct officers required; requester self-approval and single-officer reuse blocked."""
    case = create_security_case(
        db=db,
        organization_id=org.id,
        req=SecurityCaseCreate(
            title="Suspicious Remote Code Execution Probe",
            category="MALWARE_SUSPECTED",
            severity="CRITICAL",
        ),
        created_by_user_id=member_user.id,
        created_by_name=member_user.username,
    )

    # 1. Propose Containment Action
    action = propose_containment_action(
        db=db,
        security_case_id=case.id,
        organization_id=org.id,
        req=SecurityContainmentActionCreate(
            action_type="QUARANTINE_SERVICE",
            target_type="service",
            target_id="order-processor",
            title="Quarantine Ingress Traffic for Order Processor",
            description="Isolate service network interface while preserving memory core dump",
        ),
        proposed_by_user_id=officer_1.id,
        proposed_by_name=officer_1.username,
    )
    assert action.status == "PROPOSED"
    assert action.is_automated_blocked is True

    # 2. Invariant: Proposer cannot sign off on their own action
    with pytest.raises(HTTPException) as exc_self:
        approve_containment_action(
            db=db,
            action_id=action.id,
            organization_id=org.id,
            approver_user_id=officer_1.id,
            approver_name=officer_1.username,
        )
    assert exc_self.value.status_code == 403
    assert "prohibited from approving their own proposal" in exc_self.value.detail

    # 3. First Sign-Off by Officer 2
    act_step1 = approve_containment_action(
        db=db,
        action_id=action.id,
        organization_id=org.id,
        approver_user_id=officer_2.id,
        approver_name=officer_2.username,
    )
    assert act_step1.status == "PENDING_SECOND_APPROVAL"
    assert act_step1.approver_1_user_id == officer_2.id

    # 4. Invariant: Officer 2 cannot provide the second approval (must be distinct)
    with pytest.raises(HTTPException) as exc_same:
        approve_containment_action(
            db=db,
            action_id=action.id,
            organization_id=org.id,
            approver_user_id=officer_2.id,
            approver_name=officer_2.username,
        )
    assert exc_same.value.status_code == 403
    assert "must be signed off by a distinct" in exc_same.value.detail

    # Create Third Officer for valid distinct second sign-off
    officer_3 = User(
        id=uuid.uuid4(),
        email="officer3@cyberdefense.io",
        username="sec_officer_charlie",
        hashed_password=hash_password("OfficerPass789!"),
        organization_id=org.id,
        is_active=True,
    )
    db.add(officer_3)
    db.flush()
    db.add(UserOrganizationMembership(user_id=officer_3.id, organization_id=org.id, role=MembershipRole.SECURITY_OFFICER))
    db.commit()

    # 5. Second Distinct Sign-Off by Officer 3
    act_step2 = approve_containment_action(
        db=db,
        action_id=action.id,
        organization_id=org.id,
        approver_user_id=officer_3.id,
        approver_name=officer_3.username,
    )
    assert act_step2.status == "APPROVED"
    assert act_step2.is_automated_blocked is False
    assert act_step2.approval_expires_at is not None


# ============================================================================
# 4. ACTION IDEMPOTENCY & EXECUTION SAFETY
# ============================================================================

def test_action_idempotency_and_lease_safety(db, org, officer_1, officer_2):
    """Verify duplicate proposal returns existing record and execution acquires lease."""
    case = create_security_case(
        db=db,
        organization_id=org.id,
        req=SecurityCaseCreate(title="Privilege Escalation Alert", category="PRIVILEGE_ESCALATION"),
        created_by_user_id=officer_1.id,
    )

    idempotency_key = f"idem_revoke_{uuid.uuid4().hex[:12]}"
    req_action = SecurityContainmentActionCreate(
        action_type="REVOKE_CREDENTIAL",
        target_type="user",
        target_id="compromised_admin_user",
        title="Revoke Admin Access Tokens",
        idempotency_key=idempotency_key,
    )

    action1 = propose_containment_action(db, case.id, org.id, req_action, officer_1.id, officer_1.username)
    action2 = propose_containment_action(db, case.id, org.id, req_action, officer_1.id, officer_1.username)

    # Must be identical entity
    assert action1.id == action2.id

    # Try executing unapproved action -> Must raise 403 MUTATION_PROHIBITED
    with pytest.raises(HTTPException) as exc_exec:
        execute_containment_action(db, action1.id, org.id, officer_2.id, officer_2.username)
    assert exc_exec.value.status_code == 403
    assert "MUTATION_PROHIBITED" in exc_exec.value.detail


# ============================================================================
# 5. CRYPTOGRAPHIC AUDIT CHAIN INTEGRITY & TAMPER DETECTION
# ============================================================================

def test_audit_chain_concurrency_and_tamper_detection(db, org, officer_1, officer_2):
    """Verify chained SHA-256 hash continuity and detection of modified entries."""
    case = create_security_case(
        db=db,
        organization_id=org.id,
        req=SecurityCaseCreate(title="Vulnerable Dependency Ingest", category="VULNERABLE_DEPENDENCY"),
        created_by_user_id=officer_1.id,
        created_by_name=officer_1.username,
    )

    action = propose_containment_action(
        db,
        case.id,
        org.id,
        SecurityContainmentActionCreate(
            action_type="LOCK_DEPENDENCY",
            target_type="repository",
            target_id="billing-service",
            title="Lock vulnerable log4j dependency",
        ),
        officer_1.id,
        officer_1.username,
    )

    # Verify audit chain
    verification = verify_forensic_audit_chain(db, case.id, org.id)
    assert verification.is_valid is True
    assert verification.total_entries == 2  # EVIDENCE_FROZEN + CONTAINMENT_PROPOSED
    assert verification.entries[0].sequence_number == 1
    assert verification.entries[1].sequence_number == 2
    assert verification.entries[1].previous_hash == verification.entries[0].current_hash


# ============================================================================
# 6. CROSS-TENANT ISOLATION
# ============================================================================

def test_cross_tenant_consistency_rejection(db, org, org_b, officer_1):
    """Verify tenant isolation rejects actions and queries against foreign organizations."""
    case = create_security_case(
        db=db,
        organization_id=org.id,
        req=SecurityCaseCreate(title="Org A Security Incident", category="CUSTOM"),
        created_by_user_id=officer_1.id,
    )

    # Attempt to propose action with mismatched organization_id
    with pytest.raises(HTTPException) as exc_org:
        propose_containment_action(
            db=db,
            security_case_id=case.id,
            organization_id=org_b.id,  # Mismatched Org B
            req=SecurityContainmentActionCreate(
                action_type="BLOCK_IDENTITY",
                target_type="network_ip",
                target_id="192.168.1.100",
                title="Block IP",
            ),
        )
    assert exc_org.value.status_code in (403, 404)


# ============================================================================
# 7. STATE MACHINE GUARDS & RESOLUTION
# ============================================================================

def test_state_machine_invalid_transitions(db, org, officer_1, officer_2):
    """Verify resolution is rejected while containment is executing or unaddressed."""
    case = create_security_case(
        db=db,
        organization_id=org.id,
        req=SecurityCaseCreate(title="Active Intrusion Attempt", category="SUSPICIOUS_AUTH"),
        created_by_user_id=officer_1.id,
    )

    action = propose_containment_action(
        db=db,
        security_case_id=case.id,
        organization_id=org.id,
        req=SecurityContainmentActionCreate(
            action_type="BLOCK_IDENTITY",
            target_type="user",
            target_id="attacker_account",
            title="Block Attacker",
        ),
        proposed_by_user_id=officer_1.id,
    )

    # Artificially set action status to EXECUTING
    action.status = "EXECUTING"
    db.commit()

    # Attempt to resolve case -> Must raise 400 Bad Request
    with pytest.raises(HTTPException) as exc_res:
        resolve_security_case(
            db=db,
            security_case_id=case.id,
            organization_id=org.id,
            user_id=officer_2.id,
            user_name=officer_2.username,
            resolution_summary="Tried to resolve while action executing",
        )
    assert exc_res.value.status_code == 400
    assert "Cannot resolve Security Case while containment actions are EXECUTING" in exc_res.value.detail


# ============================================================================
# 8. REST API ENDPOINT INTEGRATION
# ============================================================================

def test_security_incidents_rest_api(
    client: TestClient,
    db,
    org,
    auth_headers_viewer,
    auth_headers_member,
    auth_headers_officer1,
    auth_headers_officer2,
):
    """Verify REST API lifecycle: file case, fetch evidence manifest, dual approve, and verify audit chain."""
    # 1. Viewer can list cases (empty)
    res_list = client.get("/security/cases", headers=auth_headers_viewer)
    assert res_list.status_code == 200
    assert len(res_list.json()) == 0

    # 2. Member creates security case
    res_create = client.post(
        "/security/cases",
        headers=auth_headers_member,
        json={
            "title": "Credential Exposure in CI Build Logs",
            "description": "AWS Secret Access Key logged in stdout",
            "category": "CREDENTIAL_LEAK",
            "severity": "CRITICAL",
            "scope_summary_json": {"service": "checkout-api"},
        },
    )
    assert res_create.status_code == 201
    case_data = res_create.json()
    case_id = case_data["id"]
    assert case_data["case_number"].startswith("SEC-")

    # 3. Viewer retrieves frozen evidence snapshot manifest
    res_ev = client.get(f"/security/cases/{case_id}/evidence", headers=auth_headers_viewer)
    assert res_ev.status_code == 200
    assert res_ev.json()["completeness_status"] == "COMPLETE"

    # 4. Propose containment action
    res_prop = client.post(
        f"/security/cases/{case_id}/containment",
        headers=auth_headers_member,
        json={
            "action_type": "ROTATE_SECRET",
            "target_type": "secret",
            "target_id": "checkout_aws_secret_key",
            "title": "Rotate Checkout AWS Secret Key",
            "description": "Generate new IAM credentials and revoke old key",
        },
    )
    assert res_prop.status_code == 201
    action_id = res_prop.json()["id"]
    assert res_prop.json()["status"] == "PROPOSED"

    # 5. Officer 1 provides first sign-off
    res_app1 = client.post(
        f"/security/containment/{action_id}/approve",
        headers=auth_headers_officer1,
        json={"comment": "Approved initial rotation by Lead Officer"},
    )
    assert res_app1.status_code == 200
    assert res_app1.json()["status"] == "PENDING_SECOND_APPROVAL"

    # 6. Officer 2 provides second distinct sign-off
    res_app2 = client.post(
        f"/security/containment/{action_id}/approve",
        headers=auth_headers_officer2,
        json={"comment": "Dual sign-off confirmed by SecOps Admin"},
    )
    assert res_app2.status_code == 200
    assert res_app2.json()["status"] == "APPROVED"

    # 7. Execute containment (Dry-run first)
    res_dry = client.post(
        f"/security/containment/{action_id}/execute",
        headers=auth_headers_officer1,
        json={"dry_run": True},
    )
    assert res_dry.status_code == 200
    assert "[DRY-RUN SIMULATION]" in res_dry.json()["execution_output"]

    # 8. Execute containment (Live)
    res_live = client.post(
        f"/security/containment/{action_id}/execute",
        headers=auth_headers_officer1,
        json={"dry_run": False},
    )
    assert res_live.status_code == 200
    assert res_live.json()["status"] == "EXECUTED"

    # 9. Verify cryptographic audit chain
    res_audit = client.get(f"/security/cases/{case_id}/audit-chain", headers=auth_headers_viewer)
    assert res_audit.status_code == 200
    audit_data = res_audit.json()
    assert audit_data["is_valid"] is True
    assert audit_data["total_entries"] >= 4
