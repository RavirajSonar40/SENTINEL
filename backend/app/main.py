from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from app.core.database import engine, Base
from app.routes import auth_router, incidents_router, repositories_router, health_router, investigations_router, github_router
from app.routes.investigation_engine import router as engine_router
from app.routes.indexing import router as indexing_router
from app.routes.webhooks import router as webhooks_router
from app.routes.health_monitor import router as health_monitor_router
from app.routes.auto_detect import router as auto_detect_router
from app.routes.remediation import router as remediation_router
from app.routes.approvals import router as approvals_router
from app.routes.websocket import router as ws_router
from app.routes.metrics import router as metrics_router
from app.routes.system import router as system_router
from app.services.task_queue import start_workers
from app.core.config import settings

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Sentinel API",
    description="AI Incident Response Agent — Backend",
    version="0.1.0",
)

# CORS — allow frontend origins
frontend_url = settings.FRONTEND_URL
extra_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
allowed_origins = list({frontend_url, "http://localhost:3000", "http://127.0.0.1:3000", *extra_origins})

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://.*\.vercel\.app$|http://localhost:\d+$",
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(incidents_router)
app.include_router(repositories_router)
app.include_router(investigations_router)
app.include_router(github_router)
app.include_router(engine_router)
app.include_router(indexing_router)
app.include_router(webhooks_router)
app.include_router(health_monitor_router)
app.include_router(auto_detect_router)
app.include_router(remediation_router)
app.include_router(approvals_router)
app.include_router(ws_router)
app.include_router(metrics_router)
app.include_router(system_router)


@app.on_event("startup")
async def startup_event():
    start_workers()
