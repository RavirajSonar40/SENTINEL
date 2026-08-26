from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_db
from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    """Liveness probe — returns 200 if the process is running."""
    return {"status": "ok", "service": "sentinel-api"}


@router.get("/health/ready")
def readiness_check(db: Session = Depends(get_db)):
    """Readiness probe — checks all critical dependencies."""
    checks = {}

    # Postgres
    try:
        db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"

    # Qdrant
    try:
        import httpx
        resp = httpx.get(f"{settings.QDRANT_URL}/healthz", timeout=3)
        checks["qdrant"] = "ok" if resp.status_code == 200 else f"error: {resp.status_code}"
    except Exception:
        checks["qdrant"] = "unavailable"

    # Redis
    if settings.REDIS_URL:
        try:
            import redis.asyncio as aioredis
            url = settings.REDIS_URL
            if url.startswith("rediss://"):
                r = aioredis.from_url(url, socket_timeout=2, ssl_cert_reqs=None)
            else:
                r = aioredis.from_url(url, socket_timeout=2)
            import asyncio
            asyncio.get_event_loop().run_until_complete(r.ping())
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "unavailable"
    else:
        checks["redis"] = "not_configured"

    healthy = all(v in ("ok", "unavailable", "not_configured") for v in checks.values())
    return {"status": "ready" if healthy else "degraded", "checks": checks}


@router.get("/health/db")
def health_check_db(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {"status": "error", "database": str(e)}
