"""API routes for Phase 5 Autonomous Monitoring, Ingestion Webhooks & Alert Management."""

import json
import secrets
import uuid
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Header, Request, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.permissions import require_role
from app.core.crypto import verify_hmac_sha256, decrypt_secret
from app.models.incident import (
    User, Organization, Environment, Service, Region,
    MembershipRole, UserOrganizationMembership, ServiceDeploymentConfig,
    WebhookEndpoint, TelemetrySignal, AlertRuleConfig, HealthCheckLog, Incident,
    SignalProvider, SignalType, SignalStatus, IncidentStatus, IncidentSource,
)
from app.schemas.monitoring import (
    PrometheusAlertPayload, SentryAlertPayload, GenericSignalPayload,
    TelemetrySignalResponse, AlertRuleConfigDTO, AlertRuleConfigUpdate,
    HealthCheckStatusResponse, ProbeNowRequest
)
from app.services.detection_rules import ALL_RULES, RULE_REGISTRY
from app.services.signal_correlation_service import (
    process_telemetry_signal, handle_alertmanager_resolution
)
from app.services.health_check_poller import probe_single_config

router = APIRouter(tags=["monitoring"])

MAX_WEBHOOK_PAYLOAD_BYTES = 1024 * 1024  # 1 MB
MAX_TIMESTAMP_TOLERANCE_SECONDS = 300     # 5 minutes


# ============================================================================
# PUBLIC INGESTION WEBHOOKS
# ============================================================================

@router.post("/webhooks/alerts/prometheus")
async def receive_prometheus_alert_webhook(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_sentinel_key_id: Optional[str] = Header(None, alias="X-Sentinel-Key-ID"),
    key_id_query: Optional[str] = Query(None, alias="key_id"),
    db: Session = Depends(get_db),
):
    """
    Ingest Prometheus / Alertmanager v4 JSON webhook alerts.
    Authenticates via Bearer token against dedicated 'prometheus' WebhookEndpoint.
    """
    key_id = x_sentinel_key_id or key_id_query
    if not key_id:
        raise HTTPException(status_code=401, detail="Missing key_id in header or query parameter")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization Bearer token header")

    bearer_token = authorization.split("Bearer ", 1)[1].strip()

    # 1. Tenant & Endpoint Resolution (Strictly provider == 'prometheus')
    ep = db.query(WebhookEndpoint).filter(
        WebhookEndpoint.key_id == key_id,
        WebhookEndpoint.provider == "prometheus",
        WebhookEndpoint.is_active == True,
    ).first()
    if not ep:
        raise HTTPException(status_code=401, detail="Invalid or inactive Prometheus webhook key ID")

    # 2. Bearer Token Verification
    raw_secret = decrypt_secret(ep.encrypted_secret)
    if not secrets.compare_digest(bearer_token, raw_secret):
        raise HTTPException(status_code=401, detail="Invalid Prometheus webhook authentication token")

    body_bytes = await request.body()
    if len(body_bytes) > MAX_WEBHOOK_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Webhook payload exceeds 1MB limit")

    try:
        data = json.loads(body_bytes.decode("utf-8"))
        payload = PrometheusAlertPayload(**data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Malformed Prometheus Alertmanager JSON payload: {str(e)}")

    org_id = ep.organization_id
    processed_signals = []
    resolved_incidents = []

    # 3. Process Individual Alerts
    for alert in payload.alerts:
        labels = alert.labels or {}
        annotations = alert.annotations or {}

        # Resolve Service Name
        svc_name = labels.get("service") or labels.get("job") or labels.get("app") or labels.get("service_name")
        service = None
        if svc_name:
            service = db.query(Service).filter(
                Service.organization_id == org_id,
                Service.name == svc_name.strip(),
            ).first()

        # Resolve Environment (Strict Matching)
        env_name = labels.get("environment") or labels.get("env") or labels.get("stage")
        environment = None
        if env_name:
            environment = db.query(Environment).filter(
                Environment.organization_id == org_id,
                Environment.name.ilike(env_name.strip()),
            ).first()

        # If environment is missing, check if service has an unambiguous single environment config
        if not environment and service:
            configs = db.query(ServiceDeploymentConfig).filter(
                ServiceDeploymentConfig.service_id == service.id,
                ServiceDeploymentConfig.is_active == True,
            ).all()
            if len(configs) == 1:
                environment = configs[0].environment
            elif len(configs) > 1:
                raise HTTPException(
                    status_code=422,
                    detail=f"Ambiguous environment for service '{svc_name}'. Please specify environment label."
                )

        # If still no environment found, reject with 422
        if not environment:
            raise HTTPException(
                status_code=422,
                detail="Could not resolve environment from alert labels. 'environment' or 'env' label required."
            )

        # Resolve Region
        region_code = labels.get("region") or labels.get("datacenter")
        region = None
        if region_code:
            region = db.query(Region).filter(
                Region.organization_id == org_id,
                Region.code == region_code.strip(),
            ).first()

        alert_status = alert.status or payload.status or "firing"
        alert_fp = alert.fingerprint or labels.get("alertname", "prom_alert")

        # Handle Resolved Status
        if alert_status == "resolved":
            res_inc = handle_alertmanager_resolution(
                db=db,
                organization_id=org_id,
                alert_fingerprint=alert_fp,
                service=service,
                environment=environment,
            )
            if res_inc:
                resolved_incidents.append(str(res_inc.id))
            continue

        # Map Signal Type from Alertname / Metrics
        alertname = labels.get("alertname", "PrometheusAlert")
        alert_lower = alertname.lower()
        if "cpu" in alert_lower:
            sig_type = SignalType.CPU_THRESHOLD
        elif "mem" in alert_lower:
            sig_type = SignalType.MEMORY_THRESHOLD
        elif "error" in alert_lower or "5xx" in alert_lower or "failure" in alert_lower:
            sig_type = SignalType.ERROR_RATE
        elif "latency" in alert_lower or "duration" in alert_lower or "slow" in alert_lower:
            sig_type = SignalType.LATENCY_SPIKE
        elif "crash" in alert_lower or "restart" in alert_lower:
            sig_type = SignalType.CRASH_LOOP
        elif "disk" in alert_lower or "storage" in alert_lower:
            sig_type = SignalType.DISK_THRESHOLD
        elif "queue" in alert_lower or "lag" in alert_lower:
            sig_type = SignalType.QUEUE_BACKLOG
        elif "db" in alert_lower or "database" in alert_lower or "conn" in alert_lower:
            sig_type = SignalType.DATABASE_SATURATION
        else:
            sig_type = SignalType.ERROR_RATE

        # Parse Metric Value from annotations or labels
        metric_val = None
        val_str = annotations.get("value") or labels.get("value")
        if val_str:
            try:
                metric_val = float(val_str)
            except ValueError:
                pass

        summary = annotations.get("summary") or annotations.get("description") or f"Prometheus alert: {alertname}"
        error_sig = labels.get("alertname") or f"prom:{alert_lower}"

        starts_at = alert.startsAt or datetime.now(timezone.utc).isoformat()
        event_id = f"{alert_fp}:{starts_at}"

        sig, inc, is_new = process_telemetry_signal(
            db=db,
            organization_id=org_id,
            provider=SignalProvider.PROMETHEUS,
            provider_event_id=event_id,
            signal_type=sig_type,
            service=service,
            environment=environment,
            region=region,
            metric_name=labels.get("alertname"),
            metric_value=metric_val,
            threshold_value=None,
            title=summary,
            description=annotations.get("description"),
            error_signature=error_sig,
            raw_payload={"alert": alert.model_dump(), "groupLabels": payload.groupLabels},
        )
        processed_signals.append({
            "signal_id": str(sig.id),
            "status": sig.status.value,
            "incident_id": str(inc.id) if inc else None,
            "incident_created": is_new,
        })

    return {
        "status": "processed",
        "total_alerts": len(payload.alerts),
        "signals": processed_signals,
        "resolved_incidents": resolved_incidents,
    }


@router.post("/webhooks/alerts/sentry")
async def receive_sentry_alert_webhook(
    request: Request,
    sentry_hook_signature: Optional[str] = Header(None, alias="Sentry-Hook-Signature"),
    x_sentinel_key_id: Optional[str] = Header(None, alias="X-Sentinel-Key-ID"),
    key_id_query: Optional[str] = Query(None, alias="key_id"),
    db: Session = Depends(get_db),
):
    """
    Ingest Sentry error and issue alert webhooks.
    Verifies HMAC signature via Sentry-Hook-Signature against dedicated 'sentry' WebhookEndpoint.
    """
    key_id = x_sentinel_key_id or key_id_query
    if not key_id:
        raise HTTPException(status_code=401, detail="Missing key_id in header or query parameter")

    if not sentry_hook_signature:
        raise HTTPException(status_code=401, detail="Missing Sentry-Hook-Signature header")

    body_bytes = await request.body()
    if len(body_bytes) > MAX_WEBHOOK_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Webhook payload exceeds 1MB limit")

    # 1. Tenant & Endpoint Resolution (Strictly provider == 'sentry')
    ep = db.query(WebhookEndpoint).filter(
        WebhookEndpoint.key_id == key_id,
        WebhookEndpoint.provider == "sentry",
        WebhookEndpoint.is_active == True,
    ).first()
    if not ep:
        raise HTTPException(status_code=401, detail="Invalid or inactive Sentry webhook key ID")

    # 2. HMAC Signature Verification
    raw_secret = decrypt_secret(ep.encrypted_secret)
    if not verify_hmac_sha256(body_bytes, sentry_hook_signature, raw_secret):
        raise HTTPException(status_code=401, detail="Invalid Sentry HMAC-SHA256 signature")

    try:
        data = json.loads(body_bytes.decode("utf-8"))
        payload = SentryAlertPayload(**data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Malformed Sentry webhook payload: {str(e)}")

    org_id = ep.organization_id

    # 3. Resolve Target Service by project_slug or metadata
    project_slug = payload.project_slug or (payload.issue.get("project", {}).get("slug") if payload.issue else None)
    service = None
    if project_slug:
        service = db.query(Service).filter(
            Service.organization_id == org_id,
            Service.name.ilike(project_slug.strip()),
        ).first()

    # 4. Resolve Environment
    env_str = payload.environment or "production"
    environment = db.query(Environment).filter(
        Environment.organization_id == org_id,
        Environment.name.ilike(env_str.strip()),
    ).first()

    # 5. Extract Error Signatures and Details
    exc_type = "UnhandledException"
    if payload.exception and payload.exception.get("values"):
        exc_type = payload.exception["values"][0].get("type", "UnhandledException")
    elif payload.culprit:
        exc_type = payload.culprit

    title = payload.message or f"Sentry Exception: {exc_type}"
    event_id = payload.event_id or f"sentry-{uuid.uuid4()}"

    sig, inc, is_new = process_telemetry_signal(
        db=db,
        organization_id=org_id,
        provider=SignalProvider.SENTRY,
        provider_event_id=event_id,
        signal_type=SignalType.REPEATED_EXCEPTION,
        service=service,
        environment=environment,
        region=None,
        metric_name="exception_count",
        metric_value=1.0,
        threshold_value=10.0,
        title=title,
        description=f"Sentry issue observed in {project_slug or 'project'}: {title}",
        error_signature=f"sentry:{exc_type}",
        raw_payload=data,
    )

    return {
        "status": "processed",
        "signal_id": str(sig.id),
        "incident_id": str(inc.id) if inc else None,
        "incident_created": is_new,
    }


@router.post("/webhooks/signals/generic")
async def receive_generic_telemetry_signal(
    request: Request,
    x_sentinel_key_id: Optional[str] = Header(None, alias="X-Sentinel-Key-ID"),
    x_sentinel_signature: Optional[str] = Header(None, alias="X-Sentinel-Signature"),
    x_sentinel_timestamp: Optional[str] = Header(None, alias="X-Sentinel-Timestamp"),
    db: Session = Depends(get_db),
):
    """
    Ingest custom APM/telemetry signals (DataDog, CloudWatch, custom monitoring daemons).
    Verifies HMAC-SHA256 signature and mandatory replay timestamp against dedicated 'generic' endpoint.
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

    # 2. Endpoint & Tenant Resolution (Strictly provider == 'generic')
    ep = db.query(WebhookEndpoint).filter(
        WebhookEndpoint.key_id == x_sentinel_key_id,
        WebhookEndpoint.provider == "generic",
        WebhookEndpoint.is_active == True,
    ).first()
    if not ep:
        raise HTTPException(status_code=401, detail="Invalid or inactive generic webhook key ID")

    # 3. HMAC Verification
    raw_secret = decrypt_secret(ep.encrypted_secret)
    if not verify_hmac_sha256(body_bytes, x_sentinel_signature, raw_secret):
        raise HTTPException(status_code=401, detail="Invalid HMAC-SHA256 signature")

    try:
        data = json.loads(body_bytes.decode("utf-8"))
        payload = GenericSignalPayload(**data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Malformed generic signal JSON payload: {str(e)}")

    org_id = ep.organization_id

    # 4. Resolve Entities
    service = None
    if payload.service_id:
        service = db.query(Service).filter(Service.id == payload.service_id, Service.organization_id == org_id).first()
    elif payload.service_name:
        service = db.query(Service).filter(Service.name == payload.service_name.strip(), Service.organization_id == org_id).first()

    environment = None
    if payload.environment_id:
        environment = db.query(Environment).filter(Environment.id == payload.environment_id, Environment.organization_id == org_id).first()
    elif payload.environment_name:
        environment = db.query(Environment).filter(Environment.name == payload.environment_name.strip(), Environment.organization_id == org_id).first()

    region = None
    if payload.region_id:
        region = db.query(Region).filter(Region.id == payload.region_id, Region.organization_id == org_id).first()
    elif payload.region_code:
        region = db.query(Region).filter(Region.code == payload.region_code.strip(), Region.organization_id == org_id).first()

    # Map SignalType Enum
    try:
        sig_type_enum = SignalType[payload.signal_type.upper()]
    except KeyError:
        sig_type_enum = SignalType.ERROR_RATE

    event_id = payload.event_id or f"gen-{uuid.uuid4()}"
    title = payload.title or f"Custom Telemetry: {payload.signal_type} on {service.name if service else 'service'}"

    sig, inc, is_new = process_telemetry_signal(
        db=db,
        organization_id=org_id,
        provider=SignalProvider.GENERIC,
        provider_event_id=event_id,
        signal_type=sig_type_enum,
        service=service,
        environment=environment,
        region=region,
        metric_name=payload.metric_name,
        metric_value=payload.metric_value,
        threshold_value=payload.threshold_value,
        title=title,
        description=payload.description,
        error_signature=payload.error_signature,
        raw_payload=payload.metadata,
        observed_at=payload.observed_at,
    )

    return {
        "status": "processed",
        "signal_id": str(sig.id),
        "incident_id": str(inc.id) if inc else None,
        "incident_created": is_new,
    }


# ============================================================================
# AUTHENTICATED MONITORING QUERY & MANAGEMENT ENDPOINTS
# ============================================================================

@router.get("/monitoring/signals", response_model=List[TelemetrySignalResponse])
def list_telemetry_signals(
    service_id: Optional[uuid.UUID] = None,
    environment_id: Optional[uuid.UUID] = None,
    provider: Optional[str] = None,
    signal_type: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """List telemetry signals feed with pagination and multi-tenant scoping."""
    org, _ = auth_ctx
    query = db.query(TelemetrySignal).filter(TelemetrySignal.organization_id == org.id)

    if service_id:
        query = query.filter(TelemetrySignal.service_id == service_id)
    if environment_id:
        query = query.filter(TelemetrySignal.environment_id == environment_id)
    if provider:
        query = query.filter(TelemetrySignal.provider == provider)
    if signal_type:
        query = query.filter(TelemetrySignal.signal_type == signal_type)
    if status_filter:
        query = query.filter(TelemetrySignal.status == status_filter)

    signals = query.order_by(desc(TelemetrySignal.observed_at)).offset(offset).limit(limit).all()

    results = []
    for s in signals:
        res = TelemetrySignalResponse(
            id=s.id,
            organization_id=s.organization_id,
            provider=s.provider.value if hasattr(s.provider, "value") else str(s.provider),
            provider_event_id=s.provider_event_id,
            signal_type=s.signal_type.value if hasattr(s.signal_type, "value") else str(s.signal_type),
            rule_name=s.rule_name,
            service_id=s.service_id,
            service_name=s.service.name if s.service else None,
            environment_id=s.environment_id,
            environment_name=s.environment.name if s.environment else None,
            region_id=s.region_id,
            region_code=s.region.code if s.region else None,
            metric_name=s.metric_name,
            metric_value=s.metric_value,
            threshold_value=s.threshold_value,
            fingerprint=s.fingerprint,
            correlation_key=s.correlation_key,
            title=s.title,
            description=s.description,
            error_signature=s.error_signature,
            raw_payload=s.raw_payload,
            status=s.status.value if hasattr(s.status, "value") else str(s.status),
            incident_id=s.incident_id,
            incident_number=s.incident.number if s.incident else None,
            observed_at=s.observed_at,
            created_at=s.created_at,
        )
        results.append(res)
    return results


@router.get("/monitoring/health-checks", response_model=List[HealthCheckStatusResponse])
def list_health_check_statuses(
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """List current health check probe statuses across all configured service deployment configs."""
    org, _ = auth_ctx
    configs = db.query(ServiceDeploymentConfig).filter(
        ServiceDeploymentConfig.organization_id == org.id,
        ServiceDeploymentConfig.is_active == True,
        ServiceDeploymentConfig.health_check_url.isnot(None),
        ServiceDeploymentConfig.health_check_url != "",
    ).all()

    results = []
    for c in configs:
        results.append(HealthCheckStatusResponse(
            id=c.id,
            service_id=c.service_id,
            service_name=c.service.name if c.service else "unknown",
            environment_id=c.environment_id,
            environment_name=c.environment.name if c.environment else "unknown",
            region_id=c.region_id,
            region_code=c.region.code if c.region else None,
            health_check_url=c.health_check_url,
            is_healthy=c.last_probe_is_healthy,
            consecutive_failures=c.consecutive_failures or 0,
            last_probe_status_code=c.last_probe_status_code,
            last_probe_latency_ms=c.last_probe_latency_ms,
            last_probe_error=c.last_probe_error,
            last_probed_at=c.last_probed_at,
        ))
    return results


@router.post("/monitoring/health-checks/probe-now")
async def probe_health_check_now(
    payload: ProbeNowRequest,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """
    On-demand health probe for a specific ServiceDeploymentConfig ID.
    Strictly restricted to organization-owned configs to prevent SSRF abuse.
    """
    org, _ = auth_ctx
    config = db.query(ServiceDeploymentConfig).filter(
        ServiceDeploymentConfig.id == payload.config_id,
        ServiceDeploymentConfig.organization_id == org.id,
    ).first()
    if not config:
        raise HTTPException(status_code=404, detail="Service deployment configuration not found")

    log = await probe_single_config(db, config.id)
    if not log:
        raise HTTPException(status_code=400, detail="Health check URL not configured or inactive")

    return {
        "config_id": str(config.id),
        "is_healthy": log.is_healthy,
        "status_code": log.status_code,
        "latency_ms": log.latency_ms,
        "error_message": log.error_message,
        "probed_at": log.probed_at,
    }


@router.get("/monitoring/rules", response_model=List[AlertRuleConfigDTO])
def list_alert_rules(
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """List all 12 detection rules and active organization overrides."""
    org, _ = auth_ctx
    existing_configs = {
        r.rule_name: r for r in db.query(AlertRuleConfig).filter(
            AlertRuleConfig.organization_id == org.id
        ).all()
    }

    results = []
    for rule in ALL_RULES:
        cfg = existing_configs.get(rule.rule_name)
        if cfg:
            results.append(AlertRuleConfigDTO.model_validate(cfg))
        else:
            # Return default rule configuration
            results.append(AlertRuleConfigDTO(
                id=uuid.uuid4(),
                organization_id=org.id,
                rule_name=rule.rule_name,
                is_enabled=True,
                threshold_value=rule.default_threshold,
                window_minutes=15,
                severity_override=rule.default_severity,
            ))
    return results


@router.put("/monitoring/rules/{rule_name}", response_model=AlertRuleConfigDTO)
def update_alert_rule(
    rule_name: str,
    payload: AlertRuleConfigUpdate,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """Update organization alert rule threshold, window, or toggle."""
    org, _ = auth_ctx
    if rule_name not in RULE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_name}' does not exist")

    cfg = db.query(AlertRuleConfig).filter(
        AlertRuleConfig.organization_id == org.id,
        AlertRuleConfig.rule_name == rule_name,
    ).first()

    rule_def = RULE_REGISTRY[rule_name]
    if not cfg:
        cfg = AlertRuleConfig(
            organization_id=org.id,
            rule_name=rule_name,
            is_enabled=payload.is_enabled if payload.is_enabled is not None else True,
            threshold_value=payload.threshold_value if payload.threshold_value is not None else rule_def.default_threshold,
            window_minutes=payload.window_minutes or 15,
            severity_override=payload.severity_override or rule_def.default_severity,
        )
        db.add(cfg)
    else:
        if payload.is_enabled is not None:
            cfg.is_enabled = payload.is_enabled
        if payload.threshold_value is not None:
            cfg.threshold_value = payload.threshold_value
        if payload.window_minutes is not None:
            cfg.window_minutes = payload.window_minutes
        if payload.severity_override is not None:
            cfg.severity_override = payload.severity_override

    db.commit()
    db.refresh(cfg)
    return AlertRuleConfigDTO.model_validate(cfg)


@router.get("/monitoring/correlation-summary")
def get_correlation_summary(
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """Get active signal cluster overview and auto-detected incident counts."""
    org, _ = auth_ctx
    lookback = datetime.now(timezone.utc) - timedelta(hours=24)

    total_signals_24h = db.query(TelemetrySignal).filter(
        TelemetrySignal.organization_id == org.id,
        TelemetrySignal.observed_at >= lookback,
    ).count()

    auto_incidents_24h = db.query(Incident).filter(
        Incident.organization_id == org.id,
        Incident.source.in_([IncidentSource.AUTO_DETECTION, IncidentSource.HEALTH_CHECK]),
        Incident.created_at >= lookback,
    ).count()

    open_incidents = db.query(Incident).filter(
        Incident.organization_id == org.id,
        Incident.status.notin_([IncidentStatus.RESOLVED, IncidentStatus.CANCELLED]),
    ).count()

    healthy_probes = db.query(ServiceDeploymentConfig).filter(
        ServiceDeploymentConfig.organization_id == org.id,
        ServiceDeploymentConfig.is_active == True,
        ServiceDeploymentConfig.last_probe_is_healthy == True,
    ).count()

    failing_probes = db.query(ServiceDeploymentConfig).filter(
        ServiceDeploymentConfig.organization_id == org.id,
        ServiceDeploymentConfig.is_active == True,
        ServiceDeploymentConfig.last_probe_is_healthy == False,
    ).count()

    return {
        "total_signals_24h": total_signals_24h,
        "auto_incidents_24h": auto_incidents_24h,
        "open_incidents": open_incidents,
        "healthy_probes": healthy_probes,
        "failing_probes": failing_probes,
    }
