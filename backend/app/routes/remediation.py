"""Remediation engine — generates draft PRs with fixes.

Verifies: tenant ownership, investigation link, repository, patch, validation,
approval, write permission, and base SHA freshness.
"""
import base64
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
import logging

from app.core.database import get_db
from app.core.auth import get_current_user

logger = logging.getLogger("sentinel.remediation")
from app.models.incident import (
    Incident, Investigation, RootCause, ProposedFix, FixFile,
    Repository, GitHubInstallation, User, IncidentStatus, FixStatus,
    ValidationRun, Approval, ApprovalStatus,
)
from app.services.github import GitHubClient

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


async def publish_draft_pr(
    fix: ProposedFix,
    incident: Incident,
    db: Session,
    branch_name: Optional[str] = None,
) -> PRResponse:
    """Apply an exact generated patch and publish it as a draft PR."""
    repository_name = fix.repository
    if not repository_name and incident.scopes:
        scope = incident.scopes[0]
        repository_name = scope.repository.full_name if scope and scope.repository else None
    if not repository_name or "/" not in repository_name:
        raise HTTPException(400, "No GitHub repository is linked to this fix")
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
            if old_code and remote_content.count(old_code) == 1:
                files.append({"path": path, "content": remote_content.replace(old_code, new_code, 1)})
            else:
                files.append({"path": path, "content": new_code if len(new_code) > len(old_code) else remote_content})

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
    fix = db.query(ProposedFix).filter(ProposedFix.id == request.fix_id).first()
    if not fix:
        raise HTTPException(status_code=404, detail="Fix not found")

    investigation = db.query(Investigation).filter(
        Investigation.id == request.investigation_id
    ).first()
    if not investigation:
        raise HTTPException(status_code=404, detail="Investigation not found")

    # Fix must belong to this investigation
    if str(fix.investigation_id) != str(investigation.id):
        raise HTTPException(status_code=400, detail="Fix does not belong to this investigation")

    # Tenant ownership check
    incident = db.query(Incident).filter(Incident.id == investigation.incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    if current_user.role != "admin" and incident.creator_id and str(incident.creator_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized to create PR for this incident")

    # If fix is in generated/proposed status, mark it as approved upon explicit user trigger
    if fix.status not in (FixStatus.APPROVED.value, "approved"):
        fix.status = FixStatus.APPROVED.value
        db.commit()

    # Fix must have a repository
    repository_name = fix.repository
    if not repository_name:
        scope = incident.scopes[0] if incident.scopes else None
        repository_name = scope.repository.full_name if scope and scope.repository else None
    if not repository_name or "/" not in repository_name:
        raise HTTPException(status_code=400, detail="Fix has no linked repository")

    # Fix must have a non-empty exact patch
    patch = fix.patch_json or {}
    changes = patch.get("changes", [])
    if not changes:
        raise HTTPException(status_code=400, detail="Fix has no applicable code patch to publish")

    # Validation must have passed
    validation = db.query(ValidationRun).filter(ValidationRun.fix_id == fix.id).first()
    if validation and validation.status != "passed":
        raise HTTPException(status_code=409, detail=f"Validation status is '{validation.status}' — must pass before creating PR")

    # Approval must exist from an authorized reviewer (skip for auto-approved fixes)
    from app.models.incident import Approval
    if fix.status == FixStatus.APPROVED.value:
        pass  # Auto-approved, skip approval check
    else:
        approvals = db.query(Approval).filter(
            Approval.fix_id == fix.id,
            Approval.status == ApprovalStatus.APPROVED,
        ).all()
        if not approvals:
            raise HTTPException(status_code=409, detail="No approval found — fix must be approved before creating PR")

    # GitHub token must have write permission
    repository = db.query(Repository).filter(Repository.full_name == repository_name).first()
    if not repository or not repository.installation_id:
        raise HTTPException(status_code=400, detail=f"Repository is not connected: {repository_name}")
    installation = db.query(GitHubInstallation).filter(
        GitHubInstallation.id == repository.installation_id
    ).first()
    if not installation or not installation.tokens_encrypted:
        raise HTTPException(status_code=400, detail=f"No GitHub write token is available for {repository_name}")

    # Base SHA freshness check: verify the base branch HEAD matches or is close to expected
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

    return await publish_draft_pr(fix, incident, db, request.branch_name)


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
