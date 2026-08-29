"""Pydantic schemas for Phase 10 — Incident Memory & Explainable Timeline."""
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID


class TimelineEventOut(BaseModel):
    id: str
    time: Optional[str] = None
    type: str
    category: str  # deployment, telemetry, incident, investigation, evidence, hypothesis, root_cause, remediation, human_action
    label: str
    detail: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    actor: str = "ai"  # ai, human, system
    parent_event_id: Optional[str] = None
    causal_relation: Optional[str] = None
    inferred_timestamp: bool = False
    metadata: Optional[Dict[str, Any]] = None


class TimelineMilestonesOut(BaseModel):
    mttd_seconds: Optional[int] = None
    mtta_seconds: Optional[int] = None
    mttrc_seconds: Optional[int] = None
    mttm_seconds: Optional[int] = None
    mttr_seconds: Optional[int] = None
    started_at: Optional[str] = None
    detected_at: Optional[str] = None
    acknowledged_at: Optional[str] = None
    root_cause_at: Optional[str] = None
    mitigated_at: Optional[str] = None
    resolved_at: Optional[str] = None


class ExplainableTimelineResponse(BaseModel):
    incident_id: str
    milestones: TimelineMilestonesOut
    total_events: int
    events: List[TimelineEventOut]


class ActionItemCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: str = "code_hardening"  # code_hardening, monitoring_gap, architectural_debt, runbook_improvement, infrastructure_resilience
    priority: str = "P2"  # P0, P1, P2, P3
    due_date: Optional[datetime] = None
    assigned_to_user_id: Optional[str] = None
    external_issue_url: Optional[str] = None
    notes: Optional[str] = None


class ActionItemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None  # open, in_progress, completed, wont_fix
    due_date: Optional[datetime] = None
    assigned_to_user_id: Optional[str] = None
    external_issue_url: Optional[str] = None
    notes: Optional[str] = None


class ActionItemOut(BaseModel):
    id: str
    organization_id: str
    post_mortem_id: str
    incident_id: Optional[str] = None
    assigned_to_user_id: Optional[str] = None
    created_by_user_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    category: str
    priority: str
    status: str
    due_date: Optional[str] = None
    completed_at: Optional[str] = None
    external_issue_url: Optional[str] = None
    notes: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None


class PostMortemCreate(BaseModel):
    title: str
    summary: str
    root_cause_summary: str
    impact_summary: Optional[str] = None
    trigger_event: Optional[str] = None
    detection_summary: Optional[str] = None
    resolution_summary: Optional[str] = None
    contributing_factors_json: Optional[List[Any]] = None
    lessons_learned_json: Optional[List[Any]] = None
    downtime_minutes: Optional[float] = 0.0
    affected_user_count_estimate: Optional[int] = None
    slo_impact_percent: Optional[float] = None
    resolution_type: Optional[str] = "code_fix"
    severity_actual: Optional[str] = "SEV-2"


class PostMortemUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    root_cause_summary: Optional[str] = None
    impact_summary: Optional[str] = None
    trigger_event: Optional[str] = None
    detection_summary: Optional[str] = None
    resolution_summary: Optional[str] = None
    contributing_factors_json: Optional[List[Any]] = None
    lessons_learned_json: Optional[List[Any]] = None
    downtime_minutes: Optional[float] = None
    affected_user_count_estimate: Optional[int] = None
    slo_impact_percent: Optional[float] = None
    resolution_type: Optional[str] = None
    severity_actual: Optional[str] = None
    status: Optional[str] = None


class PostMortemPublishRequest(BaseModel):
    sign_off_notes: Optional[str] = None


class PostMortemOut(BaseModel):
    id: str
    organization_id: str
    incident_id: str
    work_item_id: Optional[str] = None
    author_id: Optional[str] = None
    signed_off_by_user_id: Optional[str] = None
    title: str
    summary: str
    root_cause_summary: str
    impact_summary: Optional[str] = None
    trigger_event: Optional[str] = None
    detection_summary: Optional[str] = None
    resolution_summary: Optional[str] = None
    contributing_factors_json: List[Any] = []
    timeline_summary_json: List[Any] = []
    lessons_learned_json: List[Any] = []
    time_to_detect_seconds: Optional[int] = None
    time_to_acknowledge_seconds: Optional[int] = None
    time_to_root_cause_seconds: Optional[int] = None
    time_to_mitigate_seconds: Optional[int] = None
    time_to_resolve_seconds: Optional[int] = None
    downtime_minutes: float = 0.0
    affected_user_count_estimate: Optional[int] = None
    slo_impact_percent: Optional[float] = None
    resolution_type: str = "code_fix"
    severity_actual: str = "SEV-2"
    status: str = "draft"
    snapshot_hash: Optional[str] = None
    abstained: bool = False
    human_reviewed: bool = False
    is_current: bool = True
    version: int = 1
    memory_indexing_status: str = "pending"
    memory_indexing_error: Optional[str] = None
    signed_off_at: Optional[str] = None
    published_at: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None
    action_items: List[ActionItemOut] = []


class IncidentMemorySearchRequest(BaseModel):
    query: str
    service: Optional[str] = None
    limit: int = 5


class IncidentMemorySearchResult(BaseModel):
    id: str
    score: float
    title: str
    service: Optional[str] = None
    severity: Optional[str] = None
    root_cause: Optional[str] = None
    resolution: Optional[str] = None
    lessons_learned: Optional[List[Any]] = None
    resolved_at: Optional[str] = None


class IncidentMemorySearchResponse(BaseModel):
    results: List[IncidentMemorySearchResult]
    total: int
    source: str
