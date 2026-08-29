"""Pydantic validation schemas for Phase 5 Autonomous Monitoring & Detection."""

import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


# ============================================================================
# INGESTION PAYLOADS
# ============================================================================

class PrometheusAlertItem(BaseModel):
    status: Optional[str] = "firing"
    labels: Dict[str, str] = Field(default_factory=dict)
    annotations: Dict[str, str] = Field(default_factory=dict)
    startsAt: Optional[str] = None
    endsAt: Optional[str] = None
    generatorURL: Optional[str] = None
    fingerprint: Optional[str] = None


class PrometheusAlertPayload(BaseModel):
    version: Optional[str] = "4"
    receiver: Optional[str] = None
    status: str = "firing"  # firing | resolved
    alerts: List[PrometheusAlertItem] = Field(default_factory=list)
    groupLabels: Dict[str, str] = Field(default_factory=dict)
    commonLabels: Dict[str, str] = Field(default_factory=dict)
    commonAnnotations: Dict[str, str] = Field(default_factory=dict)
    externalURL: Optional[str] = None


class SentryAlertPayload(BaseModel):
    event_id: Optional[str] = None
    project_slug: Optional[str] = None
    project_name: Optional[str] = None
    culprit: Optional[str] = None
    message: Optional[str] = None
    level: Optional[str] = "error"
    issue: Optional[Dict[str, Any]] = None
    exception: Optional[Dict[str, Any]] = None
    tags: Optional[List[List[str]]] = None
    environment: Optional[str] = None
    release: Optional[str] = None
    timestamp: Optional[str] = None


class GenericSignalPayload(BaseModel):
    service_id: Optional[uuid.UUID] = None
    service_name: Optional[str] = None
    environment_id: Optional[uuid.UUID] = None
    environment_name: Optional[str] = None
    region_id: Optional[uuid.UUID] = None
    region_code: Optional[str] = None

    signal_type: str = "ERROR_RATE"
    metric_name: Optional[str] = None
    metric_value: Optional[float] = None
    threshold_value: Optional[float] = None

    title: Optional[str] = None
    description: Optional[str] = None
    error_signature: Optional[str] = None
    event_id: Optional[str] = None
    observed_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None


# ============================================================================
# MANAGEMENT & QUERY RESPONSE SCHEMAS
# ============================================================================

class TelemetrySignalResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    provider: str
    provider_event_id: str
    signal_type: str
    rule_name: str

    service_id: Optional[uuid.UUID] = None
    service_name: Optional[str] = None
    environment_id: Optional[uuid.UUID] = None
    environment_name: Optional[str] = None
    region_id: Optional[uuid.UUID] = None
    region_code: Optional[str] = None

    metric_name: Optional[str] = None
    metric_value: Optional[float] = None
    threshold_value: Optional[float] = None

    fingerprint: str
    correlation_key: str
    title: str
    description: Optional[str] = None
    error_signature: Optional[str] = None
    raw_payload: Optional[Dict[str, Any]] = None

    status: str
    incident_id: Optional[uuid.UUID] = None
    incident_number: Optional[int] = None
    observed_at: datetime
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AlertRuleConfigDTO(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    rule_name: str
    is_enabled: bool
    threshold_value: Optional[float] = None
    window_minutes: int
    severity_override: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AlertRuleConfigUpdate(BaseModel):
    is_enabled: Optional[bool] = None
    threshold_value: Optional[float] = None
    window_minutes: Optional[int] = Field(None, ge=1, le=1440)
    severity_override: Optional[str] = None


class HealthCheckStatusResponse(BaseModel):
    id: uuid.UUID
    service_id: uuid.UUID
    service_name: str
    environment_id: uuid.UUID
    environment_name: str
    region_id: Optional[uuid.UUID] = None
    region_code: Optional[str] = None
    health_check_url: str
    is_healthy: Optional[bool] = None
    consecutive_failures: int = 0
    last_probe_status_code: Optional[int] = None
    last_probe_latency_ms: Optional[float] = None
    last_probe_error: Optional[str] = None
    last_probed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ProbeNowRequest(BaseModel):
    config_id: uuid.UUID
