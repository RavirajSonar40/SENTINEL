from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID
from datetime import datetime

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.incident import (
    Investigation, InvestigationTask, InvestigationStatus, TaskStatus,
    Evidence, EvidenceSourceType,
    Hypothesis, HypothesisEvidence, HypothesisStatus, Confidence,
    RootCause,
    ProposedFix, FixFile, ValidationRun, ValidationStatus,
    AuditEvent, User, Incident,
)


def _check_investigation_access(inv: Investigation, user: User, db: Session):
    """Raise 403 if user is not admin and doesn't own the investigation's incident."""
    if user.role == "admin":
        return
    incident = db.query(Incident).filter(Incident.id == inv.incident_id).first()
    if not incident or incident.creator_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

router = APIRouter(prefix="/investigations", tags=["investigations"])


# --- Schemas ---

class InvestigationOut(BaseModel):
    id: str
    incident_id: str
    status: str
    current_step: Optional[str]
    progress_percent: int
    root_cause_found: bool
    confidence: Optional[str]
    llm_model: Optional[str]
    total_tokens: int
    total_cost_usd: float
    started_at: datetime
    completed_at: Optional[datetime]

class TaskOut(BaseModel):
    id: str
    task_type: str
    description: Optional[str]
    status: str
    order: int
    tool_name: Optional[str]
    error_message: Optional[str]
    attempt: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]

class EvidenceCreate(BaseModel):
    source_type: str
    source_id: Optional[str] = None
    repository: Optional[str] = None
    file_path: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    title: str
    content: Optional[str] = None
    summary: Optional[str] = None
    timestamp: Optional[datetime] = None
    source_url: Optional[str] = None
    relevance_score: Optional[float] = None

class EvidenceOut(BaseModel):
    id: str
    source_type: str
    source_id: Optional[str]
    repository: Optional[str]
    file_path: Optional[str]
    line_start: Optional[int]
    line_end: Optional[int]
    title: str
    content: Optional[str]
    summary: Optional[str]
    timestamp: Optional[datetime]
    source_url: Optional[str]
    relevance_score: Optional[float]
    collected_at: datetime

class HypothesisCreate(BaseModel):
    label: str
    description: str

class HypothesisOut(BaseModel):
    id: str
    label: str
    description: str
    status: str
    confidence: str
    supporting_evidence_count: int
    contradicting_evidence_count: int
    missing_evidence_count: int
    evaluation_notes: Optional[str]
    rejection_reason: Optional[str]
    created_at: datetime
    evaluated_at: Optional[datetime]

class RootCauseOut(BaseModel):
    id: str
    summary: str
    affected_component: Optional[str]
    causal_explanation: str
    confidence: str
    relevant_commits: Optional[list]
    relevant_files: Optional[list]
    timeline: Optional[list]
    identified_at: datetime

class ProposedFixOut(BaseModel):
    id: str
    title: str
    description: str
    problem: Optional[str]
    root_cause: Optional[str]
    proposed_change: str
    expected_behavior: Optional[str]
    risk: Optional[str]
    diff: Optional[str]
    branch_name: Optional[str]
    pr_number: Optional[int]
    pr_url: Optional[str]
    generated_at: datetime

class FixFileOut(BaseModel):
    id: str
    file_path: str
    change_type: str
    additions: int
    deletions: int

class ValidationOut(BaseModel):
    id: str
    status: str
    total_checks: int
    passed_checks: int
    failed_checks: int
    lint_result: Optional[dict]
    test_result: Optional[dict]
    build_result: Optional[dict]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


# --- Investigation Endpoints ---

@router.get("/{investigation_id}", response_model=InvestigationOut)
def get_investigation(
    investigation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv = db.query(Investigation).filter(Investigation.id == UUID(investigation_id)).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    _check_investigation_access(inv, current_user, db)
    return _inv_to_out(inv)


@router.get("/{investigation_id}/tasks", response_model=List[TaskOut])
def list_tasks(
    investigation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv = db.query(Investigation).filter(Investigation.id == UUID(investigation_id)).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    _check_investigation_access(inv, current_user, db)
    tasks = db.query(InvestigationTask).filter(
        InvestigationTask.investigation_id == UUID(investigation_id)
    ).order_by(InvestigationTask.order).all()
    return [_task_to_out(t) for t in tasks]


# --- Evidence Endpoints ---

@router.get("/{investigation_id}/evidence", response_model=List[EvidenceOut])
def list_evidence(
    investigation_id: str,
    source_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv = db.query(Investigation).filter(Investigation.id == UUID(investigation_id)).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    _check_investigation_access(inv, current_user, db)
    query = db.query(Evidence).filter(Evidence.investigation_id == UUID(investigation_id))
    if source_type:
        query = query.filter(Evidence.source_type == source_type)
    evidence = query.order_by(Evidence.collected_at).all()
    return [_evidence_to_out(e) for e in evidence]


@router.post("/{investigation_id}/evidence", response_model=EvidenceOut)
def add_evidence(
    investigation_id: str,
    payload: EvidenceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    evidence = Evidence(
        investigation_id=UUID(investigation_id),
        source_type=payload.source_type,
        source_id=payload.source_id,
        repository=payload.repository,
        file_path=payload.file_path,
        line_start=payload.line_start,
        line_end=payload.line_end,
        title=payload.title,
        content=payload.content,
        summary=payload.summary,
        timestamp=payload.timestamp,
        source_url=payload.source_url,
        relevance_score=payload.relevance_score,
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return _evidence_to_out(evidence)


# --- Hypothesis Endpoints ---

@router.get("/{investigation_id}/hypotheses", response_model=List[HypothesisOut])
def list_hypotheses(
    investigation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv = db.query(Investigation).filter(Investigation.id == UUID(investigation_id)).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    _check_investigation_access(inv, current_user, db)
    hyps = db.query(Hypothesis).filter(
        Hypothesis.investigation_id == UUID(investigation_id)
    ).order_by(Hypothesis.label).all()
    return [_hyp_to_out(h) for h in hyps]


@router.post("/{investigation_id}/hypotheses", response_model=HypothesisOut)
def create_hypothesis(
    investigation_id: str,
    payload: HypothesisCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    hyp = Hypothesis(
        investigation_id=UUID(investigation_id),
        label=payload.label,
        description=payload.description,
    )
    db.add(hyp)
    db.commit()
    db.refresh(hyp)
    return _hyp_to_out(hyp)


# --- Root Cause Endpoints ---

@router.get("/{investigation_id}/root-cause", response_model=RootCauseOut)
def get_root_cause(
    investigation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv = db.query(Investigation).filter(Investigation.id == UUID(investigation_id)).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    _check_investigation_access(inv, current_user, db)
    rc = db.query(RootCause).filter(
        RootCause.investigation_id == UUID(investigation_id)
    ).first()
    if not rc:
        raise HTTPException(status_code=404, detail="Root cause not found")
    return _rc_to_out(rc)


# --- Fix Endpoints ---

@router.get("/{investigation_id}/fixes", response_model=List[ProposedFixOut])
def list_fixes(
    investigation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv = db.query(Investigation).filter(Investigation.id == UUID(investigation_id)).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    _check_investigation_access(inv, current_user, db)
    fixes = db.query(ProposedFix).join(RootCause).filter(
        RootCause.investigation_id == UUID(investigation_id)
    ).all()
    return [_fix_to_out(f) for f in fixes]


@router.get("/fixes/{fix_id}", response_model=ProposedFixOut)
def get_fix(
    fix_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    fix = db.query(ProposedFix).filter(ProposedFix.id == UUID(fix_id)).first()
    if not fix:
        raise HTTPException(status_code=404, detail="Fix not found")
    return _fix_to_out(fix)


@router.get("/fixes/{fix_id}/files", response_model=List[FixFileOut])
def list_fix_files(
    fix_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    files = db.query(FixFile).filter(FixFile.fix_id == UUID(fix_id)).all()
    return [_file_to_out(f) for f in files]


@router.get("/fixes/{fix_id}/validations", response_model=List[ValidationOut])
def list_validations(
    fix_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    runs = db.query(ValidationRun).filter(
        ValidationRun.fix_id == UUID(fix_id)
    ).order_by(ValidationRun.created_at).all()
    return [_val_to_out(v) for v in runs]


# --- Helpers ---

def _inv_to_out(inv: Investigation) -> InvestigationOut:
    return InvestigationOut(
        id=str(inv.id),
        incident_id=str(inv.incident_id),
        status=inv.status.value if hasattr(inv.status, 'value') else inv.status,
        current_step=inv.current_step,
        progress_percent=inv.progress_percent or 0,
        root_cause_found=inv.root_cause_found or False,
        confidence=inv.confidence.value if hasattr(inv.confidence, 'value') else inv.confidence,
        llm_model=inv.llm_model,
        total_tokens=inv.total_tokens or 0,
        total_cost_usd=inv.total_cost_usd or 0.0,
        started_at=inv.started_at,
        completed_at=inv.completed_at,
    )

def _task_to_out(task: InvestigationTask) -> TaskOut:
    return TaskOut(
        id=str(task.id),
        task_type=task.task_type,
        description=task.description,
        status=task.status.value if hasattr(task.status, 'value') else task.status,
        order=task.order,
        tool_name=task.tool_name,
        error_message=task.error_message,
        attempt=task.attempt,
        started_at=task.started_at,
        completed_at=task.completed_at,
    )

def _evidence_to_out(e: Evidence) -> EvidenceOut:
    return EvidenceOut(
        id=str(e.id),
        source_type=e.source_type.value if hasattr(e.source_type, 'value') else e.source_type,
        source_id=e.source_id,
        repository=e.repository,
        file_path=e.file_path,
        line_start=e.line_start,
        line_end=e.line_end,
        title=e.title,
        content=e.content,
        summary=e.summary,
        timestamp=e.timestamp,
        source_url=e.source_url,
        relevance_score=e.relevance_score,
        collected_at=e.collected_at,
    )

def _hyp_to_out(h: Hypothesis) -> HypothesisOut:
    return HypothesisOut(
        id=str(h.id),
        label=h.label,
        description=h.description,
        status=h.status.value if hasattr(h.status, 'value') else h.status,
        confidence=h.confidence.value if hasattr(h.confidence, 'value') else h.confidence,
        supporting_evidence_count=h.supporting_evidence_count or 0,
        contradicting_evidence_count=h.contradicting_evidence_count or 0,
        missing_evidence_count=h.missing_evidence_count or 0,
        evaluation_notes=h.evaluation_notes,
        rejection_reason=h.rejection_reason,
        created_at=h.created_at,
        evaluated_at=h.evaluated_at,
    )

def _rc_to_out(rc: RootCause) -> RootCauseOut:
    return RootCauseOut(
        id=str(rc.id),
        summary=rc.summary,
        affected_component=rc.affected_component,
        causal_explanation=rc.causal_explanation,
        confidence=rc.confidence.value if hasattr(rc.confidence, 'value') else rc.confidence,
        relevant_commits=rc.relevant_commits,
        relevant_files=rc.relevant_files,
        timeline=rc.timeline,
        identified_at=rc.identified_at,
    )

def _fix_to_out(f: ProposedFix) -> ProposedFixOut:
    return ProposedFixOut(
        id=str(f.id),
        title=f.title,
        description=f.description,
        problem=f.problem,
        root_cause=f.root_cause,
        proposed_change=f.proposed_change,
        expected_behavior=f.expected_behavior,
        risk=f.risk,
        diff=f.diff,
        branch_name=f.branch_name,
        pr_number=f.pr_number,
        pr_url=f.pr_url,
        generated_at=f.generated_at,
    )

def _file_to_out(f: FixFile) -> FixFileOut:
    return FixFileOut(
        id=str(f.id),
        file_path=f.file_path,
        change_type=f.change_type,
        additions=f.additions,
        deletions=f.deletions,
    )

def _val_to_out(v: ValidationRun) -> ValidationOut:
    return ValidationOut(
        id=str(v.id),
        status=v.status.value if hasattr(v.status, 'value') else v.status,
        total_checks=v.total_checks or 0,
        passed_checks=v.passed_checks or 0,
        failed_checks=v.failed_checks or 0,
        lint_result=v.lint_result,
        test_result=v.test_result,
        build_result=v.build_result,
        started_at=v.started_at,
        completed_at=v.completed_at,
    )


# --- Timeline ---

@router.get("/investigations/{investigation_id}/timeline")
async def get_investigation_timeline(
    investigation_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get chronological timeline of investigation events."""
    from app.services.timeline import build_timeline
    investigation = db.query(Investigation).filter(Investigation.id == investigation_id).first()
    if not investigation:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return build_timeline(investigation.incident_id, db)


# --- Historical Search ---

@router.get("/investigations/search-similar")
async def search_similar_incidents(
    q: str,
    service: Optional[str] = None,
    limit: int = 5,
    current_user=Depends(get_current_user),
):
    """Search for similar past incidents."""
    from app.services.historical import search_similar_incidents
    return search_similar_incidents(q, service, limit)


# --- Evaluation ---

@router.get("/eval/benchmark")
async def get_benchmark_dataset(
    current_user=Depends(get_current_user),
):
    """Get benchmark dataset for evaluation."""
    from app.services.benchmark_dataset import get_benchmark_dataset
    return get_benchmark_dataset()


@router.post("/eval/grounding")
async def evaluate_grounding(
    root_cause_claim: str,
    evidence: List[dict],
    affected_files: Optional[List[str]] = None,
    current_user=Depends(get_current_user),
):
    """Evaluate if a root cause is grounded in evidence."""
    from app.services.evaluation import evaluate_grounding
    return evaluate_grounding(root_cause_claim, evidence, affected_files or [])
