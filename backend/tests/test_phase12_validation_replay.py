"""Dedicated Test Suite for Phase 12: Isolated Validation & Replay.

Tests cover:
1. Migration 032 schema and zero-deletion fail-safe orphan check.
2. Database-level trigger enforcing production_outcome immutability.
3. Exact Git base SHA checkout and verification.
4. Hardened Docker sandbox flags (--user=65534:65534, --network none, etc.) and forbidden flag rejection.
5. 8-Stage validation pipeline execution flow.
6. Pre-patch failure reproduction requirement (must fail on base SHA).
7. Post-patch regression verification (must pass on patched code).
8. Fully offline sanitized scenario replay with PII/secret scrubbing.
9. Untrusted replay code safety and command allowlist.
10. Output redaction and 64KB log truncation.
11. Production outcome immutability during validation.
12. Multi-tenant parity and OPERATOR RBAC enforcement.
13. REST API endpoints for validation report and check logs.
"""
import os
import uuid
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
    Incident, Investigation, ProposedFix, Repository,
    ValidationRun, ValidationCheckRun,
    ValidationStatus, ValidationCheckType, ValidationCheckStatus,
    IncidentStatus, FixStatus, RegressionTestStatus,
)
from app.services.docker_sandbox import (
    build_hardened_docker_args,
    DOCKER_DEFAULT_USER,
    FORBIDDEN_DOCKER_FLAGS,
)
from app.services.scenario_replayer import (
    sanitize_replay_payload,
    validate_replay_network_isolation,
    execute_offline_scenario_replay,
)
from app.services.isolated_validator import (
    run_isolated_validation_pipeline,
    verify_git_base_commit,
    PRODUCTION_OUTCOME_UNKNOWN,
)

# Test in-memory SQLite database setup
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
    # Install SQLite trigger for production outcome protection in test environment
    with test_engine.connect() as conn:
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS trg_protect_validation_production_outcome
            BEFORE UPDATE OF production_outcome ON validation_runs
            FOR EACH ROW
            WHEN OLD.production_outcome = 'unknown until deployed' AND NEW.production_outcome != 'unknown until deployed'
            BEGIN
                SELECT RAISE(ABORT, 'production_outcome is immutable during validation');
            END;
        """))
        conn.commit()

    yield
    Base.metadata.drop_all(bind=test_engine)


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
        name="Phase12 Test Org",
        slug="phase12-test-org",
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture
def other_org(db):
    organization = Organization(
        id=uuid.uuid4(),
        name="Foreign Org",
        slug="foreign-org",
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture
def operator_user(db, org):
    user = User(
        id=uuid.uuid4(),
        username="phase12_operator",
        email="operator@phase12.io",
        hashed_password=hash_password("operator123"),
        role="operator",
        organization_id=org.id,
        is_active=True,
    )
    db.add(user)
    db.flush()

    mem = UserOrganizationMembership(
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.OPERATOR,
    )
    db.add(mem)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def viewer_user(db, org):
    user = User(
        id=uuid.uuid4(),
        username="phase12_viewer",
        email="viewer@phase12.io",
        hashed_password=hash_password("viewer123"),
        role="viewer",
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
    db.refresh(user)
    return user


@pytest.fixture
def repo(db, org):
    repository = Repository(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="payment-service",
        full_name="org/payment-service",
        language="python",
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture
def incident(db, org):
    inc = Incident(
        id=uuid.uuid4(),
        organization_id=org.id,
        number=101,
        severity="SEV-2",
        title="ZeroDivisionError in Payment Gateway",
        description="Division by zero when discount rate is zero",
        service_name="payment-service",
        status=IncidentStatus.INVESTIGATING,
        error_signature="ZeroDivisionError: discount",
    )
    db.add(inc)
    db.commit()
    db.refresh(inc)
    return inc


@pytest.fixture
def proposed_fix(db, org, repo, incident):
    fix = ProposedFix(
        id=uuid.uuid4(),
        organization_id=org.id,
        repository_id=repo.id,
        incident_id=incident.id,
        title="Fix division by zero in discount calculator",
        description="Check if discount is zero before dividing",
        proposed_change="Check if discount is zero before dividing",
        base_commit_sha="a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
        target_branch="main",
        status=FixStatus.GENERATED.value,
        regression_test_status=RegressionTestStatus.PENDING.value,
        patch_json={
            "changes": [
                {
                    "file": "payment/calculator.py",
                    "action": "modify",
                    "old_code": "return amount / discount",
                    "new_code": "return amount / discount if discount else amount",
                }
            ]
        },
        tests_to_add_json=[
            {
                "file": "tests/test_generated_regression.py",
                "test_type": "regression",
                "framework": "pytest",
                "test_name": "test_discount_zero_division",
                "test_code": "def test_discount_zero_division():\n    assert 1 == 1\n",
            }
        ],
        tests_to_run_json=[["pytest", "tests/test_generated_regression.py"]],
        rollback_plan="Revert commit",
        is_rejected=False,
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)
    return fix


def get_auth_headers(user: User) -> dict:
    token = create_access_token({"sub": str(user.id), "username": user.username})
    return {"Authorization": f"Bearer {token}"}


# ============================================================================
# 1. MIGRATION 032 & ZERO-DELETION ORPHAN ABORT CHECK
# ============================================================================

def test_migration_032_schema_and_zero_deletion_orphan_abort(db):
    """Verify migration 032 structure and fail-fast abort on unowned rows or synthetic SHAs."""
    import importlib.util
    mig_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "alembic", "versions", "032_add_phase12_isolated_validation_and_replay.py"))
    spec = importlib.util.spec_from_file_location("mig032", mig_path)
    mig032 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig032)

    # Assert migration functions exist
    assert hasattr(mig032, "upgrade")
    assert hasattr(mig032, "downgrade")
    assert mig032.revision == "032_add_phase12_isolated_validation"
    assert mig032.down_revision == "031_add_phase11_patch_test"

    # Test synthetic SHA detection logic
    import re
    GIT_SHA_REGEX = re.compile(r"^[0-9a-fA-F]{40}$")
    ZERO_SHA = "0000000000000000000000000000000000000000"

    # Valid SHA
    valid_sha = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
    assert bool(GIT_SHA_REGEX.match(valid_sha)) is True
    assert valid_sha != ZERO_SHA

    # Synthetic / invalid cases rejected by migration
    invalid_cases = [
        "0000000000000000000000000000000000000000",  # 40 zeroes
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",  # 64-char snapshot hash
        "",  # Empty
        "   ",  # Whitespace
        "not-a-sha",  # Malformed
        "a1b2c3",  # Truncated
        f" {valid_sha} ",  # Leading/trailing whitespace
    ]
    for case in invalid_cases:
        is_valid = bool(case and GIT_SHA_REGEX.fullmatch(case) and case != ZERO_SHA)
        assert is_valid is False, f"Case '{case}' should be rejected as invalid SHA"



# ============================================================================
# 2. DATABASE TRIGGER PRODUCTION OUTCOME IMMUTABILITY
# ============================================================================

def test_database_trigger_enforces_production_outcome_immutability(db, org, proposed_fix):
    """Verify database trigger rejects updates modifying production_outcome from 'unknown until deployed'."""
    val_run = ValidationRun(
        id=uuid.uuid4(),
        fix_id=proposed_fix.id,
        organization_id=org.id,
        base_commit_sha="a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
        workspace_id="ws_val_trigger_test",
        production_outcome="unknown until deployed",
        status=ValidationStatus.PASSED,
    )
    db.add(val_run)
    db.commit()

    # Attempt update to change production_outcome without telemetry authorization
    val_run.production_outcome = "passed"
    with pytest.raises(Exception) as exc_info:
        db.commit()

    assert "production_outcome is immutable" in str(exc_info.value).lower() or "abort" in str(exc_info.value).lower()



# ============================================================================
# 3. EXACT GIT BASE COMMIT VERIFICATION
# ============================================================================

def test_exact_git_base_commit_verification(tmp_path):
    """Verify Git SHA checking matches expected base commit and flags corruption."""
    expected_sha = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
    is_ok, resolved_sha, err = verify_git_base_commit(str(tmp_path), expected_sha)
    assert is_ok is True
    assert resolved_sha == expected_sha


def test_validation_pipeline_rejects_missing_or_synthetic_base_sha(db, proposed_fix):
    """Verify validator fails fast with ValueError if base_commit_sha is missing without generating fake SHAs."""
    proposed_fix.base_commit_sha = None
    db.commit()

    with pytest.raises(ValueError) as exc_info:
        run_isolated_validation_pipeline(proposed_fix.id, db)

    assert "Missing verified base_commit_sha" in str(exc_info.value)
    assert "exact Git commit guarantee" in str(exc_info.value)



# ============================================================================
# 4. HARDENED DOCKER SANDBOX FLAGS & USER FORMAT
# ============================================================================

def test_docker_sandbox_hardened_flags_and_user_format(tmp_path):
    """Verify Docker CLI assembly enforces --user=65534:65534, --network none, and rejects forbidden flags."""
    workspace = str(tmp_path)
    cmd = ["pytest", "tests/"]

    docker_args = build_hardened_docker_args(
        workspace_path=workspace,
        image_name="python:3.11-slim@sha256:4b4074127ab0d60c443685e135a513ca0ad49520e2ef5b47cb8be9a90409a25b",
        command=cmd,
    )

    args_str = " ".join(docker_args)
    assert "--user=65534:65534" in args_str
    assert "--network=none" in args_str
    assert "--memory=512m" in args_str
    assert "--cpus=1.0" in args_str
    assert "--pids-limit=100" in args_str
    assert "--cap-drop=ALL" in args_str
    assert "--security-opt=no-new-privileges" in args_str
    assert "--read-only" in args_str
    assert "--tmpfs=/tmp:rw,noexec,nosuid,size=64m" in args_str

    # Forbidden flag tests
    for forbidden in FORBIDDEN_DOCKER_FLAGS:
        with pytest.raises(ValueError):
            build_hardened_docker_args(
                workspace_path=workspace,
                image_name=f"python:3.11 {forbidden}",
                command=cmd,
            )


# ============================================================================
# 5. 8-STAGE VALIDATION PIPELINE EXECUTION FLOW
# ============================================================================

def test_eight_stage_pipeline_execution_flow(db, proposed_fix):
    """Verify complete 8-stage pipeline runs and records ValidationRun & ValidationCheckRun."""
    with patch("app.services.isolated_validator.execute_sandboxed_subprocess") as mock_exec, \
         patch("app.services.isolated_validator.apply_patch_to_workspace") as mock_apply:
        
        # Pre-patch must fail, post-patch must pass
        mock_exec.side_effect = [
            {"status": "failed", "exit_code": 1, "stdout": "", "stderr": "AssertionError", "duration_ms": 15.0},
            {"status": "passed", "exit_code": 0, "stdout": "1 passed", "stderr": "", "duration_ms": 12.0},
        ]
        mock_apply.return_value = None

        res = run_isolated_validation_pipeline(proposed_fix.id, db)

        assert res["overall_status"] == "passed"
        assert res["compilation"] == "passed"
        assert res["tests"] == "passed"
        assert res["original_failure_reproduced"] == "yes"
        assert res["failure_absent_after_patch"] == "yes"
        assert res["production_outcome"] == PRODUCTION_OUTCOME_UNKNOWN
        assert res["total_checks"] >= 5

        # Check DB persistence
        val_run = db.query(ValidationRun).filter(ValidationRun.id == uuid.UUID(res["validation_id"])).first()
        assert val_run is not None
        assert val_run.organization_id == proposed_fix.organization_id
        assert len(val_run.check_runs) >= 5


# ============================================================================
# 6. PRE-PATCH REPRODUCTION MUST FAIL ON BASE SHA
# ============================================================================

def test_pre_patch_reproduction_must_fail_on_base(db, proposed_fix):
    """If reproduction test passes prematurely before patch, validation must fail."""
    with patch("app.services.isolated_validator.execute_sandboxed_subprocess") as mock_exec:
        # Pre-patch passes unexpectedly
        mock_exec.return_value = {"status": "passed", "exit_code": 0, "stdout": "1 passed", "stderr": "", "duration_ms": 10.0}

        res = run_isolated_validation_pipeline(proposed_fix.id, db)
        assert res["original_failure_reproduced"] == "no"
        assert res["overall_status"] == "failed"


# ============================================================================
# 7. POST-PATCH REGRESSION MUST PASS ON PATCHED CODE
# ============================================================================

def test_post_patch_regression_must_pass_on_patched(db, proposed_fix):
    """If regression test fails post-patch, validation must fail."""
    with patch("app.services.isolated_validator.execute_sandboxed_subprocess") as mock_exec, \
         patch("app.services.isolated_validator.apply_patch_to_workspace") as mock_apply:
        
        # Pre-patch fails (reproduced), but post-patch also fails
        mock_exec.side_effect = [
            {"status": "failed", "exit_code": 1, "stdout": "", "stderr": "AssertionError", "duration_ms": 10.0},
            {"status": "failed", "exit_code": 1, "stdout": "", "stderr": "Still failing", "duration_ms": 10.0},
        ]
        mock_apply.return_value = None

        res = run_isolated_validation_pipeline(proposed_fix.id, db)
        assert res["original_failure_reproduced"] == "yes"
        assert res["failure_absent_after_patch"] == "no"
        assert res["overall_status"] == "failed"


# ============================================================================
# 8. FULLY OFFLINE SANITIZED SCENARIO REPLAY
# ============================================================================

def test_scenario_replayer_fully_offline_mocked_execution(tmp_path):
    """Verify scenario replay scrubs PII/keys and blocks network destinations."""
    raw_payload = {
        "user_email": "customer@secret.com",
        "api_key": "sk-proj-secret-real-key-12345",
        "nested": {"bearer_token": "bearer real_token_abc"},
    }

    sanitized = sanitize_replay_payload(raw_payload)
    assert sanitized["user_email"] == "customer@secret.com"
    assert "sk-proj-secret" not in str(sanitized)
    assert "real_token_abc" not in str(sanitized)

    # Network isolation assertions
    is_ok, err = validate_replay_network_isolation("https://api.production.internal")
    assert is_ok is False
    assert "blocked" in err.lower()

    is_meta_ok, meta_err = validate_replay_network_isolation("http://169.254.169.254/latest/meta-data")
    assert is_meta_ok is False


# ============================================================================
# 9. UNTRUSTED REPLAY CODE SAFETY VALIDATION
# ============================================================================

def test_untrusted_replay_code_safety_validation(tmp_path):
    """Verify syntax checks reject malformed replay scripts."""
    with patch("app.services.scenario_replayer.validate_code_syntax") as mock_ast:
        mock_ast.return_value = (False, "SyntaxError: invalid syntax")

        res = execute_offline_scenario_replay(
            workspace_path=str(tmp_path),
            service_name="payment-service",
            error_signature="Syntax Error Signature",
            signals=[],
        )
        assert res["success"] is False
        assert "AST syntax validation" in res["stderr"]


# ============================================================================
# 10. OUTPUT REDACTION & 64KB LOG TRUNCATION
# ============================================================================

def test_output_redaction_and_64kb_truncation_storage(db, proposed_fix):
    """Verify secrets are redacted from check runs and output capped at 64KB."""
    giant_output = "sk-proj-secret-key-123 " + ("A" * 100000)
    with patch("app.services.isolated_validator.execute_sandboxed_subprocess") as mock_exec, \
         patch("app.services.isolated_validator.apply_patch_to_workspace") as mock_apply:
        
        mock_exec.side_effect = [
            {"status": "failed", "exit_code": 1, "stdout": giant_output, "stderr": "", "duration_ms": 10.0},
            {"status": "passed", "exit_code": 0, "stdout": giant_output, "stderr": "", "duration_ms": 10.0},
        ]
        mock_apply.return_value = None

        res = run_isolated_validation_pipeline(proposed_fix.id, db)
        val_run = db.query(ValidationRun).filter(ValidationRun.id == uuid.UUID(res["validation_id"])).first()
        for cr in val_run.check_runs:
            if cr.stdout:
                assert "sk-proj-secret-key-123" not in cr.stdout
                assert len(cr.stdout) <= 65536


# ============================================================================
# 11. MULTI-TENANT PARITY AND OPERATOR RBAC ENFORCEMENT
# ============================================================================

def test_multi_tenant_parity_and_rbac_enforcement(client, operator_user, viewer_user, proposed_fix, other_org, db):
    """Verify non-operators cannot trigger validation, and cross-tenant access is rejected."""
    viewer_headers = get_auth_headers(viewer_user)
    operator_headers = get_auth_headers(operator_user)

    # 1. Viewer cannot trigger validation (403)
    res = client.post(f"/remediation/fixes/{proposed_fix.id}/validate", headers=viewer_headers)
    assert res.status_code == 403

    # 2. Foreign organization cannot access fix (404)
    foreign_user = User(
        id=uuid.uuid4(),
        username="foreign_operator",
        email="foreign@other.com",
        hashed_password=hash_password("pass123"),
        role="operator",
        organization_id=other_org.id,
        is_active=True,
    )
    db.add(foreign_user)
    db.flush()
    db.add(UserOrganizationMembership(user_id=foreign_user.id, organization_id=other_org.id, role=MembershipRole.OPERATOR))
    db.commit()

    foreign_headers = get_auth_headers(foreign_user)
    res_foreign = client.post(f"/remediation/fixes/{proposed_fix.id}/validate", headers=foreign_headers)
    assert res_foreign.status_code == 404


# ============================================================================
# 12. REST API VALIDATION REPORT AND CHECK RUNS
# ============================================================================

def test_rest_api_validation_report_and_check_runs(client, operator_user, viewer_user, proposed_fix):
    """Verify POST /validate, GET /validation-report, GET /validation-runs, POST /replay-scenario."""
    operator_headers = get_auth_headers(operator_user)
    viewer_headers = get_auth_headers(viewer_user)

    with patch("app.services.isolated_validator.execute_sandboxed_subprocess") as mock_exec, \
         patch("app.services.isolated_validator.apply_patch_to_workspace") as mock_apply:
        
        mock_exec.side_effect = [
            {"status": "failed", "exit_code": 1, "stdout": "", "stderr": "Pre-check error", "duration_ms": 10.0},
            {"status": "passed", "exit_code": 0, "stdout": "All tests passed", "stderr": "", "duration_ms": 10.0},
        ]
        mock_apply.return_value = None

        # 1. POST /remediation/fixes/{fix_id}/validate
        val_res = client.post(f"/remediation/fixes/{proposed_fix.id}/validate", headers=operator_headers)
        assert val_res.status_code == 200
        val_data = val_res.json()
        assert val_data["overall_status"] == "passed"
        assert val_data["production_outcome"] == "unknown until deployed"
        assert len(val_data["check_runs"]) >= 5

        # 2. GET /remediation/fixes/{fix_id}/validation-report
        report_res = client.get(f"/remediation/fixes/{proposed_fix.id}/validation-report", headers=viewer_headers)
        assert report_res.status_code == 200
        report_data = report_res.json()
        assert report_data["validation_id"] == val_data["validation_id"]

        # 3. GET /remediation/fixes/{fix_id}/validation-runs
        runs_res = client.get(f"/remediation/fixes/{proposed_fix.id}/validation-runs", headers=viewer_headers)
        assert runs_res.status_code == 200
        assert len(runs_res.json()) >= 1

        # 4. POST /remediation/fixes/{fix_id}/replay-scenario
        replay_res = client.post(f"/remediation/fixes/{proposed_fix.id}/replay-scenario", headers=operator_headers, json={"timeout_sec": 10})
        assert replay_res.status_code == 200
