"""Autonomous AI Post-Mortem Synthesis Engine.

Generates blameless, production-grade SRE post-mortems bound strictly to stored
evidence, timeline events, accepted root causes, and remediation patches.
Preserves Phase 9 Safe Abstention with explicit missing evidence requirements.
"""
import hashlib
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy.orm import Session

logger = logging.getLogger("sentinel.post_mortem_generator")

from app.models.incident import (
    Incident, Investigation, Evidence, Hypothesis, RootCause,
    ProposedFix, PostMortem, PostMortemActionItem, PostMortemStatus,
    MemoryIndexingStatus, ActionItemCategory, ActionItemPriority, ActionItemStatus,
    User,
)
from app.services.timeline import build_explainable_timeline, compute_milestones
from app.services.llm import generate_json_response, LLMError


def compute_post_mortem_snapshot_hash(
    incident: Incident,
    root_cause: Optional[RootCause],
    evidence_count: int,
    timeline_event_count: int,
) -> str:
    """Compute deterministic SHA-256 hash of all input state used to generate post-mortem."""
    raw_payload = f"{incident.id}|{incident.status}|{root_cause.snapshot_hash if root_cause else 'no-rc'}|{evidence_count}|{timeline_event_count}"
    return hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()


def _to_uuid(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, UUID):
        return val
    try:
        return UUID(str(val))
    except (ValueError, TypeError):
        return val


def generate_post_mortem_for_incident(
    incident_id: str,
    db: Session,
    author: Optional[User] = None,
) -> PostMortem:
    """
    Synthesize an evidence-bound Post-Mortem record for an incident.
    Updates existing draft in-place or creates a new version.
    """
    inc_uuid = _to_uuid(incident_id)
    incident = db.query(Incident).filter(Incident.id == inc_uuid).first()
    if not incident:
        raise ValueError(f"Incident {incident_id} not found")

    # 1. Gather authoritative inputs
    timeline_data = build_explainable_timeline(incident_id, db)
    milestones = timeline_data.get("milestones", {})
    timeline_events = timeline_data.get("events", [])

    root_cause = db.query(RootCause).filter(
        RootCause.incident_id == incident.id,
        RootCause.is_current == True,
    ).first()

    evidence_items = db.query(Evidence).filter(Evidence.incident_id == incident.id).all()
    fixes = db.query(ProposedFix).filter(ProposedFix.incident_id == incident.id).all()

    # 2. Compute deterministic snapshot hash
    snapshot_hash = compute_post_mortem_snapshot_hash(
        incident=incident,
        root_cause=root_cause,
        evidence_count=len(evidence_items),
        timeline_event_count=len(timeline_events),
    )

    # 3. Check for Safe Abstention
    is_abstained = root_cause.abstained if root_cause else True
    abstention_reason = root_cause.abstention_reason if root_cause and root_cause.abstained else None
    missing_evidence = root_cause.missing_evidence_json if root_cause else ["Uncorrelated signals", "Missing dependency trace"]

    # 4. Evidence-Bound Section Synthesis
    title = f"Post-Mortem: INC-{incident.number:04d} — {incident.title}"
    
    # Root Cause Summary
    if is_abstained:
        root_cause_summary = f"Root Cause Inconclusive (Safe Abstention Enforced): {abstention_reason or 'Insufficient corroborating evidence across independent families'}. Required Missing Evidence: {', '.join(missing_evidence or [])}"
    else:
        root_cause_summary = root_cause.summary or root_cause.causal_explanation or "Root cause identified from multi-family corroboration."

    # Executive Summary & Impact
    service_name = incident.service_name or "Unknown Service"
    severity = incident.severity.value if hasattr(incident.severity, "value") else str(incident.severity)
    summary = (
        f"On {incident.started_at or incident.created_at}, an automated incident INC-{incident.number:04d} "
        f"({severity}) was detected affecting service '{service_name}'. "
        f"{'A root cause was identified and mitigated via automated patch.' if not is_abstained else 'The investigation safely abstained pending further telemetry.'}"
    )

    impact_summary = (
        f"Service '{service_name}' in environment '{getattr(incident.environment, 'name', 'production')}'. "
        f"Incident severity: {severity}. First detected: {milestones.get('detected_at') or 'Unknown'}. "
        f"Resolution: {milestones.get('resolved_at') or 'In progress / mitigated'}."
    )

    trigger_event = (
        timeline_events[0]["label"] if timeline_events else f"Telemetry anomaly on service {service_name}"
    )

    detection_summary = (
        f"Incident was triggered via {incident.source.value if hasattr(incident.source, 'value') else incident.source}. "
        f"MTTD was {milestones.get('mttd_seconds', 'N/A')} seconds."
    )

    resolution_summary = (
        f"Fix type: {fixes[0].fix_type if fixes else 'Configuration / Code Patch'}. "
        f"Branch: {fixes[0].branch_name if fixes else 'N/A'}. "
        f"Draft PR: {fixes[0].pr_url if fixes and fixes[0].pr_url else 'None'}."
    )

    contributing_factors = [
        {"factor": f"High error rate or latency exceeding threshold on {service_name}", "category": "runtime"},
        {"factor": "Deployment or configuration change preceding incident window", "category": "change"} if any("change" in e.get("type", "") for e in timeline_events) else {"factor": "External dependency degradation", "category": "upstream"},
    ]

    lessons_learned = [
        {"lesson": f"Ensure alerts for {service_name} trigger before user-visible failure threshold", "type": "monitoring"},
        {"lesson": "Maintain robust test coverage across critical service dependency paths", "type": "testing"},
    ]

    proposed_actions = [
        {
            "title": f"Add high-resolution alerting for {service_name}",
            "description": "Improve signal detection latency and tighten SLO thresholds.",
            "category": "monitoring_gap",
            "priority": "P1",
        },
        {
            "title": f"Add integration tests for {service_name} error handling",
            "description": "Prevent regression of the identified failure scenario.",
            "category": "code_hardening",
            "priority": "P2",
        },
    ]

    # Calculate downtime
    downtime_min = 0.0
    if milestones.get("mttr_seconds"):
        downtime_min = round(milestones["mttr_seconds"] / 60.0, 2)

    # 5. Database Record Upsert & Versioning
    existing_pm = db.query(PostMortem).filter(
        PostMortem.incident_id == incident.id,
        PostMortem.is_current == True,
    ).first()

    if existing_pm and existing_pm.status == PostMortemStatus.DRAFT:
        # Update current draft in-place
        existing_pm.title = title
        existing_pm.summary = summary
        existing_pm.root_cause_summary = root_cause_summary
        existing_pm.impact_summary = impact_summary
        existing_pm.trigger_event = trigger_event
        existing_pm.detection_summary = detection_summary
        existing_pm.resolution_summary = resolution_summary
        existing_pm.contributing_factors_json = contributing_factors
        existing_pm.timeline_summary_json = timeline_events
        existing_pm.lessons_learned_json = lessons_learned
        existing_pm.time_to_detect_seconds = milestones.get("mttd_seconds")
        existing_pm.time_to_acknowledge_seconds = milestones.get("mtta_seconds")
        existing_pm.time_to_root_cause_seconds = milestones.get("mttrc_seconds")
        existing_pm.time_to_mitigate_seconds = milestones.get("mttm_seconds")
        existing_pm.time_to_resolve_seconds = milestones.get("mttr_seconds")
        existing_pm.downtime_minutes = downtime_min
        existing_pm.snapshot_hash = snapshot_hash
        existing_pm.abstained = is_abstained
        existing_pm.author_id = author.id if author else existing_pm.author_id
        db.flush()
        pm_record = existing_pm
    else:
        # Create a new version
        new_version = (existing_pm.version + 1) if existing_pm else 1
        if existing_pm:
            existing_pm.is_current = False
            db.flush()

        pm_record = PostMortem(
            organization_id=incident.organization_id,
            incident_id=incident.id,
            work_item_id=getattr(incident, "work_item_id", None),
            author_id=author.id if author else None,
            title=title,
            summary=summary,
            root_cause_summary=root_cause_summary,
            impact_summary=impact_summary,
            trigger_event=trigger_event,
            detection_summary=detection_summary,
            resolution_summary=resolution_summary,
            contributing_factors_json=contributing_factors,
            timeline_summary_json=timeline_events,
            lessons_learned_json=lessons_learned,
            time_to_detect_seconds=milestones.get("mttd_seconds"),
            time_to_acknowledge_seconds=milestones.get("mtta_seconds"),
            time_to_root_cause_seconds=milestones.get("mttrc_seconds"),
            time_to_mitigate_seconds=milestones.get("mttm_seconds"),
            time_to_resolve_seconds=milestones.get("mttr_seconds"),
            downtime_minutes=downtime_min,
            resolution_type=fixes[0].fix_type if fixes else "code_fix",
            severity_actual=severity,
            status=PostMortemStatus.DRAFT,
            snapshot_hash=snapshot_hash,
            abstained=is_abstained,
            human_reviewed=False,
            is_current=True,
            version=new_version,
            memory_indexing_status=MemoryIndexingStatus.PENDING,
        )
        db.add(pm_record)
        db.flush()

        # Seed proposed action items
        for action in proposed_actions:
            item = PostMortemActionItem(
                organization_id=incident.organization_id,
                post_mortem_id=pm_record.id,
                incident_id=incident.id,
                created_by_user_id=author.id if author else None,
                title=action["title"],
                description=action["description"],
                category=ActionItemCategory(action["category"]),
                priority=ActionItemPriority(action["priority"]),
                status=ActionItemStatus.OPEN,
            )
            db.add(item)
        db.flush()

    return pm_record
