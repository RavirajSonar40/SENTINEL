"""Shared GitHub token resolution for all pipeline stages.

Token resolution order:
1. User's own installation (user_id = current_user.id)
2. Org-scoped installation (organization_id = user's org)
3. Server-level GITHUB_TOKEN (fallback)
"""
import os
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)


def encrypt_github_token(token: str) -> str:
    """Encrypt a GitHub token before persisting it."""
    return encrypt_secret(token)


def resolve_stored_github_token(value: Optional[str]) -> Optional[str]:
    """Decrypt a stored token, accepting legacy plaintext rows during migration."""
    if not value:
        return None
    try:
        return decrypt_secret(value)
    except Exception:
        logger.warning("Using a legacy plaintext GitHub token; rotate it to encrypt the stored value")
        return value


def resolve_github_token(
    user=None,
    db: Session = None,
    repository: str = None,
    organization_id=None,
) -> Optional[str]:
    """Resolve the GitHub token for the current user/context.

    Resolution order:
    1. User's own installation (user_id matches)
    2. If repository provided, look up by repo owner's installation
    3. Org-scoped installation
    4. Server-level GITHUB_TOKEN fallback

    Args:
        user: The current User object (optional, for user-scoped lookup)
        db: Database session
        repository: Repository full name like "owner/repo" (optional)
        organization_id: Organization ID for org-scoped lookup (optional)

    Returns:
        GitHub token string or None
    """
    if not db:
        return settings.GITHUB_TOKEN or os.getenv("GITHUB_TOKEN") or None

    from app.models.incident import GitHubInstallation

    # Tier 1: User's own installation (highest priority)
    if user and hasattr(user, "id") and user.id:
        installation = db.query(GitHubInstallation).filter(
            GitHubInstallation.user_id == user.id,
            GitHubInstallation.tokens_encrypted.isnot(None),
            GitHubInstallation.tokens_encrypted != "",
        ).order_by(GitHubInstallation.updated_at.desc()).first()
        if installation:
            logger.debug(f"Resolved token from user installation for user {user.id}")
            return resolve_stored_github_token(installation.tokens_encrypted)

    # Tier 2: Repo-owner-scoped installation
    if repository and "/" in repository:
        repo_owner = repository.split("/")[0]
        installation = db.query(GitHubInstallation).filter(
            GitHubInstallation.account_login == repo_owner,
            GitHubInstallation.tokens_encrypted.isnot(None),
            GitHubInstallation.tokens_encrypted != "",
        ).first()
        if installation:
            logger.debug(f"Resolved token from repo-owner installation for {repo_owner}")
            return resolve_stored_github_token(installation.tokens_encrypted)

    # Tier 3: Org-scoped installation
    if organization_id:
        # Find repos in this org, then find their installations
        from app.models.incident import Repository
        repos = db.query(Repository).filter(
            Repository.organization_id == organization_id,
            Repository.installation_id.isnot(None),
        ).all()
        for repo in repos:
            inst = db.query(GitHubInstallation).filter(
                GitHubInstallation.id == repo.installation_id,
                GitHubInstallation.tokens_encrypted.isnot(None),
                GitHubInstallation.tokens_encrypted != "",
            ).first()
            if inst:
                logger.debug(f"Resolved token from org installation for org {organization_id}")
                return resolve_stored_github_token(inst.tokens_encrypted)

    # Tier 4: Server-level fallback
    token = settings.GITHUB_TOKEN or os.getenv("GITHUB_TOKEN")
    if token:
        logger.debug("Using server-level GITHUB_TOKEN fallback")

    return token
