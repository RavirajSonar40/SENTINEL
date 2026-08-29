"""
REST API Endpoints for Phase 9: Evidence & Root-Cause Analysis.
"""
import uuid
import logging
from typing import List, Optional, Tuple
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import require_role
from app.models.incident import (
    Incident,
    Evidence,
    EvidenceSourceType,
    EvidenceCategoryType,
    EvidenceFamily,
    EvidenceTrustLevel,
    EvidenceVerificationStatus,
    Hypothesis,
    HypothesisStatus,
    Confidence,
    RootCause,
    Organization,
    UserOrganizationMembership,
    MembershipRole,
)
from app.schemas.evidence import (
    EvidenceItemCreate,
    EvidenceCorrectionRequest,
    EvidenceVerifyRequest,
    EvidenceItemResponse,
    EvidenceListResponse,
    HypothesisCreate,
    HypothesisTriageRequest,
    HypothesisResponse,
    HypothesisEvaluationResult,
    RootCauseResponse,
    RootCauseOverrideRequest,
)
from app.services.evidence_harvester import create_evidence_item, harvest_incident_evidence
from app.services.hypothesis_evaluator import (
    evaluate_incident_hypotheses,
    transition_hypothesis_status,
)

logger = logging.getLogger("sentinel.routes.evidence")

router = APIRouter(tags=["Evidence & Hypotheses"])


# ============================================================================
# 1. EVIDENCE LEDGER ENDPOINTS
# ============================================================================

@router.get("/incidents/{incident_id}/evidence", response_model=EvidenceListResponse)
def list_incident_evidence(
    incident_id: uuid.UUID,
    source_type: Optional[str] = Query(None),
    category_type: Optional[str] = Query(None),
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """List all immutable evidence items for an incident."""
    org, _ = auth_ctx
    incident = db.query(Incident).filter(
        Incident.organization_id == org.id,
        Incident.id == incident_id,
    ).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    query = db.query(Evidence).filter(
        Evidence.organization_id == org.id,
        Evidence.incident_id == incident.id,
    )

    if source_type:
        query = query.filter(Evidence.source_type == source_type)
    if category_type:
        query = query.filter(Evidence.category_type == category_type)

    items = query.order_by(Evidence.collected_at.asc()).all()

    facts_count = sum(1 for e in items if e.category_type in (EvidenceCategoryType.FACT, "fact"))
    inferences_count = sum(1 for e in items if e.category_type in (EvidenceCategoryType.INFERENCE, "inference"))
    conclusions_count = sum(1 for e in items if e.category_type in (EvidenceCategoryType.CONCLUSION, "conclusion"))
    families = sorted(list(set([e.evidence_family.value if hasattr(e.evidence_family, "value") else str(e.evidence_family) for e in items if e.evidence_family])))

    return EvidenceListResponse(
        incident_id=incident.id,
        total_count=len(items),
        facts_count=facts_count,
        inferences_count=inferences_count,
        conclusions_count=conclusions_count,
        distinct_families=families,
        items=items,
    )


@router.post("/incidents/{incident_id}/evidence", response_model=EvidenceItemResponse, status_code=status.HTTP_201_CREATED)
def submit_manual_evidence(
    incident_id: uuid.UUID,
    req: EvidenceItemCreate,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.OPERATOR)),
    db: Session = Depends(get_db),
):
    """Submit manual evidence item (append-only). Requires OPERATOR role."""
    org, membership = auth_ctx
    incident = db.query(Incident).filter(
        Incident.organization_id == org.id,
        Incident.id == incident_id,
    ).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    ev = create_evidence_item(
        db=db,
        organization_id=org.id,
        incident_id=incident.id,
        title=req.title,
        source_type=EvidenceSourceType.MANUAL,
        category_type=EvidenceCategoryType(req.category_type.lower()) if req.category_type else EvidenceCategoryType.FACT,
        content=req.content,
        summary=req.summary,
        service=req.service,
        environment=req.environment,
        region=req.region,
        repository=req.repository,
        commit_sha=req.commit_sha,
        file_path=req.file_path,
        line_start=req.line_start,
        line_end=req.line_end,
        source_url=req.source_url,
        observed_at=req.observed_at or datetime.now(timezone.utc),
        retrieval_method="manual_operator_submission",
        metadata=req.metadata,
        trust_level=EvidenceTrustLevel.UNVERIFIED,
        verification_status=EvidenceVerificationStatus.PENDING_REVIEW,
        submitted_by_user_id=membership.user_id,
    )
    if not ev:
        raise HTTPException(status_code=400, detail="Failed to create evidence item (capacity cap reached or invalid payload)")
    return ev


@router.post("/incidents/{incident_id}/evidence/{evidence_id}/verify", response_model=EvidenceItemResponse)
def verify_manual_evidence(
    incident_id: uuid.UUID,
    evidence_id: uuid.UUID,
    req: EvidenceVerifyRequest,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.OPERATOR)),
    db: Session = Depends(get_db),
):
    """Operator verification or rejection of manual evidence."""
    org, membership = auth_ctx
    ev = db.query(Evidence).filter(
        Evidence.organization_id == org.id,
        Evidence.incident_id == incident_id,
        Evidence.id == evidence_id,
    ).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence item not found")

    new_vstatus = EvidenceVerificationStatus.VERIFIED if req.status == "verified" else EvidenceVerificationStatus.REJECTED
    ev.verification_status = new_vstatus
    ev.trust_level = EvidenceTrustLevel.VERIFIED_BY_OPERATOR if new_vstatus == EvidenceVerificationStatus.VERIFIED else EvidenceTrustLevel.UNVERIFIED
    ev.verified_by_user_id = membership.user_id
    ev.verified_at = datetime.now(timezone.utc)
    if new_vstatus == EvidenceVerificationStatus.VERIFIED and ev.source_type == EvidenceSourceType.MANUAL:
        ev.evidence_family = EvidenceFamily.FAMILY_VERIFIED_HUMAN

    db.commit()
    db.refresh(ev)
    return ev


@router.post("/incidents/{incident_id}/evidence/correction", response_model=EvidenceItemResponse, status_code=status.HTTP_201_CREATED)
def submit_evidence_correction(
    incident_id: uuid.UUID,
    req: EvidenceCorrectionRequest,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.OPERATOR)),
    db: Session = Depends(get_db),
):
    """Submit an append-only correction that supersedes an existing evidence record."""
    org, membership = auth_ctx
    old_ev = db.query(Evidence).filter(
        Evidence.organization_id == org.id,
        Evidence.incident_id == incident_id,
        Evidence.id == req.supersedes_evidence_id,
    ).first()
    if not old_ev:
        raise HTTPException(status_code=404, detail="Evidence item to supersede not found")

    new_ev = create_evidence_item(
        db=db,
        organization_id=org.id,
        incident_id=incident_id,
        title=req.title,
        source_type=old_ev.source_type,
        category_type=old_ev.category_type,
        content=req.content or old_ev.content,
        summary=req.summary or old_ev.summary,
        service=old_ev.service,
        environment=old_ev.environment,
        region=old_ev.region,
        repository=old_ev.repository,
        commit_sha=old_ev.commit_sha,
        file_path=old_ev.file_path,
        observed_at=old_ev.observed_at,
        retrieval_method=f"correction_v{old_ev.version+1}",
        metadata={"correction_reason": req.correction_reason, "superseded_id": str(old_ev.id)},
        trust_level=EvidenceTrustLevel.VERIFIED_BY_OPERATOR,
        verification_status=EvidenceVerificationStatus.VERIFIED,
        submitted_by_user_id=membership.user_id,
    )
    if not new_ev:
        raise HTTPException(status_code=400, detail="Failed to create correction record")

    # Update superseded link
    old_ev.superseded_by_id = new_ev.id
    new_ev.version = old_ev.version + 1
    db.commit()
    db.refresh(new_ev)
    return new_ev


# ============================================================================
# 2. COMPETING HYPOTHESIS MATRIX ENDPOINTS
# ============================================================================

@router.get("/incidents/{incident_id}/hypotheses", response_model=List[HypothesisResponse])
def list_incident_hypotheses(
    incident_id: uuid.UUID,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """Get competing hypothesis matrix for an incident."""
    org, _ = auth_ctx
    incident = db.query(Incident).filter(
        Incident.organization_id == org.id,
        Incident.id == incident_id,
    ).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    hypotheses = db.query(Hypothesis).filter(
        Hypothesis.organization_id == org.id,
        Hypothesis.incident_id == incident.id,
    ).order_by(Hypothesis.created_at.asc()).all()

    return hypotheses


@router.post("/incidents/{incident_id}/hypotheses/evaluate", response_model=HypothesisEvaluationResult)
def evaluate_hypotheses_endpoint(
    incident_id: uuid.UUID,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.OPERATOR)),
    db: Session = Depends(get_db),
):
    """Trigger hypothesis competition and adversarial disproof evaluation. Requires OPERATOR role."""
    org, membership = auth_ctx
    res = evaluate_incident_hypotheses(db, org.id, incident_id, user_id=membership.user_id)
    return res


@router.post("/incidents/{incident_id}/hypotheses/{hypothesis_id}/triage", response_model=HypothesisResponse)
def triage_hypothesis_human_override(
    incident_id: uuid.UUID,
    hypothesis_id: uuid.UUID,
    req: HypothesisTriageRequest,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.OPERATOR)),
    db: Session = Depends(get_db),
):
    """Human operator triage override on a hypothesis. Sets human_triaged = True."""
    org, membership = auth_ctx
    hyp = db.query(Hypothesis).filter(
        Hypothesis.organization_id == org.id,
        Hypothesis.incident_id == incident_id,
        Hypothesis.id == hypothesis_id,
    ).first()
    if not hyp:
        raise HTTPException(status_code=404, detail="Hypothesis not found")

    target_status = HypothesisStatus(req.status.lower())
    transition_hypothesis_status(
        db=db,
        hypothesis=hyp,
        new_status=target_status,
        reason=req.triage_notes,
        user_id=membership.user_id,
        is_human=True,
    )
    return hyp


# ============================================================================
# 3. ROOT CAUSE & SAFE ABSTENTION ENDPOINTS
# ============================================================================

@router.get("/incidents/{incident_id}/root-cause", response_model=RootCauseResponse)
def get_incident_root_cause(
    incident_id: uuid.UUID,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """Get the current root cause analysis or safe abstention report for an incident."""
    org, _ = auth_ctx
    incident = db.query(Incident).filter(
        Incident.organization_id == org.id,
        Incident.id == incident_id,
    ).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    rc = db.query(RootCause).filter(
        RootCause.organization_id == org.id,
        RootCause.incident_id == incident.id,
        RootCause.is_current == True,
    ).first()
    if not rc:
        raise HTTPException(status_code=404, detail="Root cause analysis has not been calculated for this incident yet")
    return rc


@router.post("/incidents/{incident_id}/root-cause/override", response_model=RootCauseResponse)
def override_incident_root_cause(
    incident_id: uuid.UUID,
    req: RootCauseOverrideRequest,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.OPERATOR)),
    db: Session = Depends(get_db),
):
    """Human operator override of root cause analysis. Preserved against automated recalculation."""
    org, membership = auth_ctx
    incident = db.query(Incident).filter(
        Incident.organization_id == org.id,
        Incident.id == incident_id,
    ).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    prev_rcs = db.query(RootCause).filter(
        RootCause.organization_id == org.id,
        RootCause.incident_id == incident.id,
    ).all()
    prev_version = max([r.evaluation_version for r in prev_rcs], default=0)
    for r in prev_rcs:
        r.is_current = False
    db.commit()

    override_rc = RootCause(
        organization_id=org.id,
        incident_id=incident.id,
        summary=req.summary,
        affected_component=req.affected_component or incident.service_name,
        causal_explanation=req.causal_explanation,
        confidence=Confidence.HIGH,
        supporting_evidence_ids=[],
        contradicting_evidence_ids=[],
        evidence_sources_count=0,
        distinct_families_count=1,
        disproof_summary=f"Human Operator Override: {req.override_notes}",
        abstained=False,
        evaluation_version=prev_version + 1,
        is_current=True,
        human_overridden=True,
        human_override_notes=req.override_notes,
        overridden_by_user_id=membership.user_id,
    )
    db.add(override_rc)
    db.commit()
    db.refresh(override_rc)
    return override_rc
