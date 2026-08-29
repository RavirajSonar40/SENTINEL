import hmac
import hashlib
import json
import logging
import uuid
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Header, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.crypto import decrypt_secret
from app.core.permissions import require_role
from app.models.incident import (
    User,
    Organization,
    Incident,
    ChangeEvent,
    IncidentChangeCorrelation,
    WebhookEndpoint,
    MembershipRole,
    UserOrganizationMembership,
    ChangeType,
)
from app.schemas.changes import (
    ChangeEventCreate,
    ChangeEventBatchCreate,
    ChangeEventResponse,
    IncidentChangeCorrelationResponse,
    ChangeCorrelationReport,
    CorrelationTriageRequest,
)
from app.services.change_service import (
    ingest_change_event,
    batch_ingest_changes,
    parse_github_change_webhook,
    parse_launchdarkly_change_webhook,
    parse_terraform_change_webhook,
    parse_kubernetes_change_webhook,
    ALLOWED_PROVIDERS,
)
from app.services.change_correlation_service import (
    correlate_incident_changes,
    triage_change_correlation,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/changes", tags=["Change Intelligence"])

ALLOWED_WEBHOOK_PROVIDERS = {"github", "launchdarkly", "terraform", "kubernetes", "argo", "generic"}


# ============================================================================
# 1. CHANGE LEDGER QUERY & INGESTION ROUTES
# ============================================================================

@router.get("", response_model=List[ChangeEventResponse])
def list_changes(
    service_id: Optional[uuid.UUID] = None,
    environment_id: Optional[uuid.UUID] = None,
    repository_id: Optional[uuid.UUID] = None,
    change_type: Optional[str] = None,
    provider: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """Retrieve filtered change events for the current organization."""
    org, _ = auth_ctx
    query = db.query(ChangeEvent).filter(ChangeEvent.organization_id == org.id)

    if service_id:
        query = query.filter(ChangeEvent.service_id == service_id)
    if environment_id:
        query = query.filter(ChangeEvent.environment_id == environment_id)
    if repository_id:
        query = query.filter(ChangeEvent.repository_id == repository_id)
    if change_type:
        query = query.filter(ChangeEvent.change_type == change_type.upper())
    if provider:
        query = query.filter(ChangeEvent.provider == provider.lower())

    events = query.order_by(ChangeEvent.effective_at.desc()).offset(offset).limit(limit).all()
    return events


@router.post("", response_model=ChangeEventResponse, status_code=status.HTTP_201_CREATED)
def create_change_event(
    payload: ChangeEventCreate,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.OPERATOR)),
    db: Session = Depends(get_db),
):
    """Programmatically ingest a single change event."""
    org, _ = auth_ctx
    event, _ = ingest_change_event(
        db=db,
        organization_id=org.id,
        data=payload,
        auth_source="user_session",
    )
    return event


@router.post("/batch", response_model=Dict[str, int])
def create_change_events_batch(
    payload: ChangeEventBatchCreate,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.OPERATOR)),
    db: Session = Depends(get_db),
):
    """Batch ingest up to 100 change events."""
    org, _ = auth_ctx
    stats = batch_ingest_changes(
        db=db,
        organization_id=org.id,
        items=payload.changes,
        auth_source="user_session_batch",
    )
    return stats


@router.get("/{change_id}", response_model=ChangeEventResponse)
def get_change_detail(
    change_id: uuid.UUID,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """Retrieve a single change event by ID."""
    org, _ = auth_ctx
    event = db.query(ChangeEvent).filter(
        ChangeEvent.organization_id == org.id,
        ChangeEvent.id == change_id,
    ).first()
    if not event:
        raise HTTPException(status_code=404, detail="Change event not found")
    return event


# ============================================================================
# 2. PROVIDER-SPECIFIC WEBHOOK INGESTION
# ============================================================================

@router.post("/webhooks/{provider}", status_code=status.HTTP_200_OK)
async def ingest_provider_change_webhook(
    provider: str,
    request: Request,
    key_id: Optional[str] = Query(None),
    x_sentinel_key_id: Optional[str] = Header(None, alias="X-Sentinel-Key-Id"),
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    x_github_event: Optional[str] = Header(None, alias="X-GitHub-Event"),
    x_github_delivery: Optional[str] = Header(None, alias="X-GitHub-Delivery"),
    authorization: Optional[str] = Header(None),
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
    db: Session = Depends(get_db),
):
    """
    Ingest change events from provider webhooks with strict provider allowlisting,
    HMAC/Bearer signature verification, and replay protection.
    """
    provider_clean = provider.lower().strip()
    if provider_clean not in ALLOWED_WEBHOOK_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported webhook provider '{provider}'. Allowed: {sorted(list(ALLOWED_WEBHOOK_PROVIDERS))}",
        )

    # 1. Payload size check (2 MB ceiling)
    raw_body = await request.body()
    if len(raw_body) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Webhook payload exceeds 2 MB limit")

    # 2. Resolve WebhookEndpoint
    effective_key_id = key_id or x_sentinel_key_id
    endpoint = None

    if effective_key_id:
        endpoint = db.query(WebhookEndpoint).filter(
            WebhookEndpoint.key_id == effective_key_id,
            WebhookEndpoint.is_active == True,
        ).first()

    if not endpoint and authorization:
        token = authorization.replace("Bearer ", "").strip()
        # Find endpoint by matching decrypted secret
        candidates = db.query(WebhookEndpoint).filter(
            WebhookEndpoint.provider.in_([provider_clean, "generic", "opentelemetry"]),
            WebhookEndpoint.is_active == True,
        ).all()
        for cand in candidates:
            try:
                dec = decrypt_secret(cand.encrypted_secret)
                if hmac.compare_digest(dec, token):
                    endpoint = cand
                    break
            except Exception:
                continue

    if not endpoint:
        raise HTTPException(status_code=401, detail="Valid webhook authentication key_id or Bearer token is required")

    org_id = endpoint.organization_id

    # 3. Signature / Secret Validation
    try:
        decrypted_secret = decrypt_secret(endpoint.encrypted_secret)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt webhook endpoint secret")

    if provider_clean == "github":
        if not x_hub_signature_256:
            raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 header")
        expected_sig = "sha256=" + hmac.new(
            decrypted_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_sig, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="Invalid GitHub HMAC-SHA256 signature")
    else:
        # LaunchDarkly / Terraform / Kubernetes / Generic
        supplied_secret = None
        if authorization and authorization.startswith("Bearer "):
            supplied_secret = authorization.replace("Bearer ", "").strip()
        elif x_webhook_secret:
            supplied_secret = x_webhook_secret.strip()

        if not supplied_secret or not hmac.compare_digest(decrypted_secret, supplied_secret):
            raise HTTPException(status_code=401, detail=f"Invalid webhook secret for provider '{provider_clean}'")

    # 4. Parse JSON Payload
    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # 5. Replay Protection & Provider Event ID Extraction
    delivery_id = x_github_delivery or payload.get("delivery_id") or payload.get("event_id") or payload.get("id")
    if delivery_id:
        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        duplicate = db.query(ChangeEvent).filter(
            ChangeEvent.organization_id == org_id,
            ChangeEvent.provider == provider_clean,
            ChangeEvent.provider_event_id == str(delivery_id),
            ChangeEvent.observed_at >= recent_cutoff,
        ).first()
        if duplicate:
            return {"status": "ignored", "reason": "duplicate_delivery", "change_id": str(duplicate.id)}

    # 6. Parse into ChangeEventCreate
    change_dto = None
    if provider_clean == "github":
        event_type = x_github_event or "push"
        change_dto = parse_github_change_webhook(db, org_id, payload, event_type)
    elif provider_clean == "launchdarkly":
        change_dto = parse_launchdarkly_change_webhook(db, org_id, payload)
    elif provider_clean == "terraform":
        change_dto = parse_terraform_change_webhook(db, org_id, payload)
    elif provider_clean in ("kubernetes", "argo"):
        change_dto = parse_kubernetes_change_webhook(db, org_id, payload)
    elif provider_clean == "generic":
        title = payload.get("title") or f"Generic change from {endpoint.name}"
        c_type_str = payload.get("change_type", "CONFIGURATION").upper()
        c_type = ChangeType.CONFIGURATION
        try:
            c_type = ChangeType[c_type_str]
        except KeyError:
            c_type = ChangeType.CONFIGURATION

        change_dto = ChangeEventCreate(
            title=title[:255],
            change_type=c_type,
            provider="generic",
            provider_event_id=str(delivery_id) if delivery_id else None,
            author=payload.get("author"),
            source_url=payload.get("source_url"),
            affected_components=payload.get("affected_components", []),
            diff_summary=payload.get("diff_summary", {}),
            metadata_json=payload.get("metadata", {}),
        )

    if not change_dto:
        return {"status": "ignored", "reason": "unhandled_event_type"}

    if delivery_id:
        change_dto.provider_event_id = str(delivery_id)

    event, is_created = ingest_change_event(
        db=db,
        organization_id=org_id,
        data=change_dto,
        auth_source=f"webhook_{provider_clean}",
        integration_id=endpoint.id,
    )

    return {
        "status": "ingested",
        "created": is_created,
        "change_id": str(event.id),
        "change_type": event.change_type.value,
        "external_id": event.external_id,
    }


# ============================================================================
# 3. INCIDENT CHANGE CORRELATION & TRIAGE ROUTES
# ============================================================================

@router.get("/incidents/{incident_id}/changes", response_model=ChangeCorrelationReport)
def get_incident_changes(
    incident_id: uuid.UUID,
    lookback_window_minutes: int = Query(120, ge=15, le=10080),
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """Retrieve correlated changes for an incident."""
    org, _ = auth_ctx
    try:
        report = correlate_incident_changes(
            db=db,
            organization_id=org.id,
            incident_id=incident_id,
            lookback_window_minutes=lookback_window_minutes,
            force=False,
        )
        return report
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/incidents/{incident_id}/changes/correlate", response_model=ChangeCorrelationReport)
def force_recalculate_incident_changes(
    incident_id: uuid.UUID,
    lookback_window_minutes: int = Query(120, ge=15, le=10080),
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.OPERATOR)),
    db: Session = Depends(get_db),
):
    """Force on-demand recalculation of change correlations (bypassing debounce)."""
    org, _ = auth_ctx
    try:
        report = correlate_incident_changes(
            db=db,
            organization_id=org.id,
            incident_id=incident_id,
            lookback_window_minutes=lookback_window_minutes,
            force=True,
        )
        return report
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/incidents/{incident_id}/changes/{correlation_id}/triage", response_model=IncidentChangeCorrelationResponse)
def triage_correlation(
    incident_id: uuid.UUID,
    correlation_id: uuid.UUID,
    payload: CorrelationTriageRequest,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.OPERATOR)),
    db: Session = Depends(get_db),
):
    """Update human operator triage status on a correlation with full auditability."""
    org, membership = auth_ctx
    try:
        updated = triage_change_correlation(
            db=db,
            organization_id=org.id,
            incident_id=incident_id,
            correlation_id=correlation_id,
            user_id=membership.user_id,
            triage_status=payload.triage_status,
            reason=payload.reason,
        )
        return updated
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
