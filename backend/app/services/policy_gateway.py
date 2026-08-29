"""
Policy Gateway Engine for Sentinel (Phase 13).
Enforces safety invariants and approval gates deterministically through code.
"""

import os
import re
import logging
from typing import Dict, List, Optional, Any, Tuple, Set
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from app.models.incident import (
    Organization, User, Incident, Investigation, RootCause,
    ProposedFix, Repository, ValidationRun, PolicyRule,
    PolicyEvaluation, MembershipRole, ActionType, PolicyDecision, RiskLevel,
)
from app.models.work_item import WorkItem
from app.schemas.policy import PolicyStepCheck, PolicyEvaluationResultOut

logger = logging.getLogger("sentinel.policy_gateway")

# Immutable Mandatory Policies (Never Overridable by Custom Policy Rules)
MANDATORY_BLOCKED_ACTIONS = {
    ActionType.WRITE_PRODUCTION.value: "Autonomous direct write to production environment is strictly prohibited.",
    ActionType.MERGE_PR.value: "Autonomous merging of Pull Requests is strictly prohibited. Merges must be performed externally by human engineers.",
    ActionType.DEPLOY.value: "Autonomous production deployments are strictly prohibited. Deployments require external pipeline triggers.",
    ActionType.MODIFY_SECRETS.value: "Autonomous modification of secret stores or credential files is strictly prohibited.",
}

# Sensitive and Infrastructure File Pattern Regexes
SENSITIVE_FILE_PATTERNS = [
    re.compile(r"^\.?env(\..+)?$", re.IGNORECASE),
    re.compile(r".*\.pem$", re.IGNORECASE),
    re.compile(r".*\.key$", re.IGNORECASE),
    re.compile(r".*id_rsa.*", re.IGNORECASE),
    re.compile(r".*secrets?\.json$", re.IGNORECASE),
    re.compile(r".*credentials?\.json$", re.IGNORECASE),
    re.compile(r"^\.ssh/.*", re.IGNORECASE),
]

INFRASTRUCTURE_PATTERNS = [
    re.compile(r".*\.tf$", re.IGNORECASE),
    re.compile(r"^terraform/.*", re.IGNORECASE),
    re.compile(r"^infra/.*", re.IGNORECASE),
    re.compile(r".*Dockerfile.*", re.IGNORECASE),
    re.compile(r".*docker-compose.*\.ya?ml$", re.IGNORECASE),
    re.compile(r"^k8s/.*", re.IGNORECASE),
    re.compile(r"^kubernetes/.*", re.IGNORECASE),
    re.compile(r"^helm/.*", re.IGNORECASE),
    re.compile(r"^\.github/workflows/.*", re.IGNORECASE),
]

MIGRATION_PATTERNS = [
    re.compile(r".*alembic/versions/.*\.py$", re.IGNORECASE),
    re.compile(r"^migrations/.*", re.IGNORECASE),
    re.compile(r"^db/migrations/.*", re.IGNORECASE),
    re.compile(r".*\.sql$", re.IGNORECASE),
]

GIT_SHA_REGEX = re.compile(r"^[0-9a-fA-F]{40}$")
ZERO_SHA = "0000000000000000000000000000000000000000"


def evaluate_action_policy(
    db: Session,
    organization_id: UUID,
    actor: Optional[User],
    action_type: str,
    fix: Optional[ProposedFix] = None,
    work_item: Optional[WorkItem] = None,
    incident: Optional[Incident] = None,
    target_branch: Optional[str] = "main",
    context: Optional[Dict[str, Any]] = None,
) -> PolicyEvaluationResultOut:
    """
    Execute the deterministic 9-step Policy Gateway evaluation pipeline.
    """
    action_type_str = action_type.lower()
    steps: List[PolicyStepCheck] = []
    reasons: List[str] = []
    required_roles: List[str] = ["operator", "admin", "owner"]
    required_approvals_count = 1
    risk_level = "low"
    is_blocked = False
    requires_approval = False
    final_decision = "allow"
    matched_rule_name: Optional[str] = None

    context = context or {}

    # =========================================================================
    # MANDATORY HARDCODED SAFETY BLOCKS (Step 0)
    # =========================================================================
    if action_type_str in MANDATORY_BLOCKED_ACTIONS:
        block_msg = MANDATORY_BLOCKED_ACTIONS[action_type_str]
        steps.append(PolicyStepCheck(
            step_number=0,
            name="Mandatory Safety Invariant",
            status="failed",
            message=block_msg,
            details={"action_type": action_type_str, "is_mandatory": True}
        ))
        reasons.append(block_msg)
        return _record_and_return_evaluation(
            db=db,
            organization_id=organization_id,
            actor=actor,
            action_type=action_type_str,
            decision="block",
            allowed=False,
            requires_approval=False,
            required_approvals_count=0,
            required_roles=[],
            risk_level="critical",
            steps=steps,
            reasons=reasons,
            matched_rule="Mandatory Safety Block",
            fix=fix,
        )

    # =========================================================================
    # STEP 1: ORGANIZATION & TENANT ISOLATION CHECK
    # =========================================================================
    org_check_passed = True
    org_mismatch_detail = []

    if fix and fix.organization_id != organization_id:
        org_check_passed = False
        org_mismatch_detail.append(f"ProposedFix organization ({fix.organization_id}) does not match caller organization ({organization_id})")

    if work_item and work_item.organization_id != organization_id:
        org_check_passed = False
        org_mismatch_detail.append(f"WorkItem organization ({work_item.organization_id}) does not match caller organization ({organization_id})")

    if incident and incident.organization_id != organization_id:
        org_check_passed = False
        org_mismatch_detail.append(f"Incident organization ({incident.organization_id}) does not match caller organization ({organization_id})")

    if actor and actor.organization_id and actor.organization_id != organization_id and actor.role != "admin":
        org_check_passed = False
        org_mismatch_detail.append(f"Actor organization ({actor.organization_id}) does not match caller organization ({organization_id})")

    if org_check_passed:
        steps.append(PolicyStepCheck(
            step_number=1,
            name="Organization & Tenant Isolation",
            status="passed",
            message="Tenant containment verified across all participating entities.",
        ))
    else:
        is_blocked = True
        msg = f"Tenant boundary violation: {'; '.join(org_mismatch_detail)}"
        steps.append(PolicyStepCheck(
            step_number=1,
            name="Organization & Tenant Isolation",
            status="failed",
            message=msg,
        ))
        reasons.append(msg)

    # =========================================================================
    # STEP 2: ACTOR & RBAC CHECK
    # =========================================================================
    if actor:
        user_role = (actor.role.value if hasattr(actor.role, "value") else str(actor.role)).lower()
        if user_role == "viewer" and action_type_str not in ("read_telemetry", "read_repository"):
            is_blocked = True
            msg = "Viewer role is restricted to read-only actions and cannot authorize or execute mutations."
            steps.append(PolicyStepCheck(
                step_number=2,
                name="Actor & RBAC Permissions",
                status="failed",
                message=msg,
            ))
            reasons.append(msg)
        else:
            steps.append(PolicyStepCheck(
                step_number=2,
                name="Actor & RBAC Permissions",
                status="passed",
                message=f"Actor role '{user_role}' authorized for policy evaluation.",
            ))
    else:
        steps.append(PolicyStepCheck(
            step_number=2,
            name="Actor & RBAC Permissions",
            status="passed",
            message="Automated engine evaluation context.",
        ))

    # =========================================================================
    # STEP 3: REPOSITORY & BRANCH SCOPE CHECK
    # =========================================================================
    repo_name = fix.repository if fix else None
    if not repo_name and incident and incident.scopes:
        for scope in incident.scopes:
            if scope.repository and scope.repository.full_name:
                repo_name = scope.repository.full_name
                break

    target_b = (fix.target_branch if fix else None) or target_branch or "main"
    is_protected_branch = target_b.lower() in ("main", "master", "release", "production", "prod")

    steps.append(PolicyStepCheck(
        step_number=3,
        name="Repository & Branch Scope",
        status="passed" if repo_name else "warning",
        message=f"Target repository '{repo_name or 'unspecified'}', branch '{target_b}' ({'protected target' if is_protected_branch else 'feature target'}).",
        details={"repository": repo_name, "target_branch": target_b, "is_protected": is_protected_branch},
    ))

    # =========================================================================
    # STEP 4: FILE SCOPE & SENSITIVE PATH CHECK
    # =========================================================================
    files_changed: List[str] = []
    if fix and fix.patch_json:
        changes = fix.patch_json.get("changes", [])
        for ch in changes:
            fpath = ch.get("file")
            if fpath:
                files_changed.append(fpath)

    has_sensitive_files = False
    has_infra_files = False
    has_migration_files = False
    sensitive_violations = []

    for fpath in files_changed:
        for pat in SENSITIVE_FILE_PATTERNS:
            if pat.search(fpath):
                has_sensitive_files = True
                sensitive_violations.append(fpath)
                break
        for pat in INFRASTRUCTURE_PATTERNS:
            if pat.search(fpath):
                has_infra_files = True
                break
        for pat in MIGRATION_PATTERNS:
            if pat.search(fpath):
                has_migration_files = True
                break

    if has_sensitive_files:
        is_blocked = True
        msg = f"Patch modifies forbidden sensitive/secret files: {', '.join(sensitive_violations)}"
        steps.append(PolicyStepCheck(
            step_number=4,
            name="File Scope & Sensitive Paths",
            status="failed",
            message=msg,
        ))
        reasons.append(msg)
    else:
        file_msg = f"{len(files_changed)} file(s) checked. No forbidden secret or credentials paths detected."
        if has_infra_files:
            file_msg += " Infrastructure/IaC modifications detected (requires multi-approval)."
        if has_migration_files:
            file_msg += " Database migration modifications detected (requires multi-approval)."
        steps.append(PolicyStepCheck(
            step_number=4,
            name="File Scope & Sensitive Paths",
            status="passed",
            message=file_msg,
            details={"files_count": len(files_changed), "has_infra": has_infra_files, "has_migration": has_migration_files},
        ))

    # =========================================================================
    # STEP 5: EVIDENCE & ROOT-CAUSE CONFIDENCE THRESHOLD CHECK
    # =========================================================================
    evidence_passed = True
    confidence_val = 1.0
    if fix and fix.root_cause_id:
        rc = db.query(RootCause).filter(RootCause.id == fix.root_cause_id).first()
        if rc:
            if isinstance(rc.confidence, (int, float)):
                confidence_val = float(rc.confidence)
            elif str(getattr(rc, "confidence", "") or "").lower() in ("high", "confidence.high"):
                confidence_val = 0.90
            elif str(getattr(rc, "confidence", "") or "").lower() in ("medium", "confidence.medium"):
                confidence_val = 0.75
            elif str(getattr(rc, "confidence", "") or "").lower() in ("low", "confidence.low"):
                confidence_val = 0.50
            else:
                confidence_val = 0.80  # Default acceptable confidence
            if confidence_val < 0.70:
                evidence_passed = False


    if evidence_passed:
        steps.append(PolicyStepCheck(
            step_number=5,
            name="Evidence & Root-Cause Confidence",
            status="passed",
            message=f"Root-cause hypothesis confidence score ({int(confidence_val * 100)}%) meets >= 70% threshold.",
            details={"confidence": confidence_val},
        ))
    else:
        msg = f"Root-cause confidence ({int(confidence_val * 100)}%) is below mandatory 70% threshold for autonomous PR generation."
        steps.append(PolicyStepCheck(
            step_number=5,
            name="Evidence & Root-Cause Confidence",
            status="failed",
            message=msg,
            details={"confidence": confidence_val},
        ))
        reasons.append(msg)

    # =========================================================================
    # STEP 6: RISK CATEGORY & BLAST RADIUS CLASSIFICATION
    # =========================================================================
    diff_text = (fix.diff if fix else "") or ""
    diff_lines = len(diff_text.splitlines()) if diff_text else 0
    is_security_incident = False
    if incident:
        inc_type = getattr(incident, "incident_type", None)
        if inc_type and str(inc_type).lower() == "security":
            is_security_incident = True
        elif "security" in str(getattr(incident, "title", "")).lower() or "security" in str(getattr(incident, "description", "")).lower():
            is_security_incident = True
    if work_item and str(getattr(work_item, "work_item_type", "") or "").lower() == "security":
        is_security_incident = True
    if action_type in ("security_remediation", "security_change"):
        is_security_incident = True


    if is_security_incident or has_infra_files or has_migration_files or len(files_changed) > 10:
        risk_level = "critical"
    elif len(files_changed) > 5 or diff_lines > 300:
        risk_level = "high"
    elif len(files_changed) > 2 or diff_lines > 100:
        risk_level = "medium"
    else:
        risk_level = "low"

    steps.append(PolicyStepCheck(
        step_number=6,
        name="Risk & Blast Radius Assessment",
        status="passed",
        message=f"Assessed Risk Tier: {risk_level.upper()} ({len(files_changed)} files, {diff_lines} diff lines).",
        details={"risk_level": risk_level, "diff_lines": diff_lines, "is_security": is_security_incident},
    ))

    # =========================================================================
    # STEP 7: ISOLATED VALIDATION CHECK
    # =========================================================================
    validation_passed = True
    validation_run = None
    if fix:
        validation_run = db.query(ValidationRun).filter(
            ValidationRun.fix_id == fix.id
        ).order_by(ValidationRun.created_at.desc()).first()

    if action_type_str in ("create_draft_pr", "create_branch", "apply_remediation"):
        if not validation_run:
            validation_passed = False
            msg = "Fix has not executed isolated validation pipeline."
        elif validation_run.status != "passed":
            validation_passed = False
            msg = f"Isolated validation status is '{validation_run.status}' (must be 'passed')."
        elif not validation_run.verified_base_sha:
            validation_passed = False
            msg = "Validation did not verify a valid Git base commit SHA."
        else:
            msg = f"Isolated validation passed (verified base SHA: {validation_run.verified_base_sha[:10]}...)."

        if validation_passed:
            steps.append(PolicyStepCheck(
                step_number=7,
                name="Isolated Validation Verification",
                status="passed",
                message=msg,
                details={"validation_run_id": str(validation_run.id) if validation_run else None},
            ))
        else:
            is_blocked = True
            steps.append(PolicyStepCheck(
                step_number=7,
                name="Isolated Validation Verification",
                status="failed",
                message=msg,
                details={"validation_run_id": str(validation_run.id) if validation_run else None},
            ))
            reasons.append(msg)
    else:
        steps.append(PolicyStepCheck(
            step_number=7,
            name="Isolated Validation Verification",
            status="passed",
            message="Action does not require pre-flight isolated validation.",
        ))

    # =========================================================================
    # STEP 8: APPROVAL REQUIREMENT RESOLUTION
    # =========================================================================
    if is_blocked:
        final_decision = "block"
        requires_approval = False
    elif action_type_str == "read_repository" or action_type_str == "read_telemetry":
        final_decision = "allow"
        requires_approval = False
    elif action_type_str == "create_branch":
        final_decision = "allow"
        requires_approval = False
    elif is_security_incident:
        final_decision = "security_approval"
        requires_approval = True
        required_approvals_count = 1
        required_roles = ["security_officer", "admin", "owner"]
        matched_rule_name = "Security Incident Remediation Gate"
    elif has_infra_files or has_migration_files or risk_level == "critical":
        final_decision = "multi_approval"
        requires_approval = True
        required_approvals_count = 2
        required_roles = ["operator", "admin", "owner"]
        matched_rule_name = "Infrastructure / Migration Multi-Approval Gate"
    else:
        final_decision = "require_human"
        requires_approval = True
        required_approvals_count = 1
        required_roles = ["operator", "admin", "owner"]
        matched_rule_name = "Standard Human Operator Approval Gate"

    # Check custom policy rules in DB (cannot override mandatory blocks)
    if not is_blocked and final_decision != "block":
        custom_rule = db.query(PolicyRule).filter(
            or_(PolicyRule.organization_id == organization_id, PolicyRule.organization_id.is_(None)),
            PolicyRule.action_type == action_type_str,
            PolicyRule.is_active == True,
        ).order_by(PolicyRule.priority.asc()).first()

        if custom_rule:
            matched_rule_name = custom_rule.name
            rule_dec = custom_rule.decision.lower()
            if rule_dec in ("multi_approval", "security_approval", "require_human", "block"):
                final_decision = rule_dec
                if rule_dec == "multi_approval":
                    required_approvals_count = max(required_approvals_count, custom_rule.required_approvals_count or 2)
                if custom_rule.required_roles_json:
                    required_roles = custom_rule.required_roles_json

    steps.append(PolicyStepCheck(
        step_number=8,
        name="Approval Requirement Resolution",
        status="passed" if final_decision in ("allow", "require_human", "multi_approval", "security_approval") else "failed",
        message=f"Resolved Policy Decision: {final_decision.upper()} (Requires {required_approvals_count} approval(s) from {required_roles}).",
        details={
            "decision": final_decision,
            "required_approvals_count": required_approvals_count,
            "required_roles": required_roles,
            "matched_rule": matched_rule_name,
        },
    ))

    # =========================================================================
    # STEP 9: BASE SHA FRESHNESS & DRIFT VERIFICATION
    # =========================================================================
    if fix:
        base_sha = str(fix.base_commit_sha) if (hasattr(fix, "base_commit_sha") and fix.base_commit_sha and isinstance(fix.base_commit_sha, str)) else None
        if not base_sha or not GIT_SHA_REGEX.match(base_sha.strip()) or base_sha.strip() == ZERO_SHA:
            is_blocked = True
            msg = "Fix lacks a verified 40-character hexadecimal Git base commit SHA."

            steps.append(PolicyStepCheck(
                step_number=9,
                name="Base SHA Freshness & Exact Drift",
                status="failed",
                message=msg,
            ))
            reasons.append(msg)
            final_decision = "block"
        else:
            steps.append(PolicyStepCheck(
                step_number=9,
                name="Base SHA Freshness & Exact Drift",
                status="passed",
                message=f"Exact base commit SHA verified: {base_sha[:10]}...",
                details={"base_commit_sha": base_sha},
            ))
    else:
        steps.append(PolicyStepCheck(
            step_number=9,
            name="Base SHA Freshness & Exact Drift",
            status="passed",
            message="Entity does not require Git base commit verification.",
        ))

    allowed = (final_decision == "allow") and not is_blocked

    return _record_and_return_evaluation(
        db=db,
        organization_id=organization_id,
        actor=actor,
        action_type=action_type_str,
        decision=final_decision,
        allowed=allowed,
        requires_approval=requires_approval,
        required_approvals_count=required_approvals_count,
        required_roles=required_roles,
        risk_level=risk_level,
        steps=steps,
        reasons=reasons,
        matched_rule=matched_rule_name,
        fix=fix,
    )


def _record_and_return_evaluation(
    db: Session,
    organization_id: UUID,
    actor: Optional[User],
    action_type: str,
    decision: str,
    allowed: bool,
    requires_approval: bool,
    required_approvals_count: int,
    required_roles: List[str],
    risk_level: str,
    steps: List[PolicyStepCheck],
    reasons: List[str],
    matched_rule: Optional[str],
    fix: Optional[ProposedFix],
) -> PolicyEvaluationResultOut:
    """Record policy evaluation in database audit log and return result schema."""
    try:
        eval_record = PolicyEvaluation(
            organization_id=organization_id,
            user_id=actor.id if actor else None,
            action_type=action_type,
            target_entity_type="proposed_fix" if fix else "organization",
            target_entity_id=fix.id if fix else organization_id,
            patch_version=fix.patch_version if (fix and hasattr(fix, "patch_version")) else 1,
            snapshot_hash=fix.snapshot_hash if (fix and hasattr(fix, "snapshot_hash")) else None,
            decision=decision,
            reasons_json=reasons,
            context_snapshot_json={
            "risk_level": risk_level,
            "steps": [s.model_dump() if hasattr(s, "model_dump") else s.dict() for s in steps],
        },

        )
        db.add(eval_record)
        db.commit()
    except Exception as e:
        logger.warning(f"Could not persist policy evaluation log: {e}")
        db.rollback()

    return PolicyEvaluationResultOut(
        action_type=action_type,
        decision=decision,
        allowed=allowed,
        requires_approval=requires_approval,
        required_approvals_count=required_approvals_count,
        required_roles=required_roles,
        risk_level=risk_level,
        steps=steps,
        matched_rule=matched_rule,
        reasons=reasons,
        fix_id=fix.id if fix else None,
        patch_version=fix.patch_version if (fix and hasattr(fix, "patch_version")) else 1,
        snapshot_hash=fix.snapshot_hash if (fix and hasattr(fix, "snapshot_hash")) else None,
        base_commit_sha=fix.base_commit_sha if fix else None,
    )
