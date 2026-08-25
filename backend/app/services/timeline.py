"""Investigation timeline — chronological event view."""
from typing import List, Dict, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.incident import (
    Incident, Investigation, InvestigationTask, Evidence,
    Hypothesis, RootCause, ProposedFix, Approval, AuditEvent,
)


def build_timeline(incident_id: str, db: Session) -> List[Dict]:
    """Build a chronological timeline of all investigation events."""
    events = []

    # Get incident
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        return events

    # Incident created
    if incident.created_at:
        events.append({
            "time": incident.created_at.isoformat(),
            "type": "incident_created",
            "label": "Incident created",
            "detail": f"INC-{incident.number}: {incident.title}",
            "icon": "add_circle",
            "color": "error",
        })

    # Detection signal
    if incident.detected_at and incident.detected_at != incident.created_at:
        events.append({
            "time": incident.detected_at.isoformat(),
            "type": "signal_detected",
            "label": "Signal detected",
            "detail": f"Source: {incident.source.value if incident.source else 'unknown'}",
            "icon": "notification_important",
            "color": "tertiary",
        })

    # Get investigation
    investigation = db.query(Investigation).filter(
        Investigation.incident_id == incident_id
    ).first()

    if investigation:
        # Investigation started
        if investigation.started_at:
            events.append({
                "time": investigation.started_at.isoformat(),
                "type": "investigation_started",
                "label": "Investigation started",
                "detail": f"Model: {investigation.llm_model or 'auto'}",
                "icon": "psychology",
                "color": "primary",
            })

        # Tasks completed
        tasks = db.query(InvestigationTask).filter(
            InvestigationTask.investigation_id == investigation.id
        ).order_by(InvestigationTask.completed_at).all()

        for task in tasks:
            if task.completed_at:
                events.append({
                    "time": task.completed_at.isoformat(),
                    "type": "task_completed",
                    "label": f"Task: {task.tool_name or task.task_type}",
                    "detail": task.description or "",
                    "icon": "check_circle" if task.status == "completed" else "error",
                    "color": "primary" if task.status == "completed" else "error",
                })

        # Evidence collected
        evidence = db.query(Evidence).filter(
            Evidence.investigation_id == investigation.id
        ).order_by(Evidence.collected_at).all()

        evidence_by_time = {}
        for ev in evidence:
            if ev.collected_at:
                t = ev.collected_at.isoformat()
                if t not in evidence_by_time:
                    evidence_by_time[t] = []
                evidence_by_time[t].append(ev)

        for time_str, evs in evidence_by_time.items():
            events.append({
                "time": time_str,
                "type": "evidence_collected",
                "label": f"Evidence collected ({len(evs)} items)",
                "detail": ", ".join([e.source_type.value for e in evs[:3]]),
                "icon": "description",
                "color": "tertiary",
            })

        # Hypotheses generated
        hypotheses = db.query(Hypothesis).filter(
            Hypothesis.investigation_id == investigation.id
        ).order_by(Hypothesis.created_at).all()

        if hypotheses and hypotheses[0].created_at:
            events.append({
                "time": hypotheses[0].created_at.isoformat(),
                "type": "hypotheses_generated",
                "label": f"Hypotheses generated ({len(hypotheses)})",
                "detail": ", ".join([h.label[:30] for h in hypotheses[:3]]),
                "icon": "lightbulb",
                "color": "tertiary",
            })

        # Root cause identified
        root_cause = db.query(RootCause).filter(
            RootCause.investigation_id == investigation.id
        ).first()

        if root_cause and root_cause.identified_at:
            events.append({
                "time": root_cause.identified_at.isoformat(),
                "type": "root_cause_identified",
                "label": "Root cause identified",
                "detail": root_cause.summary[:100] if root_cause.summary else "",
                "icon": "track_changes",
                "color": "primary",
            })

        # Fix generated
        fixes = db.query(ProposedFix).filter(
            ProposedFix.investigation_id == investigation.id
        ).order_by(ProposedFix.generated_at).all()

        for fix in fixes:
            if fix.generated_at:
                events.append({
                    "time": fix.generated_at.isoformat(),
                    "type": "fix_generated",
                    "label": f"Fix: {fix.title[:50]}",
                    "detail": f"Type: {fix.fix_type}",
                    "icon": "code",
                    "color": "tertiary",
                })

        # Investigation completed
        if investigation.completed_at:
            events.append({
                "time": investigation.completed_at.isoformat(),
                "type": "investigation_completed",
                "label": "Investigation completed",
                "detail": f"Confidence: {investigation.confidence or 'unknown'}",
                "icon": "task_alt",
                "color": "primary" if investigation.root_cause_found else "tertiary",
            })

    # Approvals
    approvals = db.query(Approval).filter(
        Approval.incident_id == incident_id
    ).order_by(Approval.decided_at).all()

    for approval in approvals:
        if approval.decided_at:
            events.append({
                "time": approval.decided_at.isoformat(),
                "type": "approval",
                "label": f"Approval: {approval.status.value}",
                "detail": approval.notes[:100] if approval.notes else "",
                "icon": "thumb_up" if approval.status.value == "approved" else "thumb_down",
                "color": "primary" if approval.status.value == "approved" else "error",
            })

    # Sort by time
    events.sort(key=lambda e: e["time"])

    return events
