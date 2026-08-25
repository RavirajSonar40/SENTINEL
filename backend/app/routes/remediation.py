"""Remediation engine — generates draft PRs with fixes."""
import hashlib
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.incident import (
    Incident, Investigation, RootCause, ProposedFix, FixFile,
    User, IncidentStatus, FixStatus,
)

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
            "title": f.title,
            "description": f.description,
            "status": f.status,
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

    incident = db.query(Incident).filter(
        Incident.id == investigation.incident_id
    ).first()

    root_cause = db.query(RootCause).filter(
        RootCause.investigation_id == request.investigation_id
    ).first()

    # Generate PR content
    pr_content = generate_fix_content(fix, root_cause)
    branch_name = request.branch_name or generate_branch_name(incident, fix)

    # Update fix status
    fix.status = FixStatus.GENERATED.value
    db.commit()

    return PRResponse(
        status="generated",
        branch_name=branch_name,
        message=f"Draft PR content generated for: {fix.title}",
        pr_url=None,
    )


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
