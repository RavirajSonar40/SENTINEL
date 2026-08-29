"""Investigation timeline — deterministic explainable timeline engine.

Reconstructs chronological and causal event graphs from authoritative source-of-truth tables:
- Change Intelligence pre-incident events (deployments, config changes)
- Ingested Telemetry & Detection Signals
- Incident creation and state transitions
- Service Graph blast radius reports
- Investigation execution and tool tasks
- Multi-source Evidence items with family groupings
- Competing Hypotheses and adversarial disproofs
- Root Cause identification or Safe Abstention
- Remediation fixes, isolated validation runs, approvals, and Draft PRs
- SRE Latency Milestones (MTTD, MTTA, MTTRC, MTTM, MTTR)
"""
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone, timedelta
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.incident import (
    Incident, Investigation, InvestigationTask, Evidence,
    Hypothesis, RootCause, ProposedFix, Approval, AuditEvent,
    TelemetrySignal, IncidentSignal, ChangeEvent, IncidentBlastRadiusReport,
    PostMortem,
)
from app.schemas.incident_memory import TimelineEventOut, TimelineMilestonesOut, ExplainableTimelineResponse


# Deterministic priority rank for tie-breaking events with identical timestamps
EVENT_PRIORITY_RANK = {
    "deployment": 1,
    "change_event": 2,
    "signal_detected": 3,
    "incident_created": 4,
    "blast_radius_computed": 5,
    "investigation_started": 6,
    "task_completed": 7,
    "evidence_collected": 8,
    "hypotheses_generated": 9,
    "hypothesis_evaluated": 10,
    "root_cause_identified": 11,
    "root_cause_abstained": 12,
    "fix_generated": 13,
    "validation_run": 14,
    "approval_requested": 15,
    "approval_decided": 16,
    "pr_published": 17,
    "incident_resolved": 18,
    "post_mortem_published": 19,
    "human_audit_action": 20,
}


def _parse_time(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _calc_duration_seconds(start: Optional[datetime], end: Optional[datetime]) -> Optional[int]:
    """Calculate duration in seconds between two timestamps. Returns None if either is missing."""
    if not start or not end:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    diff = int((end - start).total_seconds())
    return max(0, diff)


def compute_milestones(incident: Incident, db: Session) -> Dict[str, Any]:
    """
    Deterministically compute exact SRE reliability milestones for an incident:
    - MTTD (Mean Time to Detect): incident.detected_at - incident.started_at
    - MTTA (Mean Time to Acknowledge): first_human_ack / investigation.started_at - incident.detected_at
    - MTTRC (Mean Time to Root Cause): root_cause.identified_at - incident.started_at/detected_at
    - MTTM (Mean Time to Mitigate): first_approved_fix_or_pr - incident.detected_at
    - MTTR (Mean Time to Resolve): incident.resolved_at - incident.started_at/detected_at
    
    Returns None for any missing milestone boundary (never 0).
    """
    onset = incident.started_at or incident.created_at
    detected = incident.detected_at or incident.first_signal_at or incident.created_at
    
    # MTTD
    mttd = _calc_duration_seconds(incident.started_at, incident.detected_at) if incident.started_at and incident.detected_at else None

    # MTTA
    investigation = db.query(Investigation).filter(Investigation.incident_id == incident.id).first()
    ack_time = None
    if investigation and investigation.started_at:
        ack_time = investigation.started_at
    elif incident.status.value != "created":
        ack_time = incident.updated_at

    mtta = _calc_duration_seconds(detected, ack_time) if detected and ack_time else None

    # MTTRC
    root_cause = db.query(RootCause).filter(RootCause.incident_id == incident.id, RootCause.is_current == True).first()
    rc_time = root_cause.identified_at if root_cause else None
    baseline_onset = incident.started_at or detected
    mttrc = _calc_duration_seconds(baseline_onset, rc_time) if baseline_onset and rc_time else None

    # MTTM
    first_fix = db.query(ProposedFix).filter(ProposedFix.incident_id == incident.id).order_by(ProposedFix.generated_at.asc()).first()
    mitigate_time = None
    if first_fix:
        mitigate_time = first_fix.generated_at
    mttm = _calc_duration_seconds(detected, mitigate_time) if detected and mitigate_time else None

    # MTTR
    resolved_time = incident.resolved_at
    mttr = _calc_duration_seconds(baseline_onset, resolved_time) if baseline_onset and resolved_time else None

    return {
        "mttd_seconds": mttd,
        "mtta_seconds": mtta,
        "mttrc_seconds": mttrc,
        "mttm_seconds": mttm,
        "mttr_seconds": mttr,
        "started_at": _parse_time(incident.started_at),
        "detected_at": _parse_time(detected),
        "acknowledged_at": _parse_time(ack_time),
        "root_cause_at": _parse_time(rc_time),
        "mitigated_at": _parse_time(mitigate_time),
        "resolved_at": _parse_time(resolved_time),
    }


def _to_uuid(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, UUID):
        return val
    try:
        return UUID(str(val))
    except (ValueError, TypeError):
        return val


def build_explainable_timeline(incident_id: str, db: Session) -> Dict[str, Any]:
    """
    Build a comprehensive, causal, explainable chronological event graph for an incident.
    """
    inc_uuid = _to_uuid(incident_id)
    incident = db.query(Incident).filter(Incident.id == inc_uuid).first()
    if not incident:
        return {
            "incident_id": str(incident_id),
            "milestones": {
                "mttd_seconds": None,
                "mtta_seconds": None,
                "mttrc_seconds": None,
                "mttm_seconds": None,
                "mttr_seconds": None,
                "started_at": None,
                "detected_at": None,
                "acknowledged_at": None,
                "root_cause_at": None,
                "mitigated_at": None,
                "resolved_at": None,
            },
            "total_events": 0,
            "events": [],
        }

    raw_events: List[Dict[str, Any]] = []
    
    incident_event_id = f"inc-{incident.id}"
    last_signal_event_id: Optional[str] = None
    investigation_event_id: Optional[str] = None
    root_cause_event_id: Optional[str] = None
    fix_event_id: Optional[str] = None

    # 1. Pre-Incident Change Intelligence Events (within 24h prior to onset)
    onset_time = incident.started_at or incident.detected_at or incident.created_at
    if onset_time and incident.organization_id:
        window_start = onset_time - timedelta(hours=24)
        changes = db.query(ChangeEvent).filter(
            ChangeEvent.organization_id == incident.organization_id,
            ChangeEvent.effective_at >= window_start,
            ChangeEvent.effective_at <= onset_time + timedelta(minutes=15),
        ).order_by(ChangeEvent.effective_at.asc()).all()

        for ch in changes:
            evt_id = f"chg-{ch.id}"
            raw_events.append({
                "id": evt_id,
                "time": _parse_time(ch.effective_at),
                "type": "change_event",
                "category": "deployment" if "DEPLOYMENT" in ch.change_type.value else "change",
                "label": f"Change: {ch.title}",
                "detail": f"{ch.change_type.value} on {ch.provider} | Risk: {ch.risk_level.value if ch.risk_level else 'UNKNOWN'}",
                "icon": "deployed_code" if "DEPLOYMENT" in ch.change_type.value else "tune",
                "color": "secondary",
                "actor": "system",
                "parent_event_id": None,
                "causal_relation": "preceding_change",
                "inferred_timestamp": False,
                "metadata": {"change_id": str(ch.id), "change_type": ch.change_type.value, "provider": ch.provider},
                "_raw_dt": ch.effective_at,
            })

    # 2. Telemetry & Ingestion Signals
    signals = db.query(TelemetrySignal).filter(TelemetrySignal.incident_id == incident.id).order_by(TelemetrySignal.observed_at.asc()).all()
    for sig in signals:
        evt_id = f"sig-{sig.id}"
        last_signal_event_id = evt_id
        raw_events.append({
            "id": evt_id,
            "time": _parse_time(sig.observed_at or sig.created_at),
            "type": "signal_detected",
            "category": "telemetry",
            "label": f"Signal: {sig.signal_type.value if hasattr(sig.signal_type, 'value') else sig.signal_type}",
            "detail": f"{sig.title or ''} ({sig.provider.value if hasattr(sig.provider, 'value') else sig.provider}) | Value: {sig.metric_value} ({sig.metric_name or ''})".strip(),
            "icon": "sensors",
            "color": "error" if "CRITICAL" in str(getattr(sig, "severity", "")) or "ERROR" in str(sig.signal_type) else "warning",
            "actor": "system",
            "parent_event_id": raw_events[0]["id"] if raw_events else None,
            "causal_relation": "triggered_by_change" if raw_events else "telemetry_anomaly",
            "inferred_timestamp": False,
            "metadata": {"signal_id": str(sig.id), "provider": sig.provider.value if hasattr(sig.provider, 'value') else str(sig.provider)},
            "_raw_dt": sig.observed_at or sig.created_at,
        })

    # 3. Incident Creation
    raw_events.append({
        "id": incident_event_id,
        "time": _parse_time(incident.created_at),
        "type": "incident_created",
        "category": "incident",
        "label": f"Incident Created: INC-{incident.number:04d}",
        "detail": f"{incident.title} | Severity: {incident.severity.value if hasattr(incident.severity, 'value') else incident.severity}",
        "icon": "warning",
        "color": "error",
        "actor": "system" if incident.source and incident.source.value != "manual" else "human",
        "parent_event_id": last_signal_event_id,
        "causal_relation": "correlated_from_signals" if last_signal_event_id else None,
        "inferred_timestamp": False,
        "metadata": {"incident_number": incident.number, "severity": incident.severity.value if hasattr(incident.severity, 'value') else str(incident.severity)},
        "_raw_dt": incident.created_at,
    })

    # 4. Service Graph Blast Radius Reports
    blast_reports = db.query(IncidentBlastRadiusReport).filter(IncidentBlastRadiusReport.incident_id == incident.id).all()
    for br in blast_reports:
        raw_events.append({
            "id": f"br-{br.id}",
            "time": _parse_time(br.calculated_at),
            "type": "blast_radius_computed",
            "category": "investigation",
            "label": f"Blast Radius Analyzed (v{br.version})",
            "detail": f"Direct Services: {len(br.direct_services or [])}, Indirect: {len(br.indirect_services or [])}, Repos: {len(br.affected_repositories or [])}",
            "icon": "hub",
            "color": "tertiary",
            "actor": "ai",
            "parent_event_id": incident_event_id,
            "causal_relation": "topology_impact_evaluation",
            "inferred_timestamp": False,
            "metadata": {"version": br.version, "direct_count": len(br.direct_services or [])},
            "_raw_dt": br.calculated_at,
        })

    # 5. Investigation & Tasks
    investigation = db.query(Investigation).filter(Investigation.incident_id == incident.id).first()
    if investigation:
        investigation_event_id = f"inv-{investigation.id}"
        if investigation.started_at:
            raw_events.append({
                "id": investigation_event_id,
                "time": _parse_time(investigation.started_at),
                "type": "investigation_started",
                "category": "investigation",
                "label": "Autonomous Investigation Started",
                "detail": f"Model: {investigation.llm_model or 'Nemotron-70B'} | Plan steps: {len(investigation.plan_json or [])}",
                "icon": "psychology",
                "color": "primary",
                "actor": "ai",
                "parent_event_id": incident_event_id,
                "causal_relation": "investigation_dispatch",
                "inferred_timestamp": False,
                "metadata": {"investigation_id": str(investigation.id)},
                "_raw_dt": investigation.started_at,
            })

        # Tasks
        tasks = db.query(InvestigationTask).filter(InvestigationTask.investigation_id == investigation.id).order_by(InvestigationTask.order.asc()).all()
        for task in tasks:
            task_dt = task.completed_at or task.started_at or (investigation.started_at + timedelta(seconds=task.order * 2) if investigation.started_at else incident.created_at)
            raw_events.append({
                "id": f"task-{task.id}",
                "time": _parse_time(task_dt),
                "type": "task_completed",
                "category": "investigation",
                "label": f"Task: {task.step_name or task.task_type}",
                "detail": f"{task.description or task.tool_name or ''} (Duration: {task.duration_ms}ms, Status: {task.status.value if hasattr(task.status, 'value') else task.status})",
                "icon": "check_circle" if str(task.status) in ("TaskStatus.COMPLETED", "completed") else "error",
                "color": "primary" if str(task.status) in ("TaskStatus.COMPLETED", "completed") else "error",
                "actor": "ai",
                "parent_event_id": investigation_event_id,
                "causal_relation": "step_execution",
                "inferred_timestamp": task.completed_at is None and task.started_at is None,
                "metadata": {"task_id": str(task.id), "tool_name": task.tool_name},
                "_raw_dt": task_dt,
            })

    # 6. Evidence Items Harvested
    evidence_items = db.query(Evidence).filter(Evidence.incident_id == incident.id).order_by(Evidence.collected_at.asc()).all()
    for ev in evidence_items:
        raw_events.append({
            "id": f"ev-{ev.id}",
            "time": _parse_time(ev.collected_at or ev.observed_at or incident.created_at),
            "type": "evidence_collected",
            "category": "evidence",
            "label": f"Evidence: {ev.title}",
            "detail": f"Family: {ev.evidence_family.value if ev.evidence_family else 'unclassified'} | Source: {ev.source_type.value if hasattr(ev.source_type, 'value') else ev.source_type} | Trust: {ev.trust_level.value if hasattr(ev.trust_level, 'value') else ev.trust_level}",
            "icon": "inventory_2",
            "color": "tertiary",
            "actor": "human" if ev.submitted_by_user_id else "ai",
            "parent_event_id": investigation_event_id,
            "causal_relation": "evidence_harvested",
            "inferred_timestamp": ev.collected_at is None,
            "metadata": {"evidence_id": str(ev.id), "content_hash": ev.content_hash, "is_redacted": ev.is_redacted},
            "_raw_dt": ev.collected_at or ev.observed_at or incident.created_at,
        })

    # 7. Hypotheses Evaluated & Disproved
    hypotheses = db.query(Hypothesis).filter(Hypothesis.incident_id == incident.id).order_by(Hypothesis.created_at.asc()).all()
    for hyp in hypotheses:
        hyp_dt = hyp.evaluated_at or hyp.created_at or (investigation.started_at if investigation else incident.created_at)
        raw_events.append({
            "id": f"hyp-{hyp.id}",
            "time": _parse_time(hyp_dt),
            "type": "hypothesis_evaluated",
            "category": "hypothesis",
            "label": f"Hypothesis: {hyp.label}",
            "detail": f"Status: {hyp.status.value.upper() if hasattr(hyp.status, 'value') else hyp.status} | Distinct Families: {hyp.distinct_families_count} | Confidence: {hyp.confidence.value if hasattr(hyp.confidence, 'value') else hyp.confidence}",
            "icon": "lightbulb" if str(hyp.status) in ("HypothesisStatus.ACCEPTED", "accepted") else "psychology_alt",
            "color": "primary" if str(hyp.status) in ("HypothesisStatus.ACCEPTED", "accepted") else "tertiary",
            "actor": "human" if hyp.human_triaged else "ai",
            "parent_event_id": investigation_event_id,
            "causal_relation": "hypothesis_verification",
            "inferred_timestamp": hyp.evaluated_at is None and hyp.created_at is None,
            "metadata": {"hypothesis_id": str(hyp.id), "status": str(hyp.status), "human_triaged": hyp.human_triaged},
            "_raw_dt": hyp_dt,
        })

    # 8. Root Cause Identified / Abstained
    root_cause = db.query(RootCause).filter(RootCause.incident_id == incident.id, RootCause.is_current == True).first()
    if root_cause:
        root_cause_event_id = f"rc-{root_cause.id}"
        is_abstained = bool(root_cause.abstained)
        raw_events.append({
            "id": root_cause_event_id,
            "time": _parse_time(root_cause.identified_at or incident.created_at),
            "type": "root_cause_abstained" if is_abstained else "root_cause_identified",
            "category": "root_cause",
            "label": "Safe Abstention (Inconclusive)" if is_abstained else "Root Cause Identified",
            "detail": root_cause.abstention_reason if is_abstained else (root_cause.summary or root_cause.causal_explanation or ""),
            "icon": "cancel" if is_abstained else "crisis_alert",
            "color": "warning" if is_abstained else "primary",
            "actor": "human" if root_cause.human_overridden else "ai",
            "parent_event_id": investigation_event_id,
            "causal_relation": "causal_synthesis",
            "inferred_timestamp": root_cause.identified_at is None,
            "metadata": {"root_cause_id": str(root_cause.id), "abstained": is_abstained, "confidence": root_cause.confidence.value if hasattr(root_cause.confidence, 'value') else str(root_cause.confidence)},
            "_raw_dt": root_cause.identified_at or incident.created_at,
        })

    # 9. Proposed Fixes & Validations
    fixes = db.query(ProposedFix).filter(ProposedFix.incident_id == incident.id).order_by(ProposedFix.generated_at.asc()).all()
    for fix in fixes:
        fix_event_id = f"fix-{fix.id}"
        raw_events.append({
            "id": fix_event_id,
            "time": _parse_time(fix.generated_at or incident.created_at),
            "type": "fix_generated",
            "category": "remediation",
            "label": f"Remediation: {fix.title}",
            "detail": f"Type: {fix.fix_type} | Repository: {fix.repository or 'unknown'} | Status: {fix.status}",
            "icon": "auto_fix_high",
            "color": "secondary",
            "actor": "ai",
            "parent_event_id": root_cause_event_id,
            "causal_relation": "remediation_patch_generation",
            "inferred_timestamp": fix.generated_at is None,
            "metadata": {"fix_id": str(fix.id), "fix_type": fix.fix_type, "pr_url": fix.pr_url},
            "_raw_dt": fix.generated_at or incident.created_at,
        })

        if fix.pr_url:
            raw_events.append({
                "id": f"pr-{fix.id}",
                "time": _parse_time(fix.generated_at or incident.created_at),
                "type": "pr_published",
                "category": "remediation",
                "label": f"GitHub Draft PR Created (#{fix.pr_number or ''})",
                "detail": f"Branch: {fix.branch_name or ''} | URL: {fix.pr_url}",
                "icon": "fork_right",
                "color": "primary",
                "actor": "ai",
                "parent_event_id": fix_event_id,
                "causal_relation": "pull_request_dispatch",
                "inferred_timestamp": False,
                "metadata": {"pr_url": fix.pr_url, "pr_number": fix.pr_number},
                "_raw_dt": fix.generated_at or incident.created_at,
            })

    # 10. Approvals & Human Actions
    approvals = db.query(Approval).filter(Approval.incident_id == incident.id).order_by(Approval.decided_at.asc()).all()
    for app in approvals:
        raw_events.append({
            "id": f"app-{app.id}",
            "time": _parse_time(app.decided_at or incident.created_at),
            "type": "approval_decided",
            "category": "human_action",
            "label": f"Human Approval: {app.status.value.upper() if hasattr(app.status, 'value') else app.status}",
            "detail": app.notes or f"Decision for fix by user {app.user_id or 'admin'}",
            "icon": "thumb_up" if str(app.status) in ("ApprovalStatus.APPROVED", "approved") else "thumb_down",
            "color": "primary" if str(app.status) in ("ApprovalStatus.APPROVED", "approved") else "error",
            "actor": "human",
            "parent_event_id": fix_event_id,
            "causal_relation": "human_governance",
            "inferred_timestamp": app.decided_at is None,
            "metadata": {"approval_id": str(app.id), "status": str(app.status)},
            "_raw_dt": app.decided_at or incident.created_at,
        })

    # 11. Incident Resolution
    if incident.resolved_at:
        raw_events.append({
            "id": f"res-{incident.id}",
            "time": _parse_time(incident.resolved_at),
            "type": "incident_resolved",
            "category": "incident",
            "label": "Incident Resolved",
            "detail": f"Resolved at {_parse_time(incident.resolved_at)}. All systems operational.",
            "icon": "task_alt",
            "color": "primary",
            "actor": "human",
            "parent_event_id": fix_event_id or incident_event_id,
            "causal_relation": "resolution_completion",
            "inferred_timestamp": False,
            "metadata": {"resolved_at": _parse_time(incident.resolved_at)},
            "_raw_dt": incident.resolved_at,
        })

    # 12. Post-Mortem Publication
    post_mortem = db.query(PostMortem).filter(PostMortem.incident_id == incident.id, PostMortem.is_current == True).first()
    if post_mortem and post_mortem.published_at:
        raw_events.append({
            "id": f"pm-{post_mortem.id}",
            "time": _parse_time(post_mortem.published_at),
            "type": "post_mortem_published",
            "category": "human_action",
            "label": f"Post-Mortem Published (v{post_mortem.version})",
            "detail": f"{post_mortem.title} | Signed off by user {post_mortem.signed_off_by_user_id or 'admin'}",
            "icon": "menu_book",
            "color": "primary",
            "actor": "human",
            "parent_event_id": f"res-{incident.id}" if incident.resolved_at else incident_event_id,
            "causal_relation": "institutional_memory_indexing",
            "inferred_timestamp": False,
            "metadata": {"post_mortem_id": str(post_mortem.id), "version": post_mortem.version},
            "_raw_dt": post_mortem.published_at,
        })

    # 13. Deterministic Sort & Tie-Breaking
    # Primary: Timestamp ASC (fallback to epoch 0 if missing)
    # Secondary: Event Priority Rank ASC
    # Tertiary: Event ID ASC (guarantees 100% deterministic ordering)
    def _sort_key(item: Dict[str, Any]):
        dt = item.get("_raw_dt")
        ts = dt.timestamp() if dt else 0.0
        evt_type = item.get("type", "")
        rank = EVENT_PRIORITY_RANK.get(evt_type, 99)
        evt_id = str(item.get("id", ""))
        return (ts, rank, evt_id)

    raw_events.sort(key=_sort_key)

    # Clean internal sort helper key
    cleaned_events = []
    for ev in raw_events:
        ev_copy = dict(ev)
        ev_copy.pop("_raw_dt", None)
        cleaned_events.append(ev_copy)

    milestones = compute_milestones(incident, db)

    return {
        "incident_id": str(incident.id),
        "milestones": milestones,
        "total_events": len(cleaned_events),
        "events": cleaned_events,
    }


def build_timeline(incident_id: str, db: Session) -> List[Dict]:
    """Legacy compatibility bridge returning list of timeline event dictionaries."""
    data = build_explainable_timeline(incident_id, db)
    return data.get("events", [])
