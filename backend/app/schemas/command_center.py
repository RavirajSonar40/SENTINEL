"""Pydantic schemas for Phase 15 Operations Command Center."""
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class FreshnessMetadata(BaseModel):
    """Metadata detailing when telemetry/metrics were observed and staleness."""
    observed_at: datetime
    source: str = Field(default="synthetic_probe", description="Source provider or probe mechanism")
    freshness_seconds: float = Field(default=0.0, description="Seconds elapsed since observed_at")
    is_stale: bool = Field(default=False, description="True if freshness_seconds exceeds 300s")


class ErrorBudgetMetric(BaseModel):
    """Error budget reliability metric with insufficient data handling."""
    value: Optional[float] = None
    display: str = "—"
    status: str = Field(default="insufficient_data", description="healthy | degraded | exhausted | insufficient_data")
    slo_target_percent: float = 99.9
    actual_availability_percent: Optional[float] = None


class TimeMetric(BaseModel):
    """Mean Time metrics (MTTD, MTTR) with sample size tracking."""
    value_minutes: Optional[float] = None
    display: str = "—"
    sample_size: int = 0


class IncidentsSummary(BaseModel):
    """Active incident counters and severity breakdown (parent incidents only)."""
    active_total: int = 0
    critical_sev1: int = 0
    major_sev2: int = 0
    minor_sev3: int = 0
    low_sev4: int = 0
    investigating_count: int = 0
    awaiting_approval_count: int = 0
    resolved_last_24h: int = 0
    mttd: TimeMetric
    mttr: TimeMetric
    freshness: FreshnessMetadata


class ServiceFleetSummary(BaseModel):
    """Microservice fleet operational counts and Tier-1 breakdown."""
    total_services: int = 0
    healthy: int = 0
    degraded: int = 0
    down: int = 0
    unknown: int = 0
    tier1_total: int = 0
    tier1_healthy: int = 0
    tier1_degraded: int = 0
    tier1_down: int = 0
    freshness: FreshnessMetadata


class DeploymentsSummary(BaseModel):
    """Deployment stream velocity, active in-flight, and change failure rates."""
    total_last_24h: int = 0
    in_progress: int = 0
    successful: int = 0
    failed: int = 0
    rolled_back: int = 0
    failure_rate_percent: float = 0.0
    freshness: FreshnessMetadata


class RemediationSummary(BaseModel):
    """Multi-repository remediation, draft PR queue, and policy status."""
    active_plans: int = 0
    pending_approvals: int = 0
    draft_prs_published: int = 0
    blocked_cyclic_plans: int = 0
    remediation_success_rate_percent: Optional[float] = None
    remediation_success_display: str = "—"


class ReliabilitySummary(BaseModel):
    """Reliability indicators including error budget, p95 latency, and system health."""
    system_status: str = "healthy"
    error_budget: ErrorBudgetMetric
    p95_latency_ms: Optional[float] = None
    overall_compliance_score: float = 100.0


class RecentActivityItem(BaseModel):
    """Chronological event item for command center live activity stream."""
    id: str
    event_type: str = Field(..., description="incident_created | deployment_completed | root_cause_identified | pr_published | probe_failed")
    title: str
    description: str
    severity: Optional[str] = None
    service_name: Optional[str] = None
    timestamp: datetime
    link_url: Optional[str] = None


class CommandCenterOverviewResponse(BaseModel):
    """Full company-wide Operations Command Center overview response."""
    organization_id: UUID
    organization_name: str
    incidents_summary: IncidentsSummary
    service_fleet: ServiceFleetSummary
    deployments_summary: DeploymentsSummary
    remediation_summary: RemediationSummary
    reliability_summary: ReliabilitySummary
    recent_activity: List[RecentActivityItem] = []
    polled_at: datetime


class OperationalServiceItem(BaseModel):
    """Service operational telemetry and microservice card details."""
    id: UUID
    name: str
    slug: str
    tier: str
    environment: str
    owner_team: Optional[str] = None
    oncall_contact: Optional[str] = None
    health_status: str = Field(..., description="healthy | degraded | down | unknown")
    health_reason: str = "Normal operation"
    version: Optional[str] = None
    commit_sha: Optional[str] = None
    repository_full_name: Optional[str] = None
    cpu_percent: Optional[float] = None
    memory_percent: Optional[float] = None
    error_rate_percent: Optional[float] = None
    p95_latency_ms: Optional[float] = None
    consecutive_probe_failures: int = 0
    latest_deployment_at: Optional[datetime] = None
    latest_deployment_author: Optional[str] = None
    open_incidents_count: int = 0
    upstream_dependencies_count: int = 0
    downstream_dependents_count: int = 0
    freshness: FreshnessMetadata


class OperationalServicesResponse(BaseModel):
    """Paginated operational services matrix."""
    items: List[OperationalServiceItem]
    total: int
    page: int
    page_size: int
    total_pages: int
    freshness: FreshnessMetadata


class ActiveCommandIncidentItem(BaseModel):
    """Rich incident card for the active command center feed."""
    id: UUID
    title: str
    severity: str
    status: str
    detection_source: str
    service_name: Optional[str] = None
    primary_defect_repo: Optional[str] = None
    candidate_repos_count: int = 0
    blast_radius_service_count: int = 0
    created_at: datetime
    duration_minutes: float
    has_active_remediation_plan: bool = False
    remediation_plan_status: Optional[str] = None
    pending_approval_id: Optional[UUID] = None


class ActiveCommandResponse(BaseModel):
    """Active command incident board feed."""
    active_incidents: List[ActiveCommandIncidentItem]
    total_active: int
    freshness: FreshnessMetadata


class QuickProbeRequest(BaseModel):
    """Payload to trigger an on-demand synthetic diagnostic probe."""
    service_id: UUID
    environment: Optional[str] = "production"


class QuickProbeResponse(BaseModel):
    """Outcome of an on-demand synthetic diagnostic probe."""
    service_id: UUID
    service_name: str
    probe_status: str = Field(..., description="success | failure")
    http_status_code: Optional[int] = None
    latency_ms: float
    message: str
    health_status_after: str
    observed_at: datetime
