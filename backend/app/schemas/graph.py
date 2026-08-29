"""Pydantic schemas for Phase 6 System Service Graph & Blast Radius Analysis."""

import uuid
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, field_validator

from app.models.incident import (
    GraphNodeType, GraphEdgeType, GraphEdgeSource, ServiceCriticality
)


class GraphNodeBase(BaseModel):
    name: str = Field(..., max_length=255)
    node_type: GraphNodeType
    identifier: str = Field(..., max_length=500)
    tier: Optional[str] = Field(None, max_length=50)
    entity_id: Optional[uuid.UUID] = None
    metadata_json: Optional[Dict[str, Any]] = None

    @field_validator("node_type", mode="before")
    @classmethod
    def normalize_node_type(cls, v: Any) -> GraphNodeType:
        if isinstance(v, str):
            return GraphNodeType(v.upper())
        return v


class GraphNodeCreate(GraphNodeBase):
    pass


class GraphNodeUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    tier: Optional[str] = Field(None, max_length=50)
    metadata_json: Optional[Dict[str, Any]] = None


class GraphNodeResponse(GraphNodeBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class GraphEdgeBase(BaseModel):
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    edge_type: GraphEdgeType
    source: GraphEdgeSource = GraphEdgeSource.SERVICE_REGISTRATION
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    criticality: ServiceCriticality = ServiceCriticality.HARD
    is_stale: bool = False
    metadata_json: Optional[Dict[str, Any]] = None

    @field_validator("edge_type", mode="before")
    @classmethod
    def normalize_edge_type(cls, v: Any) -> GraphEdgeType:
        if isinstance(v, str):
            return GraphEdgeType(v.upper())
        return v

    @field_validator("source", mode="before")
    @classmethod
    def normalize_source(cls, v: Any) -> GraphEdgeSource:
        if isinstance(v, str):
            return GraphEdgeSource(v.upper())
        return v

    @field_validator("criticality", mode="before")
    @classmethod
    def normalize_criticality(cls, v: Any) -> ServiceCriticality:
        if isinstance(v, str):
            return ServiceCriticality(v.lower())
        return v


class GraphEdgeCreate(GraphEdgeBase):
    pass


class GraphEdgeUpdate(BaseModel):
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    criticality: Optional[ServiceCriticality] = None
    is_stale: Optional[bool] = None
    metadata_json: Optional[Dict[str, Any]] = None

    @field_validator("criticality", mode="before")
    @classmethod
    def normalize_criticality(cls, v: Any) -> Optional[ServiceCriticality]:
        if isinstance(v, str):
            return ServiceCriticality(v.lower())
        return v


class GraphEdgeResponse(GraphEdgeBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TopologyGraphResponse(BaseModel):
    nodes: List[GraphNodeResponse] = []
    edges: List[GraphEdgeResponse] = []
    node_count: int = 0
    edge_count: int = 0
    nodes_by_type: Dict[str, int] = {}


class TraceSpanItem(BaseModel):
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    parent_span_id: Optional[str] = None
    service_name: str = Field(..., max_length=255)
    peer_service: Optional[str] = Field(None, max_length=255)
    http_method: Optional[str] = None
    http_url: Optional[str] = None
    http_status_code: Optional[int] = None
    duration_ms: Optional[float] = None
    is_error: Optional[bool] = False
    attributes: Optional[Dict[str, Any]] = None


class TraceSpanIngestRequest(BaseModel):
    spans: List[TraceSpanItem] = Field(..., min_length=1, max_length=500)


class ManifestImportRequest(BaseModel):
    manifest_type: str = Field("openapi", max_length=50)  # openapi, k8s, docker_compose
    service_id: Optional[uuid.UUID] = None
    content: Dict[str, Any] = {}


class BlastRadiusSimulationRequest(BaseModel):
    service_id: uuid.UUID
    environment_id: Optional[uuid.UUID] = None
    max_depth: int = Field(5, ge=1, le=15)


class BlastRadiusNodeImpact(BaseModel):
    service_id: str
    name: str
    tier: Optional[str] = None
    impact_type: str = "inferred"  # "observed" | "inferred"
    impact_level: str = "outage"   # "outage" | "degraded" | "unaffected"
    criticality: str = "hard"      # "hard" | "soft"
    distance: int = 1
    path: List[str] = []
    observed_signals: List[Dict[str, Any]] = []


class CustomerImpactEstimate(BaseModel):
    traffic_percent: Optional[float] = None
    user_percent: Optional[float] = None
    traffic_impact_mode: str = "estimated"  # "measured" | "estimated"
    traffic_confidence: str = "medium"      # "high" | "medium" | "low"
    calculation_basis: str = ""


class RootServiceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    tier: Optional[str] = None


class IncidentBlastRadiusReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    incident_id: uuid.UUID
    root_service: Optional[RootServiceSummary] = None
    version: int = 1
    is_current: bool = True
    calculated_at: datetime
    engine_version: str = "v1.0.0"
    telemetry_window_minutes: int = 30
    graph_snapshot_hash: Optional[str] = None

    direct_services: List[Dict[str, Any]] = []
    indirect_services: List[BlastRadiusNodeImpact] = []
    affected_endpoints: List[Dict[str, Any]] = []
    affected_repositories: List[Dict[str, Any]] = []
    affected_environments: List[Dict[str, Any]] = []
    affected_regions: List[Dict[str, Any]] = []
    customer_impact: CustomerImpactEstimate = Field(default_factory=CustomerImpactEstimate)
    criticality_summary: Dict[str, Any] = {}
    unknowns: List[str] = []
