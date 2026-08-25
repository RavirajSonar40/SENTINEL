"""Investigation engine API — triggers AI investigation pipeline."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.incident import (
    Incident, Investigation, InvestigationTask as InvestigationTaskModel,
    Evidence, Hypothesis as HypothesisModel, RootCause,
    ProposedFix, FixFile, User, IncidentStatus, InvestigationStatus,
    TaskStatus, EvidenceSourceType, HypothesisStatus, IncidentSeverity,
)
from app.services.investigation_engine import (
    InvestigationState, run_investigation as run_engine,
)
from app.services.hypothesis_engine import (
    generate_hypotheses, generate_hypotheses_llm, critique_hypotheses,
    identify_root_cause, generate_proposed_fixes,
)

router = APIRouter()


class InvestigateRequest(BaseModel):
    incident_id: str
    repository: Optional[str] = None
    service: Optional[str] = None


class InvestigateResponse(BaseModel):
    status: str
    investigation_id: Optional[str] = None
    tasks_completed: int = 0
    tasks_failed: int = 0
    evidence_count: int = 0
    hypotheses_count: int = 0
    confidence: str = "low"
    root_cause_found: bool = False
    message: str = ""


@router.post("/investigate")
async def trigger_investigation(
    request: InvestigateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trigger a full AI investigation pipeline for an incident."""
    # Get incident
    incident = db.query(Incident).filter(Incident.id == request.incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Create or get investigation
    investigation = db.query(Investigation).filter(
        Investigation.incident_id == incident.id
    ).first()

    if not investigation:
        investigation = Investigation(
            incident_id=incident.id,
            status=InvestigationStatus.PLANNING.value,
            confidence="low",
            started_at=datetime.now(timezone.utc),
        )
        db.add(investigation)
        db.flush()

        # Link to incident
        incident.status = IncidentStatus.INVESTIGATING.value

    # Build state — resolve repository from scopes if not provided
    repo_name = request.repository
    if not repo_name and incident.scopes:
        from app.models.incident import Repository
        first_scope = incident.scopes[0]
        repo = db.query(Repository).filter(Repository.id == first_scope.repository_id).first()
        if repo:
            repo_name = repo.full_name

    state = InvestigationState(
        incident_id=incident.id,
        incident_title=incident.title,
        incident_description=incident.description or "",
        error_signals=[incident.error_signature] if incident.error_signature else [],
        repository=repo_name,
        service=request.service or incident.service_name,
    )

    # Run investigation engine
    state = await run_engine(state)

    # Persist evidence
    evidence_count = 0
    for ev_data in state.evidence_collected[:20]:
        evidence = Evidence(
            investigation_id=investigation.id,
            source_type=EvidenceSourceType.COMMIT.value if "code" in ev_data.get("source", "") else EvidenceSourceType.FILE.value,
            title=f"{ev_data.get('symbol', ev_data.get('file', 'Unknown'))}",
            summary=ev_data.get("content_preview", "")[:500],
            repository=ev_data.get("file", "").split("/")[0] if ev_data.get("file") else None,
            file_path=ev_data.get("file"),
            source_id=ev_data.get("symbol"),
            relevance_score=ev_data.get("score", 0.5),
        )
        db.add(evidence)
        evidence_count += 1

    # Generate hypotheses (LLM-powered)
    try:
        hypotheses = await generate_hypotheses_llm(state, state.evidence_collected)
    except Exception:
        hypotheses = generate_hypotheses(state)
    hypotheses = critique_hypotheses(hypotheses, state.evidence_collected)

    # Persist hypotheses
    for h in hypotheses[:10]:
        hyp_model = HypothesisModel(
            investigation_id=investigation.id,
            incident_id=incident.id,
            label=h.label,
            description=h.description,
            confidence=h.confidence,
            status=HypothesisStatus.SUPPORTED.value if h.status == "supported" else HypothesisStatus.PROPOSED.value,
            supporting_evidence_count=h.supporting_count,
            contradicting_evidence_count=h.contradicting_count,
            rejection_reason=h.rejection_reason,
        )
        db.add(hyp_model)

    # Identify root cause
    root_cause = identify_root_cause(state, hypotheses)
    root_cause_found = False

    if root_cause:
        root_cause_found = True
        rc = RootCause(
            investigation_id=investigation.id,
            incident_id=incident.id,
            summary=root_cause.get("label", "Root Cause"),
            causal_explanation=root_cause.get("description", ""),
            confidence=root_cause.get("confidence", "medium"),
            affected_component=root_cause.get("category", "unknown"),
        )
        db.add(rc)

        # Generate proposed fixes
        fixes = generate_proposed_fixes(root_cause, state)
        for fix in fixes[:3]:
            fix_model = ProposedFix(
                investigation_id=investigation.id,
                root_cause_id=rc.id,
                incident_id=incident.id,
                fix_type=fix.get("type"),
                title=fix.get("title", "Proposed Fix"),
                description=fix.get("description", ""),
            )
            db.add(fix_model)
            db.flush()

            for file_path in fix.get("files_to_modify", [])[:5]:
                fix_file = FixFile(
                    fix_id=fix_model.id,
                    file_path=file_path,
                    change_type="modify",
                )
                db.add(fix_file)

    # Update investigation
    investigation.status = InvestigationStatus.ROOT_CAUSE_ANALYSIS.value if root_cause_found else InvestigationStatus.COLLECTING_EVIDENCE.value
    investigation.confidence = state.confidence
    investigation.completed_at = datetime.now(timezone.utc)

    # Update incident
    if root_cause_found:
        incident.status = IncidentStatus.ROOT_CAUSE_IDENTIFIED.value
    else:
        incident.status = IncidentStatus.ROOT_CAUSE_ANALYSIS.value

    db.commit()

    return InvestigateResponse(
        status="completed",
        investigation_id=investigation.id,
        tasks_completed=state.tasks_completed,
        tasks_failed=state.tasks_failed,
        evidence_count=evidence_count,
        hypotheses_count=len(hypotheses),
        confidence=state.confidence,
        root_cause_found=root_cause_found,
        message="Investigation complete" if root_cause_found else "Investigation complete — root cause not definitively identified",
    )


@router.get("/investigations/{investigation_id}/engine-status")
async def get_engine_status(
    investigation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get investigation engine status and evidence breakdown."""
    investigation = db.query(Investigation).filter(Investigation.id == investigation_id).first()
    if not investigation:
        raise HTTPException(status_code=404, detail="Investigation not found")

    evidence = db.query(Evidence).filter(Evidence.investigation_id == investigation_id).all()
    hypotheses = db.query(HypothesisModel).filter(HypothesisModel.investigation_id == investigation_id).all()

    evidence_by_source = {}
    for ev in evidence:
        src = ev.source_type or "unknown"
        evidence_by_source[src] = evidence_by_source.get(src, 0) + 1

    return {
        "investigation_id": investigation_id,
        "status": investigation.status,
        "confidence": investigation.confidence,
        "tasks_completed": investigation.tasks_completed,
        "tasks_failed": investigation.tasks_failed,
        "evidence_total": len(evidence),
        "evidence_by_source": evidence_by_source,
        "hypotheses_total": len(hypotheses),
        "hypotheses_supported": sum(1 for h in hypotheses if h.status == "supported"),
        "started_at": investigation.started_at.isoformat() if investigation.started_at else None,
        "completed_at": investigation.completed_at.isoformat() if investigation.completed_at else None,
    }
