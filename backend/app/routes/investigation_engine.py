"""Investigation engine API — triggers AI investigation pipeline."""
import json
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional, AsyncGenerator
from datetime import datetime, timezone

logger = logging.getLogger("sentinel.investigation")

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.incident import (
    Incident, Investigation, InvestigationTask as InvestigationTaskModel,
    Evidence, Hypothesis as HypothesisModel, RootCause,
    ProposedFix, FixFile, User, IncidentStatus, InvestigationStatus,
    TaskStatus, EvidenceSourceType, HypothesisStatus, IncidentSeverity,
    FixStatus,
)
from app.services.investigation_engine import (
    InvestigationState, run_investigation as run_engine,
)
from app.services.hypothesis_engine import (
    generate_hypotheses, generate_hypotheses_llm, critique_hypotheses,
    identify_root_cause, generate_proposed_fixes,
)
from app.services.diff_generator import generate_patch, format_patch_for_pr

router = APIRouter()


def _get_user_github_token(user: User, db: Session, repository: str = None) -> Optional[str]:
    """Get the GitHub token for the authenticated user from their connected installation."""
    import os
    from app.models.incident import GitHubInstallation
    from app.core.config import settings
    # Try lookup by repo owner first (most reliable)
    if repository and "/" in repository:
        repo_owner = repository.split("/")[0]
        installation = db.query(GitHubInstallation).filter(
            GitHubInstallation.account_login == repo_owner,
        ).first()
        if installation and installation.tokens_encrypted:
            return installation.tokens_encrypted
    # Fallback: get the most recent installation
    installation = db.query(GitHubInstallation).order_by(GitHubInstallation.updated_at.desc()).first()
    if installation and installation.tokens_encrypted:
        return installation.tokens_encrypted
    return settings.GITHUB_TOKEN or os.getenv("GITHUB_TOKEN") or None


class InvestigateRequest(BaseModel):
    incident_id: str
    repository: Optional[str] = None
    service: Optional[str] = None


class InvestigateResponse(BaseModel):
    status: str
    investigation_id: Optional[str] = None
    investigation_ids: Optional[List[str]] = None
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
    from app.services.repository_resolver import resolve_repositories

    # Get incident
    incident = db.query(Incident).filter(
        Incident.id == request.incident_id,
        Incident.organization_id == current_user.organization_id,
    ).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    if not incident.organization_id or incident.organization_id != current_user.organization_id:
        raise HTTPException(status_code=403, detail="Incident does not belong to the active organization")

    # Resolve candidate repositories
    if request.repository:
        # Explicit repo provided — single investigation
        repo_candidates = []
        from app.models.incident import Repository
        repo = db.query(Repository).filter(Repository.full_name == request.repository).first()
        if repo:
            from app.services.repository_resolver import RepositoryCandidate
            repo_candidates = [RepositoryCandidate(
                repository_id=str(repo.id),
                repository_full_name=repo.full_name,
                score=100,
                reasons=["explicit_request"],
            )]
        if not repo_candidates:
            # Still proceed with the name even if not in DB
            from app.services.repository_resolver import RepositoryCandidate
            repo_candidates = [RepositoryCandidate(
                repository_id="",
                repository_full_name=request.repository,
                score=100,
                reasons=["explicit_request"],
            )]
    else:
        repo_candidates = resolve_repositories(incident, db)

    if not repo_candidates:
        # No repos found — run investigation without a specific repo
        from app.services.repository_resolver import RepositoryCandidate
        repo_candidates = [RepositoryCandidate(
            repository_id="",
            repository_full_name="",
            score=0,
            reasons=["no_repos_found"],
        )]

    investigation_ids = []
    last_state = None
    last_investigation = None
    total_evidence = 0
    total_hypotheses = 0
    any_root_cause = False

    for candidate in repo_candidates:
        repo_name = candidate.repository_full_name or None

        # Create investigation for this repository
        investigation = Investigation(
            organization_id=incident.organization_id,
            incident_id=incident.id,
            status=InvestigationStatus.PLANNING.value,
            confidence="low",
            started_at=datetime.now(timezone.utc),
        )
        db.add(investigation)
        db.flush()
        investigation_ids.append(str(investigation.id))

        # Link to incident
        incident.status = IncidentStatus.INVESTIGATING.value

        # Build state
        state = InvestigationState(
            incident_id=incident.id,
            incident_title=incident.title,
            incident_description=incident.description or "",
            error_signals=[incident.error_signature] if incident.error_signature else [],
            repository=repo_name,
            service=request.service or incident.service_name,
        )

        # Get user's GitHub token
        user_token = _get_user_github_token(current_user, db, repository=repo_name)

        # Run investigation engine
        state = await run_engine(state, db=db, investigation_id=investigation.id, github_token=user_token)

        # Persist evidence
        evidence_count = 0
        for ev_data in state.evidence_collected[:20]:
            evidence = Evidence(
                organization_id=incident.organization_id,
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
        total_evidence += evidence_count

        # Generate hypotheses (LLM-powered)
        try:
            hypotheses = await generate_hypotheses_llm(state, state.evidence_collected)
        except Exception:
            hypotheses = generate_hypotheses(state)
        hypotheses = critique_hypotheses(hypotheses, state.evidence_collected)

        # Persist hypotheses
        for h in hypotheses[:10]:
            hyp_model = HypothesisModel(
                organization_id=incident.organization_id,
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
        total_hypotheses += len(hypotheses)

        # Identify root cause
        root_cause = identify_root_cause(state, hypotheses)
        root_cause_found = False

        if root_cause:
            root_cause_found = True
            any_root_cause = True
            rc = RootCause(
                organization_id=incident.organization_id,
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
                patch = await generate_patch(
                    root_cause,
                    fix.get("files_to_modify", []),
                    repository=state.repository,
                    token=state.github_token,
                )
                fix_model = ProposedFix(
                    organization_id=incident.organization_id,
                    investigation_id=investigation.id,
                    root_cause_id=rc.id,
                    incident_id=incident.id,
                    fix_type=fix.get("type"),
                    title=fix.get("title", "Proposed Fix"),
                    description=fix.get("description", ""),
                    proposed_change=fix.get("description", ""),
                    repository=state.repository,
                    diff=format_patch_for_pr(patch),
                    patch_json=patch,
                    status=FixStatus.APPROVED.value,
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

        last_state = state
        last_investigation = investigation

    # Update incident
    if any_root_cause:
        incident.status = IncidentStatus.ROOT_CAUSE_IDENTIFIED.value
    else:
        incident.status = IncidentStatus.ROOT_CAUSE_ANALYSIS.value

    db.commit()

    return InvestigateResponse(
        status="completed",
        investigation_id=investigation_ids[0] if investigation_ids else None,
        investigation_ids=investigation_ids,
        tasks_completed=last_state.tasks_completed if last_state else 0,
        tasks_failed=last_state.tasks_failed if last_state else 0,
        evidence_count=total_evidence,
        hypotheses_count=total_hypotheses,
        confidence=last_state.confidence if last_state else "low",
        root_cause_found=any_root_cause,
        message=f"Investigation complete across {len(repo_candidates)} repository(ies)",
    )


async def _stream_investigation(
    inc_id, inv_id, inc_title, inc_desc, inc_sig, inc_repositories, inc_service, repo_name, request_service, github_token=None,
) -> AsyncGenerator[str, None]:
    """Generator that yields SSE events during investigation."""
    def emit(event_type: str, data: dict):
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    step_pct = 0
    from app.core.database import SessionLocal
    from sqlalchemy import text as sql_text

    def _update_progress(step_name: str, pct: int):
        nonlocal step_pct
        step_pct = pct
        try:
            s = SessionLocal()
            s.execute(sql_text("UPDATE investigations SET current_step=:s, progress_percent=:p WHERE id=:id"),
                       {"s": step_name, "p": pct, "id": str(inv_id)})
            s.commit()
            s.close()
        except Exception as e:
            logger.debug(f"Progress update failed: {e}")

    try:
        # Step 1: Planning
        _update_progress("Planning investigation...", 5)
        yield emit("step", {
            "step": "planning",
            "status": "active",
            "message": "Planning investigation strategy...",
            "detail": f"Analyzing incident: {inc_title}",
        })

        from app.services.investigation_engine import (
            InvestigationState, run_investigation as run_engine,
        )

        repositories = [repo_name] if repo_name else list(inc_repositories)
        state = InvestigationState(
            incident_id=str(inc_id),
            incident_title=inc_title,
            incident_description=inc_desc,
            error_signals=[inc_sig] if inc_sig else [],
            repository=repositories[0] if repositories else None,
            service=request_service or inc_service,
        )

        # Step 2: Repository resolution
        _update_progress("Resolving repository...", 10)
        yield emit("step", {
            "step": "repository",
            "status": "active",
            "message": f"Resolving repository..." if repo_name else "No repository linked — will search across all indexed code",
            "detail": ", ".join(repositories) if repositories else "Auto-detect from error patterns",
        })

        # Step 3: LLM planning
        _update_progress("AI generating investigation plan...", 20)
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
        _update_progress("Searching codebase...", 35)
        yield emit("step", {
            "step": "searching",
            "status": "active",
            "message": "Searching codebase for relevant code...",
            "detail": f"Running {len([t for t in tasks if t.task_type in ('search', 'symbol', 'code', 'logs')])} search tasks in parallel",
        })

        from app.services.investigation_engine import execute_task
        search_tasks = [t for t in tasks if t.task_type in ("search", "symbol", "code", "logs")]
        other_tasks = [t for t in tasks if t.task_type not in ("search", "symbol", "code", "logs")]

        search_pairs = [
            (task, repository)
            for task in search_tasks
            for repository in (repositories or [None])
        ]
        search_work = [
            execute_task(
                type(task)(
                    id=f"{task.id}_{(repository or 'all').replace('/', '_')}",
                    task_type=task.task_type,
                    description=task.description,
                    tool_name=task.tool_name,
                    parameters={**task.parameters, "repository": repository},
                )
            )
            for task, repository in search_pairs
        ]
        search_results = await asyncio.gather(
            *search_work,
            return_exceptions=True,
        )

        # Collect evidence from search results
        for (task, repository), result in zip(search_pairs, search_results):
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
                            "repository": repository,
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
            _update_progress("Running deeper analysis...", 50)
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
        _update_progress("Assessing evidence confidence...", 60)
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
        _update_progress("AI generating hypotheses...", 70)
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
        _update_progress("Identifying root cause...", 80)
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
            _update_progress("Generating proposed fixes...", 90)
            yield emit("step", {
                "step": "fixes",
                "status": "active",
                "message": "Generating proposed fixes...",
                "detail": "Creating remediation plan",
            })

            fixes = []
            for repository in repositories or [None]:
                repository_state = InvestigationState(
                    incident_id=state.incident_id,
                    incident_title=state.incident_title,
                    incident_description=state.incident_description,
                    error_signals=state.error_signals,
                    repository=repository,
                    service=state.service,
                    evidence_collected=[
                        evidence for evidence in state.evidence_collected
                        if not repository or repository in str(evidence.get("repository", ""))
                    ],
                )
                for fix in generate_proposed_fixes(root_cause, repository_state):
                    fix["repository"] = repository
                    fixes.append(fix)
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
        _update_progress("Saving results...", 95)
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
                    patch = await generate_patch(
                        root_cause,
                        fix.get("files_to_modify", []),
                        repository=fix.get("repository") or repo_name,
                        token=github_token,
                    )
                    fix_model = ProposedFix(
                        investigation_id=inv_id,
                        root_cause_id=rc.id,
                        incident_id=inc_id,
                        fix_type=fix.get("type"),
                        title=fix.get("title", "Proposed Fix"),
                        description=fix.get("description", ""),
                        proposed_change=fix.get("description", ""),
                        repository=fix.get("repository") or repo_name,
                        diff=format_patch_for_pr(patch),
                        patch_json=patch,
                    )
                    persist_db.add(fix_model)
                    persist_db.flush()
                    for file_path in fix.get("files_to_modify", [])[:5]:
                        change = next(
                            (item for item in patch.get("changes", []) if item.get("file") == file_path),
                            {},
                        )
                        fix_file = FixFile(
                            fix_id=fix_model.id,
                            file_path=file_path,
                            change_type=change.get("action", "modify"),
                            patch=(change.get("new_code") or None),
                        )
                        persist_db.add(fix_file)

            investigation_record = persist_db.query(Investigation).filter(
                Investigation.id == inv_id
            ).first()
            incident_record = persist_db.query(Incident).filter(
                Incident.id == inc_id
            ).first()
            if not investigation_record or not incident_record:
                raise RuntimeError("Investigation records disappeared before results could be saved")

            investigation_record.status = (
                InvestigationStatus.ROOT_CAUSE_ANALYSIS
                if root_cause_found else InvestigationStatus.COLLECTING_EVIDENCE
            )
            investigation_record.confidence = state.confidence
            investigation_record.current_step = "Complete"
            investigation_record.progress_percent = 100
            investigation_record.completed_at = datetime.now(timezone.utc)
            incident_record.status = (
                IncidentStatus.ROOT_CAUSE_IDENTIFIED
                if root_cause_found else IncidentStatus.ROOT_CAUSE_ANALYSIS
            )
            persist_db.commit()

        except Exception as persist_err:
            try:
                persist_db.rollback()
            except Exception as rb_err:
                logger.warning(f"Rollback also failed during recovery: {rb_err}")
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
            from app.core.database import SessionLocal
            failed_db = SessionLocal()
            failed_investigation = failed_db.query(Investigation).filter(
                Investigation.id == inv_id
            ).first()
            if failed_investigation:
                failed_investigation.status = InvestigationStatus.FAILED
                failed_investigation.current_step = "Investigation failed"
                failed_investigation.completed_at = datetime.now(timezone.utc)
                failed_db.commit()
            failed_db.close()
        except Exception as mark_err:
            logger.warning(f"Failed to mark investigation as FAILED: {mark_err}")
        try:
            yield emit("error", {"message": str(e)[:500]})
        except Exception as emit_err:
            logger.debug(f"SSE error emit failed: {emit_err}")


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
        Investigation.incident_id == incident.id,
        Investigation.organization_id == current_user.organization_id,
    ).first()
    if not investigation:
        investigation = Investigation(
            organization_id=current_user.organization_id,
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
    inc_repositories = [scope.repository.full_name for scope in incident.scopes if scope.repository]
    inc_service = incident.service_name
    inv_id = investigation.id
    inc_id = incident.id

    repo_name = request.repository
    user_token = _get_user_github_token(current_user, db, repository=repo_name)
    return StreamingResponse(
        _stream_investigation(inc_id, inv_id, inc_title, inc_desc, inc_sig, inc_repositories, inc_service, repo_name, request.service, github_token=user_token),
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
    investigation = db.query(Investigation).filter(
        Investigation.id == investigation_id,
        Investigation.organization_id == current_user.organization_id,
    ).first()
    if not investigation:
        raise HTTPException(status_code=404, detail="Investigation not found")

    evidence = db.query(Evidence).filter(
        Evidence.investigation_id == investigation_id,
        Evidence.organization_id == current_user.organization_id,
    ).all()
    hypotheses = db.query(HypothesisModel).filter(
        HypothesisModel.investigation_id == investigation_id,
        HypothesisModel.organization_id == current_user.organization_id,
    ).all()

    evidence_by_source = {}
    for ev in evidence:
        src = ev.source_type or "unknown"
        evidence_by_source[src] = evidence_by_source.get(src, 0) + 1

    return {
        "investigation_id": investigation_id,
        "status": investigation.status,
        "confidence": investigation.confidence,
        "tasks_completed": len(evidence),
        "tasks_failed": 0,
        "evidence_total": len(evidence),
        "evidence_by_source": evidence_by_source,
        "hypotheses_total": len(hypotheses),
        "hypotheses_supported": sum(1 for h in hypotheses if h.status == "supported"),
        "started_at": investigation.started_at.isoformat() if investigation.started_at else None,
        "completed_at": investigation.completed_at.isoformat() if investigation.completed_at else None,
    }
