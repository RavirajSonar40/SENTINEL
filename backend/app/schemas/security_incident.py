"""Pydantic schemas for Phase 17: Security Incident Mode & Forensic Containment."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# 1. SECURITY CASES
# =============================================================================

class SecurityCaseCreate(BaseModel):
    title: str = Field(..., max_length=255, description="Summary title of the security incident")
    description: Optional[str] = Field(None, description="Detailed security incident report and telemetry context")
    category: str = Field("CUSTOM", description="CREDENTIAL_LEAK, SUSPICIOUS_AUTH, PRIVILEGE_ESCALATION, UNUSUAL_DATA_ACCESS, VULNERABLE_DEPENDENCY, MALWARE_SUSPECTED, CUSTOM")
    severity: str = Field("HIGH", description="CRITICAL, HIGH, MEDIUM, LOW")
    incident_id: Optional[UUID] = Field(None, description="Associated Operational Incident ID if linked")
    work_item_id: Optional[UUID] = Field(None, description="Associated WorkItem ID if linked")
    scope_summary_json: Optional[Dict[str, Any]] = Field(None, description="Initial suspected affected services, repos, tokens")


class SecurityCaseUpdate(BaseModel):
    status: Optional[str] = Field(None, description="DETECTED, CONTAINING, CONTAINED, INVESTIGATING, REMEDIATING, RESOLVED, CLOSED")
    severity: Optional[str] = Field(None, description="CRITICAL, HIGH, MEDIUM, LOW")
    resolution_summary: Optional[str] = Field(None, description="Post-incident root cause and security hardening summary")
    security_lead_id: Optional[UUID] = Field(None, description="Assigned Security Lead User ID")


class SecurityCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    incident_id: Optional[UUID] = None
    work_item_id: Optional[UUID] = None
    case_number: str
    title: str
    description: Optional[str] = None
    category: str
    severity: str
    status: str
    containment_status: str
    scope_summary_json: Optional[Dict[str, Any]] = None
    security_lead_id: Optional[UUID] = None
    security_lead_name: Optional[str] = None
    created_by_user_id: Optional[UUID] = None
    created_by_name: Optional[str] = None
    resolution_summary: Optional[str] = None
    contained_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


# =============================================================================
# 2. EVIDENCE SNAPSHOT MANIFEST
# =============================================================================

class SecurityEvidenceSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    security_case_id: UUID
    manifest_hash: str
    manifest_json: Dict[str, Any]
    completeness_status: str
    captured_by_user_id: Optional[UUID] = None
    sealed_at: datetime


# =============================================================================
# 3. CONTAINMENT ACTIONS & DUAL SIGN-OFF
# =============================================================================

class SecurityContainmentActionCreate(BaseModel):
    action_type: str = Field(..., description="REVOKE_CREDENTIAL, QUARANTINE_SERVICE, BLOCK_IDENTITY, LOCK_DEPENDENCY, ROTATE_SECRET, CUSTOM_PLAYBOOK")
    target_type: str = Field(..., description="service, user, secret, repository, network_ip")
    target_id: str = Field(..., max_length=255, description="Unique ID / name / ARN of target entity")
    title: str = Field(..., max_length=255, description="Action title (e.g. Invalidate API Key and Rotate JWT)")
    description: Optional[str] = Field(None, description="Action rationale and execution details")
    parameters_json: Optional[Dict[str, Any]] = Field(None, description="Action execution arguments (sensitive values auto-redacted)")
    idempotency_key: Optional[str] = Field(None, max_length=100, description="Idempotency key to prevent duplicate action creation")


class SecurityContainmentActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    security_case_id: UUID
    idempotency_key: Optional[str] = None
    action_type: str
    target_type: str
    target_id: str
    title: str
    description: Optional[str] = None
    parameters_json: Optional[Dict[str, Any]] = None
    status: str
    is_automated_blocked: bool
    proposed_by_user_id: Optional[UUID] = None
    proposed_by_name: Optional[str] = None
    approver_1_user_id: Optional[UUID] = None
    approver_1_name: Optional[str] = None
    approver_1_at: Optional[datetime] = None
    approver_2_user_id: Optional[UUID] = None
    approver_2_name: Optional[str] = None
    approver_2_at: Optional[datetime] = None
    approval_expires_at: Optional[datetime] = None
    execution_output: Optional[str] = None
    rollback_status: str
    executed_at: Optional[datetime] = None
    created_at: datetime


class SecurityContainmentApprovalRequest(BaseModel):
    comment: Optional[str] = Field(None, description="Approval justification notes")


class SecurityContainmentExecuteRequest(BaseModel):
    dry_run: bool = Field(False, description="Simulate action execution without applying mutations")


# =============================================================================
# 4. FORENSIC AUDIT CHAIN
# =============================================================================

class SecurityForensicAuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    security_case_id: UUID
    sequence_number: int
    event_type: str
    actor_id: Optional[UUID] = None
    actor_name: Optional[str] = None
    payload_json: Optional[Dict[str, Any]] = None
    previous_hash: str
    current_hash: str
    timestamp: datetime


class SecurityAuditChainVerificationResponse(BaseModel):
    is_valid: bool
    total_entries: int
    entries: List[SecurityForensicAuditEntryOut]
    broken_link_sequence: Optional[int] = None
    message: str
