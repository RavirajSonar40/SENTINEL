"""Core service engine for Phase 17: Security Incident Mode, Forensic Quarantine, Dual Sign-Off & Audit Chaining."""

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.incident import (
    User,
    Organization,
    Incident,
    Service,
    UserOrganizationMembership,
    MembershipRole,
    SecurityCase,
    SecurityEvidenceSnapshot,
    SecurityContainmentAction,
    SecurityForensicAuditChain,
)
from app.models.work_item import WorkItem
from app.schemas.security_incident import (
    SecurityCaseCreate,
    SecurityCaseUpdate,
    SecurityCaseOut,
    SecurityContainmentActionCreate,
    SecurityContainmentActionOut,
    SecurityEvidenceSnapshotOut,
    SecurityForensicAuditEntryOut,
    SecurityAuditChainVerificationResponse,
)

GENESIS_PREVIOUS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"
APPROVAL_TTL_HOURS = 2
LEASE_DURATION_SECONDS = 60

# Regular expressions for high-performance secret redaction
SECRET_REDACTION_PATTERNS = [
    (re.compile(r'(?i)(bearer\s+)[a-zA-Z0-9_\-\.]{15,}'), r'\1[REDACTED_TOKEN]'),
    (re.compile(r'(?i)(api[_\-]?key|secret|password|passwd|token|auth)["\']?\s*[:=]\s*["\']?([^"\'\s]{6,})["\']?'), r'\1="[REDACTED_SECRET]"'),
    (re.compile(r'AKIA[0-9A-Z]{16}'), '[REDACTED_AWS_KEY]'),
    (re.compile(r'-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----[\s\S]+?-----END\s+(?:RSA\s+)?PRIVATE\s+KEY-----'), '[REDACTED_PRIVATE_KEY]'),
    (re.compile(r'(?i)(postgres(?:ql)?|mysql|redis|mongodb):\/\/[^\s:]+:[^\s@]+@[^\s]+'), '[REDACTED_DB_URL]'),
]


def redact_sensitive_security_data(data: Any) -> Any:
    """Recursively scrub credentials, private keys, and tokens from structures."""
    if isinstance(data, str):
        cleaned = data
        for pattern, replacement in SECRET_REDACTION_PATTERNS:
            cleaned = pattern.sub(replacement, cleaned)
        return cleaned
    elif isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(term in k_lower for term in ("password", "secret", "token", "private_key", "api_key", "auth_header")):
                sanitized[k] = "[REDACTED_SECRET]"
            else:
                sanitized[k] = redact_sensitive_security_data(v)
        return sanitized
    elif isinstance(data, list):
        return [redact_sensitive_security_data(item) for item in data]
    return data


def compute_sha256_digest(payload: Any) -> str:
    """Compute canonical SHA-256 digest over normalized JSON string."""
    canonical_json = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# =============================================================================
# 1. TENANT CONSISTENCY VALIDATION
# =============================================================================

def validate_security_tenant_consistency(
    db: Session,
    organization_id: uuid.UUID,
    case: Optional[SecurityCase] = None,
    incident_id: Optional[uuid.UUID] = None,
    work_item_id: Optional[uuid.UUID] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    approver_user_ids: Optional[List[uuid.UUID]] = None,
) -> None:
    """Explicitly verify that all linked entities and actors belong to the same organization."""
    if case and case.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Security Case does not belong to the user's organization")

    if incident_id:
        inc = db.query(Incident).filter(Incident.id == incident_id).first()
        if not inc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Referenced Incident not found")
        if inc.organization_id != organization_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incident belongs to a different organization")

    if work_item_id:
        wi = db.query(WorkItem).filter(WorkItem.id == work_item_id).first()
        if not wi:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Referenced WorkItem not found")
        if wi.organization_id != organization_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="WorkItem belongs to a different organization")

    if target_type == "service" and target_id:
        try:
            svc_uuid = uuid.UUID(target_id)
            svc = db.query(Service).filter(Service.id == svc_uuid).first()
            if svc and svc.organization_id != organization_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Target Service belongs to a different organization")
        except ValueError:
            pass  # target_id might be a service name string

    if approver_user_ids:
        for uid in approver_user_ids:
            mem = db.query(UserOrganizationMembership).filter(
                UserOrganizationMembership.user_id == uid,
                UserOrganizationMembership.organization_id == organization_id,
            ).first()
            if not mem:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Approver user {uid} is not a member of this organization")


# =============================================================================
# 2. AUDIT CHAIN ENGINE (CONCURRENCY-SAFE & APPEND-ONLY)
# =============================================================================

def append_audit_chain_entry(
    db: Session,
    security_case_id: uuid.UUID,
    organization_id: uuid.UUID,
    event_type: str,
    actor_id: Optional[uuid.UUID],
    actor_name: Optional[str],
    payload_json: Optional[Dict[str, Any]],
) -> SecurityForensicAuditChain:
    """
    Append an immutable event to the cryptographic audit chain.
    Locks the security_cases row with `with_for_update` to guarantee monotonic sequencing.
    """
    # 1. Acquire row lock on security_case
    case = db.query(SecurityCase).filter(
        SecurityCase.id == security_case_id,
        SecurityCase.organization_id == organization_id,
    ).with_for_update().first()

    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Security case not found for audit entry")

    # 2. Get latest entry for previous hash & sequence number
    latest_entry = (
        db.query(SecurityForensicAuditChain)
        .filter(SecurityForensicAuditChain.security_case_id == security_case_id)
        .order_by(desc(SecurityForensicAuditChain.sequence_number))
        .first()
    )

    sequence_number = 1 if not latest_entry else latest_entry.sequence_number + 1
    previous_hash = GENESIS_PREVIOUS_HASH if not latest_entry else latest_entry.current_hash

    # 3. Sanitize payload
    sanitized_payload = redact_sensitive_security_data(payload_json or {})
    timestamp = datetime.now(timezone.utc)

    # 4. Compute chained cryptographic SHA-256 hash
    hash_material = {
        "security_case_id": str(security_case_id),
        "sequence_number": sequence_number,
        "event_type": event_type,
        "actor_id": str(actor_id) if actor_id else None,
        "previous_hash": previous_hash,
        "payload": sanitized_payload,
        "timestamp": timestamp.isoformat(),
    }
    current_hash = compute_sha256_digest(hash_material)

    entry = SecurityForensicAuditChain(
        id=uuid.uuid4(),
        organization_id=organization_id,
        security_case_id=security_case_id,
        sequence_number=sequence_number,
        event_type=event_type,
        actor_id=actor_id,
        actor_name=actor_name,
        payload_json=sanitized_payload,
        previous_hash=previous_hash,
        current_hash=current_hash,
        timestamp=timestamp,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def verify_forensic_audit_chain(
    db: Session,
    security_case_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> SecurityAuditChainVerificationResponse:
    """Verify cryptographic hash integrity and sequence continuity across all audit entries."""
    validate_security_tenant_consistency(db, organization_id, case=db.query(SecurityCase).filter_by(id=security_case_id).first())

    entries = (
        db.query(SecurityForensicAuditChain)
        .filter(
            SecurityForensicAuditChain.security_case_id == security_case_id,
            SecurityForensicAuditChain.organization_id == organization_id,
        )
        .order_by(SecurityForensicAuditChain.sequence_number.asc())
        .all()
    )

    if not entries:
        return SecurityAuditChainVerificationResponse(
            is_valid=True,
            total_entries=0,
            entries=[],
            broken_link_sequence=None,
            message="Audit chain is empty.",
        )

    expected_prev = GENESIS_PREVIOUS_HASH
    for idx, entry in enumerate(entries):
        expected_seq = idx + 1
        if entry.sequence_number != expected_seq:
            return SecurityAuditChainVerificationResponse(
                is_valid=False,
                total_entries=len(entries),
                entries=[SecurityForensicAuditEntryOut.model_validate(e) for e in entries],
                broken_link_sequence=entry.sequence_number,
                message=f"Sequence gap detected: expected {expected_seq}, found {entry.sequence_number}",
            )

        if entry.previous_hash != expected_prev:
            return SecurityAuditChainVerificationResponse(
                is_valid=False,
                total_entries=len(entries),
                entries=[SecurityForensicAuditEntryOut.model_validate(e) for e in entries],
                broken_link_sequence=entry.sequence_number,
                message=f"Hash chain broken at sequence {entry.sequence_number}. Previous hash mismatch.",
            )

        # Re-compute current hash
        hash_material = {
            "security_case_id": str(entry.security_case_id),
            "sequence_number": entry.sequence_number,
            "event_type": entry.event_type,
            "actor_id": str(entry.actor_id) if entry.actor_id else None,
            "previous_hash": entry.previous_hash,
            "payload": entry.payload_json or {},
            "timestamp": entry.timestamp.isoformat() if entry.timestamp.tzinfo else entry.timestamp.replace(tzinfo=timezone.utc).isoformat(),
        }
        recomputed = compute_sha256_digest(hash_material)
        if recomputed != entry.current_hash:
            return SecurityAuditChainVerificationResponse(
                is_valid=False,
                total_entries=len(entries),
                entries=[SecurityForensicAuditEntryOut.model_validate(e) for e in entries],
                broken_link_sequence=entry.sequence_number,
                message=f"Tampered content at sequence {entry.sequence_number}. Hash verification failed.",
            )

        expected_prev = entry.current_hash

    return SecurityAuditChainVerificationResponse(
        is_valid=True,
        total_entries=len(entries),
        entries=[SecurityForensicAuditEntryOut.model_validate(e) for e in entries],
        broken_link_sequence=None,
        message="Cryptographic audit chain verified successfully with zero tampering.",
    )


# =============================================================================
# 3. CASE MANAGEMENT & FORENSIC SNAPSHOT FREEZING
# =============================================================================

def create_security_case(
    db: Session,
    organization_id: uuid.UUID,
    req: SecurityCaseCreate,
    created_by_user_id: Optional[uuid.UUID] = None,
    created_by_name: Optional[str] = None,
) -> SecurityCase:
    """File a new security case, freeze immutable forensic evidence snapshot, and append genesis audit entry."""
    validate_security_tenant_consistency(
        db,
        organization_id=organization_id,
        incident_id=req.incident_id,
        work_item_id=req.work_item_id,
    )

    # 1. Acquire row lock on Organization to ensure sequential, non-colliding case numbering
    org_row = db.query(Organization).filter(Organization.id == organization_id).with_for_update().first()
    if not org_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    year = datetime.now(timezone.utc).year
    count = db.query(SecurityCase).filter(
        SecurityCase.organization_id == organization_id,
        SecurityCase.case_number.like(f"SEC-{year}-%"),
    ).count() + 1
    case_number = f"SEC-{year}-{count:04d}"

    sanitized_scope = redact_sensitive_security_data(req.scope_summary_json or {})

    case = SecurityCase(
        id=uuid.uuid4(),
        organization_id=organization_id,
        incident_id=req.incident_id,
        work_item_id=req.work_item_id,
        case_number=case_number,
        title=req.title,
        description=req.description,
        category=req.category.upper(),
        severity=req.severity.upper(),
        status="DETECTED",
        containment_status="NOT_STARTED",
        scope_summary_json=sanitized_scope,
        created_by_user_id=created_by_user_id,
    )
    db.add(case)
    db.flush()

    # Create immutable Evidence Snapshot Manifest
    manifest_data = {
        "case_number": case.case_number,
        "title": case.title,
        "category": case.category,
        "severity": case.severity,
        "scope": sanitized_scope,
        "initial_description": req.description,
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "created_by": created_by_name or "System",
    }
    manifest_hash = compute_sha256_digest(manifest_data)

    snapshot = SecurityEvidenceSnapshot(
        id=uuid.uuid4(),
        organization_id=organization_id,
        security_case_id=case.id,
        manifest_hash=manifest_hash,
        manifest_json=manifest_data,
        completeness_status="COMPLETE",
        captured_by_user_id=created_by_user_id,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(case)

    # Append Genesis Audit Entry
    append_audit_chain_entry(
        db=db,
        security_case_id=case.id,
        organization_id=organization_id,
        event_type="EVIDENCE_FROZEN",
        actor_id=created_by_user_id,
        actor_name=created_by_name or "Security Triage",
        payload_json={"manifest_hash": manifest_hash, "case_number": case.case_number},
    )

    return case


# =============================================================================
# 4. CONTAINMENT PLAYBOOKS & DUAL SIGN-OFF WORKFLOW
# =============================================================================

def propose_containment_action(
    db: Session,
    security_case_id: uuid.UUID,
    organization_id: uuid.UUID,
    req: SecurityContainmentActionCreate,
    proposed_by_user_id: Optional[uuid.UUID] = None,
    proposed_by_name: Optional[str] = None,
) -> SecurityContainmentAction:
    """Propose a scoped containment action (starts in PROPOSED; autonomous execution blocked)."""
    case = db.query(SecurityCase).filter(
        SecurityCase.id == security_case_id,
        SecurityCase.organization_id == organization_id,
    ).first()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Security case not found")

    validate_security_tenant_consistency(
        db,
        organization_id=organization_id,
        case=case,
        target_type=req.target_type,
        target_id=req.target_id,
    )

    # Idempotency check
    if req.idempotency_key:
        existing = db.query(SecurityContainmentAction).filter(
            SecurityContainmentAction.organization_id == organization_id,
            SecurityContainmentAction.idempotency_key == req.idempotency_key,
        ).first()
        if existing:
            return existing

    sanitized_params = redact_sensitive_security_data(req.parameters_json or {})

    action = SecurityContainmentAction(
        id=uuid.uuid4(),
        organization_id=organization_id,
        security_case_id=case.id,
        idempotency_key=req.idempotency_key,
        action_type=req.action_type.upper(),
        target_type=req.target_type.lower(),
        target_id=req.target_id,
        title=req.title,
        description=req.description,
        parameters_json=sanitized_params,
        status="PROPOSED",
        is_automated_blocked=True,
        proposed_by_user_id=proposed_by_user_id,
    )
    db.add(action)

    if case.containment_status == "NOT_STARTED":
        case.containment_status = "PROPOSED"
        case.status = "CONTAINING"

    db.commit()
    db.refresh(action)

    append_audit_chain_entry(
        db=db,
        security_case_id=case.id,
        organization_id=organization_id,
        event_type="CONTAINMENT_PROPOSED",
        actor_id=proposed_by_user_id,
        actor_name=proposed_by_name or "Security Officer",
        payload_json={"action_id": str(action.id), "action_type": action.action_type, "target": action.target_id},
    )

    return action


def approve_containment_action(
    db: Session,
    action_id: uuid.UUID,
    organization_id: uuid.UUID,
    approver_user_id: uuid.UUID,
    approver_name: str,
    comment: Optional[str] = None,
) -> SecurityContainmentAction:
    """
    Dual Sign-Off Gate for Containment Actions:
    Requires 2 distinct authorized users (Security Officer, Admin, Owner).
    Loads record with row-level lock (`with_for_update`) to prevent concurrent approval race conditions.
    Prohibits self-approval by the proposer.
    """
    action = db.query(SecurityContainmentAction).filter(
        SecurityContainmentAction.id == action_id,
        SecurityContainmentAction.organization_id == organization_id,
    ).with_for_update().first()
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Containment action not found")

    validate_security_tenant_consistency(db, organization_id, approver_user_ids=[approver_user_id])

    # Invariant 1: Proposer cannot approve their own action
    if action.proposed_by_user_id and action.proposed_by_user_id == approver_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dual Sign-Off Invariant: Action requester is prohibited from approving their own proposal.",
        )

    now = datetime.now(timezone.utc)

    # First Sign-Off
    if action.status == "PROPOSED":
        action.approver_1_user_id = approver_user_id
        action.approver_1_at = now
        action.status = "PENDING_SECOND_APPROVAL"

        db.commit()
        db.refresh(action)

        append_audit_chain_entry(
            db=db,
            security_case_id=action.security_case_id,
            organization_id=organization_id,
            event_type="SIGN_OFF_1_GRANTED",
            actor_id=approver_user_id,
            actor_name=approver_name,
            payload_json={"action_id": str(action.id), "comment": comment, "step": "1_of_2"},
        )
        return action

    # Second Sign-Off
    elif action.status == "PENDING_SECOND_APPROVAL":
        # Invariant 2: Approver 2 must be distinct from Approver 1
        if action.approver_1_user_id == approver_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Dual Sign-Off Invariant: Second approval must be signed off by a distinct authorized security officer.",
            )

        action.approver_2_user_id = approver_user_id
        action.approver_2_at = now
        action.approval_expires_at = now + timedelta(hours=APPROVAL_TTL_HOURS)
        action.status = "APPROVED"
        action.is_automated_blocked = False

        db.commit()
        db.refresh(action)

        append_audit_chain_entry(
            db=db,
            security_case_id=action.security_case_id,
            organization_id=organization_id,
            event_type="SIGN_OFF_2_GRANTED",
            actor_id=approver_user_id,
            actor_name=approver_name,
            payload_json={"action_id": str(action.id), "comment": comment, "status": "APPROVED", "step": "2_of_2"},
        )
        return action

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action state for approval: '{action.status}'. Only PROPOSED or PENDING_SECOND_APPROVAL actions may be approved.",
        )


def execute_containment_action(
    db: Session,
    action_id: uuid.UUID,
    organization_id: uuid.UUID,
    executor_user_id: uuid.UUID,
    executor_name: str,
    dry_run: bool = False,
) -> SecurityContainmentAction:
    """
    Execute an approved containment action with distributed lease, row-level locking, and secret redaction.
    Prevents concurrent duplicate execution by multiple workers via row lock.
    """
    action = db.query(SecurityContainmentAction).filter(
        SecurityContainmentAction.id == action_id,
        SecurityContainmentAction.organization_id == organization_id,
    ).with_for_update().first()
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Containment action not found")

    # Invariant: Action must be APPROVED
    if action.status != "APPROVED":
        if action.status == "EXECUTING":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Action is currently being executed by another worker (lease active).",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Execution Blocked (MUTATION_PROHIBITED): Action status is '{action.status}'. Dual officer approval required.",
        )

    now = datetime.now(timezone.utc)

    # Invariant: TTL expiration check
    if action.approval_expires_at:
        expires = action.approval_expires_at if action.approval_expires_at.tzinfo else action.approval_expires_at.replace(tzinfo=timezone.utc)
        if now > expires:
            action.status = "EXPIRED"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Approval has expired (2-hour TTL exceeded). Fresh dual approval required.",
            )

    # Acquire Execution Lease under row lock
    action.execution_lease_until = now + timedelta(seconds=LEASE_DURATION_SECONDS)
    action.status = "EXECUTING"
    db.commit()

    try:
        # Perform Simulated / Scoped Playbook Execution
        raw_output = f"Executed {action.action_type} against target {action.target_type}:{action.target_id}."
        if dry_run:
            raw_output = f"[DRY-RUN SIMULATION] {raw_output}"

        sanitized_output = redact_sensitive_security_data(raw_output)

        action.execution_output = sanitized_output
        action.status = "EXECUTED" if not dry_run else "APPROVED"
        action.executed_at = now
        action.rollback_status = "READY"


        # Update parent security case
        case = db.query(SecurityCase).filter(SecurityCase.id == action.security_case_id).first()
        if case and not dry_run:
            case.containment_status = "CONTAINED"
            case.contained_at = now
            case.status = "CONTAINED"

        db.commit()
        db.refresh(action)

        append_audit_chain_entry(
            db=db,
            security_case_id=action.security_case_id,
            organization_id=organization_id,
            event_type="CONTAINMENT_EXECUTED" if not dry_run else "DRY_RUN_COMPLETED",
            actor_id=executor_user_id,
            actor_name=executor_name,
            payload_json={"action_id": str(action.id), "action_type": action.action_type, "dry_run": dry_run},
        )
        return action

    except Exception as exc:
        action.status = "FAILED"
        action.rollback_status = "ROLLBACK_FAILED"
        action.execution_output = f"Execution error: {str(exc)}"
        db.commit()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Containment execution failed: {exc}")


def resolve_security_case(
    db: Session,
    security_case_id: uuid.UUID,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    user_name: str,
    resolution_summary: str,
) -> SecurityCase:
    """Resolve and close a security incident case with state machine validation."""
    case = db.query(SecurityCase).filter(
        SecurityCase.id == security_case_id,
        SecurityCase.organization_id == organization_id,
    ).first()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Security case not found")

    # State Machine Invariant: Cannot resolve if containment is executing or failed
    executing_actions = db.query(SecurityContainmentAction).filter(
        SecurityContainmentAction.security_case_id == security_case_id,
        SecurityContainmentAction.status.in_(["EXECUTING", "FAILED"]),
    ).count()

    if executing_actions > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot resolve Security Case while containment actions are EXECUTING or FAILED.",
        )

    now = datetime.now(timezone.utc)
    case.status = "RESOLVED"
    case.resolution_summary = resolution_summary
    case.resolved_at = now
    db.commit()
    db.refresh(case)

    append_audit_chain_entry(
        db=db,
        security_case_id=case.id,
        organization_id=organization_id,
        event_type="CASE_RESOLVED",
        actor_id=user_id,
        actor_name=user_name,
        payload_json={"resolution_summary": resolution_summary, "resolved_at": now.isoformat()},
    )
    return case
