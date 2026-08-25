from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.incident import Repository, User

router = APIRouter(prefix="/repositories", tags=["repositories"])


class RepositoryOut(BaseModel):
    id: str
    name: str
    full_name: str
    default_branch: str
    service_id: str | None = None
    github_url: str | None = None
    sync_status: str = "pending"
    last_synced_at: str | None = None


@router.get("", response_model=List[RepositoryOut])
def list_repositories(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repos = db.query(Repository).filter(Repository.owner_id == current_user.id).all()
    return [
        RepositoryOut(
            id=str(r.id),
            name=r.name,
            full_name=r.full_name,
            default_branch=r.default_branch,
            service_id=str(r.service_id) if r.service_id else None,
            github_url=r.github_url,
            sync_status=r.sync_status or "pending",
            last_synced_at=r.last_synced_at.isoformat() if r.last_synced_at else None,
        )
        for r in repos
    ]
