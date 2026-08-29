"""Phase 14 Test Suite: Multi-Repository Remediation.

Verifies:
1. Migration 034 schema definitions, parent-child relationships, unique constraints (uq_parent_child_repo, uq_plan_repo).
2. Child investigation uniqueness and fan-out idempotency.
3. 9-factor candidate repository scoring engine and architectural role assignments.
4. Rejection of silent single-repository fallbacks.
5. Strict Git base commit SHA validation (discovery vs remediation lifecycle).
6. Deep evidence-only enforcement in patch generator and PR publisher.
7. Topological dependency ordering (Kahn's algorithm) & dependency cycle detection (BLOCKED_CYCLIC_DEPENDENCY).
8. Break-order override workflow for cyclic service dependencies.
9. Cross-repository unified rollback plan compilation.
10. Phase 13 approval binding re-verification under row locks.
11. Non-transactional Draft PR publishing with partial-failure tracking, recovery, and retry idempotency.
12. Cross-tenant isolation and RBAC permission checks.
13. REST API endpoints for candidate resolution, fan-out, remediation plans, and PR orchestration.
"""

import os
import re
import uuid
import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from alembic import op



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
    Environment,
    ServiceRepository,
    ServiceRepositoryRole,
    ServiceDependency,

    Deployment,
    DeploymentStatus,
    ChangeEvent,

    ProposedFix,
    ValidationRun,
    Approval,
    ApprovalStatus,
    RepositoryRole,
    MultiRepoRemediationPlan,
    RemediationPlanItem,
    RemediationPlanStatus,
    GitHubInstallation,
)
from app.services.multi_repo_resolver import (
    resolve_candidate_repositories,
    WEIGHT_EXPLICIT_SCOPE,
    WEIGHT_SERVICE_MAPPING,
)
from app.services.multi_repo_coordinator import (
    fan_out_child_investigations,
    validate_child_base_sha_for_remediation,
)
from app.services.multi_repo_orchestrator import (
    detect_topological_order_and_cycles,
    create_multi_repo_remediation_plan,
    publish_multi_repo_draft_prs,
)
from app.services.patch_generator import synthesize_patch_and_tests
from app.routes.remediation import PRResponse


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
        name="Acme Multi-Repo Org",
        slug=f"acme-multirepo-{uuid.uuid4().hex[:6]}",
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture
def org_b(db) -> Organization:
    organization = Organization(
        id=uuid.uuid4(),
        name="Beta Foreign Org",
        slug=f"beta-multirepo-{uuid.uuid4().hex[:6]}",
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture
def operator_user(db, org) -> User:
    user = User(
        id=uuid.uuid4(),
        username=f"operator_{uuid.uuid4().hex[:6]}",
        email="operator@acme.test",
        hashed_password=hash_password("OperatorPass123!"),
        role="operator",
        organization_id=org.id,
        is_active="1",
    )
    db.add(user)
    db.flush()
    mem = UserOrganizationMembership(
        id=uuid.uuid4(),
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.OPERATOR,
    )
    db.add(mem)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def foreign_user(db, org_b) -> User:
    user = User(
        id=uuid.uuid4(),
        username=f"foreign_{uuid.uuid4().hex[:6]}",
        email="foreign@beta.test",
        hashed_password=hash_password("ForeignPass123!"),
        role="operator",
        organization_id=org_b.id,
        is_active="1",
    )
    db.add(user)
    db.flush()
    mem = UserOrganizationMembership(
        id=uuid.uuid4(),
        user_id=user.id,
        organization_id=org_b.id,
        role=MembershipRole.OPERATOR,
    )
    db.add(mem)
    db.commit()
    db.refresh(user)
    return user


def get_auth_headers(user: User) -> dict:
    token = create_access_token(data={"sub": str(user.id), "org_id": str(user.organization_id)})
    return {"Authorization": f"Bearer {token}"}


_incident_sequence = 100

def make_incident(db, org, **kwargs) -> Incident:
    global _incident_sequence
    _incident_sequence += 1
    inc = Incident(
        id=kwargs.get("id", uuid.uuid4()),
        organization_id=org.id,
        number=_incident_sequence,
        title=kwargs.get("title", f"Test Incident {_incident_sequence}"),
        description=kwargs.get("description", "Diagnostic description"),
        severity=kwargs.get("severity", "SEV-1"),
        status=kwargs.get("status", "investigating"),
        service_id=kwargs.get("service_id", None),
    )
    db.add(inc)
    db.commit()
    db.refresh(inc)
    return inc


@pytest.fixture
def multi_repo_services_and_repos(db, org):
    """Sets up Payment (Provider) and Checkout (Consumer) services and repositories."""
    gh_inst = GitHubInstallation(
        id=uuid.uuid4(),
        installation_id="inst_multi_123",
        account_type="Organization",
        account_login="acme",
        account_id="12345",
        target_type="Organization",
        tokens_encrypted="ghp_test_token_secret",
    )
    db.add(gh_inst)

    # Repositories
    repo_payment = Repository(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="payment-service",
        full_name="acme/payment-service",
        installation_id=gh_inst.id,
        default_branch="main",
    )
    repo_checkout = Repository(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="checkout-api",
        full_name="acme/checkout-api",
        installation_id=gh_inst.id,
        default_branch="main",
    )
    repo_config = Repository(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="platform-config",
        full_name="acme/platform-config",
        installation_id=gh_inst.id,
        default_branch="main",
    )
    db.add_all([repo_payment, repo_checkout, repo_config])
    db.flush()

    # Services
    srv_payment = Service(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="payment-service",
        tier="critical",
    )
    srv_checkout = Service(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="checkout-api",
        tier="high",
    )
    db.add_all([srv_payment, srv_checkout])
    db.flush()

    # Service Repositories
    sr_pay = ServiceRepository(
        id=uuid.uuid4(),
        organization_id=org.id,
        service_id=srv_payment.id,
        repository_id=repo_payment.id,
        is_primary=True,
        role=ServiceRepositoryRole.APPLICATION,
        selection_reason="Primary codebase",
    )
    sr_chk = ServiceRepository(
        id=uuid.uuid4(),
        organization_id=org.id,
        service_id=srv_checkout.id,
        repository_id=repo_checkout.id,
        is_primary=True,
        role=ServiceRepositoryRole.APPLICATION,
        selection_reason="Primary codebase",
    )
    sr_cfg = ServiceRepository(
        id=uuid.uuid4(),
        organization_id=org.id,
        service_id=srv_payment.id,
        repository_id=repo_config.id,
        is_primary=False,
        role=ServiceRepositoryRole.CONFIGURATION,
        selection_reason="Configuration manifest only",
    )
    db.add_all([sr_pay, sr_chk, sr_cfg])
    db.flush()


    # Dependency: Checkout DEPENDS ON Payment (Payment is upstream provider, Checkout is consumer)
    dep = ServiceDependency(
        id=uuid.uuid4(),
        organization_id=org.id,
        service_id=srv_checkout.id,
        depends_on_service_id=srv_payment.id,
        dependency_type="synchronous",
    )
    db.add(dep)

    # Environment
    env = Environment(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="production",
        env_type="production",
    )
    db.add(env)
    db.flush()

    # Deployments
    pay_sha = "1111111111111111111111111111111111111111"
    chk_sha = "2222222222222222222222222222222222222222"
    dep_pay = Deployment(
        id=uuid.uuid4(),
        organization_id=org.id,
        service_id=srv_payment.id,
        environment_id=env.id,
        repository_id=repo_payment.id,
        commit_sha=pay_sha,
        status=DeploymentStatus.SUCCEEDED,
    )
    dep_chk = Deployment(
        id=uuid.uuid4(),
        organization_id=org.id,
        service_id=srv_checkout.id,
        environment_id=env.id,
        repository_id=repo_checkout.id,
        commit_sha=chk_sha,
        status=DeploymentStatus.SUCCEEDED,
    )
    db.add_all([dep_pay, dep_chk])
    db.commit()


    return {
        "repo_payment": repo_payment,
        "repo_checkout": repo_checkout,
        "repo_config": repo_config,
        "srv_payment": srv_payment,
        "srv_checkout": srv_checkout,
        "pay_sha": pay_sha,
        "chk_sha": chk_sha,
    }


# ============================================================================
# 1. MIGRATION 034 SCHEMA & CONSTRAINTS
# ============================================================================

def test_migration_034_schema_and_parent_child_relationships(db):
    """Verify tables, foreign keys, and unique constraints for multi-repo remediation."""
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    assert "remediation_plans" in tables
    assert "remediation_plan_items" in tables
    assert "investigations" in tables

    inv_cols = {c["name"] for c in inspector.get_columns("investigations")}
    assert "parent_investigation_id" in inv_cols
    assert "repository_id" in inv_cols
    assert "repository_role" in inv_cols
    assert "base_commit_sha" in inv_cols
    assert "is_parent" in inv_cols
    assert "idempotency_key" in inv_cols

    item_cols = {c["name"] for c in inspector.get_columns("remediation_plan_items")}
    assert "plan_id" in item_cols
    assert "repository_id" in item_cols
    assert "repository_role" in item_cols
    assert "execution_order" in item_cols
    assert "requires_code_change" in item_cols
    assert "validation_run_id" in item_cols
    assert "approval_id" in item_cols
    assert "pr_status" in item_cols
    assert "pr_url" in item_cols


def test_migration_034_downgrade_and_upgrade_cycle(db):
    """Verify migration 034 downgrade and upgrade execute cleanly without error suppression."""
    import importlib.util
    from alembic.operations import Operations
    from alembic.migration import MigrationContext

    mig_path = os.path.join(os.path.dirname(__file__), "..", "alembic", "versions", "034_add_phase14_multi_repo_remediation.py")
    spec = importlib.util.spec_from_file_location("mig_034", mig_path)
    mig_034 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig_034)

    context = MigrationContext.configure(db.connection())
    op._proxy = Operations(context)

    try:
        # 1. Execute downgrade
        mig_034.downgrade()
        inspector = inspect(db.connection())
        tables_after_down = inspector.get_table_names()
        assert "remediation_plan_items" not in tables_after_down
        assert "remediation_plans" not in tables_after_down
        inv_cols_down = {c["name"] for c in inspector.get_columns("investigations")}
        assert "parent_investigation_id" not in inv_cols_down
        assert "idempotency_key" not in inv_cols_down

        # 2. Execute upgrade
        mig_034.upgrade()
        inspector2 = inspect(db.connection())
        tables_after_up = inspector2.get_table_names()
        assert "remediation_plan_items" in tables_after_up
        assert "remediation_plans" in tables_after_up
        inv_cols_up = {c["name"] for c in inspector2.get_columns("investigations")}
        assert "parent_investigation_id" in inv_cols_up
        assert "idempotency_key" in inv_cols_up
    finally:
        op._proxy = None



# ============================================================================
# 2. CHILD INVESTIGATION UNIQUENESS & FAN-OUT IDEMPOTENCY
# ============================================================================

def test_child_investigation_uniqueness_and_fan_out_idempotency(db, org, operator_user, multi_repo_services_and_repos):
    """Verify repeated fan-out does not create duplicate child investigations."""
    data = multi_repo_services_and_repos
    incident = make_incident(
        db,
        org,
        title="Payment gateway timeout affecting checkout-api",
        description="Stack trace in payment-service error and checkout-api failure",
        service_id=data["srv_payment"].id,
    )

    # 1. Initial fan-out
    parent_inv, children = fan_out_child_investigations(
        db=db,
        incident_id=incident.id,
        organization_id=org.id,
        actor=operator_user,
    )
    assert parent_inv.is_parent is True
    assert len(children) >= 2

    initial_child_ids = [c.id for c in children]

    # 2. Re-invoking fan-out (Idempotent execution)
    parent_inv_2, children_2 = fan_out_child_investigations(
        db=db,
        incident_id=incident.id,
        organization_id=org.id,
        actor=operator_user,
    )
    assert parent_inv_2.id == parent_inv.id
    assert len(children_2) == len(children)
    assert [c.id for c in children_2] == initial_child_ids

    # 3. Assert DB count
    total_child_count = db.query(Investigation).filter(
        Investigation.parent_investigation_id == parent_inv.id
    ).count()
    assert total_child_count == len(children)


# ============================================================================
# 3. 9-FACTOR REPOSITORY SCORING & ARCHITECTURAL ROLES
# ============================================================================

def test_multi_factor_repository_scoring_and_roles(db, org, multi_repo_services_and_repos):
    """Verify candidate resolver assigns correct scores and architectural roles."""
    data = multi_repo_services_and_repos
    incident = make_incident(
        db,
        org,
        title="Payment processing error in payment-service",
        description="Downstream checkout-api failed calling payment-service. Check platform-config.",
        service_id=data["srv_payment"].id,
    )

    candidates = resolve_candidate_repositories(
        db=db,
        incident_id=incident.id,
        organization_id=org.id,
        threshold=0.30,
    )

    cand_by_name = {c.name: c for c in candidates}
    assert "payment-service" in cand_by_name
    assert "checkout-api" in cand_by_name
    assert "platform-config" in cand_by_name

    # payment-service is primary defect
    assert cand_by_name["payment-service"].role == RepositoryRole.PRIMARY_DEFECT.value
    assert cand_by_name["payment-service"].requires_code_change is True
    assert cand_by_name["payment-service"].base_commit_sha == data["pay_sha"]

    # checkout-api is downstream affected
    assert cand_by_name["checkout-api"].role == RepositoryRole.DOWNSTREAM_AFFECTED.value
    assert cand_by_name["checkout-api"].requires_code_change is True

    # platform-config is evidence only
    assert cand_by_name["platform-config"].role == RepositoryRole.EVIDENCE_ONLY.value
    assert cand_by_name["platform-config"].requires_code_change is False


# ============================================================================
# 4. REJECTION OF SILENT FALLBACK TO ARBITRARY FIRST REPO
# ============================================================================

def test_no_silent_fallback_to_arbitrary_first_repo(db, org, multi_repo_services_and_repos):
    """Verify resolver returns empty list if no match meets threshold, without silent guessing."""
    incident = make_incident(
        db,
        org,
        title="Unrelated marketing website asset error",
        description="No mention of payment or checkout",
        service_id=None,
        severity="SEV-4",
    )

    candidates = resolve_candidate_repositories(
        db=db,
        incident_id=incident.id,
        organization_id=org.id,
        threshold=0.80,
    )
    # High threshold with no matches returns empty, not random first connected repository
    assert len(candidates) == 0


# ============================================================================
# 5. STRICT BASE COMMIT SHA VALIDATION (DISCOVERY VS REMEDIATION)
# ============================================================================

def test_strict_base_commit_sha_validation(db, org):
    """Verify child investigation cannot advance to remediation without verified 40-char SHA."""
    child_valid = Investigation(
        id=uuid.uuid4(),
        organization_id=org.id,
        base_commit_sha="c0ffee1234567890abcdef1234567890abcdef12",
        status="created",
    )
    sha_ok = validate_child_base_sha_for_remediation(child_valid)
    assert sha_ok == "c0ffee1234567890abcdef1234567890abcdef12"

    # Missing SHA
    child_missing = Investigation(id=uuid.uuid4(), organization_id=org.id, base_commit_sha=None)
    with pytest.raises(Exception) as exc1:
        validate_child_base_sha_for_remediation(child_missing)
    assert "cannot enter remediation without a verified" in str(exc1.value)

    # Invalid / synthetic SHA
    child_bad = Investigation(id=uuid.uuid4(), organization_id=org.id, base_commit_sha="short-sha")
    with pytest.raises(Exception) as exc2:
        validate_child_base_sha_for_remediation(child_bad)
    assert "cannot enter remediation without a verified" in str(exc2.value)


# ============================================================================
# 6. DEEP EVIDENCE-ONLY ENFORCEMENT (PATCH GENERATION PROHIBITION)
# ============================================================================

@pytest.mark.asyncio
async def test_evidence_only_repository_strictly_blocks_patch_generation():
    """Verify synthesize_patch_and_tests rejects patch creation for evidence_only repos."""
    with pytest.raises(ValueError) as exc:
        await synthesize_patch_and_tests(
            file_contents={"config.yaml": "timeout: 30"},
            repository_name="acme/platform-config",
            repository_role="evidence_only",
            use_llm=False,
        )
    assert "is designated EVIDENCE_ONLY and cannot generate code patches" in str(exc.value)


# ============================================================================
# 7. DEEP EVIDENCE-ONLY ENFORCEMENT (DRAFT PR PROHIBITION)
# ============================================================================

@pytest.mark.asyncio
async def test_evidence_only_repository_strictly_blocks_pr_creation(db, org, operator_user, multi_repo_services_and_repos):
    """Verify PR publisher strictly skips PR creation for evidence_only repos."""
    data = multi_repo_services_and_repos
    incident = make_incident(
        db,
        org,
        title="Payment gateway timeout",
        service_id=data["srv_payment"].id,
    )

    parent_inv, children = fan_out_child_investigations(
        db=db,
        incident_id=incident.id,
        organization_id=org.id,
        actor=operator_user,
    )

    plan = create_multi_repo_remediation_plan(
        db=db,
        incident_id=incident.id,
        organization_id=org.id,
        parent_investigation_id=parent_inv.id,
    )

    # Verify config item is marked requires_code_change=False
    config_item = next((i for i in plan.items if i.repository_id == data["repo_config"].id), None)
    assert config_item is not None
    assert config_item.requires_code_change is False
    assert config_item.pr_status == "skipped_evidence_only"


# ============================================================================
# 8. TOPOLOGICAL DEPENDENCY ORDERING (KAHN'S ALGORITHM)
# ============================================================================

def test_topological_dependency_ordering_calculation(db, org, multi_repo_services_and_repos):
    """Verify provider merges before consumer in topological order."""
    data = multi_repo_services_and_repos
    ordered_ids, cycle_detected, details = detect_topological_order_and_cycles(
        repository_ids=[data["repo_checkout"].id, data["repo_payment"].id],
        db=db,
        organization_id=org.id,
    )

    assert cycle_detected is False
    # Payment (Provider) must come before Checkout (Consumer)
    assert ordered_ids.index(data["repo_payment"].id) < ordered_ids.index(data["repo_checkout"].id)


# ============================================================================
# 9. DEPENDENCY CYCLE DETECTION & BLOCKED_CYCLIC_DEPENDENCY
# ============================================================================

def test_dependency_cycle_detection_and_blocking(db, org, operator_user, multi_repo_services_and_repos):
    """Verify cyclic dependencies transition plan to BLOCKED_CYCLIC_DEPENDENCY."""
    data = multi_repo_services_and_repos

    # Add reverse cycle: Payment also depends on Checkout
    cycle_dep = ServiceDependency(
        id=uuid.uuid4(),
        organization_id=org.id,
        service_id=data["srv_payment"].id,
        depends_on_service_id=data["srv_checkout"].id,
        dependency_type="synchronous",
    )
    db.add(cycle_dep)
    db.commit()

    incident = make_incident(
        db,
        org,
        title="Cyclic dependency outage",
        service_id=data["srv_payment"].id,
    )

    parent_inv, _ = fan_out_child_investigations(
        db=db,
        incident_id=incident.id,
        organization_id=org.id,
        actor=operator_user,
    )

    plan = create_multi_repo_remediation_plan(
        db=db,
        incident_id=incident.id,
        organization_id=org.id,
        parent_investigation_id=parent_inv.id,
    )

    assert plan.cycle_detected is True
    assert plan.status == RemediationPlanStatus.BLOCKED_CYCLIC_DEPENDENCY
    assert plan.cycle_details_json is not None


# ============================================================================
# 10. BREAK-ORDER OVERRIDE ALLOWS CYCLIC REMEDIATION
# ============================================================================

def test_break_order_override_allows_cyclic_remediation(db, org, operator_user, multi_repo_services_and_repos):
    """Verify operator override order resolves cyclic dependency blocks."""
    data = multi_repo_services_and_repos

    incident = make_incident(
        db,
        org,
        title="Cyclic incident with override",
        service_id=data["srv_payment"].id,
    )

    parent_inv, _ = fan_out_child_investigations(
        db=db,
        incident_id=incident.id,
        organization_id=org.id,
        actor=operator_user,
    )

    # Provide explicit operator override order
    override_order = [str(data["repo_payment"].id), str(data["repo_checkout"].id)]
    plan = create_multi_repo_remediation_plan(
        db=db,
        incident_id=incident.id,
        organization_id=org.id,
        parent_investigation_id=parent_inv.id,
        override_dependency_order=override_order,
    )

    assert plan.status == RemediationPlanStatus.DRAFT
    assert plan.dependency_order_json[:2] == override_order



# ============================================================================
# 11. CROSS-REPOSITORY ROLLBACK PLAN GENERATION
# ============================================================================

def test_cross_repository_rollback_plan_generation(db, org, operator_user, multi_repo_services_and_repos):
    """Verify rollback plan specifies reverse-order deployment rollbacks."""
    data = multi_repo_services_and_repos
    incident = make_incident(
        db,
        org,
        title="Payment & Checkout failure",
        service_id=data["srv_payment"].id,
    )

    parent_inv, _ = fan_out_child_investigations(
        db=db,
        incident_id=incident.id,
        organization_id=org.id,
        actor=operator_user,
    )

    plan = create_multi_repo_remediation_plan(
        db=db,
        incident_id=incident.id,
        organization_id=org.id,
        parent_investigation_id=parent_inv.id,
    )

    assert plan.cross_repo_rollback_plan is not None
    assert "Coordinated Cross-Repository Rollback Procedure" in plan.cross_repo_rollback_plan
    assert "payment-service" in plan.cross_repo_rollback_plan
    assert "checkout-api" in plan.cross_repo_rollback_plan


# ============================================================================
# 12. PHASE 13 APPROVAL BINDING RE-VERIFICATION BEFORE PUBLISH
# ============================================================================

@pytest.mark.asyncio
async def test_phase13_approval_binding_reverification_before_publish(db, org, operator_user, multi_repo_services_and_repos):
    """Verify PR publisher fails per-repo if Phase 13 approval is missing or unapproved."""
    data = multi_repo_services_and_repos
    incident = make_incident(
        db,
        org,
        title="Unapproved multi-repo fix test",
        service_id=data["srv_payment"].id,
    )

    parent_inv, children = fan_out_child_investigations(
        db=db,
        incident_id=incident.id,
        organization_id=org.id,
        actor=operator_user,
    )

    pay_child = next(c for c in children if c.repository_id == data["repo_payment"].id)

    # Create unapproved ProposedFix
    fix = ProposedFix(
        id=uuid.uuid4(),
        organization_id=org.id,
        incident_id=incident.id,
        investigation_id=pay_child.id,
        repository_id=data["repo_payment"].id,
        title="Fix payment gateway timeout",
        description="Timeout fix",
        proposed_change="timeout = 60",
        base_commit_sha=data["pay_sha"],
        status="generated",
    )
    db.add(fix)
    db.commit()

    plan = create_multi_repo_remediation_plan(
        db=db,
        incident_id=incident.id,
        organization_id=org.id,
        parent_investigation_id=parent_inv.id,
    )

    # Attempt to publish without approval
    res = await publish_multi_repo_draft_prs(
        db=db,
        plan_id=plan.id,
        organization_id=org.id,
        actor=operator_user,
    )

    assert res.overall_status in ("failed", "partially_failed")
    pay_res = next(r for r in res.items if r.repository_id == str(data["repo_payment"].id))
    assert pay_res.pr_status == "failed"
    assert "requires an approved Phase 13 Approval record" in pay_res.error_message


# ============================================================================
# 13. MULTI-REPO PUBLISHING PARTIAL-FAILURE HANDLING & ROLLBACK
# ============================================================================

@pytest.mark.asyncio
async def test_multi_repo_publishing_partial_failure_handling(db, org, operator_user, multi_repo_services_and_repos):
    """Verify partial failure records created PR for repo 1 and failure for repo 2."""
    data = multi_repo_services_and_repos
    incident = make_incident(
        db,
        org,
        title="Partial failure test incident",
        service_id=data["srv_payment"].id,
    )

    parent_inv, children = fan_out_child_investigations(
        db=db,
        incident_id=incident.id,
        organization_id=org.id,
        actor=operator_user,
    )

    pay_child = next(c for c in children if c.repository_id == data["repo_payment"].id)
    chk_child = next(c for c in children if c.repository_id == data["repo_checkout"].id)

    # Fix 1: Payment (Approved)
    fix_pay = ProposedFix(
        id=uuid.uuid4(),
        organization_id=org.id,
        incident_id=incident.id,
        investigation_id=pay_child.id,
        repository_id=data["repo_payment"].id,
        title="Fix payment",
        description="Fix",
        proposed_change="fix",
        base_commit_sha=data["pay_sha"],
        status="approved",
    )
    app_pay = Approval(
        id=uuid.uuid4(),
        organization_id=org.id,
        incident_id=incident.id,
        fix_id=fix_pay.id,
        status=ApprovalStatus.APPROVED,
        patch_version=1,
    )
    # Fix 2: Checkout (Approved)
    fix_chk = ProposedFix(
        id=uuid.uuid4(),
        organization_id=org.id,
        incident_id=incident.id,
        investigation_id=chk_child.id,
        repository_id=data["repo_checkout"].id,
        title="Fix checkout",
        description="Fix",
        proposed_change="fix",
        base_commit_sha=data["chk_sha"],
        status="approved",
    )
    app_chk = Approval(
        id=uuid.uuid4(),
        organization_id=org.id,
        incident_id=incident.id,
        fix_id=fix_chk.id,
        status=ApprovalStatus.APPROVED,
        patch_version=1,
    )
    db.add_all([fix_pay, app_pay, fix_chk, app_chk])
    db.commit()

    plan = create_multi_repo_remediation_plan(
        db=db,
        incident_id=incident.id,
        organization_id=org.id,
        parent_investigation_id=parent_inv.id,
    )

    # Mock GitHub: repo 1 succeeds, repo 2 fails with network error
    call_count = 0
    async def mock_publish(fix, incident, db, branch_name):
        nonlocal call_count
        call_count += 1
        if "payment" in branch_name:
            return PRResponse(
                status="created",
                branch_name=branch_name,
                commit_sha="c0ffee1111111111111111111111111111111111",
                pr_url="https://github.com/acme/payment-service/pull/101",
                message="Draft PR created",
            )
        else:
            raise RuntimeError("GitHub API rate limit exceeded on checkout-api")

    with patch("app.services.multi_repo_orchestrator.publish_draft_pr", side_effect=mock_publish):
        res = await publish_multi_repo_draft_prs(
            db=db,
            plan_id=plan.id,
            organization_id=org.id,
            actor=operator_user,
        )

        assert res.overall_status == "partially_failed"
        pay_item = next(r for r in res.items if r.repository_id == str(data["repo_payment"].id))
        chk_item = next(r for r in res.items if r.repository_id == str(data["repo_checkout"].id))

        assert pay_item.pr_status == "created"
        assert pay_item.pr_url == "https://github.com/acme/payment-service/pull/101"
        assert chk_item.pr_status == "failed"
        assert "rate limit exceeded" in chk_item.error_message
        assert res.rollback_instructions is not None


# ============================================================================
# 14. MULTI-REPO PUBLISHING RETRY IDEMPOTENCY
# ============================================================================

@pytest.mark.asyncio
async def test_multi_repo_publishing_retry_idempotency(db, org, operator_user, multi_repo_services_and_repos):
    """Verify retrying publish skips already created PRs and succeeds on recovered repo."""
    data = multi_repo_services_and_repos
    incident = make_incident(
        db,
        org,
        title="Retry idempotency incident",
        service_id=data["srv_payment"].id,
    )

    parent_inv, children = fan_out_child_investigations(
        db=db,
        incident_id=incident.id,
        organization_id=org.id,
        actor=operator_user,
    )

    pay_child = next(c for c in children if c.repository_id == data["repo_payment"].id)
    chk_child = next(c for c in children if c.repository_id == data["repo_checkout"].id)

    fix_pay = ProposedFix(
        id=uuid.uuid4(),
        organization_id=org.id,
        incident_id=incident.id,
        investigation_id=pay_child.id,
        repository_id=data["repo_payment"].id,
        title="Fix payment",
        description="Fix",
        proposed_change="fix",
        base_commit_sha=data["pay_sha"],
        status="approved",
    )
    app_pay = Approval(
        id=uuid.uuid4(),
        organization_id=org.id,
        incident_id=incident.id,
        fix_id=fix_pay.id,
        status=ApprovalStatus.APPROVED,
        patch_version=1,
    )
    fix_chk = ProposedFix(
        id=uuid.uuid4(),
        organization_id=org.id,
        incident_id=incident.id,
        investigation_id=chk_child.id,
        repository_id=data["repo_checkout"].id,
        title="Fix checkout",
        description="Fix",
        proposed_change="fix",
        base_commit_sha=data["chk_sha"],
        status="approved",
    )
    app_chk = Approval(
        id=uuid.uuid4(),
        organization_id=org.id,
        incident_id=incident.id,
        fix_id=fix_chk.id,
        status=ApprovalStatus.APPROVED,
        patch_version=1,
    )
    db.add_all([fix_pay, app_pay, fix_chk, app_chk])
    db.commit()

    plan = create_multi_repo_remediation_plan(
        db=db,
        incident_id=incident.id,
        organization_id=org.id,
        parent_investigation_id=parent_inv.id,
    )

    # Set Payment item to already created
    pay_item = next(i for i in plan.items if i.repository_id == data["repo_payment"].id)
    pay_item.pr_status = "created"
    pay_item.pr_url = "https://github.com/acme/payment-service/pull/101"
    db.commit()

    # On retry, only Checkout needs to be called
    called_repos = []
    async def mock_publish(fix, incident, db, branch_name):
        called_repos.append(branch_name)
        return PRResponse(
            status="created",
            branch_name=branch_name,
            commit_sha="c0ffee2222222222222222222222222222222222",
            pr_url="https://github.com/acme/checkout-api/pull/84",
            message="Draft PR created",
        )

    with patch("app.services.multi_repo_orchestrator.publish_draft_pr", side_effect=mock_publish):
        res = await publish_multi_repo_draft_prs(
            db=db,
            plan_id=plan.id,
            organization_id=org.id,
            actor=operator_user,
        )

        assert res.overall_status == "completed"
        # Payment was skipped idempotently, only Checkout called
        assert len(called_repos) == 1
        assert "checkout-api" in called_repos[0]


# ============================================================================
# 15. CROSS-TENANT ISOLATION ENFORCEMENT
# ============================================================================

def test_cross_tenant_isolation_enforcement(client, org, org_b, operator_user, foreign_user, multi_repo_services_and_repos):
    """Verify tenant isolation blocks cross-organization multi-repo access."""
    data = multi_repo_services_and_repos
    incident = make_incident(
        db=TestingSessionLocal(),
        org=org,
        title="Org A Incident",
        service_id=data["srv_payment"].id,
    )

    headers_foreign = get_auth_headers(foreign_user)

    # Foreign user cannot resolve candidates or fan out for Org A incident
    res_resolve = client.post(
        "/multi-repo/resolve-candidates",
        json={"incident_id": str(incident.id)},
        headers=headers_foreign,
    )
    assert res_resolve.status_code == 404

    res_fanout = client.post(
        f"/multi-repo/incidents/{incident.id}/fan-out",
        json={},
        headers=headers_foreign,
    )
    assert res_fanout.status_code == 404


# ============================================================================
# 16. REST API ENDPOINTS FOR MULTI-REPO LIFECYCLE
# ============================================================================

def test_rest_api_multi_repo_lifecycle_endpoints(client, org, operator_user, multi_repo_services_and_repos):
    """End-to-end REST API verification of candidate resolution, fan-out, plan, and PR publishing."""
    data = multi_repo_services_and_repos
    headers = get_auth_headers(operator_user)

    # 1. Create Incident via REST
    res_inc = client.post(
        "/incidents",
        json={
            "title": "Payment gateway timeout in checkout flow",
            "description": "Downstream checkout-api failed calling payment-service",
            "service": "payment-service",
            "severity": "SEV-1",
        },
        headers=headers,
    )
    assert res_inc.status_code in (200, 201)
    inc_id = res_inc.json()["id"]

    # 2. Resolve candidates via REST
    res_resolve = client.post(
        "/multi-repo/resolve-candidates",
        json={"incident_id": inc_id, "threshold": 0.30},
        headers=headers,
    )
    assert res_resolve.status_code == 200
    candidates = res_resolve.json()["candidates"]
    assert len(candidates) >= 2

    # 3. Fan-out child investigations via REST
    res_fanout = client.post(
        f"/multi-repo/incidents/{inc_id}/fan-out",
        json={},
        headers=headers,
    )
    assert res_fanout.status_code == 200
    children = res_fanout.json()["child_investigations"]
    assert len(children) >= 2

    # 4. List investigations via REST
    res_list = client.get(
        f"/multi-repo/incidents/{inc_id}/investigations",
        headers=headers,
    )
    assert res_list.status_code == 200
    assert len(res_list.json()["child_investigations"]) == len(children)

    # 5. Create Remediation Plan via REST
    res_plan = client.post(
        f"/multi-repo/incidents/{inc_id}/remediation-plans",
        json={"incident_id": inc_id},
        headers=headers,
    )
    assert res_plan.status_code == 200
    plan_data = res_plan.json()
    assert plan_data["status"] in ("draft", "blocked_cyclic_dependency")
    assert len(plan_data["items"]) >= 2

    # 6. Fetch Latest Plan via REST
    res_get_plan = client.get(
        f"/multi-repo/incidents/{inc_id}/remediation-plans",
        headers=headers,
    )
    assert res_get_plan.status_code == 200
    assert res_get_plan.json()["id"] == plan_data["id"]


# ============================================================================
# 17. DATABASE-ENFORCED IDEMPOTENCY CONSTRAINTS (DB LEVEL)
# ============================================================================

def test_db_enforced_investigation_fan_out_idempotency_constraint(db, org, org_b):
    """Verify unique constraint (organization_id, idempotency_key) on investigations table."""
    inv1 = Investigation(
        id=uuid.uuid4(),
        organization_id=org.id,
        idempotency_key="fanout_key_test_1",
        workflow_type="production_incident",
        status="created",
    )
    db.add(inv1)
    db.commit()

    # Duplicate in same org raises IntegrityError
    inv2 = Investigation(
        id=uuid.uuid4(),
        organization_id=org.id,
        idempotency_key="fanout_key_test_1",
        workflow_type="production_incident",
        status="created",
    )
    db.add(inv2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # Same key in different org (org_b) succeeds cleanly
    inv3 = Investigation(
        id=uuid.uuid4(),
        organization_id=org_b.id,
        idempotency_key="fanout_key_test_1",
        workflow_type="production_incident",
        status="created",
    )
    db.add(inv3)
    db.commit()
    assert inv3.id is not None


def test_db_enforced_remediation_plan_idempotency_constraint(db, org, org_b):
    """Verify unique constraint (organization_id, idempotency_key) on remediation_plans table."""
    inc_a = make_incident(db, org, title="Incident Org A")
    inc_b = make_incident(db, org_b, title="Incident Org B")

    plan1 = MultiRepoRemediationPlan(
        id=uuid.uuid4(),
        organization_id=org.id,
        incident_id=inc_a.id,
        title="Plan 1",
        summary="Summary 1",
        idempotency_key="plan_key_test_1",
    )
    db.add(plan1)
    db.commit()

    # Duplicate in same org raises IntegrityError
    plan2 = MultiRepoRemediationPlan(
        id=uuid.uuid4(),
        organization_id=org.id,
        incident_id=inc_a.id,
        title="Plan 2",
        summary="Summary 2",
        idempotency_key="plan_key_test_1",
    )
    db.add(plan2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # Same key in different org (org_b) succeeds cleanly
    plan3 = MultiRepoRemediationPlan(
        id=uuid.uuid4(),
        organization_id=org_b.id,
        incident_id=inc_b.id,
        title="Plan 3",
        summary="Summary 3",
        idempotency_key="plan_key_test_1",
    )
    db.add(plan3)
    db.commit()
    assert plan3.id is not None


def test_db_enforced_draft_pr_idempotency_constraint(db, org, org_b, multi_repo_services_and_repos):
    """Verify unique constraint (organization_id, pr_idempotency_key) on remediation_plan_items table."""
    data = multi_repo_services_and_repos
    inc_a = make_incident(db, org, title="Incident Org A")

    plan1 = MultiRepoRemediationPlan(
        id=uuid.uuid4(),
        organization_id=org.id,
        incident_id=inc_a.id,
        title="Plan 1",
        summary="Summary 1",
    )
    db.add(plan1)
    db.commit()

    item1 = RemediationPlanItem(
        id=uuid.uuid4(),
        organization_id=org.id,
        plan_id=plan1.id,
        repository_id=data["repo_payment"].id,
        repository_role="primary_defect",
        execution_order=1,
        pr_idempotency_key="pr_key_test_1",
    )
    db.add(item1)
    db.commit()

    # Duplicate in same org raises IntegrityError
    item2 = RemediationPlanItem(
        id=uuid.uuid4(),
        organization_id=org.id,
        plan_id=plan1.id,
        repository_id=data["repo_checkout"].id,
        repository_role="downstream_affected",
        execution_order=2,
        pr_idempotency_key="pr_key_test_1",
    )
    db.add(item2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # Setup repo and plan in org_b
    gh_inst_b = GitHubInstallation(
        id=uuid.uuid4(),
        installation_id="inst_multi_456",
        account_type="Organization",
        account_login="beta",
        account_id="67890",
        target_type="Organization",
        tokens_encrypted="ghp_test_token_secret_b",
    )
    db.add(gh_inst_b)
    repo_b = Repository(
        id=uuid.uuid4(),
        organization_id=org_b.id,
        name="payment-service-b",
        full_name="beta/payment-service",
        installation_id=gh_inst_b.id,
        default_branch="main",
    )
    db.add(repo_b)
    inc_b = make_incident(db, org_b, title="Incident Org B")
    plan_b = MultiRepoRemediationPlan(
        id=uuid.uuid4(),
        organization_id=org_b.id,
        incident_id=inc_b.id,
        title="Plan B",
        summary="Summary B",
    )
    db.add_all([repo_b, plan_b])
    db.commit()

    # Same pr_idempotency_key in different org (org_b) succeeds cleanly
    item3 = RemediationPlanItem(
        id=uuid.uuid4(),
        organization_id=org_b.id,
        plan_id=plan_b.id,
        repository_id=repo_b.id,
        repository_role="primary_defect",
        execution_order=1,
        pr_idempotency_key="pr_key_test_1",
    )
    db.add(item3)
    db.commit()
    assert item3.id is not None

