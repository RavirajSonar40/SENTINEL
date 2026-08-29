"""REST API routes for Phase 10 — Incident Memory, Explainable Timeline, and Post-Mortems."""
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger("sentinel.incident_memory_routes")

from app.core.database import get_db
from app.core.permissions import (
    require_viewer,
    require_member,
    require_operator,
    require_admin,
)
from app.models.incident import (
    Incident, User, PostMortem, PostMortemActionItem,
    PostMortemStatus, MemoryIndexingStatus, ActionItemStatus,
    ActionItemPriority, ActionItemCategory, AuditEvent,
    Organization, UserOrganizationMembership,
)
from app.schemas.incident_memory import (
    ExplainableTimelineResponse,
    TimelineEventOut,
    TimelineMilestonesOut,
    PostMortemCreate,
    PostMortemUpdate,
    PostMortemOut,
    PostMortemPublishRequest,
    ActionItemCreate,
    ActionItemUpdate,
    ActionItemOut,
    IncidentMemorySearchRequest,
    IncidentMemorySearchResult,
    IncidentMemorySearchResponse,
)
from app.services.timeline import build_explainable_timeline
from app.services.post_mortem_generator import generate_post_mortem_for_incident
from app.services.historical import index_post_mortem, search_similar_incidents

router = APIRouter(tags=["incident-memory"])


def _to_uuid(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, UUID):
        return val
    try:
        return UUID(str(val))
    except (ValueError, TypeError):
        return val


def _format_action_item(item: PostMortemActionItem) -> ActionItemOut:
    return ActionItemOut(
        id=str(item.id),
        organization_id=str(item.organization_id),
        post_mortem_id=str(item.post_mortem_id),
        incident_id=str(item.incident_id) if item.incident_id else None,
        assigned_to_user_id=str(item.assigned_to_user_id) if item.assigned_to_user_id else None,
        created_by_user_id=str(item.created_by_user_id) if item.created_by_user_id else None,
        title=item.title,
        description=item.description,
        category=item.category.value if hasattr(item.category, "value") else str(item.category),
        priority=item.priority.value if hasattr(item.priority, "value") else str(item.priority),
        status=item.status.value if hasattr(item.status, "value") else str(item.status),
        due_date=item.due_date.isoformat() if item.due_date else None,
        completed_at=item.completed_at.isoformat() if item.completed_at else None,
        external_issue_url=item.external_issue_url,
        notes=item.notes,
        created_at=item.created_at.isoformat() if item.created_at else datetime.now(timezone.utc).isoformat(),
        updated_at=item.updated_at.isoformat() if item.updated_at else None,
    )


def _format_post_mortem(pm: PostMortem) -> PostMortemOut:
    return PostMortemOut(
        id=str(pm.id),
        organization_id=str(pm.organization_id),
        incident_id=str(pm.incident_id),
        work_item_id=str(pm.work_item_id) if pm.work_item_id else None,
        author_id=str(pm.author_id) if pm.author_id else None,
        signed_off_by_user_id=str(pm.signed_off_by_user_id) if pm.signed_off_by_user_id else None,
        title=pm.title,
        summary=pm.summary,
        root_cause_summary=pm.root_cause_summary,
        impact_summary=pm.impact_summary,
        trigger_event=pm.trigger_event,
        detection_summary=pm.detection_summary,
        resolution_summary=pm.resolution_summary,
        contributing_factors_json=pm.contributing_factors_json or [],
        timeline_summary_json=pm.timeline_summary_json or [],
        lessons_learned_json=pm.lessons_learned_json or [],
        time_to_detect_seconds=pm.time_to_detect_seconds,
        time_to_acknowledge_seconds=pm.time_to_acknowledge_seconds,
        time_to_root_cause_seconds=pm.time_to_root_cause_seconds,
        time_to_mitigate_seconds=pm.time_to_mitigate_seconds,
        time_to_resolve_seconds=pm.time_to_resolve_seconds,
        downtime_minutes=pm.downtime_minutes or 0.0,
        affected_user_count_estimate=pm.affected_user_count_estimate,
        slo_impact_percent=pm.slo_impact_percent,
        resolution_type=pm.resolution_type,
        severity_actual=pm.severity_actual,
        status=pm.status.value if hasattr(pm.status, "value") else str(pm.status),
        snapshot_hash=pm.snapshot_hash,
        abstained=pm.abstained,
        human_reviewed=pm.human_reviewed,
        is_current=pm.is_current,
        version=pm.version,
        memory_indexing_status=pm.memory_indexing_status.value if hasattr(pm.memory_indexing_status, "value") else str(pm.memory_indexing_status),
        memory_indexing_error=pm.memory_indexing_error,
        signed_off_at=pm.signed_off_at.isoformat() if pm.signed_off_at else None,
        published_at=pm.published_at.isoformat() if pm.published_at else None,
        created_at=pm.created_at.isoformat() if pm.created_at else datetime.now(timezone.utc).isoformat(),
        updated_at=pm.updated_at.isoformat() if pm.updated_at else None,
        action_items=[_format_action_item(item) for item in (pm.action_items or [])],
    )


# ============================================================================
# 1. EXPLAINABLE TIMELINE ENDPOINTS
# ============================================================================

@router.get("/incidents/{incident_id}/timeline", response_model=ExplainableTimelineResponse)
def get_incident_timeline(
    incident_id: str,
    db: Session = Depends(get_db),
    org_membership: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
):
    """Retrieve complete explainable causal timeline with SRE latency milestones."""
    org, membership = org_membership
    inc_uuid = _to_uuid(incident_id)
    incident = db.query(Incident).filter(
        Incident.id == inc_uuid,
        Incident.organization_id == org.id,
    ).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found or inaccessible")

    data = build_explainable_timeline(incident_id, db)
    return ExplainableTimelineResponse(
        incident_id=str(incident_id),
        milestones=TimelineMilestonesOut(**data["milestones"]),
        total_events=data["total_events"],
        events=[TimelineEventOut(**e) for e in data["events"]],
    )


# ============================================================================
# 2. POST-MORTEM ENDPOINTS
# ============================================================================

@router.post("/incidents/{incident_id}/post-mortem/generate", response_model=PostMortemOut)
def generate_post_mortem(
    incident_id: str,
    db: Session = Depends(get_db),
    org_membership: Tuple[Organization, UserOrganizationMembership] = Depends(require_member),
):
    """Synthesize or refresh an AI-generated draft Post-Mortem for an incident."""
    org, membership = org_membership
    inc_uuid = _to_uuid(incident_id)
    incident = db.query(Incident).filter(
        Incident.id == inc_uuid,
        Incident.organization_id == org.id,
    ).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found or inaccessible")

    user = db.query(User).filter(User.id == membership.user_id).first()
    pm = generate_post_mortem_for_incident(incident_id, db, author=user)
    db.commit()
    db.refresh(pm)
    return _format_post_mortem(pm)


@router.get("/incidents/{incident_id}/post-mortem", response_model=PostMortemOut)
def get_post_mortem(
    incident_id: str,
    db: Session = Depends(get_db),
    org_membership: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
):
    """Fetch the active Post-Mortem and action items for an incident."""
    org, membership = org_membership
    inc_uuid = _to_uuid(incident_id)
    pm = db.query(PostMortem).filter(
        PostMortem.incident_id == inc_uuid,
        PostMortem.organization_id == org.id,
        PostMortem.is_current == True,
    ).first()
    if not pm:
        raise HTTPException(status_code=404, detail="Post-mortem not found for this incident")
    return _format_post_mortem(pm)


@router.put("/incidents/{incident_id}/post-mortem", response_model=PostMortemOut)
def update_post_mortem(
    incident_id: str,
    payload: PostMortemUpdate,
    db: Session = Depends(get_db),
    org_membership: Tuple[Organization, UserOrganizationMembership] = Depends(require_member),
):
    """Edit draft post-mortem fields before final publication."""
    org, membership = org_membership
    inc_uuid = _to_uuid(incident_id)
    pm = db.query(PostMortem).filter(
        PostMortem.incident_id == inc_uuid,
        PostMortem.organization_id == org.id,
        PostMortem.is_current == True,
    ).first()
    if not pm:
        raise HTTPException(status_code=404, detail="Post-mortem not found")

    if payload.title is not None:
        pm.title = payload.title
    if payload.summary is not None:
        pm.summary = payload.summary
    if payload.root_cause_summary is not None:
        pm.root_cause_summary = payload.root_cause_summary
    if payload.impact_summary is not None:
        pm.impact_summary = payload.impact_summary
    if payload.trigger_event is not None:
        pm.trigger_event = payload.trigger_event
    if payload.detection_summary is not None:
        pm.detection_summary = payload.detection_summary
    if payload.resolution_summary is not None:
        pm.resolution_summary = payload.resolution_summary
    if payload.contributing_factors_json is not None:
        pm.contributing_factors_json = payload.contributing_factors_json
    if payload.lessons_learned_json is not None:
        pm.lessons_learned_json = payload.lessons_learned_json
    if payload.downtime_minutes is not None:
        pm.downtime_minutes = payload.downtime_minutes
    if payload.affected_user_count_estimate is not None:
        pm.affected_user_count_estimate = payload.affected_user_count_estimate
    if payload.slo_impact_percent is not None:
        pm.slo_impact_percent = payload.slo_impact_percent
    if payload.resolution_type is not None:
        pm.resolution_type = payload.resolution_type
    if payload.severity_actual is not None:
        pm.severity_actual = payload.severity_actual
    if payload.status is not None:
        pm.status = PostMortemStatus(payload.status)

    pm.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(pm)
    return _format_post_mortem(pm)


@router.post("/incidents/{incident_id}/post-mortem/publish", response_model=PostMortemOut)
def publish_post_mortem(
    incident_id: str,
    payload: Optional[PostMortemPublishRequest] = None,
    db: Session = Depends(get_db),
    org_membership: Tuple[Organization, UserOrganizationMembership] = Depends(require_operator),
):
    """
    Sign off and publish a post-mortem, indexing it into institutional Pinecone memory.
    Requires OPERATOR or ADMIN role.
    """
    org, membership = org_membership
    inc_uuid = _to_uuid(incident_id)
    pm = db.query(PostMortem).filter(
        PostMortem.incident_id == inc_uuid,
        PostMortem.organization_id == org.id,
        PostMortem.is_current == True,
    ).first()
    if not pm:
        raise HTTPException(status_code=404, detail="Post-mortem not found")

    pm.status = PostMortemStatus.PUBLISHED
    pm.human_reviewed = True
    pm.signed_off_by_user_id = membership.user_id
    pm.signed_off_at = datetime.now(timezone.utc)
    pm.published_at = datetime.now(timezone.utc)

    # Index into canonical vector memory (Pinecone) with mandatory tenant isolation
    pm_dict = {
        "id": str(pm.id),
        "organization_id": str(pm.organization_id),
        "incident_id": str(pm.incident_id),
        "title": pm.title,
        "summary": pm.summary,
        "root_cause_summary": pm.root_cause_summary,
        "impact_summary": pm.impact_summary,
        "resolution_summary": pm.resolution_summary,
        "lessons_learned_json": pm.lessons_learned_json,
        "service": getattr(pm.incident, "service_name", ""),
        "severity_actual": pm.severity_actual,
        "published_at": pm.published_at.isoformat(),
        "version": pm.version,
    }

    try:
        indexed = index_post_mortem(pm_dict)
        if indexed:
            pm.memory_indexing_status = MemoryIndexingStatus.INDEXED
            pm.memory_indexing_error = None
        else:
            pm.memory_indexing_status = MemoryIndexingStatus.FAILED
            pm.memory_indexing_error = "Vector store indexing failed"
    except Exception as exc:
        logger.error(f"Vector memory indexing error during publish: {exc}")
        pm.memory_indexing_status = MemoryIndexingStatus.FAILED
        pm.memory_indexing_error = str(exc)

    # Record Audit Event
    audit = AuditEvent(
        incident_id=pm.incident_id,
        user_id=membership.user_id,
        event_type="post_mortem_published",
        description=f"Post-mortem v{pm.version} published",
        metadata_json={
            "post_mortem_id": str(pm.id),
            "version": pm.version,
            "indexing_status": pm.memory_indexing_status.value,
            "sign_off_notes": payload.sign_off_notes if payload else None,
        },
    )
    db.add(audit)
    db.commit()
    db.refresh(pm)
    return _format_post_mortem(pm)


# ============================================================================
# 3. ACTION ITEMS ENDPOINTS
# ============================================================================

@router.post("/incidents/{incident_id}/post-mortem/action-items", response_model=ActionItemOut)
def create_action_item(
    incident_id: str,
    payload: ActionItemCreate,
    db: Session = Depends(get_db),
    org_membership: Tuple[Organization, UserOrganizationMembership] = Depends(require_member),
):
    """Add a preventive action item to an incident's post-mortem."""
    org, membership = org_membership
    inc_uuid = _to_uuid(incident_id)
    pm = db.query(PostMortem).filter(
        PostMortem.incident_id == inc_uuid,
        PostMortem.organization_id == org.id,
        PostMortem.is_current == True,
    ).first()
    if not pm:
        raise HTTPException(status_code=404, detail="Active post-mortem not found for this incident")

    assigned_uuid = _to_uuid(payload.assigned_to_user_id) if payload.assigned_to_user_id else None
    item = PostMortemActionItem(
        organization_id=org.id,
        post_mortem_id=pm.id,
        incident_id=pm.incident_id,
        created_by_user_id=membership.user_id,
        assigned_to_user_id=assigned_uuid,
        title=payload.title,
        description=payload.description,
        category=ActionItemCategory(payload.category),
        priority=ActionItemPriority(payload.priority),
        status=ActionItemStatus.OPEN,
        due_date=payload.due_date,
        external_issue_url=payload.external_issue_url,
        notes=payload.notes,
    )
    db.add(item)
    db.flush()

    audit = AuditEvent(
        incident_id=pm.incident_id,
        user_id=membership.user_id,
        event_type="action_item_created",
        description=f"Action item created: {item.title}",
        metadata_json={"action_item_id": str(item.id), "title": item.title, "priority": item.priority.value},
    )
    db.add(audit)
    db.commit()
    db.refresh(item)
    return _format_action_item(item)


@router.get("/incident-memory/action-items", response_model=List[ActionItemOut])
def list_action_items(
    status_filter: Optional[str] = Query(None, alias="status"),
    priority_filter: Optional[str] = Query(None, alias="priority"),
    category_filter: Optional[str] = Query(None, alias="category"),
    db: Session = Depends(get_db),
    org_membership: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
):
    """List organization action items across all post-mortems with status and priority filters."""
    org, membership = org_membership
    query = db.query(PostMortemActionItem).filter(PostMortemActionItem.organization_id == org.id)

    if status_filter:
        query = query.filter(PostMortemActionItem.status == ActionItemStatus(status_filter))
    if priority_filter:
        query = query.filter(PostMortemActionItem.priority == ActionItemPriority(priority_filter))
    if category_filter:
        query = query.filter(PostMortemActionItem.category == ActionItemCategory(category_filter))

    items = query.order_by(PostMortemActionItem.created_at.desc()).all()
    return [_format_action_item(item) for item in items]


@router.patch("/incident-memory/action-items/{item_id}", response_model=ActionItemOut)
def update_action_item(
    item_id: str,
    payload: ActionItemUpdate,
    db: Session = Depends(get_db),
    org_membership: Tuple[Organization, UserOrganizationMembership] = Depends(require_member),
):
    """Update action item status, assignee, priority, or due date with RBAC and audit logging."""
    org, membership = org_membership
    item_uuid = _to_uuid(item_id)
    item = db.query(PostMortemActionItem).filter(
        PostMortemActionItem.id == item_uuid,
        PostMortemActionItem.organization_id == org.id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Action item not found")

    old_status = item.status.value if hasattr(item.status, "value") else str(item.status)
    old_assignee = str(item.assigned_to_user_id) if item.assigned_to_user_id else None

    if payload.title is not None:
        item.title = payload.title
    if payload.description is not None:
        item.description = payload.description
    if payload.category is not None:
        item.category = ActionItemCategory(payload.category)
    if payload.priority is not None:
        item.priority = ActionItemPriority(payload.priority)
    if payload.assigned_to_user_id is not None:
        item.assigned_to_user_id = _to_uuid(payload.assigned_to_user_id)
    if payload.due_date is not None:
        item.due_date = payload.due_date
    if payload.external_issue_url is not None:
        item.external_issue_url = payload.external_issue_url
    if payload.notes is not None:
        item.notes = payload.notes
    if payload.status is not None:
        new_status = ActionItemStatus(payload.status)
        item.status = new_status
        if new_status == ActionItemStatus.COMPLETED and not item.completed_at:
            item.completed_at = datetime.now(timezone.utc)
        elif new_status != ActionItemStatus.COMPLETED:
            item.completed_at = None

    item.updated_at = datetime.now(timezone.utc)

    # Emit audit log for status/assignee mutations
    audit = AuditEvent(
        incident_id=item.incident_id,
        user_id=membership.user_id,
        event_type="action_item_updated",
        description=f"Action item {item.title} updated",
        metadata_json={
            "action_item_id": str(item.id),
            "old_status": old_status,
            "new_status": item.status.value if hasattr(item.status, "value") else str(item.status),
            "old_assignee": old_assignee,
            "new_assignee": str(item.assigned_to_user_id) if item.assigned_to_user_id else None,
        },
    )
    db.add(audit)
    db.commit()
    db.refresh(item)
    return _format_action_item(item)


# ============================================================================
# 4. SEMANTIC MEMORY SEARCH ENDPOINT
# ============================================================================

@router.post("/incident-memory/search", response_model=IncidentMemorySearchResponse)
def search_memory(
    payload: IncidentMemorySearchRequest,
    db: Session = Depends(get_db),
    org_membership: Tuple[Organization, UserOrganizationMembership] = Depends(require_viewer),
):
    """
    Search historical incident memory using semantic vector similarity.
    Strictly tenant-isolated: only returns matches belonging to the requester's organization.
    """
    org, membership = org_membership
    matches = search_similar_incidents(
        query=payload.query,
        organization_id=str(org.id),
        service=payload.service,
        limit=payload.limit,
    )

    results = [
        IncidentMemorySearchResult(
            id=m["id"],
            score=m.get("score", 0.0),
            title=m.get("title", ""),
            service=m.get("service"),
            severity=m.get("severity"),
            root_cause=m.get("root_cause"),
            resolution=m.get("resolution"),
            resolved_at=m.get("resolved_at"),
        )
        for m in matches
    ]

    return IncidentMemorySearchResponse(
        results=results,
        total=len(results),
        source="pinecone",
    )
