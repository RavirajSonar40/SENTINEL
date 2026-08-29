"""REST API router for Phase 17: Security Incident Mode, Evidence Snapshots, Dual Sign-Off & Audit Chaining."""

from typing import List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import require_viewer, require_member, require_security_officer
from app.models.incident import (
    User,
    Organization,
    UserOrganizationMembership,
    SecurityCase,
    SecurityEvidenceSnapshot,
    SecurityContainmentAction,
)
from app.schemas.security_incident import (
    SecurityCaseCreate,
    SecurityCaseUpdate,
    SecurityCaseOut,
    SecurityEvidenceSnapshotOut,
    SecurityContainmentActionCreate,
    SecurityContainmentActionOut,
    SecurityContainmentApprovalRequest,
    SecurityContainmentExecuteRequest,
    SecurityForensicAuditEntryOut,
    SecurityAuditChainVerificationResponse,
)
from app.services.security_incident import (
    create_security_case,
    propose_containment_action,
    approve_containment_action,
    execute_containment_action,
    verify_forensic_audit_chain,
    resolve_security_case,
)

security_incident_router = APIRouter(prefix="/security", tags=["Security Incidents & Forensic Quarantine"])


# =============================================================================
# 1. SECURITY CASES
# =============================================================================

@security_incident_router.get("/cases", response_model=List[SecurityCaseOut])
def list_security_cases(
    category: Optional[str] = Query(None, description="Filter by category (CREDENTIAL_LEAK, SUSPICIOUS_AUTH, etc.)"),
    severity: Optional[str] = Query(None, description="Filter by severity (CRITICAL, HIGH, MEDIUM, LOW)"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (DETECTED, CONTAINING, CONTAINED, etc.)"),
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """List security cases for the active organization with optional filters (Viewer+)."""
    org, _ = context
    query = db.query(SecurityCase).filter(SecurityCase.organization_id == org.id)
    if category:
        query = query.filter(SecurityCase.category == category.upper())
    if severity:
        query = query.filter(SecurityCase.severity == severity.upper())
    if status_filter:
        query = query.filter(SecurityCase.status == status_filter.upper())

    cases = query.order_by(SecurityCase.created_at.desc()).all()
    results = []
    for c in cases:
        lead = db.query(User).filter(User.id == c.security_lead_id).first() if c.security_lead_id else None
        creator = db.query(User).filter(User.id == c.created_by_user_id).first() if c.created_by_user_id else None
        results.append(
            SecurityCaseOut(
                id=c.id,
                organization_id=c.organization_id,
                incident_id=c.incident_id,
                work_item_id=c.work_item_id,
                case_number=c.case_number,
                title=c.title,
                description=c.description,
                category=c.category,
                severity=c.severity,
                status=c.status,
                containment_status=c.containment_status,
                scope_summary_json=c.scope_summary_json,
                security_lead_id=c.security_lead_id,
                security_lead_name=lead.username if lead else None,
                created_by_user_id=c.created_by_user_id,
                created_by_name=creator.username if creator else None,
                resolution_summary=c.resolution_summary,
                contained_at=c.contained_at,
                resolved_at=c.resolved_at,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
        )
    return results


@security_incident_router.post("/cases", response_model=SecurityCaseOut, status_code=status.HTTP_201_CREATED)
def create_security_case_endpoint(
    req: SecurityCaseCreate,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_member),
    db: Session = Depends(get_db),
):
    """File a new security incident case, freeze immutable forensic snapshot, and create genesis audit entry (Member+)."""
    org, membership = context
    user = db.query(User).filter(User.id == membership.user_id).first()
    case = create_security_case(
        db=db,
        organization_id=org.id,
        req=req,
        created_by_user_id=membership.user_id,
        created_by_name=user.username if user else "Security Reporter",
    )
    return SecurityCaseOut(
        id=case.id,
        organization_id=case.organization_id,
        incident_id=case.incident_id,
        work_item_id=case.work_item_id,
        case_number=case.case_number,
        title=case.title,
        description=case.description,
        category=case.category,
        severity=case.severity,
        status=case.status,
        containment_status=case.containment_status,
        scope_summary_json=case.scope_summary_json,
        security_lead_id=case.security_lead_id,
        created_by_user_id=case.created_by_user_id,
        created_by_name=user.username if user else None,
        resolution_summary=case.resolution_summary,
        contained_at=case.contained_at,
        resolved_at=case.resolved_at,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


@security_incident_router.get("/cases/{case_id}", response_model=SecurityCaseOut)
def get_security_case_endpoint(
    case_id: UUID,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """Retrieve full details of a specific security incident case (Viewer+)."""
    org, _ = context
    case = db.query(SecurityCase).filter(
        SecurityCase.id == case_id,
        SecurityCase.organization_id == org.id,
    ).first()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Security case not found")

    lead = db.query(User).filter(User.id == case.security_lead_id).first() if case.security_lead_id else None
    creator = db.query(User).filter(User.id == case.created_by_user_id).first() if case.created_by_user_id else None

    return SecurityCaseOut(
        id=case.id,
        organization_id=case.organization_id,
        incident_id=case.incident_id,
        work_item_id=case.work_item_id,
        case_number=case.case_number,
        title=case.title,
        description=case.description,
        category=case.category,
        severity=case.severity,
        status=case.status,
        containment_status=case.containment_status,
        scope_summary_json=case.scope_summary_json,
        security_lead_id=case.security_lead_id,
        security_lead_name=lead.username if lead else None,
        created_by_user_id=case.created_by_user_id,
        created_by_name=creator.username if creator else None,
        resolution_summary=case.resolution_summary,
        contained_at=case.contained_at,
        resolved_at=case.resolved_at,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


@security_incident_router.get("/cases/{case_id}/evidence", response_model=SecurityEvidenceSnapshotOut)
def get_security_evidence_endpoint(
    case_id: UUID,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """Retrieve the immutable, cryptographically sealed evidence snapshot manifest (Viewer+)."""
    org, _ = context
    snapshot = db.query(SecurityEvidenceSnapshot).filter(
        SecurityEvidenceSnapshot.security_case_id == case_id,
        SecurityEvidenceSnapshot.organization_id == org.id,
    ).first()
    if not snapshot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence snapshot not found for this case")

    return SecurityEvidenceSnapshotOut.model_validate(snapshot)


@security_incident_router.get("/cases/{case_id}/audit-chain", response_model=SecurityAuditChainVerificationResponse)
def get_audit_chain_endpoint(
    case_id: UUID,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """Verify cryptographic hash integrity and retrieve all chained forensic audit entries (Viewer+)."""
    org, _ = context
    return verify_forensic_audit_chain(db=db, security_case_id=case_id, organization_id=org.id)


# =============================================================================
# 2. CONTAINMENT ACTIONS & DUAL SIGN-OFF
# =============================================================================

@security_incident_router.get("/cases/{case_id}/containment", response_model=List[SecurityContainmentActionOut])
def list_containment_actions_endpoint(
    case_id: UUID,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """List all proposed, approved, and executed containment actions for a case (Viewer+)."""
    org, _ = context
    actions = (
        db.query(SecurityContainmentAction)
        .filter(
            SecurityContainmentAction.security_case_id == case_id,
            SecurityContainmentAction.organization_id == org.id,
        )
        .order_by(SecurityContainmentAction.created_at.desc())
        .all()
    )
    results = []
    for a in actions:
        proposer = db.query(User).filter(User.id == a.proposed_by_user_id).first() if a.proposed_by_user_id else None
        app1 = db.query(User).filter(User.id == a.approver_1_user_id).first() if a.approver_1_user_id else None
        app2 = db.query(User).filter(User.id == a.approver_2_user_id).first() if a.approver_2_user_id else None
        results.append(
            SecurityContainmentActionOut(
                id=a.id,
                organization_id=a.organization_id,
                security_case_id=a.security_case_id,
                idempotency_key=a.idempotency_key,
                action_type=a.action_type,
                target_type=a.target_type,
                target_id=a.target_id,
                title=a.title,
                description=a.description,
                parameters_json=a.parameters_json,
                status=a.status,
                is_automated_blocked=a.is_automated_blocked,
                proposed_by_user_id=a.proposed_by_user_id,
                proposed_by_name=proposer.username if proposer else None,
                approver_1_user_id=a.approver_1_user_id,
                approver_1_name=app1.username if app1 else None,
                approver_1_at=a.approver_1_at,
                approver_2_user_id=a.approver_2_user_id,
                approver_2_name=app2.username if app2 else None,
                approver_2_at=a.approver_2_at,
                approval_expires_at=a.approval_expires_at,
                execution_output=a.execution_output,
                rollback_status=a.rollback_status,
                executed_at=a.executed_at,
                created_at=a.created_at,
            )
        )
    return results


@security_incident_router.post("/cases/{case_id}/containment", response_model=SecurityContainmentActionOut, status_code=status.HTTP_201_CREATED)
def propose_containment_action_endpoint(
    case_id: UUID,
    req: SecurityContainmentActionCreate,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_member),
    db: Session = Depends(get_db),
):
    """Propose a scoped containment action (Member+; execution blocked until dual sign-off)."""
    org, membership = context
    user = db.query(User).filter(User.id == membership.user_id).first()
    action = propose_containment_action(
        db=db,
        security_case_id=case_id,
        organization_id=org.id,
        req=req,
        proposed_by_user_id=membership.user_id,
        proposed_by_name=user.username if user else "Security Proposer",
    )
    return SecurityContainmentActionOut(
        id=action.id,
        organization_id=action.organization_id,
        security_case_id=action.security_case_id,
        idempotency_key=action.idempotency_key,
        action_type=action.action_type,
        target_type=action.target_type,
        target_id=action.target_id,
        title=action.title,
        description=action.description,
        parameters_json=action.parameters_json,
        status=action.status,
        is_automated_blocked=action.is_automated_blocked,
        proposed_by_user_id=action.proposed_by_user_id,
        proposed_by_name=user.username if user else None,
        rollback_status=action.rollback_status,
        created_at=action.created_at,
    )


@security_incident_router.post("/containment/{action_id}/approve", response_model=SecurityContainmentActionOut)
def approve_containment_action_endpoint(
    action_id: UUID,
    req: SecurityContainmentApprovalRequest,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_security_officer),
    db: Session = Depends(get_db),
):
    """Sign off on containment action (Dual-Signoff Gate: Requires 2 distinct Security Officer/Admin/Owner signatures)."""
    org, membership = context
    user = db.query(User).filter(User.id == membership.user_id).first()
    action = approve_containment_action(
        db=db,
        action_id=action_id,
        organization_id=org.id,
        approver_user_id=membership.user_id,
        approver_name=user.username if user else "Security Officer",
        comment=req.comment,
    )
    app1 = db.query(User).filter(User.id == action.approver_1_user_id).first() if action.approver_1_user_id else None
    app2 = db.query(User).filter(User.id == action.approver_2_user_id).first() if action.approver_2_user_id else None

    return SecurityContainmentActionOut(
        id=action.id,
        organization_id=action.organization_id,
        security_case_id=action.security_case_id,
        idempotency_key=action.idempotency_key,
        action_type=action.action_type,
        target_type=action.target_type,
        target_id=action.target_id,
        title=action.title,
        description=action.description,
        parameters_json=action.parameters_json,
        status=action.status,
        is_automated_blocked=action.is_automated_blocked,
        proposed_by_user_id=action.proposed_by_user_id,
        approver_1_user_id=action.approver_1_user_id,
        approver_1_name=app1.username if app1 else None,
        approver_1_at=action.approver_1_at,
        approver_2_user_id=action.approver_2_user_id,
        approver_2_name=app2.username if app2 else None,
        approver_2_at=action.approver_2_at,
        approval_expires_at=action.approval_expires_at,
        execution_output=action.execution_output,
        rollback_status=action.rollback_status,
        executed_at=action.executed_at,
        created_at=action.created_at,
    )


@security_incident_router.post("/containment/{action_id}/execute", response_model=SecurityContainmentActionOut)
def execute_containment_action_endpoint(
    action_id: UUID,
    req: SecurityContainmentExecuteRequest,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_security_officer),
    db: Session = Depends(get_db),
):
    """Execute dual-approved containment playbook action (Security Officer/Admin+)."""
    org, membership = context
    user = db.query(User).filter(User.id == membership.user_id).first()
    action = execute_containment_action(
        db=db,
        action_id=action_id,
        organization_id=org.id,
        executor_user_id=membership.user_id,
        executor_name=user.username if user else "Security Executor",
        dry_run=req.dry_run,
    )
    return SecurityContainmentActionOut.model_validate(action)


# =============================================================================
# 3. CASE RESOLUTION
# =============================================================================

@security_incident_router.post("/cases/{case_id}/resolve", response_model=SecurityCaseOut)
def resolve_security_case_endpoint(
    case_id: UUID,
    req: SecurityCaseUpdate,
    context: Tuple[Organization, UserOrganizationMembership] = Depends(require_security_officer),
    db: Session = Depends(get_db),
):
    """Resolve and close a security incident case with post-mortem hardening summary (Security Officer/Admin+)."""
    org, membership = context
    user = db.query(User).filter(User.id == membership.user_id).first()
    case = resolve_security_case(
        db=db,
        security_case_id=case_id,
        organization_id=org.id,
        user_id=membership.user_id,
        user_name=user.username if user else "Security Officer",
        resolution_summary=req.resolution_summary or "Security incident contained, reviewed, and closed.",
    )
    return SecurityCaseOut.model_validate(case)
