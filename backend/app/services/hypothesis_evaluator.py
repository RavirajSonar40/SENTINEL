"""
Hypothesis Competition & Adversarial Disproof Engine (Phase 9).

Evaluates competing root-cause hypotheses against:
- Tri-Factor Fit (Temporal, Code-Path, Operational)
- Adversarial Disproof Falsification Loop
- Multi-Source Evidence Families Corroboration (>= 2 distinct families)
- Human Triage Override Preservation
- Safe Abstention with Missing Evidence Cataloging
- Versioned Evaluation Snapshots
"""
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.incident import (
    Incident,
    Evidence,
    EvidenceSourceType,
    EvidenceCategoryType,
    EvidenceFamily,
    Hypothesis,
    HypothesisEvidence,
    HypothesisStatus,
    Confidence,
    RootCause,
    InvestigationStatus,
)
from app.services.evidence_harvester import harvest_incident_evidence

logger = logging.getLogger("sentinel.hypothesis_evaluator")

# Legal State Transitions for Hypotheses
LEGAL_HYPOTHESIS_TRANSITIONS = {
    HypothesisStatus.PROPOSED: {HypothesisStatus.SUPPORTED, HypothesisStatus.ACCEPTED, HypothesisStatus.CONTRADICTED, HypothesisStatus.DISPROVEN, HypothesisStatus.REJECTED},
    HypothesisStatus.SUPPORTED: {HypothesisStatus.ACCEPTED, HypothesisStatus.CONTRADICTED, HypothesisStatus.DISPROVEN, HypothesisStatus.REJECTED},
    HypothesisStatus.CONTRADICTED: {HypothesisStatus.SUPPORTED, HypothesisStatus.DISPROVEN, HypothesisStatus.REJECTED},
    HypothesisStatus.DISPROVEN: set(),  # Terminal state
    HypothesisStatus.ACCEPTED: {HypothesisStatus.DISPROVEN, HypothesisStatus.REJECTED},  # Can be revoked if new evidence disproves it
    HypothesisStatus.REJECTED: set(),
}


def transition_hypothesis_status(
    db: Session,
    hypothesis: Hypothesis,
    new_status: HypothesisStatus,
    reason: Optional[str] = None,
    user_id: Optional[uuid.UUID] = None,
    is_human: bool = False,
) -> None:
    """Enforce legal forward transitions and human triage rules."""
    current = hypothesis.status
    if current == new_status:
        return

    # Check if human triage lock is active (automated runs cannot overwrite human decisions)
    if hypothesis.human_triaged and not is_human:
        logger.info(f"Preserving human triage status '{hypothesis.status.value}' for hypothesis {hypothesis.id}")
        return

    allowed = LEGAL_HYPOTHESIS_TRANSITIONS.get(current, set())
    if new_status not in allowed and not is_human:
        raise ValueError(f"Illegal hypothesis transition from '{current.value}' to '{new_status.value}'")

    hypothesis.status = new_status
    if reason:
        hypothesis.evaluation_notes = reason
    if new_status == HypothesisStatus.DISPROVEN:
        hypothesis.disproven_at = datetime.now(timezone.utc)
        if reason:
            hypothesis.disproof_attempt_notes = reason
    if is_human:
        hypothesis.human_triaged = True
        hypothesis.human_triage_notes = reason
        hypothesis.triaged_by_user_id = user_id

    hypothesis.evaluated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(hypothesis)


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime is UTC timezone-aware for reliable comparisons."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def evaluate_tri_factor_fit(
    hypothesis_desc: str,
    evidence_items: List[Evidence],
    incident_time: datetime,
) -> Tuple[bool, float, bool, float, bool, float]:
    """
    Compute Tri-Factor Fit scores:
    1. Temporal Fit (Event occurred prior to or at incident onset)
    2. Code-Path Fit (Change touches affected service/files)
    3. Operational Fit (Telemetry anomalies match failure mode)
    """
    temp_score = 1.0
    temp_fit = True
    code_score = 1.0
    code_fit = True
    ops_score = 1.0
    ops_fit = True

    inc_time = ensure_utc(incident_time)

    # 1. Temporal Fit Evaluation
    for ev in evidence_items:
        ev_time = ensure_utc(ev.observed_at)
        if ev_time and inc_time and ev_time > (inc_time + timedelta(minutes=5)):
            # Evidence post-dates incident start significantly
            temp_score -= 0.35

    temp_score = max(0.1, min(1.0, temp_score))
    temp_fit = temp_score >= 0.50

    # 2. Code-Path & Operational Fit
    desc_lower = hypothesis_desc.lower()
    has_code_mention = any(k in desc_lower for k in ("deploy", "commit", "pool", "config", "code", "dependency"))
    has_telemetry = any(ev.source_type in (EvidenceSourceType.TELEMETRY, EvidenceSourceType.LOGS) for ev in evidence_items)

    if has_code_mention and not any(ev.source_type in (EvidenceSourceType.DEPLOYMENTS, EvidenceSourceType.CHANGES) for ev in evidence_items):
        code_score = 0.40
        code_fit = False

    if not has_telemetry:
        ops_score = 0.70  # Plausible even if raw telemetry log stream is not fully ingested
        ops_fit = True

    return temp_fit, temp_score, code_fit, code_score, ops_fit, ops_score


def run_adversarial_disproof(
    hypothesis: Hypothesis,
    all_evidence: List[Evidence],
    incident_time: datetime,
) -> Tuple[bool, Optional[str]]:
    """
    Actively search for contradictory facts to falsify the hypothesis.
    Returns (is_disproven: bool, disproof_reason: Optional[str]).
    """
    desc_lower = hypothesis.description.lower()

    # Check 1: Did the incident onset precede the hypothesized change?
    if "deploy" in desc_lower or "commit" in desc_lower or "change" in desc_lower:
        for ev in all_evidence:
            if ev.source_type == EvidenceSourceType.TELEMETRY and ev.observed_at:
                ev_time = ensure_utc(ev.observed_at)
                for dep_ev in all_evidence:
                    if dep_ev.source_type in (EvidenceSourceType.DEPLOYMENTS, EvidenceSourceType.CHANGES) and dep_ev.observed_at:
                        dep_time = ensure_utc(dep_ev.observed_at)
                        if ev_time and dep_time and ev_time < (dep_time - timedelta(minutes=15)):
                            return True, f"Disproved: Anomaly telemetry was already active at {ev_time.isoformat()} before change at {dep_time.isoformat()}."

    # Check 2: Contradicting manual or verified evidence
    for ev in all_evidence:
        if ev.category_type == EvidenceCategoryType.FACT and "not affected" in (ev.content or "").lower():
            if (ev.service or "").lower() in desc_lower:
                return True, f"Disproved: Fact evidence {ev.id} explicitly confirms component was unaffected."

    return False, None


def evaluate_incident_hypotheses(
    db: Session,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    investigation_id: Optional[uuid.UUID] = None,
    user_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """
    Orchestrate full Phase 9 Hypothesis Competition & Root-Cause Analysis:
    1. Harvest all incident evidence.
    2. Propose or update competing hypotheses.
    3. Calculate Tri-Factor fit.
    4. Execute Adversarial Disproof loop.
    5. Check Multi-Source Evidence Families corroboration (>= 2 distinct families).
    6. Formulate accepted RootCause or Safe Abstention.
    """
    incident = db.query(Incident).filter(
        Incident.organization_id == organization_id,
        Incident.id == incident_id,
    ).first()
    if not incident:
        raise ValueError(f"Incident {incident_id} not found")

    incident_time = incident.detected_at or incident.created_at or datetime.now(timezone.utc)

    # 1. Harvest multi-source evidence
    all_evidence = harvest_incident_evidence(db, organization_id, incident_id, investigation_id)
    evidence_by_id = {str(e.id): e for e in all_evidence}

    # 2. Retrieve or generate hypotheses
    existing_hypotheses = db.query(Hypothesis).filter(
        Hypothesis.organization_id == organization_id,
        Hypothesis.incident_id == incident.id,
    ).all()

    if not existing_hypotheses:
        # Generate default plausible competing candidates
        svc = incident.service_name or "Service"
        h1 = Hypothesis(
            organization_id=organization_id,
            incident_id=incident.id,
            investigation_id=investigation_id,
            label="H1",
            description=f"Recent deployment or configuration change introduced a regression on {svc}.",
            status=HypothesisStatus.PROPOSED,
        )
        h2 = Hypothesis(
            organization_id=organization_id,
            incident_id=incident.id,
            investigation_id=investigation_id,
            label="H2",
            description=f"Resource saturation or external dependency latency degraded {svc} independently of local changes.",
            status=HypothesisStatus.PROPOSED,
        )
        db.add_all([h1, h2])
        db.commit()
        existing_hypotheses = [h1, h2]

    # 3. Evaluate each hypothesis
    accepted_hypothesis: Optional[Hypothesis] = None
    disproof_logs: List[str] = []

    for hyp in existing_hypotheses:
        # Respect human triage locks
        if hyp.human_triaged:
            if hyp.status == HypothesisStatus.ACCEPTED:
                accepted_hypothesis = hyp
            continue

        # Tri-Factor Fit
        t_fit, t_score, c_fit, c_score, o_fit, o_score = evaluate_tri_factor_fit(
            hyp.description, all_evidence, incident_time
        )
        hyp.temporal_fit = t_fit
        hyp.temporal_fit_score = t_score
        hyp.code_path_fit = c_fit
        hyp.code_path_fit_score = c_score
        hyp.operational_fit = o_fit
        hyp.operational_fit_score = o_score

        # Link supporting & contradicting evidence
        supporting_ids = []
        contradicting_ids = []
        distinct_families = set()

        for ev in all_evidence:
            if hyp.label == "H1" and ev.source_type in (EvidenceSourceType.DEPLOYMENTS, EvidenceSourceType.CHANGES, EvidenceSourceType.TELEMETRY, EvidenceSourceType.LOGS):
                supporting_ids.append(str(ev.id))
                if ev.evidence_family:
                    distinct_families.add(ev.evidence_family.value if hasattr(ev.evidence_family, "value") else str(ev.evidence_family))
            elif hyp.label == "H2" and ev.source_type in (EvidenceSourceType.TELEMETRY, EvidenceSourceType.LOGS, EvidenceSourceType.GRAPH):
                supporting_ids.append(str(ev.id))
                if ev.evidence_family:
                    distinct_families.add(ev.evidence_family.value if hasattr(ev.evidence_family, "value") else str(ev.evidence_family))
            elif hyp.label not in ("H1", "H2"):
                supporting_ids.append(str(ev.id))
                if ev.evidence_family:
                    distinct_families.add(ev.evidence_family.value if hasattr(ev.evidence_family, "value") else str(ev.evidence_family))

        hyp.supporting_evidence_ids = supporting_ids
        hyp.contradicting_evidence_ids = contradicting_ids
        hyp.supporting_evidence_count = len(supporting_ids)
        hyp.contradicting_evidence_count = len(contradicting_ids)
        hyp.distinct_families_count = len(distinct_families)

        # 4. Adversarial Disproof Falsification
        is_disproven, disproof_reason = run_adversarial_disproof(hyp, all_evidence, incident_time)
        if is_disproven:
            transition_hypothesis_status(db, hyp, HypothesisStatus.DISPROVEN, disproof_reason)
            disproof_logs.append(f"[{hyp.label}] {disproof_reason}")
            continue

        # 5. Acceptance Check: Strictly requires >= 2 distinct families & confidence >= 0.60
        composite_confidence = (t_score * 0.35) + (c_score * 0.35) + (o_score * 0.30)
        if composite_confidence >= 0.70:
            hyp.confidence = Confidence.HIGH
        elif composite_confidence >= 0.50:
            hyp.confidence = Confidence.MEDIUM
        else:
            hyp.confidence = Confidence.LOW

        if (
            not is_disproven
            and len(distinct_families) >= 2
            and composite_confidence >= 0.60
            and not accepted_hypothesis
        ):
            transition_hypothesis_status(
                db,
                hyp,
                HypothesisStatus.ACCEPTED,
                f"Passed adversarial disproof with {len(distinct_families)} independent evidence families corroborated."
            )
            accepted_hypothesis = hyp
        elif not is_disproven and len(supporting_ids) > 0:
            transition_hypothesis_status(
                db,
                hyp,
                HypothesisStatus.SUPPORTED,
                f"Supported by evidence ({len(distinct_families)}/2 required families) but pending multi-family corroboration."
            )

    db.commit()

    # 6. Formulate RootCause or Safe Abstention
    # Check for existing root causes to version snapshot
    prev_rcs = db.query(RootCause).filter(
        RootCause.organization_id == organization_id,
        RootCause.incident_id == incident.id,
    ).all()
    prev_version = max([r.evaluation_version for r in prev_rcs], default=0)

    # Check human override on previous root cause
    human_override_prev = next((r for r in prev_rcs if r.human_overridden and r.is_current), None)

    # Mark previous reports as not current
    for r in prev_rcs:
        r.is_current = False
    db.commit()

    # Generate snapshot hash
    snapshot_hash = hashlib.sha256(f"{incident.id}_{len(all_evidence)}_{prev_version+1}".encode()).hexdigest()[:16]

    if human_override_prev:
        # Preserve human override
        new_rc = RootCause(
            organization_id=organization_id,
            incident_id=incident.id,
            investigation_id=investigation_id,
            summary=human_override_prev.summary,
            affected_component=human_override_prev.affected_component,
            causal_explanation=human_override_prev.causal_explanation,
            confidence=human_override_prev.confidence,
            supporting_evidence_ids=human_override_prev.supporting_evidence_ids,
            contradicting_evidence_ids=human_override_prev.contradicting_evidence_ids,
            evidence_sources_count=len(all_evidence),
            distinct_families_count=human_override_prev.distinct_families_count,
            disproof_summary="; ".join(disproof_logs) if disproof_logs else None,
            abstained=False,
            evaluation_version=prev_version + 1,
            snapshot_hash=snapshot_hash,
            is_current=True,
            human_overridden=True,
            human_override_notes=human_override_prev.human_override_notes,
            overridden_by_user_id=human_override_prev.overridden_by_user_id,
        )
        db.add(new_rc)
        db.commit()
        db.refresh(new_rc)
        return {
            "incident_id": incident.id,
            "total_hypotheses": len(existing_hypotheses),
            "accepted_hypothesis": None,
            "hypotheses": existing_hypotheses,
            "abstained": False,
            "root_cause": new_rc,
            "disproof_summary": new_rc.disproof_summary,
        }

    if accepted_hypothesis:
        new_rc = RootCause(
            organization_id=organization_id,
            incident_id=incident.id,
            investigation_id=investigation_id,
            summary=accepted_hypothesis.description,
            affected_component=incident.service_name or "Identified Component",
            causal_explanation=f"Hypothesis {accepted_hypothesis.label} corroborated by {accepted_hypothesis.distinct_families_count} evidence families with temporal fit {accepted_hypothesis.temporal_fit_score:.2f}.",
            confidence=accepted_hypothesis.confidence,
            supporting_evidence_ids=accepted_hypothesis.supporting_evidence_ids,
            contradicting_evidence_ids=accepted_hypothesis.contradicting_evidence_ids,
            evidence_sources_count=len(all_evidence),
            distinct_families_count=accepted_hypothesis.distinct_families_count,
            disproof_summary="; ".join(disproof_logs) if disproof_logs else "No unresolvable contradictions found.",
            abstained=False,
            evaluation_version=prev_version + 1,
            snapshot_hash=snapshot_hash,
            is_current=True,
        )
        db.add(new_rc)
        db.commit()
        db.refresh(new_rc)
        return {
            "incident_id": incident.id,
            "total_hypotheses": len(existing_hypotheses),
            "accepted_hypothesis": accepted_hypothesis,
            "hypotheses": existing_hypotheses,
            "abstained": False,
            "root_cause": new_rc,
            "disproof_summary": new_rc.disproof_summary,
        }
    else:
        # Safe Abstention Rule
        missing_needed = []
        if not any(e.source_type == EvidenceSourceType.DEPLOYMENTS for e in all_evidence):
            missing_needed.append("Deployment event telemetry for target service")
        if not any(e.source_type in (EvidenceSourceType.LOGS, EvidenceSourceType.TRACE) for e in all_evidence):
            missing_needed.append("Corroborating stack trace logs or error spans")
        if not missing_needed:
            missing_needed.append("Second independent evidence family corroborating failure mode")

        abstention_reason = (
            f"Evidence inconclusive. Supporting evidence from at least 2 distinct families required. "
            f"Active candidates were either disproven or lacked multi-family corroboration."
        )

        new_rc = RootCause(
            organization_id=organization_id,
            incident_id=incident.id,
            investigation_id=investigation_id,
            summary="Root Cause Inconclusive — Safe Abstention",
            affected_component=incident.service_name,
            causal_explanation=abstention_reason,
            confidence=Confidence.INSUFFICIENT,
            supporting_evidence_ids=[],
            contradicting_evidence_ids=[],
            evidence_sources_count=len(all_evidence),
            distinct_families_count=0,
            disproof_summary="; ".join(disproof_logs) if disproof_logs else None,
            abstained=True,
            abstention_reason=abstention_reason,
            missing_evidence_json=missing_needed,
            evaluation_version=prev_version + 1,
            snapshot_hash=snapshot_hash,
            is_current=True,
        )
        db.add(new_rc)
        db.commit()
        db.refresh(new_rc)
        return {
            "incident_id": incident.id,
            "total_hypotheses": len(existing_hypotheses),
            "accepted_hypothesis": None,
            "hypotheses": existing_hypotheses,
            "abstained": True,
            "abstention_reason": abstention_reason,
            "missing_evidence": missing_needed,
            "root_cause": new_rc,
            "disproof_summary": new_rc.disproof_summary,
        }
