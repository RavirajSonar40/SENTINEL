"""REST API router for Phase 16: Advanced Reliability, SLOs, Predictions & Business Impact."""
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.core.database import get_db
from app.core.permissions import require_viewer, require_member, require_admin
from app.models.incident import (
    Organization,
    UserOrganizationMembership,
    SLOConfig,
    SLOBurnRateSnapshot,
    PredictiveAnomaly,
    BusinessImpactConfig,
    Service,
    Incident,
)
from app.services.workflow_router import validate_cross_org_entities
from app.schemas.reliability import (
    SLOConfigCreate,
    SLOConfigUpdate,
    SLOConfigOut,
    SLOBurnDownResponse,
    SLOBurnDownPoint,
    PredictiveAnomalyOut,
    PredictiveAnomalyAcknowledge,
    BusinessImpactConfigIn,
    BusinessImpactConfigOut,
    IncidentBusinessImpactOut,
)
from app.services.reliability import (
    calculate_slo_burn_rates,
    detect_predictive_anomalies,
    estimate_incident_business_impact,
    _compute_freshness,
)

reliability_router = APIRouter(prefix="/reliability", tags=["Reliability & SLOs"])


# =============================================================================
# 1. SLO TARGETS & MULTI-WINDOW BURN RATES
# =============================================================================

@reliability_router.get("/slos", response_model=List[SLOConfigOut])
def list_slos(
    service_id: Optional[UUID] = Query(None, description="Filter by service ID"),
    is_active: Optional[bool] = Query(None, description="Filter active/inactive SLOs"),
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """List all configured service SLOs with live multi-window burn rates and compliance."""
    org, _ = context
    query = db.query(SLOConfig).filter(SLOConfig.organization_id == org.id)
    if service_id:
        query = query.filter(SLOConfig.service_id == service_id)
    if is_active is not None:
        query = query.filter(SLOConfig.is_active == is_active)

    slos = query.order_by(SLOConfig.created_at.desc()).all()
    results = []

    for slo in slos:
        svc = db.query(Service).filter(Service.id == slo.service_id).first()
        svc_name = svc.name if svc else "Unknown Service"

        burn_rates, exhaustion, compliance, budget_rem, total_samples, freshness, overall_status = (
            calculate_slo_burn_rates(db, slo)
        )

        results.append(
            SLOConfigOut(
                id=slo.id,
                organization_id=slo.organization_id,
                service_id=slo.service_id,
                service_name=svc_name,
                name=slo.name,
                target_percent=slo.target_percent,
                sli_type=slo.sli_type,
                threshold_value=slo.threshold_value,
                window_days=slo.window_days,
                is_active=slo.is_active,
                current_compliance_percent=compliance,
                compliance_display=f"{compliance:.2f}%" if compliance is not None else "—",
                budget_remaining_percent=budget_rem,
                budget_display=f"{budget_rem:.1f}%" if budget_rem is not None else "—",
                burn_rates=burn_rates,
                time_to_exhaustion=exhaustion,
                total_samples_observed=total_samples,
                freshness=freshness,
                status=overall_status,
                created_at=slo.created_at,
                updated_at=slo.updated_at,
            )
        )

    return results


@reliability_router.post("/slos", response_model=SLOConfigOut, status_code=status.HTTP_201_CREATED)
def create_slo(
    req: SLOConfigCreate,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_member),
    db: Session = Depends(get_db),
):
    """Create a new SLO target for a microservice (Member+)."""
    org, _ = context
    # Tenant ownership check
    validate_cross_org_entities(
        db=db,
        organization_id=org.id,
        service_id=req.service_id,
    )


    svc = db.query(Service).filter(Service.id == req.service_id, Service.organization_id == org.id).first()
    if not svc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found in organization")

    # Check unique name per service
    existing = (
        db.query(SLOConfig)
        .filter(
            SLOConfig.organization_id == org.id,
            SLOConfig.service_id == req.service_id,
            SLOConfig.name == req.name,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"SLO '{req.name}' already exists for this service")

    slo = SLOConfig(
        organization_id=org.id,
        service_id=req.service_id,
        name=req.name,
        target_percent=req.target_percent,
        sli_type=req.sli_type.lower(),
        threshold_value=req.threshold_value,
        window_days=req.window_days,
        is_active=True,
    )
    db.add(slo)
    db.commit()
    db.refresh(slo)

    burn_rates, exhaustion, compliance, budget_rem, total_samples, freshness, overall_status = (
        calculate_slo_burn_rates(db, slo)
    )

    return SLOConfigOut(
        id=slo.id,
        organization_id=slo.organization_id,
        service_id=slo.service_id,
        service_name=svc.name,
        name=slo.name,
        target_percent=slo.target_percent,
        sli_type=slo.sli_type,
        threshold_value=slo.threshold_value,
        window_days=slo.window_days,
        is_active=slo.is_active,
        current_compliance_percent=compliance,
        compliance_display=f"{compliance:.2f}%" if compliance is not None else "—",
        budget_remaining_percent=budget_rem,
        budget_display=f"{budget_rem:.1f}%" if budget_rem is not None else "—",
        burn_rates=burn_rates,
        time_to_exhaustion=exhaustion,
        total_samples_observed=total_samples,
        freshness=freshness,
        status=overall_status,
        created_at=slo.created_at,
        updated_at=slo.updated_at,
    )


@reliability_router.get("/slos/{slo_id}/burn-down", response_model=SLOBurnDownResponse)
def get_slo_burn_down(
    slo_id: UUID,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """Retrieve error budget burn-down timeline points for an SLO."""
    org, _ = context
    slo = db.query(SLOConfig).filter(SLOConfig.id == slo_id, SLOConfig.organization_id == org.id).first()
    if not slo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SLO not found")

    svc = db.query(Service).filter(Service.id == slo.service_id).first()
    svc_name = svc.name if svc else "Unknown Service"

    snapshots = (
        db.query(SLOBurnRateSnapshot)
        .filter(SLOBurnRateSnapshot.slo_id == slo.id)
        .order_by(SLOBurnRateSnapshot.captured_hour.asc())
        .limit(100)
        .all()
    )

    points = [
        SLOBurnDownPoint(
            timestamp=s.captured_hour,
            budget_remaining_percent=s.budget_remaining_percent or 100.0,
            burn_rate=s.burn_rate_1h or 1.0,
            event_note=s.status if s.status != "healthy" else None,
        )
        for s in snapshots
    ]

    # Current calculation
    _, _, _, budget_rem, _, _, _ = calculate_slo_burn_rates(db, slo)

    return SLOBurnDownResponse(
        slo_id=slo.id,
        slo_name=slo.name,
        service_name=svc_name,
        target_percent=slo.target_percent,
        current_budget_remaining=budget_rem,
        points=points,
    )


@reliability_router.patch("/slos/{slo_id}", response_model=SLOConfigOut)
def update_slo(
    slo_id: UUID,
    req: SLOConfigUpdate,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_member),
    db: Session = Depends(get_db),
):
    """Update an existing SLO configuration (Member+)."""
    org, _ = context
    slo = db.query(SLOConfig).filter(SLOConfig.id == slo_id, SLOConfig.organization_id == org.id).first()
    if not slo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SLO not found")

    if req.name is not None:
        slo.name = req.name
    if req.target_percent is not None:
        slo.target_percent = req.target_percent
    if req.threshold_value is not None:
        slo.threshold_value = req.threshold_value
    if req.is_active is not None:
        slo.is_active = req.is_active

    db.commit()
    db.refresh(slo)

    svc = db.query(Service).filter(Service.id == slo.service_id).first()
    svc_name = svc.name if svc else "Unknown Service"
    burn_rates, exhaustion, compliance, budget_rem, total_samples, freshness, overall_status = (
        calculate_slo_burn_rates(db, slo)
    )

    return SLOConfigOut(
        id=slo.id,
        organization_id=slo.organization_id,
        service_id=slo.service_id,
        service_name=svc_name,
        name=slo.name,
        target_percent=slo.target_percent,
        sli_type=slo.sli_type,
        threshold_value=slo.threshold_value,
        window_days=slo.window_days,
        is_active=slo.is_active,
        current_compliance_percent=compliance,
        compliance_display=f"{compliance:.2f}%" if compliance is not None else "—",
        budget_remaining_percent=budget_rem,
        budget_display=f"{budget_rem:.1f}%" if budget_rem is not None else "—",
        burn_rates=burn_rates,
        time_to_exhaustion=exhaustion,
        total_samples_observed=total_samples,
        freshness=freshness,
        status=overall_status,
        created_at=slo.created_at,
        updated_at=slo.updated_at,
    )


# =============================================================================
# 2. PREDICTIVE ANOMALY & EARLY WARNING RADAR
# =============================================================================

@reliability_router.get("/predictions", response_model=List[PredictiveAnomalyOut])
def get_predictive_anomalies(
    status_filter: Optional[str] = Query("ACTIVE", description="Filter by status (ACTIVE, ACKNOWLEDGED, RESOLVED, ALL)"),
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """Run real-time predictive drift engine and return active early-warning anomalies."""
    org, _ = context
    # Detect fresh anomalies
    detect_predictive_anomalies(db, org.id)

    query = db.query(PredictiveAnomaly).filter(PredictiveAnomaly.organization_id == org.id)
    if status_filter and status_filter.upper() != "ALL":
        query = query.filter(PredictiveAnomaly.status == status_filter.upper())

    anomalies = query.order_by(PredictiveAnomaly.created_at.desc()).all()
    results = []
    for a in anomalies:
        svc = db.query(Service).filter(Service.id == a.service_id).first()
        svc_name = svc.name if svc else "Unknown Service"
        results.append(
            PredictiveAnomalyOut(
                id=a.id,
                organization_id=a.organization_id,
                service_id=a.service_id,
                service_name=svc_name,
                metric_name=a.metric_name,
                current_value=a.current_value,
                threshold_value=a.threshold_value,
                projected_breach_at=a.projected_breach_at,
                time_to_breach_minutes=a.time_to_breach_minutes,
                growth_rate_per_minute=a.growth_rate_per_minute,
                r_squared=a.r_squared,
                confidence_score=a.confidence_score,
                severity=a.severity,
                is_active=a.is_active,
                status=a.status,
                recommendation=a.recommendation,
                created_at=a.created_at,
            )
        )
    return results


@reliability_router.post("/predictions/{anomaly_id}/acknowledge")
def acknowledge_predictive_anomaly(
    anomaly_id: UUID,
    req: PredictiveAnomalyAcknowledge,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_member),
    db: Session = Depends(get_db),
):
    """Acknowledge a predictive warning (Member+)."""
    org, _ = context
    anomaly = (
        db.query(PredictiveAnomaly)
        .filter(PredictiveAnomaly.id == anomaly_id, PredictiveAnomaly.organization_id == org.id)
        .first()
    )
    if not anomaly:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Predictive anomaly not found")

    anomaly.status = "ACKNOWLEDGED"
    db.commit()
    return {"message": "Predictive anomaly acknowledged", "id": str(anomaly.id), "status": anomaly.status}


# =============================================================================
# 3. FINANCIAL & BUSINESS IMPACT QUANTIFICATION
# =============================================================================

@reliability_router.get("/business-impact/{incident_id}", response_model=IncidentBusinessImpactOut)
def get_incident_business_impact(
    incident_id: UUID,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """Calculate and return real-time or post-mortem incident financial & user impact."""
    org, _ = context
    try:
        return estimate_incident_business_impact(db, incident_id, org.id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found in organization")


@reliability_router.get("/business-impact/config", response_model=List[BusinessImpactConfigOut])
def get_business_impact_configs(
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """List configured revenue and user baselines for the organization."""
    org, _ = context
    configs = db.query(BusinessImpactConfig).filter(BusinessImpactConfig.organization_id == org.id).all()
    results = []
    for c in configs:
        svc = db.query(Service).filter(Service.id == c.service_id).first() if c.service_id else None
        results.append(
            BusinessImpactConfigOut(
                id=c.id,
                organization_id=c.organization_id,
                service_id=c.service_id,
                service_name=svc.name if svc else None,
                tier=c.tier,
                hourly_revenue_rate_usd=c.hourly_revenue_rate_usd,
                active_users_baseline=c.active_users_baseline,
                currency=c.currency,
                is_org_default=(c.service_id is None and c.tier is None),
            )
        )
    return results


@reliability_router.put("/business-impact/config", response_model=BusinessImpactConfigOut)
def set_business_impact_config(
    req: BusinessImpactConfigIn,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Configure financial revenue baseline and user weightings (Admin+)."""
    org, _ = context
    if req.service_id:
        validate_cross_org_entities(
            db=db,
            organization_id=org.id,
            service_id=req.service_id,
        )


    # Upsert logic
    query = db.query(BusinessImpactConfig).filter(BusinessImpactConfig.organization_id == org.id)
    if req.service_id:
        query = query.filter(BusinessImpactConfig.service_id == req.service_id)
    elif req.tier:
        query = query.filter(BusinessImpactConfig.tier == req.tier, BusinessImpactConfig.service_id == None)
    else:
        query = query.filter(BusinessImpactConfig.service_id == None, BusinessImpactConfig.tier == None)

    existing = query.first()
    if existing:
        existing.hourly_revenue_rate_usd = req.hourly_revenue_rate_usd
        existing.active_users_baseline = req.active_users_baseline
        existing.currency = req.currency
        existing.tier = req.tier
        db.commit()
        db.refresh(existing)
        cfg_obj = existing
    else:
        new_cfg = BusinessImpactConfig(
            organization_id=org.id,
            service_id=req.service_id,
            tier=req.tier,
            hourly_revenue_rate_usd=req.hourly_revenue_rate_usd,
            active_users_baseline=req.active_users_baseline,
            currency=req.currency,
        )
        db.add(new_cfg)
        db.commit()
        db.refresh(new_cfg)
        cfg_obj = new_cfg

    svc = db.query(Service).filter(Service.id == cfg_obj.service_id).first() if cfg_obj.service_id else None
    return BusinessImpactConfigOut(
        id=cfg_obj.id,
        organization_id=cfg_obj.organization_id,
        service_id=cfg_obj.service_id,
        service_name=svc.name if svc else None,
        tier=cfg_obj.tier,
        hourly_revenue_rate_usd=cfg_obj.hourly_revenue_rate_usd,
        active_users_baseline=cfg_obj.active_users_baseline,
        currency=cfg_obj.currency,
        is_org_default=(cfg_obj.service_id is None and cfg_obj.tier is None),
    )
