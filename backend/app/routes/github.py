"""GitHub integration routes."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID
import httpx

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.config import settings
from app.models.incident import (
    User, Repository, GitHubInstallation, GitHubRepositorySync,
    GitHubWebhookEvent,
)
from app.services.github import GitHubClient, get_github_client

router = APIRouter(prefix="/github", tags=["github"])


# --- Config ---
GITHUB_CLIENT_ID = settings.GITHUB_CLIENT_ID
GITHUB_CLIENT_SECRET = settings.GITHUB_CLIENT_SECRET
GITHUB_REDIRECT_URI = settings.GITHUB_REDIRECT_URI
FRONTEND_URL = settings.FRONTEND_URL


# --- OAuth ---

@router.get("/login")
def github_login():
    """Redirect to GitHub OAuth."""
    if not GITHUB_CLIENT_ID:
        raise HTTPException(500, "GitHub OAuth not configured")
    url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={GITHUB_REDIRECT_URI}"
        f"&scope=repo,admin:repo_hook,user,read:org"
    )
    return RedirectResponse(url)


@router.get("/callback")
async def github_callback(code: str, iss: Optional[str] = None, db: Session = Depends(get_db)):
    """Handle GitHub OAuth callback."""
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise HTTPException(500, "GitHub OAuth not configured")

    # Exchange code for access token
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        if resp.is_error:
            raise HTTPException(
                status_code=502,
                detail="GitHub token exchange failed",
            )
        data = resp.json()

    access_token = data.get("access_token")
    if not access_token:
        github_error = data.get("error_description") or data.get("error")
        detail = f"GitHub OAuth failed: {github_error}" if github_error else "GitHub OAuth returned no access token"
        raise HTTPException(400, detail)

    # Get user info
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        user_data = resp.json()

    # Get installations (may fail if no GitHub App is installed)
    installations = []
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.github.com/user/installations",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
            if resp.status_code == 200:
                installations = resp.json().get("installations", [])
    except Exception:
        pass

    # Store installation(s)
    for inst in installations:
        existing = db.query(GitHubInstallation).filter(
            GitHubInstallation.installation_id == str(inst["id"])
        ).first()
        if not existing:
            inst_record = GitHubInstallation(
                installation_id=str(inst["id"]),
                account_type=inst["account"]["type"],
                account_login=inst["account"]["login"],
                account_id=str(inst["account"]["id"]),
                target_type=inst["target_type"],
                permissions=inst.get("permissions"),
                repository_selection=inst.get("repository_selection"),
                tokens_encrypted=access_token,  # TODO: encrypt
            )
            db.add(inst_record)
        else:
            existing.tokens_encrypted = access_token
            existing.permissions = inst.get("permissions")
            existing.repository_selection = inst.get("repository_selection")
            existing.updated_at = func.now()

    db.commit()

    # Redirect to frontend integrations page
    return RedirectResponse(f"{FRONTEND_URL}/integrations?connected=github")


@router.get("/status")
def github_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check GitHub connection status."""
    installations = db.query(GitHubInstallation).all()
    repos = db.query(Repository).filter(Repository.owner_id == current_user.id).all()
    return {
        "configured": bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET),
        "installations": len(installations),
        "repositories": len(repos),
        "connected": len(installations) > 0 or len(repos) > 0,
    }


# --- Repository Sync ---

class RepoSyncRequest(BaseModel):
    installation_id: str


@router.post("/sync")
async def sync_repositories(
    payload: RepoSyncRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sync repositories from a GitHub installation."""
    installation = db.query(GitHubInstallation).filter(
        GitHubInstallation.installation_id == payload.installation_id
    ).first()
    if not installation:
        raise HTTPException(404, "Installation not found")

    # Create sync record
    sync = GitHubRepositorySync(
        installation_id=installation.id,
        repository_id=UUID(int=0),  # placeholder, will update per repo
        sync_status="running",
    )
    db.add(sync)
    db.commit()

    token = installation.tokens_encrypted
    github = GitHubClient(token)

    try:
        repos = await github.list_repos()
        synced = 0
        for repo_data in repos:
            owner = repo_data["owner"]["login"]
            repo_name = repo_data["name"]
            full_name = repo_data["full_name"]

            # Upsert repository
            repo = db.query(Repository).filter(Repository.full_name == full_name).first()
            if not repo:
                repo = Repository(
                    name=repo_name,
                    full_name=full_name,
                    owner_id=current_user.id,
                    default_branch=repo_data.get("default_branch", "main"),
                    github_url=repo_data.get("html_url"),
                    installation_id=installation.id,
                )
                db.add(repo)
                db.flush()
            else:
                repo.installation_id = installation.id
                repo.default_branch = repo_data.get("default_branch", "main")
                repo.github_url = repo_data.get("html_url")

            # Create sync record for this repo
            repo_sync = GitHubRepositorySync(
                installation_id=installation.id,
                repository_id=repo.id,
                sync_status="completed",
                commits_synced=0,
                branches_synced=0,
            )
            db.add(repo_sync)
            synced += 1

        db.commit()
        return {"synced": synced, "status": "completed"}

    except Exception as e:
        db.rollback()
        return {"synced": 0, "status": "failed", "error": str(e)}


# --- API Routes ---

@router.get("/installations")
def list_installations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    installs = db.query(GitHubInstallation).all()
    return [
        {
            "id": str(i.id),
            "installation_id": i.installation_id,
            "account_login": i.account_login,
            "account_type": i.account_type,
            "repository_selection": i.repository_selection,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        }
        for i in installs
    ]


@router.get("/installations/{installation_id}/repos")
async def list_installation_repos(
    installation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    installation = db.query(GitHubInstallation).filter(
        GitHubInstallation.installation_id == installation_id
    ).first()
    if not installation:
        raise HTTPException(404, "Installation not found")

    repos = db.query(Repository).filter(
        Repository.installation_id == installation.id
    ).all()

    return [
        {
            "id": str(r.id),
            "name": r.name,
            "full_name": r.full_name,
            "default_branch": r.default_branch,
            "github_url": r.github_url,
            "sync_status": "synced",
            "last_synced": None,
        }
        for r in repos
    ]


@router.get("/repos/{owner}/{repo}/commits")
async def list_commits(
    owner: str,
    repo: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    branch: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Find installation for this repo
    repo_obj = db.query(Repository).filter(Repository.full_name == f"{owner}/{repo}").first()
    if not repo_obj or not repo_obj.installation_id:
        raise HTTPException(404, "Repository not connected")

    installation = db.query(GitHubInstallation).filter(
        GitHubInstallation.id == repo_obj.installation_id
    ).first()
    if not installation:
        raise HTTPException(404, "Installation not found")

    token = installation.tokens_encrypted
    github = GitHubClient(token)

    commits = await github.list_commits(owner, repo, since, until, branch, limit)
    return [
        {
            "sha": c["sha"],
            "message": c["commit"]["message"],
            "author": c["commit"]["author"]["name"],
            "email": c["commit"]["author"]["email"],
            "date": c["commit"]["author"]["date"],
            "url": c["html_url"],
            "files": [f["filename"] for f in c.get("files", [])] if "files" in c else [],
        }
        for c in commits
    ]


@router.get("/repos/{owner}/{repo}/commits/{sha}")
async def get_commit(
    owner: str,
    repo: str,
    sha: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo_obj = db.query(Repository).filter(Repository.full_name == f"{owner}/{repo}").first()
    if not repo_obj or not repo_obj.installation_id:
        raise HTTPException(404, "Repository not connected")

    installation = db.query(GitHubInstallation).filter(
        GitHubInstallation.id == repo_obj.installation_id
    ).first()
    token = installation.tokens_encrypted
    github = GitHubClient(token)

    commit = await github.get_commit(owner, repo, sha)
    diff = await github.get_commit_diff(owner, repo, sha)

    return {
        "sha": commit["sha"],
        "message": commit["commit"]["message"],
        "author": commit["commit"]["author"]["name"],
        "email": commit["commit"]["author"]["email"],
        "date": commit["commit"]["author"]["date"],
        "url": commit["html_url"],
        "files": commit.get("files", []),
        "diff": diff,
        "stats": commit.get("stats", {}),
    }


@router.get("/repos/{owner}/{repo}/branches")
async def list_branches(
    owner: str,
    repo: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo_obj = db.query(Repository).filter(Repository.full_name == f"{owner}/{repo}").first()
    if not repo_obj or not repo_obj.installation_id:
        raise HTTPException(404, "Repository not connected")

    installation = db.query(GitHubInstallation).filter(
        GitHubInstallation.id == repo_obj.installation_id
    ).first()
    token = installation.tokens_encrypted
    github = GitHubClient(token)

    branches = await github.list_branches(owner, repo)
    return [
        {
            "name": b["name"],
            "commit_sha": b["commit"]["sha"],
            "protected": b.get("protected", False),
        }
        for b in branches
    ]


@router.get("/repos/{owner}/{repo}/pulls")
async def list_pull_requests(
    owner: str,
    repo: str,
    state: str = "all",
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo_obj = db.query(Repository).filter(Repository.full_name == f"{owner}/{repo}").first()
    if not repo_obj or not repo_obj.installation_id:
        raise HTTPException(404, "Repository not connected")

    installation = db.query(GitHubInstallation).filter(
        GitHubInstallation.id == repo_obj.installation_id
    ).first()
    token = installation.tokens_encrypted
    github = GitHubClient(token)

    prs = await github.list_prs(owner, repo, state, limit)
    return [
        {
            "number": pr["number"],
            "title": pr["title"],
            "state": pr["state"],
            "author": pr["user"]["login"],
            "created_at": pr["created_at"],
            "updated_at": pr["updated_at"],
            "merged_at": pr.get("merged_at"),
            "url": pr["html_url"],
            "head_branch": pr["head"]["ref"],
            "base_branch": pr["base"]["ref"],
        }
        for pr in prs
    ]


@router.get("/repos/{owner}/{repo}/pulls/{number}")
async def get_pull_request(
    owner: str,
    repo: str,
    number: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo_obj = db.query(Repository).filter(Repository.full_name == f"{owner}/{repo}").first()
    if not repo_obj or not repo_obj.installation_id:
        raise HTTPException(404, "Repository not connected")

    installation = db.query(GitHubInstallation).filter(
        GitHubInstallation.id == repo_obj.installation_id
    ).first()
    token = installation.tokens_encrypted
    github = GitHubClient(token)

    pr = await github.get_pr(owner, repo, number)
    files = await github.get_pr_files(owner, repo, number)
    diff = await github.get_pr_diff(owner, repo, number)

    return {
        "number": pr["number"],
        "title": pr["title"],
        "state": pr["state"],
        "author": pr["user"]["login"],
        "created_at": pr["created_at"],
        "updated_at": pr["updated_at"],
        "merged_at": pr.get("merged_at"),
        "url": pr["html_url"],
        "head_branch": pr["head"]["ref"],
        "base_branch": pr["base"]["ref"],
        "files": files,
        "diff": diff,
    }


# --- Webhook ---

@router.post("/webhook")
async def github_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """Receive GitHub webhook events."""
    delivery_id = request.headers.get("X-GitHub-Delivery")
    event_type = request.headers.get("X-GitHub-Event")
    signature = request.headers.get("X-Hub-Signature-256")

    if not delivery_id or not event_type:
        raise HTTPException(400, "Missing required headers")

    body = await request.body()
    payload = await request.json()

    # Store webhook event
    event = GitHubWebhookEvent(
        delivery_id=delivery_id,
        event_type=event_type,
        action=payload.get("action"),
        payload=payload,
    )
    db.add(event)
    db.commit()

    # Process based on event type
    # TODO: Trigger investigation for push/deployment events

    return {"status": "received"}


# --- Utility ---

from sqlalchemy.sql import func