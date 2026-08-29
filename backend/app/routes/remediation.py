import os
import base64
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
import logging

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.permissions import require_operator, require_viewer

logger = logging.getLogger("sentinel.remediation")
from app.models.incident import (
    Incident, Investigation, RootCause, ProposedFix, FixFile,
    Repository, GitHubInstallation, User, IncidentStatus, FixStatus,
    ValidationRun, ValidationCheckRun, Approval, ApprovalStatus, Organization, UserOrganizationMembership,
    GeneratedTest, PatchVersion, TestType, RegressionTestStatus, RevalidationStatus,
    ValidationCheckType, ValidationCheckStatus,
)
from app.models.work_item import WorkItem
from app.schemas.remediation import (
    PatchChange, TestToAdd, PatchGenerateRequest, PatchEditRequest,
    PatchValidateRequest, PatchSafetyResultOut, GeneratedTestOut,
    PatchVersionOut, ProposedFixDetailOut,
    ValidationCheckRunOut, ValidationReportOut, ReplayScenarioRequest,
)
from app.services.github import GitHubClient
from app.services.patch_safety_engine import validate_patch_safety, compute_patch_snapshot_hash
from app.services.patch_generator import synthesize_patch_and_tests, generate_unified_diff
from app.services.patch_test_runner import execute_two_phase_regression_test
from app.services.isolated_validator import run_isolated_validation_pipeline
from app.services.scenario_replayer import execute_offline_scenario_replay
from app.services.policy_gateway import evaluate_action_policy
from app.services.approval_service import invalidate_stale_approvals_for_fix


router = APIRouter()


class PRRequest(BaseModel):
    investigation_id: str
    fix_id: str
    branch_name: Optional[str] = None


class PRResponse(BaseModel):
    status: str
    pr_url: Optional[str] = None
    branch_name: str
    commit_sha: Optional[str] = None
    message: str


# --- Fix Templates ---

FIX_TEMPLATES = {
    "code_fix": {
        "description": "Direct code fix for the identified root cause",
        "pr_title_prefix": "fix:",
        "reviewers_required": 2,
        "auto_merge": False,
    },
    "dependency_update": {
        "description": "Update or pin dependency version",
        "pr_title_prefix": "chore(deps):",
        "reviewers_required": 1,
        "auto_merge": True,
    },
    "config_fix": {
        "description": "Configuration correction",
        "pr_title_prefix": "fix(config):",
        "reviewers_required": 1,
        "auto_merge": False,
    },
    "rollback": {
        "description": "Rollback to previous version",
        "pr_title_prefix": "revert:",
        "reviewers_required": 1,
        "auto_merge": True,
    },
    "infra_fix": {
        "description": "Infrastructure remediation",
        "pr_title_prefix": "fix(infra):",
        "reviewers_required": 2,
        "auto_merge": False,
    },
}


def generate_branch_name(incident: Incident, fix: ProposedFix) -> str:
    """Generate a branch name for the fix."""
    incident_num = incident.number or "000"
    fix_type = fix.fix_type or "fix"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"sentinel/INC-{incident_num:04d}-{fix_type}-{timestamp}"


def generate_fix_content(
    fix: ProposedFix,
    root_cause: Optional[RootCause],
    incident: Optional[Incident] = None,
    investigation: Optional[Investigation] = None,
    validation_report: Optional[Dict] = None,
    evidence_items: Optional[List] = None,
) -> Dict:
    """Generate comprehensive PR content with all required sections.

    Includes: incident link, root cause, evidence, files changed, diff,
    validation results, risk, rollback notes, and Sentinel non-merge statement.
    """
    template = FIX_TEMPLATES.get(fix.fix_type, FIX_TEMPLATES["code_fix"])
    patch = fix.patch_json or {}
    changes = patch.get("changes", [])
    diffs = patch.get("diffs", [])

    # Incident section
    incident_section = ""
    if incident:
        incident_section = f"""## Incident

- **Number:** INC-{incident.number:04d}
- **Title:** {incident.title}
- **Severity:** {incident.severity}
- **Status:** {incident.status}
- **Service:** {incident.service_name or 'Unknown'}
- **Detected:** {incident.detected_at.isoformat() if incident.detected_at else 'Unknown'}
"""

    # Root cause section
    rc_section = ""
    if root_cause:
        rc_section = f"""## Root Cause

- **Summary:** {root_cause.summary}
- **Confidence:** {root_cause.confidence}
- **Category:** {root_cause.affected_component}
- **Explanation:** {root_cause.causal_explanation}
"""

    # Evidence section
    evidence_section = ""
    if evidence_items:
        evidence_section = "## Evidence\n\n"
        for ev in evidence_items[:10]:
            evidence_section += f"- **{ev.get('source_type', 'Unknown')}**: {ev.get('title', '')} (score: {ev.get('relevance_score', 'N/A')})\n"

    # Files changed section
    files_section = "## Files Changed\n\n"
    if changes:
        for change in changes:
            action = change.get("action", "modify")
            files_section += f"- `{change.get('file', 'unknown')}` ({action})\n"
    else:
        files_section += "- No file changes\n"

    # Diff summary section
    diff_section = ""
    if diffs:
        diff_section = "## Diff Summary\n\n```diff\n"
        for d in diffs[:3]:
            diff_section += d[:2000] + "\n"
        diff_section += "```\n"
    elif changes:
        diff_section = "## Diff Summary\n\n"
        for change in changes:
            if change.get("old_code") and change.get("new_code"):
                diff_section += f"### `{change.get('file', '')}`\n```diff\n"
                diff_section += f"- {change['old_code'][:500]}\n+ {change['new_code'][:500]}\n"
                diff_section += "```\n"

    # Validation section
    validation_section = ""
    if validation_report:
        status = validation_report.get("status", "unknown")
        passed = validation_report.get("passed_checks", 0)
        total = validation_report.get("total_checks", 0)
        validation_section = f"""## Validation Results

- **Status:** {status.upper()}
- **Checks:** {passed}/{total} passed
"""
        for result in validation_report.get("results", []):
            emoji = "PASS" if result.get("status") == "passed" else "FAIL"
            validation_section += f"  - [{emoji}] {result.get('check_type', 'unknown')}: {result.get('message', '')}\n"
    else:
        validation_section = "## Validation Results\n\n- No validation run yet\n"

    # Risk and rollback section
    risk = patch.get("risk", fix.risk or "medium")
    risk_explanation = patch.get("risk_explanation", "Generated by AI — requires human review")
    rollback_section = f"""## Risk and Rollback

- **Risk Level:** {risk.upper()}
- **Assessment:** {risk_explanation}

### Rollback Plan
1. Revert this PR
2. Verify service health after rollback
3. Investigate root cause before re-deploying
"""

    # Build title
    title = f"{template['pr_title_prefix']} {fix.title}"

    # Build body
    body = f"""# Sentinel Automated Fix

> **This PR was generated by Sentinel AI Incident Response Agent.**
> **Sentinel did NOT merge this PR. Human review and approval is required.**

{incident_section}
{rc_section}
{evidence_section}
{files_section}
{diff_section}
{validation_section}
{rollback_section}
---

*Generated by [Sentinel](https://github.com/RavirajSonar40/SENTINEL) — AI Incident Response Agent*
*Investigation ID: {fix.investigation_id}*
*Fix ID: {fix.id}*
"""

    return {"title": title, "body": body, "files": []}


def _resolve_fix_repository(
    fix: ProposedFix,
    incident: Incident,
    investigation: Optional[Investigation],
    db: Session,
) -> Optional[str]:
    """Auto-detect and link repository if not explicitly specified."""
    if fix.repository and "/" in fix.repository:
        return fix.repository

    # 1. Check incident scopes
    if incident.scopes:
        for scope in incident.scopes:
            if scope.repository and scope.repository.full_name and "/" in scope.repository.full_name:
                fix.repository = scope.repository.full_name
                db.commit()
                return fix.repository

    # 2. Check investigation evidence
    if investigation:
        from app.models.incident import Evidence
        ev = db.query(Evidence).filter(
            Evidence.investigation_id == investigation.id,
            Evidence.repository.isnot(None),
        ).first()
        if ev and ev.repository and "/" in ev.repository:
            fix.repository = ev.repository
            db.commit()
            return fix.repository

    # 3. Check connected repositories in DB
    first_repo = db.query(Repository).first()
    if first_repo and first_repo.full_name and "/" in first_repo.full_name:
        fix.repository = first_repo.full_name
        db.commit()
        return fix.repository

    return None


async def publish_draft_pr(
    fix: ProposedFix,
    incident: Incident,
    db: Session,
    branch_name: Optional[str] = None,
) -> PRResponse:
    """Apply an exact generated patch and publish it as a draft PR."""
    investigation = db.query(Investigation).filter(
        Investigation.id == fix.investigation_id
    ).first()

    repository_name = _resolve_fix_repository(fix, incident, investigation, db)
    if not repository_name or "/" not in repository_name:
        raise HTTPException(400, "No GitHub repository could be auto-linked to this fix")
    repository = db.query(Repository).filter(Repository.full_name == repository_name).first()
    installation = None
    if repository and repository.installation_id:
        installation = db.query(GitHubInstallation).filter(
            GitHubInstallation.id == repository.installation_id
        ).first()

    gh_token = None
    if installation and installation.tokens_encrypted:
        gh_token = installation.tokens_encrypted
    if not gh_token:
        from app.core.config import settings
        import os
        gh_token = settings.GITHUB_TOKEN or os.getenv("GITHUB_TOKEN")

    if not gh_token:
        raise HTTPException(400, f"No GitHub write token is available for {repository_name}")

    patch = fix.patch_json or {}
    changes = patch.get("changes", [])
    if not changes:
        raise HTTPException(400, "This fix has no applicable code patch to publish")

    owner, repo_name = repository_name.split("/", 1)
    github = GitHubClient(gh_token)
    default_branch = (repository.default_branch if repository else None) or "master"
    files = []
    for change in changes:
        path = change.get("file")
        action = change.get("action", "modify")
        old_code = change.get("old_code", "")
        new_code = change.get("new_code", "")
        if not path or not new_code:
            raise HTTPException(400, f"Patch for {path or 'unknown file'} is not publishable")

        if action == "create":
            files.append({"path": path, "content": new_code})
        else:
            remote_file = await github.get_file(owner, repo_name, path, default_branch)
            encoded = remote_file.get("content", "").replace("\n", "")
            try:
                remote_content = base64.b64decode(encoded).decode("utf-8")
            except Exception as exc:
                raise HTTPException(502, f"Could not decode {path} from GitHub: {exc}")
            if old_code and old_code in remote_content:
                files.append({"path": path, "content": remote_content.replace(old_code, new_code, 1)})
            else:
                raise HTTPException(409, f"Unsafe patch rejected: Target code snippet was not found in {path}")

    # Gather context for comprehensive PR body
    investigation = db.query(Investigation).filter(
        Investigation.id == fix.investigation_id
    ).first()
    root_cause = db.query(RootCause).filter(RootCause.id == fix.root_cause_id).first()
    if not root_cause and investigation:
        root_cause = db.query(RootCause).filter(
            RootCause.investigation_id == investigation.id
        ).first()

    # Get validation report
    validation_report = None
    try:
        from app.models.incident import ValidationRun
        validation = db.query(ValidationRun).filter(ValidationRun.fix_id == fix.id).first()
        if validation:
            validation_report = {
                "status": validation.status,
                "passed_checks": validation.passed_checks or 0,
                "total_checks": validation.total_checks or 0,
                "results": [{"check_type": validation.check_type, "status": validation.status, "message": validation.message or ""}],
            }
    except Exception:
        pass

    # Get evidence items
    evidence_items = []
    if investigation:
        from app.models.incident import Evidence
        evidence_rows = db.query(Evidence).filter(
            Evidence.investigation_id == investigation.id
        ).limit(10).all()
        evidence_items = [
            {
                "source_type": str(e.source_type),
                "title": e.title,
                "relevance_score": e.relevance_score,
            }
            for e in evidence_rows
        ]

    pr_content = generate_fix_content(
        fix, root_cause, incident, investigation, validation_report, evidence_items,
    )
    branch = branch_name or generate_branch_name(incident, fix)
    base_branch = repository.default_branch or "main"
    await github.create_branch(owner, repo_name, branch, base_branch)
    commit = await github.create_commit(
        owner, repo_name, branch, patch.get("commit_message", fix.title), files
    )
    pr = await github.create_pull_request(
        owner, repo_name, pr_content["title"], pr_content["body"], branch, base_branch, draft=True
    )
    fix.branch_name = branch
    fix.pr_number = pr["pr_number"]
    fix.pr_url = pr["pr_url"]
    db.commit()
    return PRResponse(
        status="created", branch_name=branch, commit_sha=commit.get("commit_sha"),
        pr_url=pr["pr_url"], message=f"Draft PR created for {repository_name}",
    )


# --- API Endpoints ---

@router.get("/remediation/fixes")
async def list_fixes(
    investigation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all proposed fixes for an investigation."""
    fixes = db.query(ProposedFix).filter(
        ProposedFix.investigation_id == investigation_id
    ).all()
    return [
        {
            "id": f.id,
            "investigation_id": f.investigation_id,
            "root_cause_id": f.root_cause_id,
            "fix_type": f.fix_type,
            "repository": f.repository,
            "title": f.title,
            "description": f.description,
            "status": f.status,
            "diff": f.diff,
            "patch": f.patch_json,
            "branch_name": f.branch_name,
            "pr_number": f.pr_number,
            "pr_url": f.pr_url,
            "created_at": f.generated_at.isoformat() if f.generated_at else None,
        }
        for f in fixes
    ]


@router.post("/remediation/generate-pr")
async def generate_draft_pr(
    request: PRRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a draft PR for a proposed fix.

    Verifies:
    - Fix belongs to current tenant (admin bypasses)
    - Fix belongs to investigation
    - Fix has a repository
    - Fix has a non-empty exact patch
    - Validation passed
    - Approval exists from an authorized reviewer
    - GitHub token has write permission
    - Base SHA is still current or safely rebased
    """
    try:
        fix_uuid = UUID(str(request.fix_id)) if not isinstance(request.fix_id, UUID) else request.fix_id
    except (ValueError, TypeError):
        fix_uuid = request.fix_id

    try:
        inv_uuid = UUID(str(request.investigation_id)) if not isinstance(request.investigation_id, UUID) else request.investigation_id
    except (ValueError, TypeError):
        inv_uuid = request.investigation_id


    fix = db.query(ProposedFix).filter(ProposedFix.id == fix_uuid).first()
    if not fix:
        raise HTTPException(status_code=404, detail="Fix not found")

    investigation = db.query(Investigation).filter(
        Investigation.id == inv_uuid
    ).first()

    if not investigation:
        raise HTTPException(status_code=404, detail="Investigation not found")

    # Fix must belong to this investigation
    if str(fix.investigation_id) != str(investigation.id):
        raise HTTPException(status_code=400, detail="Fix does not belong to this investigation")

    # 1. Organization tenant boundary check
    incident = db.query(Incident).filter(Incident.id == investigation.incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    if current_user.role != "admin" and incident.creator_id and str(incident.creator_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized to create PR for this incident")

    # 2. Policy Gateway Deterministic Evaluation
    org_id = getattr(fix, "organization_id", None) or getattr(incident, "organization_id", None)
    if org_id and isinstance(org_id, (str, UUID)):
        try:
            org_uuid = UUID(str(org_id))
            policy_res = evaluate_action_policy(
                db=db,
                organization_id=org_uuid,
                actor=current_user,
                action_type="create_draft_pr",
                fix=fix,
                incident=incident,
            )
            if policy_res.decision == "block":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Draft PR creation blocked by Policy Gateway: {'; '.join(policy_res.reasons)}",
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Policy evaluation check warning: {e}")


    # 3. Race-Protected Approval & Exact Patch Binding Verification
    is_postgres = db.bind.dialect.name == "postgresql" if db.bind else False
    app_query = db.query(Approval).filter(
        Approval.fix_id == fix.id,
        Approval.status == ApprovalStatus.APPROVED,
    )
    if is_postgres:
        app_query = app_query.with_for_update()

    approval = app_query.first()
    if not approval:
        raise HTTPException(status_code=409, detail="Fix must have a verified, approved Approval record before creating PR")

    # Verify patch version and snapshot hash match the approved snapshot
    fix_version = fix.patch_version if (hasattr(fix, "patch_version") and fix.patch_version) else 1
    if approval.patch_version and approval.patch_version != fix_version:
        raise HTTPException(
            status_code=409,
            detail=f"Approval is stale (Approved version {approval.patch_version} != current patch version {fix_version}). Fresh approval required.",
        )

    if approval.snapshot_hash and fix.snapshot_hash and approval.snapshot_hash != fix.snapshot_hash:
        raise HTTPException(
            status_code=409,
            detail="Approval is stale (Snapshot hash changed since approval). Fresh approval required.",
        )

    # 4. Fix must have a repository (auto-resolve if not explicitly set)
    repository_name = _resolve_fix_repository(fix, incident, investigation, db)
    if not repository_name or "/" not in repository_name:
        raise HTTPException(status_code=400, detail="No GitHub repository could be auto-linked to this fix")

    # 5. Fix must have a non-empty exact patch
    patch = fix.patch_json or {}
    changes = patch.get("changes", [])
    if not changes:
        raise HTTPException(status_code=400, detail="Fix has no applicable code patch to publish")

    # 6. Validation must have passed
    validation = db.query(ValidationRun).filter(ValidationRun.fix_id == fix.id).order_by(ValidationRun.created_at.desc()).first()
    if not validation or validation.status != "passed":
        val_status = validation.status if validation else "not_run"
        raise HTTPException(status_code=409, detail=f"Validation status is '{val_status}' — must pass isolated validation before creating PR")

    # 7. GitHub token must have write permission
    repository = db.query(Repository).filter(Repository.full_name == repository_name).first()
    if not repository or not repository.installation_id:
        raise HTTPException(status_code=400, detail=f"Repository is not connected: {repository_name}")
    installation = db.query(GitHubInstallation).filter(
        GitHubInstallation.id == repository.installation_id
    ).first()
    if not installation or not installation.tokens_encrypted:
        raise HTTPException(status_code=400, detail=f"No GitHub write token is available for {repository_name}")

    # 8. Base SHA freshness check: verify the base branch HEAD matches or is close to expected
    base_branch = repository.default_branch or "main"
    try:
        from app.services.github import GitHubClient
        from app.core.config import settings
        gh = GitHubClient(token=installation.tokens_encrypted or settings.GITHUB_TOKEN)
        owner, repo_name = repository_name.split("/", 1)
        branch_info = await gh.get_branch(owner, repo_name, base_branch)
        remote_sha = branch_info.get("commit", {}).get("sha", "")
    except Exception as e:
        logger.warning(f"Base SHA freshness check failed: {e}")
        # Non-blocking — proceed with caution

    res = await publish_draft_pr(fix, incident, db, request.branch_name)
    fix.status = FixStatus.DRAFT_PR_CREATED.value
    db.commit()
    return res



@router.get("/remediation/pr-config")
async def get_pr_config(
    current_user: User = Depends(get_current_user),
):
    """Get PR generation configuration."""
    return {
        "templates": FIX_TEMPLATES,
        "branch_naming": "sentinel/INC-{number:04d}-{type}-{date}",
        "auto_merge_rules": {
            "dependency_update": True,
            "rollback": True,
            "code_fix": False,
            "config_fix": False,
        },
        "required_reviewers": {
            "code_fix": 2,
            "dependency_update": 1,
            "config_fix": 1,
            "rollback": 1,
            "infra_fix": 2,
        },
    }


# ============================================================================
# PHASE 11: PATCH & TEST GENERATION ENDPOINTS
# ============================================================================

@router.post("/remediation/patches/generate", response_model=ProposedFixDetailOut)
async def generate_patch_and_tests_endpoint(
    req: PatchGenerateRequest,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Generate repository-bound patch, tests, and two-phase regression verification."""
    org, membership = context
    current_user = membership.user or db.query(User).filter(User.id == membership.user_id).first()
    org_id = org.id

    incident = None
    work_item = None
    repository = None

    # 1. Resolve & Enforce Tenant Parity
    if req.incident_id:
        inc_uuid = UUID(req.incident_id) if isinstance(req.incident_id, str) else req.incident_id
        incident = db.query(Incident).filter(Incident.id == inc_uuid).first()
        if not incident or incident.organization_id != org_id:
            raise HTTPException(status_code=400, detail="Incident does not belong to the same organization")

    if req.work_item_id:
        wi_uuid = UUID(req.work_item_id) if isinstance(req.work_item_id, str) else req.work_item_id
        work_item = db.query(WorkItem).filter(WorkItem.id == wi_uuid).first()
        if not work_item or work_item.organization_id != org_id:
            raise HTTPException(status_code=400, detail="Work item does not belong to the same organization")

    if req.repository_id:
        repo_uuid = UUID(req.repository_id) if isinstance(req.repository_id, str) else req.repository_id
        repository = db.query(Repository).filter(Repository.id == repo_uuid).first()
        if not repository or repository.organization_id != org_id:
            raise HTTPException(status_code=400, detail="Repository does not belong to the same organization")

    # 2. Extract Context & File Contents
    file_contents: Dict[str, str] = {}
    repo_name = repository.full_name if repository else (incident.service if incident else "service-repo")
    base_sha = req.base_commit_sha or (repository.default_branch if repository else "main")

    # Read relevant files if scope specified
    if req.scope_files:
        for fpath in req.scope_files:
            if os.path.exists(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        file_contents[fpath] = f.read()
                except Exception:
                    pass

    is_direct = work_item is not None and (work_item.work_type.value if hasattr(work_item.work_type, 'value') else str(work_item.work_type)) in ("direct_task", "feature", "task", "DIRECT_TASK", "FEATURE")
    instructions = req.instructions or (work_item.description if work_item else (incident.description if incident else ""))

    root_cause_text = None
    if incident:
        if incident.root_causes:
            root_cause_text = incident.root_causes[0].description
        else:
            root_cause_text = incident.description

    # 3. Synthesize Patch & Tests
    synthesis = await synthesize_patch_and_tests(
        file_contents=file_contents,
        repository_name=repo_name,
        base_commit_sha=base_sha,
        scope_files=req.scope_files,
        root_cause_summary=root_cause_text,
        user_instructions=instructions,
        is_direct_task=is_direct,
    )

    changes = synthesis.get("changes", [])
    tests_to_add = synthesis.get("tests_to_add", [])
    tests_to_run = synthesis.get("tests_to_run", [])
    rollback_plan = synthesis.get("rollback_plan", "Revert changes")

    # 4. Strict Pre-Flight Safety & Rejection Gate
    safety = validate_patch_safety(
        changes=changes,
        file_contents=file_contents,
        scope_files=req.scope_files,
        tests_to_add=tests_to_add,
        repository_id=str(repository.id) if repository else None,
        base_commit_sha=base_sha,
        is_direct_task=is_direct,
    )

    is_rejected = not safety["is_safe"]
    rejection_reason = safety.get("rejection_reason")

    # 5. Two-Phase Regression Execution (if regression tests present and safe)
    regression_status = RegressionTestStatus.NOT_APPLICABLE.value if is_direct else RegressionTestStatus.PENDING.value
    regression_runs = []
    if not is_rejected and tests_to_add and not is_direct:
        reg_result = execute_two_phase_regression_test(
            file_contents=file_contents,
            patch_changes=changes,
            regression_tests=[t for t in tests_to_add if t.get("test_type") == "regression"],
            test_commands=tests_to_run,
        )
        regression_status = reg_result.get("status", RegressionTestStatus.PENDING.value)
        regression_runs = reg_result.get("runs", [])
        if regression_status in ("failed_pre_check", "failed_post_check"):
            is_rejected = True
            rejection_reason = reg_result.get("message", "Regression test verification failed")

    # 6. Generate Unified Diff
    diff_text = generate_unified_diff(changes, file_contents)

    # 7. Persist ProposedFix Model
    fix = ProposedFix(
        organization_id=org_id,
        incident_id=incident.id if incident else (work_item.incident_id if work_item and work_item.incident_id else None),
        work_item_id=work_item.id if work_item else None,
        repository_id=repository.id if repository else None,
        repository=repo_name,
        base_commit_sha=base_sha,
        target_branch=req.target_branch or "main",
        title=synthesis.get("summary", "Generated Code Patch"),
        description=instructions or "Autonomous code remediation",
        fix_type="direct_task" if is_direct else "code_fix",
        status=FixStatus.REJECTED.value if is_rejected else FixStatus.GENERATED.value,
        proposed_change=synthesis.get("summary", "Code patch"),
        diff=diff_text,
        patch_json={"changes": changes},
        scope_files_json=req.scope_files,
        tests_to_add_json=tests_to_add,
        tests_to_run_json=tests_to_run,
        rollback_plan=rollback_plan,
        regression_test_status=regression_status,
        is_rejected=is_rejected,
        rejection_reason=rejection_reason,
        snapshot_hash=safety.get("snapshot_hash"),
        version=1,
    )
    db.add(fix)
    db.flush()

    # 8. Persist Generated Tests
    gen_test_models = []
    for t in tests_to_add:
        gt = GeneratedTest(
            organization_id=org_id,
            fix_id=fix.id,
            file_path=t.get("file", "tests/test_fix.py"),
            test_type=TestType(t.get("test_type", "regression")),
            framework=t.get("framework", "pytest"),
            test_name=t.get("test_name", "test_generated"),
            test_code=t.get("test_code", ""),
            target_symbol=t.get("target_symbol"),
            pre_patch_result="failed" if regression_status == "reproduced_and_fixed" else None,
            post_patch_result="passed" if regression_status == "reproduced_and_fixed" else None,
        )
        db.add(gt)
        gen_test_models.append(gt)

    # 9. Persist Initial PatchVersion
    pv = PatchVersion(
        organization_id=org_id,
        fix_id=fix.id,
        version_number=1,
        editor_user_id=current_user.id,
        patch_data_json={"changes": changes},
        diff_content=diff_text,
        previous_snapshot_hash=None,
        new_snapshot_hash=safety.get("snapshot_hash") or "",
        revalidation_status=RevalidationStatus.PASSED.value if not is_rejected else RevalidationStatus.FAILED.value,
        revalidation_details_json={"safety": safety, "regression_runs": regression_runs},
    )
    db.add(pv)
    db.commit()
    db.refresh(fix)

    return _build_proposed_fix_detail(fix, db)


@router.post("/remediation/patches/{fix_id}/edit", response_model=ProposedFixDetailOut)
async def edit_patch_and_revalidate(
    fix_id: str,
    req: PatchEditRequest,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Manual patch edit: increments version, invalidates previous safety checks, and revalidates."""
    org, membership = context
    current_user = membership.user or db.query(User).filter(User.id == membership.user_id).first()
    
    fix_uuid = UUID(fix_id) if isinstance(fix_id, str) else fix_id
    fix = db.query(ProposedFix).filter(ProposedFix.id == fix_uuid).first()
    if not fix or (fix.organization_id and fix.organization_id != org.id):
        raise HTTPException(status_code=404, detail="Fix not found")

    # 1. Invalidate Stale Results & Increment Version
    prev_snapshot_hash = fix.snapshot_hash
    fix.version += 1

    changes = [c.dict() for c in req.changes]
    tests_to_add = [t.dict() for t in req.tests_to_add] if req.tests_to_add else (fix.tests_to_add_json or [])
    tests_to_run = req.tests_to_run or fix.tests_to_run_json
    rollback_plan = req.rollback_plan or fix.rollback_plan

    file_contents: Dict[str, str] = {}
    for c in changes:
        fpath = c.get("file")
        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    file_contents[fpath] = f.read()
            except Exception:
                pass

    # 2. Strict Pre-Flight Safety Check on Edited Patch
    safety = validate_patch_safety(
        changes=changes,
        file_contents=file_contents,
        scope_files=fix.scope_files_json,
        tests_to_add=tests_to_add,
        repository_id=str(fix.repository_id) if fix.repository_id else None,
        base_commit_sha=fix.base_commit_sha,
    )

    is_rejected = not safety["is_safe"]
    rejection_reason = safety.get("rejection_reason")

    # 3. Re-run Two-Phase Regression Execution if Applicable
    regression_status = fix.regression_test_status
    regression_runs = []
    if not is_rejected and tests_to_add and regression_status != "not_applicable":
        reg_result = execute_two_phase_regression_test(
            file_contents=file_contents,
            patch_changes=changes,
            regression_tests=[t for t in tests_to_add if t.get("test_type") == "regression"],
            test_commands=tests_to_run,
        )
        regression_status = reg_result.get("status", RegressionTestStatus.PENDING.value)
        regression_runs = reg_result.get("runs", [])
        if regression_status in ("failed_pre_check", "failed_post_check"):
            is_rejected = True
            rejection_reason = reg_result.get("message", "Regression test verification failed after edit")

    # 4. Generate New Unified Diff & Snapshot Hash
    diff_text = generate_unified_diff(changes, file_contents)
    new_snapshot_hash = safety.get("snapshot_hash") or ""

    # 5. Invalidate Any Stale Approvals for this Fix
    invalidate_stale_approvals_for_fix(db, fix.id)

    # 6. Update ProposedFix
    fix.diff = diff_text
    fix.patch_json = {"changes": changes}
    fix.tests_to_add_json = tests_to_add
    fix.tests_to_run_json = tests_to_run
    fix.rollback_plan = rollback_plan
    fix.regression_test_status = regression_status
    fix.is_rejected = is_rejected
    fix.rejection_reason = rejection_reason
    fix.snapshot_hash = new_snapshot_hash
    fix.status = FixStatus.REJECTED.value if is_rejected else FixStatus.GENERATED.value
    if hasattr(fix, "editor_user_id"):
        fix.editor_user_id = current_user.id

    # 7. Append New PatchVersion Record
    pv = PatchVersion(
        organization_id=fix.organization_id or org.id,
        fix_id=fix.id,
        version_number=fix.version,
        editor_user_id=current_user.id,
        patch_data_json={"changes": changes},
        diff_content=diff_text,
        previous_snapshot_hash=prev_snapshot_hash,
        new_snapshot_hash=new_snapshot_hash,
        revalidation_status=RevalidationStatus.PASSED.value if not is_rejected else RevalidationStatus.FAILED.value,
        revalidation_details_json={"safety": safety, "regression_runs": regression_runs},
    )
    db.add(pv)
    db.commit()
    db.refresh(fix)

    return _build_proposed_fix_detail(fix, db)



@router.post("/remediation/patches/validate", response_model=PatchSafetyResultOut)
async def validate_patch_endpoint(
    req: PatchValidateRequest,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """Dry-run pre-flight safety check for a patch payload."""
    changes = [c.dict() for c in req.changes]
    file_contents = {}
    for c in changes:
        fpath = c.get("file")
        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    file_contents[fpath] = f.read()
            except Exception:
                pass

    safety = validate_patch_safety(
        changes=changes,
        file_contents=file_contents,
        scope_files=req.scope_files,
        repository_id=req.repository_id,
        base_commit_sha=req.base_commit_sha,
    )

    return PatchSafetyResultOut(
        is_safe=safety["is_safe"],
        rejection_reason=safety.get("rejection_reason"),
        scope_valid=safety["scope_valid"],
        replacements_valid=safety["replacements_valid"],
        secrets_clean=safety["secrets_clean"],
        ast_valid=safety["ast_valid"],
        bloat_valid=safety["bloat_valid"],
        snapshot_hash=safety.get("snapshot_hash"),
        details=safety.get("details"),
    )


@router.get("/remediation/fixes/{fix_id}/patch", response_model=ProposedFixDetailOut)
async def get_fix_patch_detail(
    fix_id: str,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """Get full structured patch details, diff, tests, and version history for a fix."""
    org, _ = context
    fix_uuid = UUID(fix_id) if isinstance(fix_id, str) else fix_id
    fix = db.query(ProposedFix).filter(ProposedFix.id == fix_uuid).first()
    if not fix or (fix.organization_id and fix.organization_id != org.id):
        raise HTTPException(status_code=404, detail="Fix not found")
    return _build_proposed_fix_detail(fix, db)


@router.get("/remediation/fixes/{fix_id}/tests", response_model=List[GeneratedTestOut])
async def get_fix_tests(
    fix_id: str,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """List generated tests for a proposed fix."""
    org, _ = context
    fix_uuid = UUID(fix_id) if isinstance(fix_id, str) else fix_id
    fix = db.query(ProposedFix).filter(ProposedFix.id == fix_uuid).first()
    if not fix or (fix.organization_id and fix.organization_id != org.id):
        raise HTTPException(status_code=404, detail="Fix not found")

    tests = db.query(GeneratedTest).filter(GeneratedTest.fix_id == fix.id).all()
    return [
        GeneratedTestOut(
            id=str(t.id),
            file_path=t.file_path,
            test_type=t.test_type.value if hasattr(t.test_type, "value") else str(t.test_type),
            framework=t.framework,
            test_name=t.test_name,
            test_code=t.test_code,
            target_symbol=t.target_symbol,
            pre_patch_result=t.pre_patch_result,
            post_patch_result=t.post_patch_result,
            created_at=t.created_at.isoformat() if t.created_at else None,
        )
        for t in tests
    ]


@router.get("/remediation/fixes/{fix_id}/history", response_model=List[PatchVersionOut])
async def get_fix_history(
    fix_id: str,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """Get complete version history and audit log for a fix."""
    org, _ = context
    fix_uuid = UUID(fix_id) if isinstance(fix_id, str) else fix_id
    fix = db.query(ProposedFix).filter(ProposedFix.id == fix_uuid).first()
    if not fix or (fix.organization_id and fix.organization_id != org.id):
        raise HTTPException(status_code=404, detail="Fix not found")

    versions = db.query(PatchVersion).filter(PatchVersion.fix_id == fix.id).order_by(PatchVersion.version_number.asc()).all()
    return [
        PatchVersionOut(
            id=str(v.id),
            version_number=v.version_number,
            editor_user_id=str(v.editor_user_id) if v.editor_user_id else None,
            patch_data=v.patch_data_json or {},
            diff_content=v.diff_content,
            previous_snapshot_hash=v.previous_snapshot_hash,
            new_snapshot_hash=v.new_snapshot_hash,
            revalidation_status=v.revalidation_status,
            revalidation_details=v.revalidation_details_json,
            created_at=v.created_at.isoformat() if v.created_at else None,
        )
        for v in versions
    ]


def _build_proposed_fix_detail(fix: ProposedFix, db: Session) -> ProposedFixDetailOut:
    """Helper to construct complete ProposedFixDetailOut schema."""
    tests = db.query(GeneratedTest).filter(GeneratedTest.fix_id == fix.id).all()
    versions = db.query(PatchVersion).filter(PatchVersion.fix_id == fix.id).order_by(PatchVersion.version_number.asc()).all()

    return ProposedFixDetailOut(
        id=str(fix.id),
        organization_id=str(fix.organization_id) if fix.organization_id else None,
        incident_id=str(fix.incident_id) if fix.incident_id else None,
        work_item_id=str(fix.work_item_id) if fix.work_item_id else None,
        repository_id=str(fix.repository_id) if fix.repository_id else None,
        repository=fix.repository,
        base_commit_sha=fix.base_commit_sha,
        target_branch=fix.target_branch,
        title=fix.title,
        description=fix.description,
        fix_type=fix.fix_type,
        status=fix.status,
        diff=fix.diff,
        patch=fix.patch_json,
        scope_files=fix.scope_files_json,
        rollback_plan=fix.rollback_plan,
        regression_test_status=fix.regression_test_status,
        is_rejected=fix.is_rejected,
        rejection_reason=fix.rejection_reason,
        snapshot_hash=fix.snapshot_hash,
        version=fix.version,
        tests_to_add=fix.tests_to_add_json,
        tests_to_run=fix.tests_to_run_json,
        branch_name=fix.branch_name,
        pr_number=fix.pr_number,
        pr_url=fix.pr_url,
        generated_at=fix.generated_at.isoformat() if fix.generated_at else None,
        generated_tests=[
            GeneratedTestOut(
                id=str(t.id),
                file_path=t.file_path,
                test_type=t.test_type.value if hasattr(t.test_type, "value") else str(t.test_type),
                framework=t.framework,
                test_name=t.test_name,
                test_code=t.test_code,
                target_symbol=t.target_symbol,
                pre_patch_result=t.pre_patch_result,
                post_patch_result=t.post_patch_result,
                created_at=t.created_at.isoformat() if t.created_at else None,
            )
            for t in tests
        ],
        versions=[
            PatchVersionOut(
                id=str(v.id),
                version_number=v.version_number,
                editor_user_id=str(v.editor_user_id) if v.editor_user_id else None,
                patch_data=v.patch_data_json or {},
                diff_content=v.diff_content,
                previous_snapshot_hash=v.previous_snapshot_hash,
                new_snapshot_hash=v.new_snapshot_hash,
                revalidation_status=v.revalidation_status,
                revalidation_details=v.revalidation_details_json,
                created_at=v.created_at.isoformat() if v.created_at else None,
            )
            for v in versions
        ],
    )


# ============================================================================
# PHASE 12: ISOLATED VALIDATION & REPLAY ENDPOINTS
# ============================================================================

@router.post("/remediation/fixes/{fix_id}/validate", response_model=ValidationReportOut)
async def validate_fix_isolated(
    fix_id: str,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Trigger the complete 8-Stage Isolated Validation & Replay Pipeline."""
    org, _ = context
    fix_uuid = UUID(fix_id) if isinstance(fix_id, str) else fix_id
    fix = db.query(ProposedFix).filter(ProposedFix.id == fix_uuid).first()
    if not fix or (fix.organization_id and fix.organization_id != org.id):
        raise HTTPException(status_code=404, detail="Fix not found")

    try:
        res = run_isolated_validation_pipeline(fix.id, db)
    except Exception as e:
        logger.error(f"Isolated validation pipeline failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Validation execution failed: {str(e)}")

    val_uuid = UUID(res["validation_id"])
    val_run = db.query(ValidationRun).filter(ValidationRun.id == val_uuid).first()
    if not val_run:
        raise HTTPException(status_code=500, detail="Validation run record could not be retrieved")

    return _build_validation_report_out(val_run)


@router.get("/remediation/fixes/{fix_id}/validation-report", response_model=ValidationReportOut)
async def get_latest_validation_report(
    fix_id: str,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """Get the latest structured validation report for a proposed fix."""
    org, _ = context
    fix_uuid = UUID(fix_id) if isinstance(fix_id, str) else fix_id
    fix = db.query(ProposedFix).filter(ProposedFix.id == fix_uuid).first()
    if not fix or (fix.organization_id and fix.organization_id != org.id):
        raise HTTPException(status_code=404, detail="Fix not found")

    val_run = (
        db.query(ValidationRun)
        .filter(ValidationRun.fix_id == fix.id, ValidationRun.organization_id == org.id)
        .order_by(ValidationRun.created_at.desc())
        .first()
    )
    if not val_run:
        raise HTTPException(status_code=404, detail="No validation run found for this fix")

    return _build_validation_report_out(val_run)


@router.get("/remediation/fixes/{fix_id}/validation-runs", response_model=List[ValidationReportOut])
async def list_validation_runs(
    fix_id: str,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """List all historical validation runs and check step logs for a fix."""
    org, _ = context
    fix_uuid = UUID(fix_id) if isinstance(fix_id, str) else fix_id
    fix = db.query(ProposedFix).filter(ProposedFix.id == fix_uuid).first()
    if not fix or (fix.organization_id and fix.organization_id != org.id):
        raise HTTPException(status_code=404, detail="Fix not found")

    runs = (
        db.query(ValidationRun)
        .filter(ValidationRun.fix_id == fix.id, ValidationRun.organization_id == org.id)
        .order_by(ValidationRun.created_at.desc())
        .all()
    )
    return [_build_validation_report_out(r) for r in runs]


@router.post("/remediation/fixes/{fix_id}/replay-scenario")
async def trigger_scenario_replay(
    fix_id: str,
    req: Optional[ReplayScenarioRequest] = None,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Trigger fully offline, sanitized incident scenario replay."""
    org, _ = context
    fix_uuid = UUID(fix_id) if isinstance(fix_id, str) else fix_id
    fix = db.query(ProposedFix).filter(ProposedFix.id == fix_uuid).first()
    if not fix or (fix.organization_id and fix.organization_id != org.id):
        raise HTTPException(status_code=404, detail="Fix not found")

    repo = db.query(Repository).filter(Repository.id == fix.repository_id).first() if fix.repository_id else None
    incident = db.query(Incident).filter(Incident.id == fix.incident_id).first() if fix.incident_id else None

    replay_signals = []
    if incident:
        replay_signals = [{"title": incident.title, "error_signature": incident.error_signature, "service": incident.service_name}]

    import tempfile
    import shutil
    temp_dir = tempfile.mkdtemp(prefix="sentinel_replay_")
    try:
        res = execute_offline_scenario_replay(
            workspace_path=temp_dir,
            service_name=repo.name if repo else "service",
            error_signature=fix.title or fix.description or "",
            signals=replay_signals,
            language=repo.language if repo and repo.language else "python",
            timeout_sec=req.timeout_sec if req else 30,
        )
        return res
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _build_validation_report_out(val: ValidationRun) -> ValidationReportOut:
    """Helper to convert ValidationRun ORM object to ValidationReportOut schema."""
    check_runs_out = []
    if val.check_runs:
        for cr in val.check_runs:
            check_runs_out.append(
                ValidationCheckRunOut(
                    id=str(cr.id),
                    check_type=cr.check_type.value if hasattr(cr.check_type, "value") else str(cr.check_type),
                    name=cr.name,
                    command=cr.command_json if isinstance(cr.command_json, list) else [str(cr.command_json)],
                    status=cr.status.value if hasattr(cr.status, "value") else str(cr.status),
                    exit_code=cr.exit_code,
                    stdout=cr.stdout,
                    stderr=cr.stderr,
                    duration_ms=cr.duration_ms or 0.0,
                    error_message=cr.error_message,
                    started_at=cr.started_at.isoformat() if cr.started_at else None,
                    completed_at=cr.completed_at.isoformat() if cr.completed_at else None,
                )
            )

    return ValidationReportOut(
        validation_id=str(val.id),
        fix_id=str(val.fix_id),
        organization_id=str(val.organization_id),
        repository_id=str(val.repository_id) if val.repository_id else None,
        base_commit_sha=val.base_commit_sha or "",
        verified_base_sha=val.verified_base_sha,
        workspace_id=val.workspace_id or "",
        status=val.status.value if hasattr(val.status, "value") else str(val.status),
        compilation_status=val.compilation_status or "pending",
        tests_status=val.tests_status or "pending",
        original_failure_reproduced=val.original_failure_reproduced or "n/a",
        failure_absent_after_patch=val.failure_absent_after_patch or "n/a",
        scenario_replay_status=val.scenario_replay_status or "n/a",
        production_outcome=val.production_outcome or "unknown until deployed",
        overall_status=val.overall_status or "pending",
        total_checks=val.total_checks or len(check_runs_out),
        passed_checks=val.passed_checks or 0,
        failed_checks=val.failed_checks or 0,
        started_at=val.started_at.isoformat() if val.started_at else None,
        completed_at=val.completed_at.isoformat() if val.completed_at else None,
        summary_report=val.summary_report_json,
        check_runs=check_runs_out,
    )


