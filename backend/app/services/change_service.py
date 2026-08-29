import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.incident import (
    ChangeEvent,
    ChangeType,
    ChangeRiskLevel,
    Service,
    Repository,
    Environment,
    Deployment,
)
from app.schemas.changes import ChangeEventCreate

logger = logging.getLogger(__name__)

ALLOWED_PROVIDERS = {
    "github",
    "launchdarkly",
    "terraform",
    "kubernetes",
    "argo",
    "alembic",
    "flyway",
    "manual",
    "generic",
}

SENSITIVE_KEY_PATTERNS = [
    r"password",
    r"secret",
    r"token",
    r"api[_-]?key",
    r"auth",
    r"credential",
    r"private[_-]?key",
    r"cookie",
    r"database[_-]?url",
    r"connection[_-]?string",
    r"bearer",
    r"cert",
    r"ssh[_-]?key",
]

SENSITIVE_REGEX = re.compile("|".join(SENSITIVE_KEY_PATTERNS), re.IGNORECASE)


def redact_sensitive_data(obj: Any) -> Any:
    """Recursively redact sensitive key-values in dicts and lists."""
    if isinstance(obj, dict):
        sanitized = {}
        for k, v in obj.items():
            if SENSITIVE_REGEX.search(str(k)):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = redact_sensitive_data(v)
        return sanitized
    elif isinstance(obj, list):
        return [redact_sensitive_data(item) for item in obj]
    elif isinstance(obj, str):
        if len(obj) > 2048:
            return obj[:2048] + "...[TRUNCATED]"
        return obj
    return obj


def generate_change_fingerprint(
    organization_id: uuid.UUID,
    provider: str,
    change_type: str,
    service_id: Optional[uuid.UUID],
    effective_at: datetime,
    title: str,
) -> str:
    """Generate a deterministic SHA-256 fallback fingerprint when no external ID is supplied."""
    raw = f"{organization_id}:{provider.lower()}:{change_type.upper()}:{service_id or 'none'}:{effective_at.isoformat()}:{title.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def ingest_change_event(
    db: Session,
    organization_id: uuid.UUID,
    data: ChangeEventCreate,
    auth_source: str = "api_token",
    integration_id: Optional[uuid.UUID] = None,
) -> Tuple[ChangeEvent, bool]:
    """
    Idempotently ingest a ChangeEvent.
    Returns (change_event, is_created).
    """
    provider = (data.provider or "manual").lower().strip()
    if provider not in ALLOWED_PROVIDERS:
        provider = "generic"

    effective_at = data.effective_at or datetime.now(timezone.utc)
    if effective_at.tzinfo is None:
        effective_at = effective_at.replace(tzinfo=timezone.utc)

    # 1. Resolve External ID
    external_id = data.external_id
    if not external_id or not external_id.strip():
        if data.provider_event_id:
            external_id = f"{provider}:{data.provider_event_id}"
        elif data.commit_sha:
            external_id = f"commit:{data.commit_sha}"
        else:
            external_id = generate_change_fingerprint(
                organization_id=organization_id,
                provider=provider,
                change_type=data.change_type.value,
                service_id=data.service_id,
                effective_at=effective_at,
                title=data.title,
            )

    # 2. Sanitize diff_summary and metadata_json
    clean_diff = redact_sensitive_data(data.diff_summary or {})
    clean_meta = redact_sensitive_data(data.metadata_json or {})

    # 3. Check for existing record by (org_id, provider, change_type, external_id)
    existing = db.query(ChangeEvent).filter(
        ChangeEvent.organization_id == organization_id,
        ChangeEvent.provider == provider,
        ChangeEvent.change_type == data.change_type,
        ChangeEvent.external_id == external_id,
    ).first()

    if existing:
        existing.title = data.title
        existing.description = data.description or existing.description
        existing.service_id = data.service_id or existing.service_id
        existing.environment_id = data.environment_id or existing.environment_id
        existing.repository_id = data.repository_id or existing.repository_id
        existing.deployment_id = data.deployment_id or existing.deployment_id
        existing.commit_sha = data.commit_sha or existing.commit_sha
        existing.author = data.author or existing.author
        existing.risk_level = data.risk_level or existing.risk_level
        existing.effective_at = effective_at
        existing.source_url = data.source_url or existing.source_url
        existing.affected_components = data.affected_components or existing.affected_components
        existing.diff_summary = clean_diff
        existing.metadata_json = clean_meta
        flag_modified(existing, "affected_components")
        flag_modified(existing, "diff_summary")
        flag_modified(existing, "metadata_json")
        db.commit()
        db.refresh(existing)
        return existing, False

    # Create new change event
    event = ChangeEvent(
        organization_id=organization_id,
        service_id=data.service_id,
        environment_id=data.environment_id,
        repository_id=data.repository_id,
        deployment_id=data.deployment_id,
        provider=provider,
        provider_event_id=data.provider_event_id,
        auth_source=auth_source,
        integration_id=integration_id,
        change_type=data.change_type,
        title=data.title,
        description=data.description,
        external_id=external_id,
        commit_sha=data.commit_sha,
        author=data.author,
        risk_level=data.risk_level,
        effective_at=effective_at,
        observed_at=datetime.now(timezone.utc),
        source_url=data.source_url,
        affected_components=data.affected_components or [],
        diff_summary=clean_diff,
        metadata_json=clean_meta,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event, True


def batch_ingest_changes(
    db: Session,
    organization_id: uuid.UUID,
    items: List[ChangeEventCreate],
    auth_source: str = "api_batch",
) -> Dict[str, int]:
    """Batch ingest up to 100 change events."""
    created = 0
    updated = 0
    for item in items[:100]:
        _, is_created = ingest_change_event(db, organization_id, item, auth_source=auth_source)
        if is_created:
            created += 1
        else:
            updated += 1
    return {"created": created, "updated": updated, "total": len(items)}


# ============================================================================
# PROVIDER-SPECIFIC WEBHOOK PARSERS
# ============================================================================

def parse_github_change_webhook(
    db: Session,
    organization_id: uuid.UUID,
    payload: Dict[str, Any],
    event_type: str,
) -> Optional[ChangeEventCreate]:
    """Parse GitHub Push / Pull Request / Release webhook payloads into ChangeEventCreate."""
    repo_data = payload.get("repository", {})
    repo_full_name = repo_data.get("full_name")

    repo_id = None
    if repo_full_name:
        repo = db.query(Repository).filter(
            Repository.organization_id == organization_id,
            Repository.full_name == repo_full_name,
        ).first()
        if repo:
            repo_id = repo.id

    if event_type == "push":
        commits = payload.get("commits", [])
        head_commit = payload.get("head_commit") or (commits[-1] if commits else {})
        commit_sha = head_commit.get("id") or payload.get("after")
        author = head_commit.get("author", {}).get("name") or payload.get("pusher", {}).get("name")
        title = head_commit.get("message", "Git push commit").split("\n")[0][:255]
        ref = payload.get("ref", "")
        branch = ref.replace("refs/heads/", "")

        return ChangeEventCreate(
            title=f"Commit: {title}",
            change_type=ChangeType.CODE_COMMIT,
            provider="github",
            provider_event_id=commit_sha,
            repository_id=repo_id,
            external_id=commit_sha,
            commit_sha=commit_sha,
            author=author,
            risk_level=ChangeRiskLevel.LOW,
            source_url=head_commit.get("url") or payload.get("compare"),
            diff_summary={
                "branch": branch,
                "added": head_commit.get("added", []),
                "removed": head_commit.get("removed", []),
                "modified": head_commit.get("modified", []),
            },
            metadata_json={"ref": ref, "commits_count": len(commits)},
        )

    elif event_type == "pull_request":
        action = payload.get("action")
        pr = payload.get("pull_request", {})
        merged = pr.get("merged", False)
        if action != "closed" or not merged:
            return None  # Only index merged PRs as change events

        pr_number = pr.get("number")
        title = pr.get("title", "Pull Request")[:255]
        author = pr.get("user", {}).get("login")
        merged_at_str = pr.get("merged_at")
        merged_at = datetime.fromisoformat(merged_at_str.replace("Z", "+00:00")) if merged_at_str else None

        return ChangeEventCreate(
            title=f"PR #{pr_number}: {title}",
            change_type=ChangeType.PULL_REQUEST,
            provider="github",
            provider_event_id=f"pr_{pr_number}",
            repository_id=repo_id,
            external_id=f"pr_{repo_full_name}_{pr_number}",
            commit_sha=pr.get("merge_commit_sha"),
            author=author,
            risk_level=ChangeRiskLevel.MEDIUM if pr.get("additions", 0) > 200 else ChangeRiskLevel.LOW,
            effective_at=merged_at,
            source_url=pr.get("html_url"),
            diff_summary={
                "additions": pr.get("additions", 0),
                "deletions": pr.get("deletions", 0),
                "changed_files": pr.get("changed_files", 0),
            },
            metadata_json={"base_branch": pr.get("base", {}).get("ref")},
        )

    return None


def parse_launchdarkly_change_webhook(
    db: Session,
    organization_id: uuid.UUID,
    payload: Dict[str, Any],
) -> Optional[ChangeEventCreate]:
    """Parse LaunchDarkly flag toggle / rollout webhook."""
    flag_key = payload.get("name") or payload.get("key") or "feature_flag"
    action = payload.get("action") or "toggle"
    title = f"Feature Flag '{flag_key}' {action}"
    author = payload.get("member", {}).get("email") or payload.get("user", {}).get("name")
    env_name = payload.get("environment", {}).get("name")

    env_id = None
    if env_name:
        env = db.query(Environment).filter(
            Environment.organization_id == organization_id,
            Environment.name == env_name,
        ).first()
        if env:
            env_id = env.id

    return ChangeEventCreate(
        title=title[:255],
        change_type=ChangeType.FEATURE_FLAG,
        provider="launchdarkly",
        provider_event_id=payload.get("_id") or str(uuid.uuid4()),
        environment_id=env_id,
        author=author,
        risk_level=ChangeRiskLevel.HIGH if "enable" in action.lower() or "on" in action.lower() else ChangeRiskLevel.MEDIUM,
        source_url=payload.get("url"),
        affected_components=[flag_key],
        diff_summary={
            "flag_key": flag_key,
            "action": action,
            "old_value": payload.get("previousValue"),
            "new_value": payload.get("currentValue"),
        },
        metadata_json=payload.get("metadata", {}),
    )


def parse_terraform_change_webhook(
    db: Session,
    organization_id: uuid.UUID,
    payload: Dict[str, Any],
) -> Optional[ChangeEventCreate]:
    """Parse Terraform Cloud / Atlantis apply webhook."""
    workspace = payload.get("workspace_name") or payload.get("run", {}).get("workspace", {}).get("name") or "infrastructure"
    title = f"Terraform Applied in {workspace}"
    author = payload.get("run", {}).get("created_by", {}).get("username")
    run_id = payload.get("run", {}).get("id") or str(uuid.uuid4())

    return ChangeEventCreate(
        title=title[:255],
        change_type=ChangeType.INFRASTRUCTURE,
        provider="terraform",
        provider_event_id=run_id,
        author=author,
        risk_level=ChangeRiskLevel.HIGH,
        source_url=payload.get("run", {}).get("url"),
        affected_components=[workspace],
        diff_summary={
            "resources_added": payload.get("run", {}).get("resources_added", 0),
            "resources_changed": payload.get("run", {}).get("resources_changed", 0),
            "resources_deleted": payload.get("run", {}).get("resources_deleted", 0),
        },
        metadata_json={"workspace": workspace, "run_id": run_id},
    )


def parse_kubernetes_change_webhook(
    db: Session,
    organization_id: uuid.UUID,
    payload: Dict[str, Any],
) -> Optional[ChangeEventCreate]:
    """Parse Kubernetes / ArgoCD sync / scaling event webhook."""
    app_name = payload.get("app_name") or payload.get("metadata", {}).get("name") or "workload"
    change_type_str = payload.get("type", "SCALING_CHANGE").upper()

    change_type = ChangeType.SCALING_CHANGE
    if "DEPLOY" in change_type_str or "ROLLOUT" in change_type_str:
        change_type = ChangeType.DEPLOYMENT
    elif "CONFIG" in change_type_str:
        change_type = ChangeType.CONFIGURATION

    service = db.query(Service).filter(
        Service.organization_id == organization_id,
        Service.slug == app_name.lower(),
    ).first()

    return ChangeEventCreate(
        title=f"K8s {change_type.value}: {app_name}",
        change_type=change_type,
        provider="kubernetes",
        provider_event_id=payload.get("uid") or str(uuid.uuid4()),
        service_id=service.id if service else None,
        author="kubernetes-controller",
        risk_level=ChangeRiskLevel.MEDIUM,
        affected_components=[app_name],
        diff_summary={
            "replicas": payload.get("replicas"),
            "image": payload.get("image"),
        },
        metadata_json=payload.get("metadata", {}),
    )
