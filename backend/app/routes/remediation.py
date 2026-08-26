"""Remediation engine — generates draft PRs with fixes."""
import base64
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.incident import (
    Incident, Investigation, RootCause, ProposedFix, FixFile,
    Repository, GitHubInstallation, User, IncidentStatus, FixStatus,
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


def generate_fix_content(fix: ProposedFix, root_cause: Optional[RootCause]) -> Dict:
    """Generate fix content based on type and root cause."""
    template = FIX_TEMPLATES.get(fix.fix_type, FIX_TEMPLATES["code_fix"])

    if fix.fix_type == "rollback":
        return {
            "title": f"{template['pr_title_prefix']} rollback to previous version",
            "body": f"""## Rollback Proposal

**Incident:** {root_cause.summary if root_cause else 'Unknown'}
**Root Cause:** {root_cause.causal_explanation if root_cause else 'N/A'}

### Rollback Instructions
1. Revert the deployment to the previous stable version
2. Verify service health after rollback
3. Investigate the root cause before re-deploying

### Risk Assessment
- Risk: LOW
- Impact: Service restoration
- Verification: Health checks pass
""",
            "files": [],
        }


    elif fix.fix_type == "dependency_update":
        return {
            "title": f"{template['pr_title_prefix']} update dependencies to fix {fix.title}",
            "body": f"""## Dependency Update

**Issue:** {fix.title}
**Description:** {fix.description}

### Changes
- Update or pin the problematic dependency version
- Run full test suite to verify compatibility

### Testing
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Manual verification
""",
            "files": [
                {"path": "package.json", "change": "Update dependency version"},
                {"path": "requirements.txt", "change": "Pin dependency version"},
            ],
        }

    elif fix.fix_type == "config_fix":
        return {
            "title": f"{template['pr_title_prefix']} correct configuration for {fix.title}",
            "body": f"""## Configuration Fix

**Issue:** {fix.title}
**Description:** {fix.description}

### Changes
- Revert or correct the configuration change
- Add validation to prevent future misconfigurations

### Verification
- [ ] Configuration validated
- [ ] Service starts correctly
- [ ] Health checks pass
""",
            "files": [
                {"path": "config.yaml", "change": "Correct configuration"},
                {"path": ".env", "change": "Revert environment variables"},
            ],
        }

    else:
        return {
            "title": f"{template['pr_title_prefix']} {fix.title}",
            "body": f"""## Proposed Fix

**Issue:** {fix.title}
**Description:** {fix.description}

### Changes
{chr(10).join(f'- {fp}' for fp in (fix.files_to_modify or []))}

### Testing
- [ ] All tests pass
- [ ] No regressions
- [ ] Manual verification
""",
            "files": [],
        }


async def publish_draft_pr(
    fix: ProposedFix,
    incident: Incident,
    db: Session,
    branch_name: Optional[str] = None,
) -> PRResponse:
    """Apply an exact generated patch and publish it as a draft PR."""
    repository_name = fix.repository
    if not repository_name:
        scope = incident.scopes[0] if incident.scopes else None
        repository_name = scope.repository.full_name if scope and scope.repository else None
    if not repository_name or "/" not in repository_name:
        raise HTTPException(400, "No GitHub repository is linked to this fix")

    repository = db.query(Repository).filter(Repository.full_name == repository_name).first()
    if not repository or not repository.installation_id:
        raise HTTPException(400, f"Repository is not connected: {repository_name}")
    installation = db.query(GitHubInstallation).filter(
        GitHubInstallation.id == repository.installation_id
    ).first()
    if not installation or not installation.tokens_encrypted:
        raise HTTPException(400, f"No GitHub write token is available for {repository_name}")

    patch = fix.patch_json or {}
    changes = patch.get("changes", [])
    if not changes:
        raise HTTPException(400, "This fix has no applicable code patch to publish")

    owner, repo_name = repository_name.split("/", 1)
    github = GitHubClient(installation.tokens_encrypted)
    files = []
    for change in changes:
        path = change.get("file")
        old_code = change.get("old_code", "")
        new_code = change.get("new_code", "")
        if not path or change.get("action", "modify") != "modify" or not old_code or not new_code:
            raise HTTPException(400, f"Patch for {path or 'unknown file'} is not publishable")
        remote_file = await github.get_file(owner, repo_name, path, repository.default_branch)
        encoded = remote_file.get("content", "").replace("\n", "")
        try:
            remote_content = base64.b64decode(encoded).decode("utf-8")
        except Exception as exc:
            raise HTTPException(502, f"Could not decode {path} from GitHub: {exc}")
        if remote_content.count(old_code) != 1:
            raise HTTPException(409, f"Patch no longer matches {repository_name}/{path}")
        files.append({"path": path, "content": remote_content.replace(old_code, new_code, 1)})

    root_cause = db.query(RootCause).filter(RootCause.id == fix.root_cause_id).first()
    pr_content = generate_fix_content(fix, root_cause)
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
    """Generate a draft PR for a proposed fix."""
    fix = db.query(ProposedFix).filter(ProposedFix.id == request.fix_id).first()
    if not fix:
        raise HTTPException(status_code=404, detail="Fix not found")

    investigation = db.query(Investigation).filter(
        Investigation.id == request.investigation_id
    ).first()
    if not investigation:
        raise HTTPException(status_code=404, detail="Investigation not found")
    if fix.status != FixStatus.APPROVED.value:
        raise HTTPException(
            status_code=409,
            detail="Fix must be explicitly approved before creating a draft PR",
        )

    incident = db.query(Incident).filter(
        Incident.id == investigation.incident_id
    ).first()

    root_cause = db.query(RootCause).filter(
        RootCause.investigation_id == request.investigation_id
    ).first()

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
