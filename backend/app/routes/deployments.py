"""REST & Webhook endpoints for Phase 4 Deployment Inventory & Release Tracking."""

import json
import uuid
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Header, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.core.auth import get_current_user
from app.core.permissions import get_active_membership, require_role
from app.core.crypto import (
    encrypt_secret, decrypt_secret, verify_hmac_sha256, generate_webhook_credentials
)
from app.models.incident import (
    User, Organization, UserOrganizationMembership, MembershipRole,
    Deployment, DeploymentStatus, DeploymentProvider,
    WebhookEndpoint, Service, Environment, Region, Repository,
    ServiceRepository, ServiceRepositoryRole
)
from app.schemas.deployments import (
    DeploymentCreate, DeploymentStatusUpdate, DeploymentResponse,
    GenericWebhookDeploymentPayload, WebhookEndpointCreate, WebhookEndpointResponse,
    DeploymentCommitComparisonResponse
)
from app.services.deployment_service import (
    record_deployment, update_deployment_status,
    get_current_deployment, get_deployments_in_window,
    get_previous_stable_deployment, get_commits_between_deployments
)

router = APIRouter(tags=["Deployments"])
MAX_WEBHOOK_PAYLOAD_BYTES = 1024 * 1024  # 1 MB
MAX_TIMESTAMP_TOLERANCE_SECONDS = 300   # 5 minutes


def _serialize_deployment(dep: Deployment) -> DeploymentResponse:
    return DeploymentResponse(
        id=dep.id,
        organization_id=dep.organization_id,
        service_id=dep.service_id,
        environment_id=dep.environment_id,
        region_id=dep.region_id,
        repository_id=dep.repository_id,
        service_name=dep.service.name if dep.service else None,
        environment_name=dep.environment.name if dep.environment else None,
        region_code=dep.region.code if dep.region else None,
        repository_full_name=dep.repository.full_name if dep.repository else None,
        commit_sha=dep.commit_sha,
        commit_message=dep.commit_message,
        version=dep.version,
        provider=dep.provider,
        provider_event_id=dep.provider_event_id,
        external_deployment_id=dep.external_deployment_id,
        status=dep.status,
        url=dep.url,
        deployed_at=dep.deployed_at,
        started_at=dep.started_at,
        finished_at=dep.finished_at,
        duration_seconds=dep.duration_seconds,
        deployed_by=dep.deployed_by,
        is_current=dep.is_current,
        metadata=dep.metadata_json or {},
        created_at=dep.created_at,
        updated_at=dep.updated_at,
    )


# ============================================================================
# AUTHENTICATED REST API ROUTES
# ============================================================================

@router.post("/deployments", response_model=DeploymentResponse, status_code=status.HTTP_201_CREATED)
def create_deployment(
    payload: DeploymentCreate,
    current_user: User = Depends(get_current_user),
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Register a new deployment event in the active organization ledger."""
    org, membership = auth_ctx
    dep = record_deployment(db, org.id, payload, deployed_by=current_user.username)
    return _serialize_deployment(dep)


@router.get("/deployments", response_model=List[DeploymentResponse])
def list_deployments(
    service_id: Optional[uuid.UUID] = None,
    environment_id: Optional[uuid.UUID] = None,
    region_id: Optional[uuid.UUID] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    commit_sha: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """List deployment ledger events with filtering and pagination."""
    org, membership = auth_ctx
    query = db.query(Deployment).filter(Deployment.organization_id == org.id)
    if service_id:
        query = query.filter(Deployment.service_id == service_id)
    if environment_id:
        query = query.filter(Deployment.environment_id == environment_id)
    if region_id:
        query = query.filter(Deployment.region_id == region_id)
    if status_filter:
        query = query.filter(Deployment.status == status_filter)
    if commit_sha:
        query = query.filter(Deployment.commit_sha == commit_sha.strip())

    deployments = query.order_by(Deployment.deployed_at.desc()).offset(offset).limit(limit).all()
    return [_serialize_deployment(d) for d in deployments]


@router.get("/deployments/current", response_model=Optional[DeploymentResponse])
def get_active_deployment(
    service_id: uuid.UUID = Query(...),
    environment_id: uuid.UUID = Query(...),
    region_id: Optional[uuid.UUID] = None,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """Retrieve the currently active (running) deployment for a service/environment/region."""
    org, membership = auth_ctx
    dep = get_current_deployment(db, org.id, service_id, environment_id, region_id)
    if not dep:
        return None
    return _serialize_deployment(dep)


@router.get("/deployments/window", response_model=List[DeploymentResponse])
def get_deployments_by_window(
    service_id: uuid.UUID = Query(...),
    window_start: str = Query(...),
    window_end: str = Query(...),
    environment_id: Optional[uuid.UUID] = None,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """Query deployments active or executed during an incident time window."""
    org, membership = auth_ctx
    try:
        ws_str = window_start.strip().replace(" ", "+")
        we_str = window_end.strip().replace(" ", "+")
        start_dt = datetime.fromisoformat(ws_str.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(we_str.replace("Z", "+00:00"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid ISO datetime format for window_start/window_end: {str(e)}")

    deployments = get_deployments_in_window(
        db, org.id, service_id, start_dt, end_dt, environment_id
    )
    return [_serialize_deployment(d) for d in deployments]


@router.get("/deployments/{deployment_id}", response_model=DeploymentResponse)
def get_deployment_detail(
    deployment_id: uuid.UUID,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """Fetch details of a single deployment."""
    org, membership = auth_ctx
    dep = db.query(Deployment).filter(
        Deployment.id == deployment_id,
        Deployment.organization_id == org.id,
    ).first()
    if not dep:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return _serialize_deployment(dep)


@router.patch("/deployments/{deployment_id}/status", response_model=DeploymentResponse)
def change_deployment_status(
    deployment_id: uuid.UUID,
    payload: DeploymentStatusUpdate,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Transition deployment status according to state machine rules."""
    org, membership = auth_ctx
    dep = update_deployment_status(
        db=db,
        org_id=org.id,
        deployment_id=deployment_id,
        new_status=payload.status,
        finished_at=payload.finished_at,
        error_message=payload.error_message,
        metadata=payload.metadata,
    )
    return _serialize_deployment(dep)


@router.get("/deployments/{deployment_id}/previous-stable", response_model=Optional[DeploymentResponse])
def get_previous_stable(
    deployment_id: uuid.UUID,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """Find the previous stable (SUCCEEDED) deployment on the same target."""
    org, membership = auth_ctx
    dep = db.query(Deployment).filter(
        Deployment.id == deployment_id,
        Deployment.organization_id == org.id,
    ).first()
    if not dep:
        raise HTTPException(status_code=404, detail="Deployment not found")

    prev = get_previous_stable_deployment(db, org.id, dep)
    if not prev:
        return None
    return _serialize_deployment(prev)


@router.get("/deployments/{deployment_id}/commits-between", response_model=DeploymentCommitComparisonResponse)
def get_commits_diff(
    deployment_id: uuid.UUID,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """Compute commit differences between this deployment and the previous stable deployment."""
    org, membership = auth_ctx
    dep = db.query(Deployment).filter(
        Deployment.id == deployment_id,
        Deployment.organization_id == org.id,
    ).first()
    if not dep:
        raise HTTPException(status_code=404, detail="Deployment not found")

    prev = get_previous_stable_deployment(db, org.id, dep)
    if not prev:
        return DeploymentCommitComparisonResponse(
            status="unavailable",
            reason="No previous deployment found to compare against.",
            repository_full_name=dep.repository.full_name if dep.repository else None,
            base_commit_sha=dep.commit_sha,
            head_commit_sha=dep.commit_sha,
            total_commits=0,
            commits=[],
        )

    res = get_commits_between_deployments(db, org.id, dep, prev)
    return DeploymentCommitComparisonResponse(**res)


# ============================================================================
# WEBHOOK ENDPOINTS CREDENTIAL MANAGEMENT
# ============================================================================

@router.post("/webhook-endpoints", response_model=WebhookEndpointResponse, status_code=status.HTTP_201_CREATED)
def create_webhook_endpoint(
    payload: WebhookEndpointCreate,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """Generate a new generic webhook endpoint with encrypted secret. Returns raw secret once."""
    org, membership = auth_ctx
    key_id, raw_secret = generate_webhook_credentials()
    encrypted = encrypt_secret(raw_secret)

    ep = WebhookEndpoint(
        organization_id=org.id,
        name=payload.name.strip(),
        provider=(payload.provider or "generic").lower().strip(),
        key_id=key_id,
        encrypted_secret=encrypted,
        is_active=True,
    )
    db.add(ep)
    db.commit()
    db.refresh(ep)

    resp = WebhookEndpointResponse.model_validate(ep)
    resp.raw_secret = raw_secret
    return resp


@router.get("/webhook-endpoints", response_model=List[WebhookEndpointResponse])
def list_webhook_endpoints(
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """List webhook endpoints for the organization (secrets are redacted)."""
    org, membership = auth_ctx
    endpoints = db.query(WebhookEndpoint).filter(
        WebhookEndpoint.organization_id == org.id
    ).all()
    return [WebhookEndpointResponse.model_validate(ep) for ep in endpoints]


@router.delete("/webhook-endpoints/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_webhook_endpoint(
    endpoint_id: uuid.UUID,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """Deactivate/delete a webhook endpoint."""
    org, membership = auth_ctx
    ep = db.query(WebhookEndpoint).filter(
        WebhookEndpoint.id == endpoint_id,
        WebhookEndpoint.organization_id == org.id,
    ).first()
    if not ep:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")
    db.delete(ep)
    db.commit()
    return None


# ============================================================================
# PUBLIC INGESTION WEBHOOKS
# ============================================================================

@router.post("/webhooks/deployments/generic")
async def receive_generic_deployment_webhook(
    request: Request,
    x_sentinel_key_id: Optional[str] = Header(None, alias="X-Sentinel-Key-ID"),
    x_sentinel_signature: Optional[str] = Header(None, alias="X-Sentinel-Signature"),
    x_sentinel_timestamp: Optional[str] = Header(None, alias="X-Sentinel-Timestamp"),
    db: Session = Depends(get_db),
):
    """
    Ingest deployment events from CI/CD pipelines (GitLab, Jenkins, CircleCI, Argo, etc.).
    Verifies HMAC-SHA256 signature and mandatory replay timestamp.
    """
    if not x_sentinel_key_id or not x_sentinel_signature:
        raise HTTPException(status_code=401, detail="Missing X-Sentinel-Key-ID or X-Sentinel-Signature header")

    if not x_sentinel_timestamp:
        raise HTTPException(status_code=401, detail="Missing X-Sentinel-Timestamp header (replay protection required)")

    body_bytes = await request.body()
    if len(body_bytes) > MAX_WEBHOOK_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Webhook payload exceeds 1MB limit")

    # 1. Replay Protection
    try:
        ts = float(x_sentinel_timestamp)
        now_ts = datetime.now(timezone.utc).timestamp()
        if abs(now_ts - ts) > MAX_TIMESTAMP_TOLERANCE_SECONDS:
            raise HTTPException(status_code=401, detail="Webhook timestamp expired (replay protection)")
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid X-Sentinel-Timestamp header")

    # 2. Tenant & Credential Resolution
    ep = db.query(WebhookEndpoint).filter(
        WebhookEndpoint.key_id == x_sentinel_key_id,
        WebhookEndpoint.is_active == True,
    ).first()
    if not ep:
        raise HTTPException(status_code=401, detail="Invalid or inactive webhook key ID")

    # 3. HMAC Verification
    raw_secret = decrypt_secret(ep.encrypted_secret)
    if not verify_hmac_sha256(body_bytes, x_sentinel_signature, raw_secret):
        raise HTTPException(status_code=401, detail="Invalid HMAC-SHA256 signature")

    # 4. Parse JSON Payload
    try:
        data = json.loads(body_bytes.decode("utf-8"))
        payload = GenericWebhookDeploymentPayload(**data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Malformed webhook JSON payload: {str(e)}")

    org_id = ep.organization_id

    # 5. Resolve Entities
    service_id = payload.service_id
    if not service_id and payload.service_name:
        svc = db.query(Service).filter(
            Service.organization_id == org_id,
            Service.name == payload.service_name.strip(),
        ).first()
        if not svc:
            raise HTTPException(status_code=404, detail=f"Service '{payload.service_name}' not found in organization")
        service_id = svc.id

    if not service_id:
        raise HTTPException(status_code=400, detail="Missing required service_id or service_name")

    environment_id = payload.environment_id
    if not environment_id and payload.environment_name:
        env = db.query(Environment).filter(
            Environment.organization_id == org_id,
            Environment.name == payload.environment_name.strip(),
        ).first()
        if not env:
            raise HTTPException(status_code=404, detail=f"Environment '{payload.environment_name}' not found in organization")
        environment_id = env.id

    if not environment_id:
        raise HTTPException(status_code=400, detail="Missing required environment_id or environment_name")

    region_id = payload.region_id
    if not region_id and payload.region_code:
        reg = db.query(Region).filter(
            Region.organization_id == org_id,
            Region.code == payload.region_code.strip(),
        ).first()
        if reg:
            region_id = reg.id

    repository_id = payload.repository_id
    if not repository_id and payload.repository_full_name:
        rep = db.query(Repository).filter(
            Repository.organization_id == org_id,
            Repository.full_name == payload.repository_full_name.strip(),
        ).first()
        if rep:
            repository_id = rep.id

    # 6. Record Deployment
    create_dto = DeploymentCreate(
        service_id=service_id,
        environment_id=environment_id,
        region_id=region_id,
        repository_id=repository_id,
        commit_sha=payload.commit_sha,
        commit_message=payload.commit_message,
        version=payload.version,
        provider=DeploymentProvider.GENERIC_WEBHOOK.value,
        provider_event_id=payload.event_id,
        external_deployment_id=payload.external_id,
        status=payload.status or DeploymentStatus.SUCCEEDED.value,
        url=payload.url,
        started_at=payload.started_at,
        finished_at=payload.finished_at,
        metadata=payload.metadata,
    )

    dep = record_deployment(db, org_id, create_dto, deployed_by=payload.deployed_by or "Generic Webhook")
    return {
        "status": "processed",
        "deployment_id": str(dep.id),
        "is_current": dep.is_current,
    }


@router.post("/webhooks/deployments/github")
async def receive_github_deployment_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    x_github_event: Optional[str] = Header(None, alias="X-GitHub-Event"),
    x_github_delivery: Optional[str] = Header(None, alias="X-GitHub-Delivery"),
    db: Session = Depends(get_db),
):
    """
    Ingest GitHub deployment and deployment_status webhooks.
    Resolves organization by repository full_name, verifies HMAC signature,
    and resolves target service using ServiceRepository many-to-many bindings.
    """
    if not x_hub_signature_256:
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 header")

    body_bytes = await request.body()
    if len(body_bytes) > MAX_WEBHOOK_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Webhook payload exceeds 1MB limit")

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    repo_data = payload.get("repository", {})
    repo_full_name = repo_data.get("full_name")
    if not repo_full_name:
        raise HTTPException(status_code=400, detail="Missing repository.full_name in payload")

    # 1. Tenant Resolution
    repo = db.query(Repository).filter(Repository.full_name == repo_full_name).first()
    if not repo:
        raise HTTPException(status_code=404, detail=f"Repository '{repo_full_name}' is not registered with Sentinel")

    org_id = repo.organization_id

    # 2. Secret Resolution & HMAC Verification (Dedicated GitHub Webhook Secrets Only)
    secret_candidates: List[str] = []

    # A. Dedicated GitHub App installation token/secret if present on repository
    if repo.installation and repo.installation.tokens_encrypted:
        try:
            dec = decrypt_secret(repo.installation.tokens_encrypted)
            if dec:
                secret_candidates.append(dec)
        except Exception:
            pass

    # B. Dedicated organization GitHub WebhookEndpoint (provider == "github")
    gh_endpoints = db.query(WebhookEndpoint).filter(
        WebhookEndpoint.organization_id == org_id,
        WebhookEndpoint.is_active == True,
        WebhookEndpoint.provider == "github",
    ).all()
    for ep in gh_endpoints:
        try:
            dec = decrypt_secret(ep.encrypted_secret)
            if dec:
                secret_candidates.append(dec)
        except Exception:
            pass

    # C. Global settings GITHUB_WEBHOOK_SECRET
    if settings.GITHUB_WEBHOOK_SECRET and settings.GITHUB_WEBHOOK_SECRET.strip():
        secret_candidates.append(settings.GITHUB_WEBHOOK_SECRET.strip())

    if not secret_candidates:
        raise HTTPException(
            status_code=401,
            detail="No dedicated GitHub webhook secret configured for this organization or repository installation"
        )

    if not any(verify_hmac_sha256(body_bytes, x_hub_signature_256, sec) for sec in secret_candidates):
        raise HTTPException(status_code=401, detail="Invalid GitHub HMAC-SHA256 signature")

    # 3. Idempotency Check on Delivery ID
    if x_github_delivery:
        existing = db.query(Deployment).filter(
            Deployment.organization_id == org_id,
            Deployment.provider == DeploymentProvider.GITHUB.value,
            Deployment.provider_event_id == x_github_delivery,
        ).first()
        if existing:
            return {"status": "already_processed", "deployment_id": str(existing.id)}

    # 4. Resolve Target Service (Many-to-Many ServiceRepository resolution)
    service_repos = db.query(ServiceRepository).filter(
        ServiceRepository.repository_id == repo.id,
        ServiceRepository.organization_id == org_id,
    ).all()

    service: Optional[Service] = None

    # Check payload service hint
    target_hint = payload.get("deployment", {}).get("service")
    if not target_hint and isinstance(payload.get("deployment", {}).get("payload"), dict):
        target_hint = payload.get("deployment", {}).get("payload", {}).get("service")

    if target_hint:
        svc = db.query(Service).filter(
            Service.organization_id == org_id,
            (Service.name == target_hint) | (Service.slug == target_hint)
        ).first()
        if svc:
            service = svc

    if not service and service_repos:
        # A. Prefer primary APPLICATION mapping
        primary_app = next(
            (sr for sr in service_repos if sr.is_primary and (sr.role == ServiceRepositoryRole.APPLICATION or sr.role == "application")),
            None
        )
        if primary_app:
            service = db.query(Service).filter(Service.id == primary_app.service_id, Service.organization_id == org_id).first()

        # B. Otherwise prefer any primary mapping
        if not service:
            primary_any = next((sr for sr in service_repos if sr.is_primary), None)
            if primary_any:
                service = db.query(Service).filter(Service.id == primary_any.service_id, Service.organization_id == org_id).first()

        # C. Otherwise check application mappings
        if not service:
            app_mappings = [sr for sr in service_repos if (sr.role == ServiceRepositoryRole.APPLICATION or sr.role == "application")]
            if len(app_mappings) == 1:
                service = db.query(Service).filter(Service.id == app_mappings[0].service_id, Service.organization_id == org_id).first()
            elif len(app_mappings) > 1:
                raise HTTPException(
                    status_code=422,
                    detail=f"Ambiguous service mapping: repository '{repo_full_name}' is linked to {len(app_mappings)} application services without a designated primary. Please configure a primary service mapping in the catalog."
                )

        # D. Otherwise check total service mappings
        if not service:
            if len(service_repos) == 1:
                service = db.query(Service).filter(Service.id == service_repos[0].service_id, Service.organization_id == org_id).first()
            elif len(service_repos) > 1:
                raise HTTPException(
                    status_code=422,
                    detail=f"Ambiguous service mapping: repository '{repo_full_name}' is linked to {len(service_repos)} services without a designated primary. Please configure a primary service mapping in the catalog."
                )

    # E. Legacy single relationship fallback
    if not service and repo.service_id:
        service = db.query(Service).filter(Service.id == repo.service_id, Service.organization_id == org_id).first()

    if not service:
        raise HTTPException(
            status_code=422,
            detail=f"No service linked to repository '{repo_full_name}'. Please link this repository to a service in the catalog before ingesting deployments."
        )

    # 5. Resolve Target Environment
    env_name = payload.get("deployment", {}).get("environment") or "production"
    environment = db.query(Environment).filter(
        Environment.organization_id == org_id,
        Environment.name.ilike(env_name),
    ).first()
    if not environment:
        environment = db.query(Environment).filter(Environment.organization_id == org_id).first()

    if not environment:
        raise HTTPException(status_code=404, detail="No environment found for organization")

    # 6. Extract Commit and Status
    deployment_obj = payload.get("deployment", {})
    status_obj = payload.get("deployment_status", {})

    commit_sha = deployment_obj.get("sha") or payload.get("after") or "0000000000000000000000000000000000000000"
    gh_state = status_obj.get("state") or "pending"

    status_map = {
        "pending": DeploymentStatus.PENDING.value,
        "in_progress": DeploymentStatus.IN_PROGRESS.value,
        "queued": DeploymentStatus.PENDING.value,
        "success": DeploymentStatus.SUCCEEDED.value,
        "failure": DeploymentStatus.FAILED.value,
        "error": DeploymentStatus.FAILED.value,
        "inactive": DeploymentStatus.CANCELLED.value,
    }
    mapped_status = status_map.get(gh_state.lower(), DeploymentStatus.PENDING.value)

    create_dto = DeploymentCreate(
        service_id=service.id,
        environment_id=environment.id,
        repository_id=repo.id,
        commit_sha=commit_sha,
        commit_message=deployment_obj.get("description") or f"GitHub {x_github_event or 'deployment'}",
        provider=DeploymentProvider.GITHUB.value,
        provider_event_id=x_github_delivery,
        external_deployment_id=str(deployment_obj.get("id")) if deployment_obj.get("id") else None,
        status=mapped_status,
        url=status_obj.get("target_url") or deployment_obj.get("url"),
        metadata=payload,
    )

    dep = record_deployment(db, org_id, create_dto, deployed_by="GitHub Webhook")
    return {
        "status": "processed",
        "deployment_id": str(dep.id),
        "is_current": dep.is_current,
    }
