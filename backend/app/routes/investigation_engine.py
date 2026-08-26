"""Investigation engine API — triggers AI investigation pipeline."""
import json
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional, AsyncGenerator
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
            incident_id=incident.id,
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
                proposed_change=fix.get("description", ""),
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
        investigation_id=str(investigation.id),
        tasks_completed=state.tasks_completed,
        tasks_failed=state.tasks_failed,
        evidence_count=evidence_count,
        hypotheses_count=len(hypotheses),
        confidence=state.confidence,
        root_cause_found=root_cause_found,
        message="Investigation complete" if root_cause_found else "Investigation complete — root cause not definitively identified",
    )


async def _stream_investigation(
    inc_id, inv_id, inc_title, inc_desc, inc_sig, inc_scopes, inc_service, repo_name, request_service,
) -> AsyncGenerator[str, None]:
    """Generator that yields SSE events during investigation."""
    def emit(event_type: str, data: dict):
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    try:
        # Step 1: Planning
        yield emit("step", {
            "step": "planning",
            "status": "active",
            "message": "Planning investigation strategy...",
            "detail": f"Analyzing incident: {inc_title}",
        })

        from app.services.investigation_engine import (
            InvestigationState, run_investigation as run_engine,
        )

        state = InvestigationState(
            incident_id=str(inc_id),
            incident_title=inc_title,
            incident_description=inc_desc,
            error_signals=[inc_sig] if inc_sig else [],
            repository=repo_name,
            service=request_service or inc_service,
        )

        # Step 2: Repository resolution
        yield emit("step", {
            "step": "repository",
            "status": "active",
            "message": f"Resolving repository..." if repo_name else "No repository linked — will search across all indexed code",
            "detail": repo_name or "Auto-detect from error patterns",
        })

        # Step 3: LLM planning
        yield emit("step", {
            "step": "llm_planning",
            "status": "active",
            "message": "AI is generating investigation plan...",
            "detail": "Selecting tools and search strategies",
        })

        from app.services.investigation_engine import generate_tasks_llm, _generate_default_tasks
        try:
            tasks = await generate_tasks_llm(state)
        except Exception:
            tasks = _generate_default_tasks(state)

        task_descriptions = [t.description for t in tasks]
        yield emit("step", {
            "step": "llm_planning",
            "status": "completed",
            "message": f"Generated {len(tasks)} investigation tasks",
            "detail": task_descriptions,
        })

        # Step 4: Execute search tasks
        yield emit("step", {
            "step": "searching",
            "status": "active",
            "message": "Searching codebase for relevant code...",
            "detail": f"Running {len([t for t in tasks if t.task_type in ('search', 'symbol', 'code', 'logs')])} search tasks in parallel",
        })

        from app.services.investigation_engine import execute_task
        search_tasks = [t for t in tasks if t.task_type in ("search", "symbol", "code", "logs")]
        other_tasks = [t for t in tasks if t.task_type not in ("search", "symbol", "code", "logs")]

        search_results = await asyncio.gather(
            *[execute_task(t) for t in search_tasks],
            return_exceptions=True,
        )

        # Collect evidence from search results
        for task, result in zip(search_tasks, search_results):
            if isinstance(result, Exception):
                state.tasks_failed += 1
                state.error_log.append(f"Task {task.id} failed: {result}")
            else:
                state.tasks_completed += 1
                if isinstance(result, dict) and "results" in result:
                    for item in result["results"]:
                        state.evidence_collected.append({
                            "source": "code_search",
                            "tool": task.tool_name,
                            "file": item.get("file"),
                            "symbol": item.get("symbol"),
                            "type": item.get("type"),
                            "score": item.get("score"),
                            "content_preview": item.get("content_preview", "")[:500],
                        })

        evidence_files = list(set(e.get("file", "") for e in state.evidence_collected if e.get("file")))
        yield emit("step", {
            "step": "searching",
            "status": "completed",
            "message": f"Found {len(state.evidence_collected)} pieces of evidence",
            "detail": {
                "evidence_count": len(state.evidence_collected),
                "files_found": evidence_files[:10],
                "tasks_completed": state.tasks_completed,
                "tasks_failed": state.tasks_failed,
            },
        })

        # Step 5: Execute remaining tasks
        if other_tasks:
            yield emit("step", {
                "step": "deep_analysis",
                "status": "active",
                "message": "Running deeper analysis tasks...",
                "detail": f"Executing {len(other_tasks)} additional tasks (file reads, git history, etc.)",
            })

            for task in other_tasks:
                if task.tool_name == "read_file" and not task.parameters.get("file_path"):
                    if state.evidence_collected:
                        task.parameters["file_path"] = state.evidence_collected[0].get("file", "")
                if task.tool_name == "get_git_history" and not task.parameters.get("file_path"):
                    if state.evidence_collected:
                        task.parameters["file_path"] = state.evidence_collected[0].get("file", "")

            remaining_results = await asyncio.gather(
                *[execute_task(t) for t in other_tasks],
                return_exceptions=True,
            )
            for task, result in zip(other_tasks, remaining_results):
                if isinstance(result, Exception):
                    state.tasks_failed += 1
                else:
                    state.tasks_completed += 1

            yield emit("step", {
                "step": "deep_analysis",
                "status": "completed",
                "message": f"Deep analysis complete — {state.tasks_completed} tasks succeeded",
                "detail": f"{state.tasks_failed} tasks failed",
            })

        # Step 6: Assess confidence
        total = state.tasks_completed + state.tasks_failed
        if total > 0:
            success_rate = state.tasks_completed / total
            if success_rate >= 0.8 and len(state.evidence_collected) >= 5:
                state.confidence = "high"
            elif success_rate >= 0.5 and len(state.evidence_collected) >= 2:
                state.confidence = "medium"
            else:
                state.confidence = "low"
        state.status = "evidence_collected"

        yield emit("step", {
            "step": "confidence",
            "status": "completed",
            "message": f"Evidence confidence: {state.confidence}",
            "detail": f"{state.tasks_completed}/{total} tasks succeeded, {len(state.evidence_collected)} evidence items",
        })

        # Step 7: Generate hypotheses
        yield emit("step", {
            "step": "hypotheses",
            "status": "active",
            "message": "AI is generating hypotheses...",
            "detail": "Analyzing evidence to propose possible root causes",
        })

        from app.services.hypothesis_engine import (
            generate_hypotheses, generate_hypotheses_llm, critique_hypotheses,
            identify_root_cause, generate_proposed_fixes,
        )

        try:
            hypotheses = await generate_hypotheses_llm(state, state.evidence_collected)
        except Exception:
            hypotheses = generate_hypotheses(state)
        hypotheses = critique_hypotheses(hypotheses, state.evidence_collected)

        hyp_summary = [{"label": h.label, "confidence": h.confidence, "status": h.status} for h in hypotheses]
        yield emit("step", {
            "step": "hypotheses",
            "status": "completed",
            "message": f"Generated {len(hypotheses)} hypotheses",
            "detail": hyp_summary,
        })

        # Step 8: Identify root cause
        yield emit("step", {
            "step": "root_cause",
            "status": "active",
            "message": "Identifying most likely root cause...",
            "detail": "Evaluating hypotheses against evidence",
        })

        root_cause = identify_root_cause(state, hypotheses)
        root_cause_found = False

        if root_cause:
            root_cause_found = True
            yield emit("step", {
                "step": "root_cause",
                "status": "completed",
                "message": f"Root cause identified: {root_cause.get('label', 'Unknown')}",
                "detail": {
                    "label": root_cause.get("label"),
                    "description": root_cause.get("description"),
                    "confidence": root_cause.get("confidence"),
                    "category": root_cause.get("category"),
                },
            })

            # Step 9: Generate fixes
            yield emit("step", {
                "step": "fixes",
                "status": "active",
                "message": "Generating proposed fixes...",
                "detail": "Creating remediation plan",
            })

            fixes = generate_proposed_fixes(root_cause, state)
            fix_summary = [{"title": f.get("title"), "type": f.get("type")} for f in fixes]
            yield emit("step", {
                "step": "fixes",
                "status": "completed",
                "message": f"Generated {len(fixes)} proposed fixes",
                "detail": fix_summary,
            })
        else:
            yield emit("step", {
                "step": "root_cause",
                "status": "completed",
                "message": "No definitive root cause identified",
                "detail": "Confidence insufficient — more evidence needed",
            })

        # Persist everything to DB (use fresh session since the route's session is closed)
        from app.core.database import SessionLocal
        from app.models.incident import (
            Evidence as EvidenceModel, Hypothesis as HypothesisModel,
            RootCause, ProposedFix, FixFile, IncidentStatus, InvestigationStatus,
            EvidenceSourceType, HypothesisStatus, IncidentSeverity,
        )

        persist_db = SessionLocal()
        try:
            for ev_data in state.evidence_collected[:20]:
                evidence = EvidenceModel(
                    investigation_id=inv_id,
                    incident_id=inc_id,
                    source_type=EvidenceSourceType.COMMIT.value if "code" in ev_data.get("source", "") else EvidenceSourceType.FILE.value,
                    title=f"{ev_data.get('symbol', ev_data.get('file', 'Unknown'))}",
                    summary=ev_data.get("content_preview", "")[:500],
                    repository=ev_data.get("file", "").split("/")[0] if ev_data.get("file") else None,
                    file_path=ev_data.get("file"),
                    source_id=ev_data.get("symbol"),
                    relevance_score=ev_data.get("score", 0.5),
                )
                persist_db.add(evidence)

            for h in hypotheses[:10]:
                hyp_model = HypothesisModel(
                    investigation_id=inv_id,
                    incident_id=inc_id,
                    label=h.label,
                    description=h.description,
                    confidence=h.confidence,
                    status=HypothesisStatus.SUPPORTED.value if h.status == "supported" else HypothesisStatus.PROPOSED.value,
                    supporting_evidence_count=h.supporting_count,
                    contradicting_evidence_count=h.contradicting_count,
                    rejection_reason=h.rejection_reason,
                )
                persist_db.add(hyp_model)

            rc = None
            if root_cause:
                rc = RootCause(
                    investigation_id=inv_id,
                    incident_id=inc_id,
                    summary=root_cause.get("label", "Root Cause"),
                    causal_explanation=root_cause.get("description", ""),
                    confidence=root_cause.get("confidence", "medium"),
                    affected_component=root_cause.get("category", "unknown"),
                )
                persist_db.add(rc)
                persist_db.flush()

                for fix in fixes[:3]:
                    fix_model = ProposedFix(
                        investigation_id=inv_id,
                        root_cause_id=rc.id,
                        incident_id=inc_id,
                        fix_type=fix.get("type"),
                        title=fix.get("title", "Proposed Fix"),
                        description=fix.get("description", ""),
                        proposed_change=fix.get("description", ""),
                    )
                    persist_db.add(fix_model)
                    persist_db.flush()
                    for file_path in fix.get("files_to_modify", [])[:5]:
                        fix_file = FixFile(fix_id=fix_model.id, file_path=file_path, change_type="modify")
                        persist_db.add(fix_file)

            from sqlalchemy import text
            new_status = InvestigationStatus.ROOT_CAUSE_ANALYSIS.value if root_cause_found else InvestigationStatus.COLLECTING_EVIDENCE.value
            inc_status = IncidentStatus.ROOT_CAUSE_IDENTIFIED.value if root_cause_found else IncidentStatus.ROOT_CAUSE_ANALYSIS.value
            persist_db.execute(text("UPDATE investigations SET status=:s, confidence=:c, completed_at=NOW() WHERE id=:id"),
                               {"s": new_status, "c": state.confidence, "id": str(inv_id)})
            persist_db.execute(text("UPDATE incidents SET status=:s WHERE id=:id"),
                               {"s": inc_status, "id": str(inc_id)})
            persist_db.commit()
        except Exception as persist_err:
            try:
                persist_db.rollback()
            except Exception:
                pass
            raise persist_err
        finally:
            persist_db.close()

        # Final event
        yield emit("complete", {
            "status": "completed",
            "investigation_id": str(inv_id),
            "root_cause_found": root_cause_found,
            "confidence": state.confidence,
            "evidence_count": len(state.evidence_collected),
            "hypotheses_count": len(hypotheses),
            "tasks_completed": state.tasks_completed,
            "tasks_failed": state.tasks_failed,
        })

    except Exception as e:
        try:
            yield emit("error", {"message": str(e)[:500]})
        except Exception:
            pass


@router.post("/investigate/stream")
async def trigger_investigation_stream(
    request: InvestigateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trigger investigation with real-time SSE progress updates."""
    incident = db.query(Incident).filter(Incident.id == request.incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

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
        incident.status = IncidentStatus.INVESTIGATING.value
        db.commit()

    # Refresh so attributes survive after session closes
    db.refresh(incident)
    db.refresh(investigation)

    # Snapshot values before session closes
    inc_title = incident.title or "Unknown"
    inc_desc = incident.description or ""
    inc_sig = incident.error_signature
    inc_scopes = list(incident.scopes) if incident.scopes else []
    inc_service = incident.service_name
    inv_id = investigation.id
    inc_id = incident.id

    repo_name = request.repository
    if not repo_name and inc_scopes:
        from app.models.incident import Repository
        first_scope = inc_scopes[0]
        repo = db.query(Repository).filter(Repository.id == first_scope.repository_id).first()
        if repo:
            repo_name = repo.full_name

    return StreamingResponse(
        _stream_investigation(inc_id, inv_id, inc_title, inc_desc, inc_sig, inc_scopes, inc_service, repo_name, request.service),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
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
