from app.routes.auth import router as auth_router
from app.routes.incidents import router as incidents_router
from app.routes.repositories import router as repositories_router
from app.routes.health import router as health_router
from app.routes.investigations import router as investigations_router
from app.routes.github import router as github_router

__all__ = [
    "auth_router",
    "incidents_router",
    "repositories_router",
    "health_router",
    "investigations_router",
    "github_router",
]
