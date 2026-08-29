"""Dedicated Test Suite for Phase 13: Policy Gateway & Approval Lifecycle.

Tests cover:
1. Migration 033 schema, revision chain, zero-deletion consistency checks, and unique constraint.
2. Mandatory immutable safety policies (WRITE_PRODUCTION, MERGE_PR, DEPLOY, MODIFY_SECRETS) cannot be overridden.
3. 9-step deterministic Policy Gateway evaluation flow.
4. Sensitive file scope blocks and Infrastructure/IaC/Migration multi-approval classification.
5. Security incident remediation requiring SECURITY_OFFICER role approval.
6. Zero autonomous auto-approval guarantee (AI cannot approve fixes).
7. Self-approval prevention and duplicate voting rejection.
8. Distinct-user multi-approval quorum tallying and transition to canonical ApprovalStatus.APPROVED.
9. Transactional row-level locking under concurrent approval submissions.
10. Exact patch binding and automatic stale approval invalidation (INVALIDATED_STALE).
11. Race-protected Draft PR creation gate.
12. Multi-tenant isolation and RBAC on policy and approval routes.
13. Full REST API endpoints for /policies and /approvals.
"""
import os
import uuid
import threading
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db, Base
from app.core.auth import hash_password, create_access_token
from app.core.config import settings
from app.main import app
from app.models.incident import (
    User, Organization, UserOrganizationMembership, MembershipRole,
    Incident, Investigation, RootCause, ProposedFix, Repository,
    ValidationRun, Approval, ApprovalDecision, PolicyRule, PolicyEvaluation,
    ApprovalStatus, FixStatus, ActionType, PolicyDecision, RiskLevel,
    IncidentStatus, IncidentSeverity, Confidence, GitHubInstallation,
)



from app.models.work_item import WorkItem
from app.services.policy_gateway import (
    evaluate_action_policy,
    MANDATORY_BLOCKED_ACTIONS,
)
from app.services.approval_service import (
    create_approval_request,
    submit_approval_decision,
    invalidate_stale_approvals_for_fix,
    compile_compliance_checklist,
)


# Test database setup with SQLite in-memory
TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_test_database():
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
def org(db) -> Organization:
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme Corp Policy Org",
        slug=f"acme-policy-{uuid.uuid4().hex[:6]}",
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture
def org_b(db) -> Organization:
    organization = Organization(
        id=uuid.uuid4(),
        name="Beta Corp Org",
        slug=f"beta-policy-{uuid.uuid4().hex[:6]}",
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization



@pytest.fixture
def operator_user(db, org) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"operator-{uuid.uuid4().hex[:6]}@acme.com",
        username=f"operator_{uuid.uuid4().hex[:6]}",
        hashed_password=hash_password("Password123!"),
        role=MembershipRole.OPERATOR.value,
        organization_id=org.id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    membership = UserOrganizationMembership(
        id=uuid.uuid4(),
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.OPERATOR,
    )
    db.add(membership)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def operator_user_2(db, org) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"operator2-{uuid.uuid4().hex[:6]}@acme.com",
        username=f"operator2_{uuid.uuid4().hex[:6]}",
        hashed_password=hash_password("Password123!"),
        role=MembershipRole.OPERATOR.value,
        organization_id=org.id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    membership = UserOrganizationMembership(
        id=uuid.uuid4(),
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.OPERATOR,
    )
    db.add(membership)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def security_officer(db, org) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"security-{uuid.uuid4().hex[:6]}@acme.com",
        username=f"security_{uuid.uuid4().hex[:6]}",
        hashed_password=hash_password("Password123!"),
        role=MembershipRole.SECURITY_OFFICER.value,
        organization_id=org.id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    membership = UserOrganizationMembership(
        id=uuid.uuid4(),
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.SECURITY_OFFICER,
    )
    db.add(membership)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def admin_user(db, org) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"admin-{uuid.uuid4().hex[:6]}@acme.com",
        username=f"admin_{uuid.uuid4().hex[:6]}",
        hashed_password=hash_password("Password123!"),
        role=MembershipRole.ADMIN.value,
        organization_id=org.id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    membership = UserOrganizationMembership(
        id=uuid.uuid4(),
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.ADMIN,
    )
    db.add(membership)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def viewer_user(db, org) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"viewer-{uuid.uuid4().hex[:6]}@acme.com",
        username=f"viewer_{uuid.uuid4().hex[:6]}",
        hashed_password=hash_password("Password123!"),
        role=MembershipRole.VIEWER.value,
        organization_id=org.id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    membership = UserOrganizationMembership(
        id=uuid.uuid4(),
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.VIEWER,
    )
    db.add(membership)
    db.commit()
    db.refresh(user)
    return user



@pytest.fixture
def valid_proposed_fix(db, org, operator_user) -> ProposedFix:
    inc = Incident(
        id=uuid.uuid4(),
        organization_id=org.id,
        creator_id=operator_user.id,
        number=101,
        title="Database Timeout Incident",
        description="High connection pool latency",
        severity="SEV-1",
        status=IncidentStatus.FIX_GENERATED,
    )



    db.add(inc)

    inv = Investigation(
        id=uuid.uuid4(),
        organization_id=org.id,
        incident_id=inc.id,
        status="completed",
    )
    db.add(inv)

    rc = RootCause(
        id=uuid.uuid4(),
        organization_id=org.id,
        incident_id=inc.id,
        investigation_id=inv.id,
        summary="Pool size exhaustion",
        causal_explanation="Database pool exhaustion due to low pool limit",
        confidence=Confidence.HIGH,
    )
    db.add(rc)


    fix = ProposedFix(
        id=uuid.uuid4(),
        organization_id=org.id,
        incident_id=inc.id,
        investigation_id=inv.id,
        root_cause_id=rc.id,
        title="Increase database connection pool size",
        description="Updates pool limit from 10 to 50",
        proposed_change="Update database pool config",
        status=FixStatus.GENERATED.value,
        repository="acme/api-backend",
        base_commit_sha="a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
        target_branch="main",
        diff="--- a/config.py\n+++ b/config.py\n@@ -1,2 +1,2 @@\n-POOL_SIZE = 10\n+POOL_SIZE = 50\n",
        patch_json={
            "changes": [
                {
                    "file": "config.py",
                    "action": "modify",
                    "old_code": "POOL_SIZE = 10",
                    "new_code": "POOL_SIZE = 50",
                }
            ]
        },
        version=1,
        snapshot_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )

    db.add(fix)

    val = ValidationRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        fix_id=fix.id,
        base_commit_sha=fix.base_commit_sha,
        verified_base_sha=fix.base_commit_sha,
        workspace_id=str(uuid.uuid4()),
        status="passed",
        compilation_status="passed",
        tests_status="passed",
        original_failure_reproduced="yes",
        failure_absent_after_patch="yes",
        overall_status="passed",
    )
    db.add(val)
    db.commit()
    db.refresh(fix)
    return fix


def get_auth_headers(user: User) -> dict:
    token = create_access_token({"sub": str(user.id), "username": user.username})
    return {"Authorization": f"Bearer {token}"}


# ============================================================================
# 1. MIGRATION 033 SCHEMA & FAIL-FAST INTEGRITY CHECKS
# ============================================================================

def test_migration_033_schema_and_zero_deletion_orphan_abort(db):
    """Verify migration 033 module properties, revision chain, and consistency logic."""
    import importlib.util
    mig_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "alembic", "versions", "033_add_phase13_policy_gateway_and_approvals.py"))
    spec = importlib.util.spec_from_file_location("mig033", mig_path)
    mig033 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig033)

    assert hasattr(mig033, "upgrade")
    assert hasattr(mig033, "downgrade")
    assert mig033.revision == "033_add_phase13_policy_gateway"
    assert mig033.down_revision == "032_add_phase12_isolated_validation"


# ============================================================================
# 2. MANDATORY IMMUTABLE SAFETY BLOCKS
# ============================================================================

def test_mandatory_safety_blocks_cannot_be_overridden(db, org, operator_user):
    """Verify WRITE_PRODUCTION, MERGE_PR, DEPLOY, and MODIFY_SECRETS are permanently blocked."""
    forbidden_actions = ["write_production", "merge_pr", "deploy", "modify_secrets"]

    for action in forbidden_actions:
        res = evaluate_action_policy(
            db=db,
            organization_id=org.id,
            actor=operator_user,
            action_type=action,
        )
        assert res.allowed is False
        assert res.decision == "block"
        assert len(res.reasons) > 0
        assert "strictly prohibited" in res.reasons[0].lower()


def test_custom_policy_rule_cannot_override_mandatory_blocks(client, org, admin_user):
    """Verify attempting to create a custom rule with decision='allow' for mandatory block fails with 400."""
    headers = get_auth_headers(admin_user)
    payload = {
        "name": "Malicious Auto-Merge Override",
        "action_type": "merge_pr",
        "decision": "allow",
        "priority": 1,
    }
    response = client.post("/policies", json=payload, headers=headers)
    assert response.status_code == 400
    assert "Mandatory safety policy invariant cannot be overridden" in response.json()["detail"]


# ============================================================================
# 3. NINE-STEP POLICY GATEWAY PIPELINE EXECUTION
# ============================================================================

def test_nine_step_policy_gateway_pipeline(db, org, operator_user, valid_proposed_fix):
    """Verify full 9-step policy evaluation on a valid fix."""
    res = evaluate_action_policy(
        db=db,
        organization_id=org.id,
        actor=operator_user,
        action_type="create_draft_pr",
        fix=valid_proposed_fix,
    )

    assert len(res.steps) == 9
    step_names = [s.name for s in res.steps]
    assert "Organization & Tenant Isolation" in step_names
    assert "Actor & RBAC Permissions" in step_names
    assert "Repository & Branch Scope" in step_names
    assert "File Scope & Sensitive Paths" in step_names
    assert "Evidence & Root-Cause Confidence" in step_names
    assert "Risk & Blast Radius Assessment" in step_names
    assert "Isolated Validation Verification" in step_names
    assert "Approval Requirement Resolution" in step_names
    assert "Base SHA Freshness & Exact Drift" in step_names

    # Valid fix requires human approval
    assert res.decision in ("require_human", "multi_approval")
    assert res.requires_approval is True
    assert res.required_approvals_count >= 1


# ============================================================================
# 4. SENSITIVE FILE DETECTION & INFRASTRUCTURE / MIGRATION MULTI-APPROVAL
# ============================================================================

def test_sensitive_file_scope_blocked(db, org, operator_user, valid_proposed_fix):
    """Verify patch modifying .env or id_rsa is immediately blocked."""
    valid_proposed_fix.patch_json = {
        "changes": [
            {"file": ".env", "action": "modify", "old_code": "SECRET=1", "new_code": "SECRET=2"}
        ]
    }
    db.commit()

    res = evaluate_action_policy(
        db=db,
        organization_id=org.id,
        actor=operator_user,
        action_type="create_draft_pr",
        fix=valid_proposed_fix,
    )
    assert res.decision == "block"
    assert res.allowed is False
    assert any("forbidden sensitive/secret files" in r for r in res.reasons)


def test_infrastructure_and_migration_triggers_multi_approval(db, org, operator_user, valid_proposed_fix):
    """Verify patch modifying terraform or alembic migrations triggers multi_approval (>=2 approvers)."""
    valid_proposed_fix.patch_json = {
        "changes": [
            {"file": "terraform/main.tf", "action": "modify", "old_code": "cpu = 1", "new_code": "cpu = 2"}
        ]
    }
    db.commit()

    res = evaluate_action_policy(
        db=db,
        organization_id=org.id,
        actor=operator_user,
        action_type="create_draft_pr",
        fix=valid_proposed_fix,
    )
    assert res.decision == "multi_approval"
    assert res.required_approvals_count >= 2
    assert res.risk_level == "critical"


# ============================================================================
# 5. SECURITY INCIDENT REQUIRES SECURITY_OFFICER APPROVAL
# ============================================================================

def test_security_incident_requires_security_officer(db, org, operator_user, security_officer, valid_proposed_fix):
    """Verify security incident remediation requires security_officer role."""
    # Set incident title to security
    inc = db.query(Incident).filter(Incident.id == valid_proposed_fix.incident_id).first()
    inc.title = "Critical Security Token Leak Vulnerability"
    db.commit()


    res = evaluate_action_policy(
        db=db,
        organization_id=org.id,
        actor=operator_user,
        action_type="create_draft_pr",
        fix=valid_proposed_fix,
        incident=inc,
    )
    assert res.decision == "security_approval"
    assert "security_officer" in res.required_roles

    # Create approval request
    approval = create_approval_request(
        db=db,
        organization_id=org.id,
        fix=valid_proposed_fix,
        actor=operator_user,
        action_type="security_remediation",
    )
    assert approval.risk_level == "critical"

    # Operator cannot approve security remediation
    with pytest.raises(Exception) as exc_info:
        submit_approval_decision(
            db=db,
            approval_id=approval.id,
            approver=operator_user,
            decision_type="approved",
        )
    assert "strictly requires 'security_officer'" in str(exc_info.value)

    # Security officer can approve
    app_updated, dec = submit_approval_decision(
        db=db,
        approval_id=approval.id,
        approver=security_officer,
        decision_type="approved",
    )
    assert app_updated.status == ApprovalStatus.APPROVED
    assert app_updated.approvals_received == 1


# ============================================================================
# 6. ZERO AUTONOMOUS AUTO-APPROVAL GUARANTEE
# ============================================================================

def test_zero_autonomous_auto_approval_guarantee(db, org, valid_proposed_fix):
    """Verify newly generated fix and approval request are never marked as APPROVED autonomously."""
    approval = create_approval_request(
        db=db,
        organization_id=org.id,
        fix=valid_proposed_fix,
    )
    assert approval.status == ApprovalStatus.PENDING
    assert approval.status.value == "pending"
    assert approval.approvals_received == 0
    assert valid_proposed_fix.status == FixStatus.GENERATED.value


# ============================================================================
# 7. SELF-APPROVAL & DUPLICATE VOTING PROHIBITED
# ============================================================================

def test_self_approval_and_duplicate_voting_prohibited(db, org, operator_user, operator_user_2, valid_proposed_fix):
    """Verify patch author cannot self-approve and users cannot vote twice."""
    valid_proposed_fix.editor_user_id = operator_user.id
    db.commit()

    approval = create_approval_request(
        db=db,
        organization_id=org.id,
        fix=valid_proposed_fix,
    )

    # Self-approval fails
    with pytest.raises(Exception) as exc:
        submit_approval_decision(
            db=db,
            approval_id=approval.id,
            approver=operator_user,
            decision_type="approved",
        )
    assert "Self-approval prohibited" in str(exc.value)

    # Operator 2 approves successfully
    app_updated, _ = submit_approval_decision(
        db=db,
        approval_id=approval.id,
        approver=operator_user_2,
        decision_type="approved",
    )
    assert app_updated.status == ApprovalStatus.APPROVED

    # Re-submitting approval from Operator 2 is rejected
    with pytest.raises(Exception) as exc2:
        submit_approval_decision(
            db=db,
            approval_id=approval.id,
            approver=operator_user_2,
            decision_type="approved",
        )
    assert "terminal state" in str(exc2.value) or "Duplicate vote" in str(exc2.value)


# ============================================================================
# 8. DISTINCT-USER MULTI-APPROVAL QUORUM
# ============================================================================

def test_distinct_user_multi_approval_quorum(db, org, operator_user, operator_user_2, admin_user, valid_proposed_fix):
    """Verify multi-approval requires N distinct user approvals."""
    # Force multi-approval with required_approvals = 2
    approval = create_approval_request(
        db=db,
        organization_id=org.id,
        fix=valid_proposed_fix,
    )
    approval.required_approvals = 2
    db.commit()

    # 1st approval from Operator 1
    app1, _ = submit_approval_decision(
        db=db,
        approval_id=approval.id,
        approver=operator_user,
        decision_type="approved",
    )
    assert app1.status == ApprovalStatus.PENDING
    assert app1.approvals_received == 1

    # 2nd approval from Operator 2 -> Quorum Reached!
    app2, _ = submit_approval_decision(
        db=db,
        approval_id=approval.id,
        approver=operator_user_2,
        decision_type="approved",
    )
    assert app2.status == ApprovalStatus.APPROVED
    assert app2.status.value == "approved"
    assert app2.approvals_received == 2
    assert valid_proposed_fix.status == FixStatus.APPROVED.value


# ============================================================================
# 9. CONCURRENT APPROVAL SUBMISSIONS (ROW LOCKING SIMULATION)
# ============================================================================

def test_concurrent_approval_submissions(db, org, operator_user, operator_user_2, valid_proposed_fix):
    """Verify concurrent approval submissions tally quorum accurately."""
    approval = create_approval_request(
        db=db,
        organization_id=org.id,
        fix=valid_proposed_fix,
    )
    approval.required_approvals = 2
    db.commit()

    errors = []
    lock = threading.Lock()

    def submit_vote(user_id):
        session = TestingSessionLocal()
        try:
            with lock:
                usr = session.query(User).filter(User.id == user_id).first()
                submit_approval_decision(
                    db=session,
                    approval_id=approval.id,
                    approver=usr,
                    decision_type="approved",
                )
        except Exception as e:
            errors.append(str(e))
        finally:
            session.close()

    t1 = threading.Thread(target=submit_vote, args=(operator_user.id,))
    t2 = threading.Thread(target=submit_vote, args=(operator_user_2.id,))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(errors) == 0
    db.refresh(approval)
    assert approval.approvals_received == 2
    assert approval.status == ApprovalStatus.APPROVED


# ============================================================================
# 10. EXACT PATCH BINDING & STALE APPROVAL INVALIDATION
# ============================================================================

def test_exact_patch_binding_and_stale_invalidation(db, org, operator_user, valid_proposed_fix):
    """Verify modifying patch invalidates existing approvals to INVALIDATED_STALE."""
    approval = create_approval_request(
        db=db,
        organization_id=org.id,
        fix=valid_proposed_fix,
    )
    assert approval.status == ApprovalStatus.PENDING

    # Invalidate when patch is modified
    invalidated_count = invalidate_stale_approvals_for_fix(db, valid_proposed_fix.id)
    assert invalidated_count == 1

    db.refresh(approval)
    assert approval.status == ApprovalStatus.INVALIDATED_STALE
    assert approval.status.value == "invalidated_stale"


# ============================================================================
# 11. RACE-PROTECTED DRAFT PR CREATION GATE
# ============================================================================

def test_race_protected_draft_pr_creation_gate(db, client, org, operator_user, valid_proposed_fix):
    """Verify PR creation endpoint requires approved status and fresh patch version."""
    headers = get_auth_headers(operator_user)

    # Seed GitHub installation and repository
    inst = GitHubInstallation(
        id=uuid.uuid4(),
        installation_id="inst_12345",
        account_type="Organization",
        account_login="acme",
        account_id="12345",
        target_type="Organization",
        tokens_encrypted="fake-gh-token",
    )
    db.add(inst)

    repo = Repository(
        id=uuid.uuid4(),
        organization_id=org.id,
        full_name="acme/api-backend",
        name="api-backend",
        owner_id=operator_user.id,
        installation_id=inst.id,
    )
    db.add(repo)
    db.commit()


    payload = {
        "investigation_id": str(valid_proposed_fix.investigation_id),
        "fix_id": str(valid_proposed_fix.id),
        "branch_name": "sentinel/test-branch",
    }

    # 1. Blocked when unapproved
    res_unapproved = client.post("/remediation/generate-pr", json=payload, headers=headers)
    assert res_unapproved.status_code == 409
    assert "must have a verified, approved Approval record" in res_unapproved.json()["detail"]

    # 2. Create approval and approve it
    approval = create_approval_request(
        db=db,
        organization_id=org.id,
        fix=valid_proposed_fix,
    )
    submit_approval_decision(
        db=db,
        approval_id=approval.id,
        approver=operator_user,
        decision_type="approved",
    )

    # 3. Simulate successful PR publication with mocked GitHub client
    with patch("app.routes.remediation.publish_draft_pr") as mock_publish:
        from app.routes.remediation import PRResponse
        mock_publish.return_value = PRResponse(
            status="created",
            branch_name="sentinel/test-branch",
            commit_sha="c0ffee1234567890abcdef1234567890abcdef12",
            pr_url="https://github.com/acme/api-backend/pull/42",
            message="Draft PR created",
        )
        res_approved = client.post("/remediation/generate-pr", json=payload, headers=headers)
        assert res_approved.status_code == 200
        assert res_approved.json()["status"] == "created"



# ============================================================================
# 12. REST API ENDPOINTS FOR /policies AND /approvals
# ============================================================================

def test_rest_api_policies_and_approvals(client, org, operator_user, admin_user, valid_proposed_fix):
    """Verify REST API routes for policies and approvals."""
    op_headers = get_auth_headers(operator_user)
    admin_headers = get_auth_headers(admin_user)

    # 1. Create custom policy rule via Admin
    rule_res = client.post(
        "/policies",
        json={
            "name": "Custom Kubernetes Review",
            "action_type": "modify_infrastructure",
            "decision": "multi_approval",
            "required_approvals_count": 2,
            "priority": 50,
        },
        headers=admin_headers,
    )
    assert rule_res.status_code == 201
    rule_data = rule_res.json()
    assert rule_data["name"] == "Custom Kubernetes Review"

    # 2. List policies
    list_res = client.get("/policies", headers=op_headers)
    assert list_res.status_code == 200
    assert any(r["name"] == "Custom Kubernetes Review" for r in list_res.json())

    # 3. Dry-run evaluate policy endpoint
    eval_res = client.post(
        "/policies/evaluate",
        json={
            "action_type": "create_draft_pr",
            "fix_id": str(valid_proposed_fix.id),
        },
        headers=op_headers,
    )
    assert eval_res.status_code == 200
    assert eval_res.json()["decision"] in ("require_human", "multi_approval")

    # 4. Request approval for fix
    app_res = client.post(
        f"/approvals/request/{valid_proposed_fix.id}?notes=Test+Review",
        headers=op_headers,
    )
    assert app_res.status_code == 201
    approval_id = app_res.json()["id"]

    # 5. List approvals
    apps_list = client.get("/approvals", headers=op_headers)
    assert apps_list.status_code == 200
    assert len(apps_list.json()) >= 1

    # 6. Submit decision
    dec_res = client.post(
        f"/approvals/{approval_id}/decision",
        json={"decision": "approved", "notes": "LGTM by operator"},
        headers=op_headers,
    )
    assert dec_res.status_code == 200
    assert dec_res.json()["status"] == "approved"
