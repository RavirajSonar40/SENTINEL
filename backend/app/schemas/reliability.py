"""Pydantic schemas for Phase 16: Advanced Reliability, SLO Tracking & Predictions."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field
from app.schemas.command_center import FreshnessMetadata


class SLOConfigCreate(BaseModel):
    service_id: UUID
    name: str = Field(..., min_length=1, max_length=200)
    target_percent: float = Field(default=99.9, ge=50.0, le=100.0)
    sli_type: str = Field(default="availability", description="availability, latency, error_rate")
    threshold_value: Optional[float] = Field(default=None, description="e.g. 200.0 (ms) for latency, 0.1 (%) for error rate")
    window_days: int = Field(default=30, ge=1, le=365)


class SLOConfigUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    target_percent: Optional[float] = Field(default=None, ge=50.0, le=100.0)
    threshold_value: Optional[float] = None
    is_active: Optional[bool] = None


class SLOBurnRateOut(BaseModel):
    burn_rate_1h: Optional[float] = None
    burn_rate_6h: Optional[float] = None
    burn_rate_24h: Optional[float] = None
    burn_status_1h: str = "normal"  # normal, elevated, critical_page
    burn_status_6h: str = "normal"  # normal, elevated, critical_page
    burn_status_24h: str = "normal"


class SLOTimeToExhaustionOut(BaseModel):
    hours_remaining: Optional[float] = None
    display: str = "—"
    status: str = "insufficient_data"  # healthy, warning, exhausted, insufficient_data


class SLOConfigOut(BaseModel):
    id: UUID
    organization_id: UUID
    service_id: UUID
    service_name: str
    name: str
    target_percent: float
    sli_type: str
    threshold_value: Optional[float] = None
    window_days: int
    is_active: bool
    current_compliance_percent: Optional[float] = None
    compliance_display: str = "—"
    budget_remaining_percent: Optional[float] = None
    budget_display: str = "—"
    burn_rates: SLOBurnRateOut
    time_to_exhaustion: SLOTimeToExhaustionOut
    total_samples_observed: int = 0
    freshness: FreshnessMetadata
    status: str = "healthy"  # healthy, warning, critical_burn, exhausted, insufficient_data
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SLOBurnDownPoint(BaseModel):
    timestamp: datetime
    budget_remaining_percent: float
    burn_rate: float
    event_note: Optional[str] = None


class SLOBurnDownResponse(BaseModel):
    slo_id: UUID
    slo_name: str
    service_name: str
    target_percent: float
    current_budget_remaining: Optional[float]
    points: List[SLOBurnDownPoint]


class PredictiveAnomalyOut(BaseModel):
    id: UUID
    organization_id: UUID
    service_id: UUID
    service_name: str
    metric_name: str
    current_value: float
    threshold_value: float
    projected_breach_at: Optional[datetime] = None
    time_to_breach_minutes: float
    growth_rate_per_minute: float
    r_squared: float
    confidence_score: float
    severity: str  # WARNING, CRITICAL, CRITICAL_BREACH_ACTIVE
    is_active: bool
    status: str  # ACTIVE, ACKNOWLEDGED, RESOLVED
    recommendation: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PredictiveAnomalyAcknowledge(BaseModel):
    comment: Optional[str] = None


class BusinessImpactConfigIn(BaseModel):
    service_id: Optional[UUID] = None
    tier: Optional[str] = None
    hourly_revenue_rate_usd: float = Field(ge=0.0)
    active_users_baseline: int = Field(default=1000, ge=0)
    currency: str = Field(default="USD", max_length=10)


class BusinessImpactConfigOut(BaseModel):
    id: UUID
    organization_id: UUID
    service_id: Optional[UUID] = None
    service_name: Optional[str] = None
    tier: Optional[str] = None
    hourly_revenue_rate_usd: float
    active_users_baseline: int
    currency: str
    is_org_default: bool = False

    class Config:
        from_attributes = True


class IncidentBusinessImpactOut(BaseModel):
    id: UUID
    incident_id: UUID
    incident_title: str
    service_id: Optional[UUID] = None
    service_name: str
    outage_duration_minutes: float
    degradation_factor: float
    hourly_revenue_rate_usd: Optional[float] = None
    estimated_financial_loss_usd: Optional[float] = None
    financial_loss_display: str = "—"
    affected_user_count: int = 0
    sla_breach_detected: bool = False
    currency: str = "USD"
    status: str = "calculated"  # calculated, unconfigured, insufficient_data
    is_estimated_default: bool = False
    calculated_at: datetime

    class Config:
        from_attributes = True
