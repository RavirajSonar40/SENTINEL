"""Phase 11 Test Suite — Patch Generation, Test Generation, Pre-Flight Safety, and Versioning."""
import os
import sys
import uuid
import shutil
import pytest
from datetime import datetime, timezone
from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.auth import create_access_token
from app.main import app
from app.models.incident import (
    User, Organization, Repository, Incident, Investigation, RootCause,
    ProposedFix, FixFile, GeneratedTest, PatchVersion,
    MembershipRole, UserOrganizationMembership,
    FixStatus, TestType, RegressionTestStatus, RevalidationStatus,
)
from app.models.work_item import WorkItem, WorkType, WorkItemStatus
from app.services.ast_validator import (
    validate_python_syntax,
    validate_json_syntax,
    validate_yaml_syntax,
    validate_javascript_syntax,
    validate_typescript_syntax,
    validate_go_syntax,
    validate_shell_syntax,
    validate_rust_syntax,
    validate_code_syntax,
)
from app.services.patch_safety_engine import (
    validate_patch_safety,
    sanitize_relative_path,
    compute_patch_snapshot_hash,
    check_boilerplate_hallucination,
)
from app.services.patch_test_runner import (
    validate_command_array,
    build_sandboxed_environment,
    resolve_contained_workspace_path,
    apply_patch_to_workspace,
    run_sandboxed_command,
    execute_two_phase_regression_test,
)
from app.services.patch_generator import (
    generate_unified_diff,
    build_direct_task_readme,
    synthesize_patch_and_tests,
)


# In-memory SQLite with StaticPool for deterministic test isolation
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=test_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
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
    o = Organization(name="Sentinel Security Corp", slug=f"sentinel-sec-{uuid.uuid4().hex[:6]}")
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


@pytest.fixture
def other_org(db):
    o = Organization(name="External Tenant Corp", slug=f"external-{uuid.uuid4().hex[:6]}")
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


@pytest.fixture
def admin_user(db, org):
    uid = uuid.uuid4().hex[:6]
    u = User(
        username=f"admin_{uid}",
        email=f"admin-{uid}@sentinel.io",
        hashed_password="hashed_test_password",
        role="admin",
        organization_id=org.id,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)

    m = UserOrganizationMembership(
        user_id=u.id,
        organization_id=org.id,
        role=MembershipRole.OWNER,
    )
    db.add(m)
    db.commit()
    return u


@pytest.fixture
def operator_user(db, org):
    uid = uuid.uuid4().hex[:6]
    u = User(
        username=f"operator_{uid}",
        email=f"operator-{uid}@sentinel.io",
        hashed_password="hashed_test_password",
        role="operator",
        organization_id=org.id,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)

    m = UserOrganizationMembership(
        user_id=u.id,
        organization_id=org.id,
        role=MembershipRole.OPERATOR,
    )
    db.add(m)
    db.commit()
    return u


@pytest.fixture
def repo(db, org):
    r = Repository(
        organization_id=org.id,
        name="payment-service",
        full_name="sentinel/payment-service",
        default_branch="main",
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@pytest.fixture
def incident(db, org, admin_user):
    import random
    from app.models.incident import IncidentSeverity, IncidentStatus
    inc = Incident(
        number=random.randint(10000, 99999),
        organization_id=org.id,
        title="High Latency on Payment Gateway",
        description="Payment gateway timed out during peak load",
        severity=IncidentSeverity.SEV2,
        status=IncidentStatus.INVESTIGATING,
        creator_id=admin_user.id,
    )
    db.add(inc)
    db.commit()
    db.refresh(inc)
    return inc


@pytest.fixture
def work_item(db, org, incident, repo):
    w = WorkItem(
        organization_id=org.id,
        title="Increase Connection Pool Size",
        description="Modify redis_client.py to increase max_connections to 50",
        work_type=WorkType.DIRECT_TASK,
        status=WorkItemStatus.CREATED,
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


def get_auth_headers(user: User) -> dict:
    token = create_access_token(data={"sub": str(user.id)})
    return {"Authorization": f"Bearer {token}"}


# ============================================================================
# 1. MIGRATION 031 SCHEMA EXECUTION
# ============================================================================

def test_migration_031_schema_execution(db, org, incident, repo, work_item):
    """Verify Migration 031 creates all tables, foreign keys, and indexes cleanly."""
    fix = ProposedFix(
        organization_id=org.id,
        incident_id=incident.id,
        work_item_id=work_item.id,
        repository_id=repo.id,
        repository=repo.full_name,
        base_commit_sha="a1b2c3d4e5f6789012345678901234567890abcd",
        target_branch="main",
        title="Fix Connection Pool Defect",
        description="Increases pool size",
        proposed_change="max_connections = 50",
        diff="--- a/pool.py\n+++ b/pool.py",
        patch_json={"changes": [{"file": "pool.py", "action": "modify", "old_code": "10", "new_code": "50"}]},
        scope_files_json=["pool.py"],
        rollback_plan="Revert pool.py",
        regression_test_status=RegressionTestStatus.REPRODUCED_AND_FIXED.value,
        snapshot_hash="abcd1234ef567890hash",
        version=1,
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)

    test = GeneratedTest(
        organization_id=org.id,
        fix_id=fix.id,
        file_path="tests/test_pool.py",
        test_type=TestType.REGRESSION,
        framework="pytest",
        test_name="test_pool_size",
        test_code="def test_pool(): assert True",
        target_symbol="RedisPool",
        pre_patch_result="failed",
        post_patch_result="passed",
    )
    db.add(test)

    ver = PatchVersion(
        organization_id=org.id,
        fix_id=fix.id,
        version_number=1,
        editor_user_id=None,
        patch_data_json=fix.patch_json,
        diff_content=fix.diff,
        previous_snapshot_hash=None,
        new_snapshot_hash=fix.snapshot_hash,
        revalidation_status=RevalidationStatus.PASSED.value,
    )
    db.add(ver)
    db.commit()

    saved_fix = db.query(ProposedFix).filter(ProposedFix.id == fix.id).first()
    assert saved_fix is not None
    assert len(saved_fix.generated_tests) == 1
    assert len(saved_fix.versions) == 1
    assert saved_fix.generated_tests[0].framework == "pytest"
    assert saved_fix.versions[0].new_snapshot_hash == "abcd1234ef567890hash"


# ============================================================================
# 2. AST & COMPILER SYNTAX VALIDATION ACROSS LANGUAGES
# ============================================================================

def test_ast_syntax_validation_per_language():
    """Verify real AST & compiler syntax validation across Python, JSON, YAML, JS/TS."""
    # Python
    ok, err = validate_python_syntax("def add(a, b):\n    return a + b\n")
    assert ok is True and err is None

    ok, err = validate_python_syntax("def bad_syntax(a, b:\n    return a + b\n")
    assert ok is False and "SyntaxError" in err

    # JSON
    ok, err = validate_json_syntax('{"key": "value", "numbers": [1, 2, 3]}')
    assert ok is True and err is None

    ok, err = validate_json_syntax('{"key": "value", "unclosed": [1, 2, }')
    assert ok is False and "DecodeError" in err

    # YAML
    ok, err = validate_yaml_syntax("services:\n  web:\n    port: 8080\n")
    assert ok is True and err is None

    ok, err = validate_yaml_syntax("services:\n  web:\n    port: [1, 2")
    assert ok is False

    # JavaScript
    ok, err = validate_javascript_syntax("function calculate(x) { return x * 2; }")
    assert ok is True

    ok, err = validate_javascript_syntax("function calculate(x) { return x * 2; ")
    assert ok is False and "SyntaxError" in err

    # TypeScript (via real compiler)
    ts_code_valid = """interface PaymentConfig {
    timeoutMs: number;
    retries: number;
}
export function configurePayment(cfg: PaymentConfig): boolean {
    return cfg.timeoutMs > 0;
}
"""
    ok_ts, err_ts = validate_typescript_syntax(ts_code_valid)
    assert ok_ts is True

    ts_code_invalid = """interface PaymentConfig {
    timeoutMs: number
    retries:
}
"""
    ok_ts_bad, err_ts_bad = validate_typescript_syntax(ts_code_invalid)
    assert ok_ts_bad is False and ("SyntaxError" in err_ts_bad or "error TS" in err_ts_bad)


def test_missing_tool_fails_closed(monkeypatch):
    """Verify that when a required compiler tool is missing, validation returns failure rather than passing."""
    # Mock shutil.which to return None for Go and Shell
    monkeypatch.setattr(shutil, "which", lambda cmd: None)

    ok_go, err_go = validate_go_syntax("package main\nfunc main() {}")
    assert ok_go is False
    assert "unavailable" in err_go

    ok_sh, err_sh = validate_shell_syntax("echo 'test'")
    assert ok_sh is False
    assert "unavailable" in err_sh

    ok_rs, err_rs = validate_rust_syntax("fn main() {}")
    assert ok_rs is False
    assert "unavailable" in err_rs


# ============================================================================
# 3. PRE-FLIGHT PATCH SAFETY & REJECTION ENGINE
# ============================================================================

def test_patch_safety_rejects_ambiguous_old_code():
    """Verify rejection when old_code count is not strictly 1."""
    source_file = "def helper():\n    return 10\ndef other():\n    return 10\n"
    file_contents = {"helper.py": source_file}

    # 1. 0 occurrences -> Out of sync
    change_0 = [{"file": "helper.py", "action": "modify", "old_code": "return 999", "new_code": "return 20"}]
    res_0 = validate_patch_safety(change_0, file_contents)
    assert res_0["is_safe"] is False
    assert "0 occurrences" in res_0["rejection_reason"]

    # 2. >1 occurrences -> Ambiguous
    change_multi = [{"file": "helper.py", "action": "modify", "old_code": "return 10", "new_code": "return 20"}]
    res_multi = validate_patch_safety(change_multi, file_contents)
    assert res_multi["is_safe"] is False
    assert "ambiguous" in res_multi["rejection_reason"]

    # 3. Exactly 1 occurrence -> Safe
    change_exact = [{"file": "helper.py", "action": "modify", "old_code": "def helper():\n    return 10", "new_code": "def helper():\n    return 20"}]
    res_exact = validate_patch_safety(change_exact, file_contents)
    assert res_exact["is_safe"] is True


def test_patch_safety_rejects_scope_breach_and_path_traversal():
    """Verify rejection when modifying out-of-scope files or attempting path traversal."""
    file_contents = {"app/main.py": "x = 1\n", "secrets.env": "API_KEY=123\n"}

    # Path traversal
    change_trav = [{"file": "../etc/passwd", "action": "modify", "old_code": "root", "new_code": "admin"}]
    res_trav = validate_patch_safety(change_trav, file_contents)
    assert res_trav["is_safe"] is False
    assert "Path traversal" in res_trav["rejection_reason"]

    # Sensitive path (.env)
    change_env = [{"file": "secrets.env", "action": "modify", "old_code": "123", "new_code": "456"}]
    res_env = validate_patch_safety(change_env, file_contents)
    assert res_env["is_safe"] is False
    assert "Access to sensitive file" in res_env["rejection_reason"]

    # Approved scope breach
    change_out_of_scope = [{"file": "app/main.py", "action": "modify", "old_code": "x = 1", "new_code": "x = 2"}]
    res_scope = validate_patch_safety(change_out_of_scope, file_contents, scope_files=["app/other.py"])
    assert res_scope["is_safe"] is False
    assert "outside approved scope" in res_scope["rejection_reason"]


def test_patch_safety_detects_and_rejects_secrets():
    """Verify rejection when patch introduces private keys or credentials."""
    file_contents = {"config.py": "SECRET = None\n"}
    change_secret = [{
        "file": "config.py",
        "action": "modify",
        "old_code": "SECRET = None",
        "new_code": "SECRET = 'ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890'",
    }]
    res = validate_patch_safety(change_secret, file_contents)
    assert res["is_safe"] is False
    assert "Secret detected" in res["rejection_reason"]


def test_patch_safety_rejects_forbidden_boilerplate():
    """Verify rejection of generic placeholder template text."""
    file_contents = {"README.md": ""}
    change_bp = [{
        "file": "README.md",
        "action": "create",
        "old_code": "",
        "new_code": "# Project\nTODO: add content here\nLorem ipsum dolor sit amet",
    }]
    res = validate_patch_safety(change_bp, file_contents)
    assert res["is_safe"] is False
    assert "Boilerplate check failed" in res["rejection_reason"]


# ============================================================================
# 4. RUNNER SECURITY: PATH CONTAINMENT & NETWORK ISOLATION
# ============================================================================

def test_runner_path_containment():
    """Verify independent runner-level path containment checks."""
    import tempfile
    workspace = tempfile.mkdtemp(prefix="sentinel_containment_")
    try:
        # Valid path inside workspace
        valid_path = resolve_contained_workspace_path(workspace, "src/index.ts")
        assert valid_path.startswith(os.path.realpath(workspace))

        # Traversal attempts
        with pytest.raises(ValueError, match="Path traversal"):
            resolve_contained_workspace_path(workspace, "../outside.py")

        with pytest.raises(ValueError, match="Path traversal"):
            resolve_contained_workspace_path(workspace, "src/../../outside.py")

        # Absolute paths
        with pytest.raises(ValueError, match="Absolute"):
            resolve_contained_workspace_path(workspace, "/etc/passwd")

        # Sensitive paths
        with pytest.raises(ValueError, match="Access to sensitive file"):
            resolve_contained_workspace_path(workspace, ".env.production")
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_runner_sandboxed_environment_network_and_credentials():
    """Verify network isolation env vars and scrubbed credentials in runner environment."""
    env = build_sandboxed_environment()
    assert env["HTTP_PROXY"] == "http://127.0.0.1:1"
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:1"
    assert env["ALL_PROXY"] == "socks5://127.0.0.1:1"
    assert env["PIP_NO_INDEX"] == "1"
    assert env["NPM_CONFIG_OFFLINE"] == "true"
    assert env["GOPROXY"] == "off"
    assert env["CARGO_NET_OFFLINE"] == "true"
    assert "OPENAI_API_KEY" not in env
    assert "DATABASE_URL" not in env


# ============================================================================
# 5. STRICT PATCH APPLICATION IN RUNNER
# ============================================================================

def test_strict_patch_application_in_runner():
    """Verify fail-fast behavior when applying patch changes inside workspace."""
    import tempfile
    workspace = tempfile.mkdtemp(prefix="sentinel_apply_")
    try:
        # 1. Modify missing file -> Fails
        with pytest.raises(ValueError, match="Cannot modify non-existent file"):
            apply_patch_to_workspace(workspace, [{"file": "missing.py", "action": "modify", "old_code": "a", "new_code": "b"}])

        # 2. Modify with 0 count old_code -> Fails
        fpath = os.path.join(workspace, "service.py")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write("x = 10\n")
        with pytest.raises(ValueError, match="old_code not found"):
            apply_patch_to_workspace(workspace, [{"file": "service.py", "action": "modify", "old_code": "x = 999", "new_code": "x = 20"}])

        # 3. Modify with ambiguous (>1 count) old_code -> Fails
        with open(fpath, "w", encoding="utf-8") as f:
            f.write("val = 1\nval = 1\n")
        with pytest.raises(ValueError, match="ambiguous old_code"):
            apply_patch_to_workspace(workspace, [{"file": "service.py", "action": "modify", "old_code": "val = 1", "new_code": "val = 2"}])

        # 4. Modify with exact 1 count -> Passes
        with open(fpath, "w", encoding="utf-8") as f:
            f.write("def calculate():\n    return 42\n")
        apply_patch_to_workspace(workspace, [{"file": "service.py", "action": "modify", "old_code": "return 42", "new_code": "return 100"}])
        with open(fpath, "r", encoding="utf-8") as f:
            assert f.read() == "def calculate():\n    return 100\n"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


# ============================================================================
# 6. COMMAND ALLOWLIST & SHELL=FALSE EXECUTION
# ============================================================================

def test_command_allowlist_and_metacharacter_rejection():
    """Verify strict array format and rejection of shell operators (; && | > < $())."""
    # 1. Shell metacharacters
    assert validate_command_array(["pytest", "tests/; rm -rf /"])[0] is False
    assert validate_command_array(["pytest", "tests/ && echo hacked"])[0] is False
    assert validate_command_array(["pytest", "tests/ | cat"])[0] is False
    assert validate_command_array(["pytest", "$(whoami)"])[0] is False

    # 2. Non-allowlisted binaries
    assert validate_command_array(["curl", "http://evil.com"])[0] is False
    assert validate_command_array(["bash", "-c", "pytest"])[0] is False

    # 3. Allowlisted runners
    ok, err, resolved = validate_command_array(["pytest", "-v", "tests/test_one.py"])
    assert ok is True
    assert "-m" in resolved and "pytest" in resolved


# ============================================================================
# 7. TWO-PHASE BUG REGRESSION EXECUTION
# ============================================================================

def test_two_phase_regression_execution():
    """Verify pre-patch FAIL and post-patch PASS logic."""
    base_file = """def divide(a, b):
    return a / b  # Bug: ZeroDivisionError
"""
    file_contents = {"calculator.py": base_file}
    
    patch_change = [{
        "file": "calculator.py",
        "action": "modify",
        "old_code": "return a / b  # Bug: ZeroDivisionError",
        "new_code": "return a / b if b != 0 else 0",
    }]

    regression_test = [{
        "file": "tests/test_div.py",
        "test_code": """from calculator import divide

def test_divide_by_zero():
    assert divide(10, 0) == 0
""",
    }]

    res = execute_two_phase_regression_test(
        file_contents=file_contents,
        patch_changes=patch_change,
        regression_tests=regression_test,
    )
    assert res["status"] == "reproduced_and_fixed"
    assert res["pre_patch_failed"] is True
    assert res["post_patch_passed"] is True


def test_two_phase_regression_fails_if_already_passing():
    """Verify rejection when regression test passes on base SHA before patch."""
    base_file = "def add(a, b): return a + b\n"
    file_contents = {"add.py": base_file}

    patch_change = [{
        "file": "add.py",
        "action": "modify",
        "old_code": "return a + b",
        "new_code": "return a + b  # patched",
    }]

    regression_test = [{
        "file": "tests/test_add.py",
        "test_code": "from add import add\ndef test_add(): assert add(1, 2) == 3\n",
    }]

    res = execute_two_phase_regression_test(
        file_contents=file_contents,
        patch_changes=patch_change,
        regression_tests=regression_test,
    )
    assert res["status"] == "failed_pre_check"
    assert res["pre_patch_failed"] is False


# ============================================================================
# 8. DIRECT TASK SYNTHESIS & ZERO BOILERPLATE
# ============================================================================

def test_direct_task_readme_patch():
    """Verify concrete README generation without generic boilerplate."""
    readme_patch = build_direct_task_readme(
        repository_name="sentinel/order-management",
        service_names=["order-processor", "inventory-sync"],
        file_list=["app/main.py", "app/orders.py"],
    )
    assert len(readme_patch["changes"]) == 1
    content = readme_patch["changes"][0]["new_code"]
    assert "Order Management" in content
    assert "order-processor" in content
    assert "TODO" not in content
    assert len(readme_patch["tests_to_add"]) >= 1


# ============================================================================
# 9. SERVICE-LAYER TENANT PARITY REJECTION
# ============================================================================

def test_service_layer_tenant_parity_rejection(client, operator_user, org, other_org, db, monkeypatch):
    """Verify API rejects work items or repositories from another tenant."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")
    headers = get_auth_headers(operator_user)

    other_repo = Repository(
        organization_id=other_org.id,
        name="foreign-repo",
        full_name="other/foreign-repo",
    )
    db.add(other_repo)
    db.commit()

    # Attempt to generate patch with cross-tenant repository
    res = client.post(
        "/remediation/patches/generate",
        headers=headers,
        json={"repository_id": str(other_repo.id)},
    )
    assert res.status_code in (400, 403)
    assert "same organization" in res.json()["detail"] or "Forbidden" in res.json()["detail"]


# ============================================================================
# 10. REST API PATCH LIFECYCLE & MANUAL EDIT VERSIONING
# ============================================================================

def test_rest_api_patch_lifecycle_and_manual_edit(client, operator_user, org, incident, repo, work_item, db, monkeypatch):
    """Verify generation, retrieval, manual edit, version audit increment, and revalidation."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")
    headers = get_auth_headers(operator_user)

    # 1. Generate Patch via API
    gen_res = client.post(
        "/remediation/patches/generate",
        headers=headers,
        json={
            "incident_id": str(incident.id),
            "work_item_id": str(work_item.id),
            "repository_id": str(repo.id),
            "instructions": "Increase max_connections in redis pool",
        },
    )
    assert gen_res.status_code == 200
    fix_data = gen_res.json()
    fix_id = fix_data["id"]
    assert fix_data["version"] == 1
    assert len(fix_data["versions"]) == 1
    original_snapshot = fix_data["snapshot_hash"]

    # 2. Retrieve Patch Details
    get_res = client.get(f"/remediation/fixes/{fix_id}/patch", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == fix_id

    # 3. Retrieve Tests
    tests_res = client.get(f"/remediation/fixes/{fix_id}/tests", headers=headers)
    assert tests_res.status_code == 200
    assert isinstance(tests_res.json(), list)

    # 4. Manual Edit Patch -> Increments Version & Revalidates
    edit_res = client.post(
        f"/remediation/patches/{fix_id}/edit",
        headers=headers,
        json={
            "changes": [
                {
                    "file": "remediation_fix.py",
                    "action": "create",
                    "old_code": "",
                    "new_code": "# Updated remediation script\ndef verify(): return 42\n",
                }
            ],
            "rollback_plan": "Remove updated remediation_fix.py",
        },
    )
    assert edit_res.status_code == 200
    updated_data = edit_res.json()
    assert updated_data["version"] == 2
    assert updated_data["snapshot_hash"] != original_snapshot

    # 5. Retrieve Version History
    hist_res = client.get(f"/remediation/fixes/{fix_id}/history", headers=headers)
    assert hist_res.status_code == 200
    history = hist_res.json()
    assert len(history) == 2
    assert history[0]["version_number"] == 1
    assert history[1]["version_number"] == 2
    assert history[1]["previous_snapshot_hash"] == original_snapshot
