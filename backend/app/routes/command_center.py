"""
Command Center REST API Routes.
Phase 15: Operations Command Center UI, fleet matrix, and active command workspace.
"""

from typing import Optional, Tuple
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import require_viewer, require_member
from app.models.incident import User, Organization, UserOrganizationMembership
from app.schemas.command_center import (
    CommandCenterOverviewResponse,
    OperationalServicesResponse,
    ActiveCommandResponse,
    QuickProbeRequest,
    QuickProbeResponse,
)
from app.services.command_center import (
    get_command_center_overview,
    get_operational_services_paginated,
    get_active_command_feed,
    trigger_quick_diagnostic_probe,
)

router = APIRouter(prefix="/command-center", tags=["Operations Command Center"])


@router.get("/overview", response_model=CommandCenterOverviewResponse)
def get_overview_endpoint(
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """
    Get company-wide Operations Command Center live overview.
    Aggregates active incidents by severity, microservice fleet health, deployment velocity,
    remediation draft PR queues, and reliability indicators with freshness metadata.
    """
    org, _ = context
    return get_command_center_overview(db=db, organization_id=org.id)


@router.get("/services-operational", response_model=OperationalServicesResponse)
def get_services_operational_endpoint(
    tier: Optional[str] = Query(None, description="Filter by service tier (e.g. tier_1, tier_2, tier_3)"),
    environment: Optional[str] = Query(None, description="Filter by environment name"),
    health: Optional[str] = Query(None, description="Filter by health status: healthy, degraded, down, unknown"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(25, ge=1, le=100, description="Items per page"),
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """
    Get paginated operational microservice fleet matrix with runtime telemetry,
    open incident associations, dependency counts, and freshness metadata.
    """
    org, _ = context
    return get_operational_services_paginated(
        db=db,
        organization_id=org.id,
        tier=tier,
        environment_name=environment,
        health_filter=health,
        page=page,
        page_size=page_size,
    )


@router.get("/active-command", response_model=ActiveCommandResponse)
def get_active_command_endpoint(
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """
    Get active incident command feed with blast radius estimations and remediation progress.
    """
    org, _ = context
    return get_active_command_feed(db=db, organization_id=org.id)


@router.post("/quick-probe", response_model=QuickProbeResponse)
def trigger_quick_probe_endpoint(
    req: QuickProbeRequest,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_member),
    db: Session = Depends(get_db),
):
    """
    Trigger an on-demand synthetic diagnostic probe for a service (Member role or above required).
    """
    org, membership = context
    try:
        return trigger_quick_diagnostic_probe(
            db=db,
            organization_id=org.id,
            service_id=req.service_id,
            actor_user_id=membership.user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
