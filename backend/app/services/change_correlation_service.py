import math
import logging
import uuid
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import func

from app.models.incident import (
    Incident,
    ChangeEvent,
    ChangeType,
    IncidentChangeCorrelation,
    IncidentChangeCorrelationReport,
    CorrelationStatus,
    GraphNode,
    GraphEdge,
    GraphNodeType,
)
from app.schemas.changes import ChangeCorrelationReport, IncidentChangeCorrelationResponse

logger = logging.getLogger(__name__)

# Complete 11-Type Scoring Weight Table
CHANGE_TYPE_BASE_WEIGHTS: Dict[ChangeType, float] = {
    ChangeType.FEATURE_FLAG: 0.95,
    ChangeType.DEPLOYMENT: 0.95,
    ChangeType.CONFIGURATION: 0.90,
    ChangeType.ENVIRONMENT_VARIABLE: 0.90,
    ChangeType.DATABASE_MIGRATION: 0.85,
    ChangeType.SCALING_CHANGE: 0.80,
    ChangeType.DEPENDENCY_UPGRADE: 0.80,
    ChangeType.INFRASTRUCTURE: 0.75,
    ChangeType.CODE_COMMIT: 0.70,
    ChangeType.PULL_REQUEST: 0.70,
    ChangeType.API_CONTRACT: 0.65,
}

# Exponential temporal decay parameter (30 minutes in seconds)
TEMPORAL_DECAY_TAU_SECONDS = 1800.0

# Debounce interval per incident (60 seconds)
CORRELATION_DEBOUNCE_SECONDS = 60


def compute_graph_distance(
    db: Session,
    organization_id: uuid.UUID,
    root_service_id: Optional[uuid.UUID],
    target_service_id: Optional[uuid.UUID],
) -> float:
    """
    Compute shortest graph topological hop distance from root service to target service
    using Phase 6 service graph edges. Returns 0 for root service, integer for hops,
    or 1.5 fallback for unknown / unmapped services.
    """
    if not root_service_id or not target_service_id:
        return 1.5
    if root_service_id == target_service_id:
        return 0.0

    # Look up GraphNode IDs for root and target
    root_node = db.query(GraphNode).filter(
        GraphNode.organization_id == organization_id,
        GraphNode.entity_id == root_service_id,
    ).first()

    target_node = db.query(GraphNode).filter(
        GraphNode.organization_id == organization_id,
        GraphNode.entity_id == target_service_id,
    ).first()

    if not root_node or not target_node:
        return 1.5

    # BFS traversal to find shortest path
    all_edges = db.query(GraphEdge).filter(
        GraphEdge.organization_id == organization_id,
        GraphEdge.is_stale == False,
    ).all()

    adj: Dict[uuid.UUID, List[uuid.UUID]] = {}
    for e in all_edges:
        adj.setdefault(e.source_node_id, []).append(e.target_node_id)
        adj.setdefault(e.target_node_id, []).append(e.source_node_id)  # undirected for proximity

    queue = [(root_node.id, 0)]
    visited = {root_node.id}

    while queue:
        curr_id, dist = queue.pop(0)
        if curr_id == target_node.id:
            return float(dist)
        if dist < 5:
            for neighbor in adj.get(curr_id, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, dist + 1))

    return 2.5  # Reached depth limit without path


def calculate_correlation_score(
    change_type: ChangeType,
    time_delta_seconds: int,
    graph_distance: float,
) -> float:
    """
    Score formula:
    Score = round( W(type) * exp( - |time_delta| / tau ) * ( 1 / (1 + 0.4 * dist) ), 4 )
    """
    base_w = CHANGE_TYPE_BASE_WEIGHTS.get(change_type, 0.70)
    abs_delta = abs(time_delta_seconds)
    temporal_decay = math.exp(-abs_delta / TEMPORAL_DECAY_TAU_SECONDS)
    distance_multiplier = 1.0 / (1.0 + 0.4 * graph_distance)

    raw_score = base_w * temporal_decay * distance_multiplier
    return round(max(0.0, min(1.0, raw_score)), 4)


def correlate_incident_changes(
    db: Session,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    lookback_window_minutes: int = 120,
    force: bool = False,
) -> ChangeCorrelationReport:
    """
    Perform temporal and topological correlation between an incident and recent changes.
    Non-destructive: updates scores and rankings without overwriting human triage decisions.
    """
    incident = db.query(Incident).filter(
        Incident.organization_id == organization_id,
        Incident.id == incident_id,
    ).first()
    if not incident:
        raise ValueError(f"Incident {incident_id} not found in organization {organization_id}")

    onset_time = incident.detected_at or incident.created_at or datetime.now(timezone.utc)
    if onset_time.tzinfo is None:
        onset_time = onset_time.replace(tzinfo=timezone.utc)

    # 1. Debounce check against current persistent report
    latest_report = db.query(IncidentChangeCorrelationReport).filter(
        IncidentChangeCorrelationReport.organization_id == organization_id,
        IncidentChangeCorrelationReport.incident_id == incident_id,
        IncidentChangeCorrelationReport.is_current == True,
    ).first()

    if latest_report and not force:
        last_calc = latest_report.calculated_at
        if last_calc:
            if last_calc.tzinfo is None:
                last_calc = last_calc.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - last_calc).total_seconds()
            if elapsed < CORRELATION_DEBOUNCE_SECONDS:
                logger.info(f"Skipping change correlation for incident {incident_id} (debounced, elapsed={elapsed:.1f}s)")
                corrs = db.query(IncidentChangeCorrelation).filter(
                    IncidentChangeCorrelation.organization_id == organization_id,
                    IncidentChangeCorrelation.incident_id == incident_id,
                ).order_by(IncidentChangeCorrelation.rank.asc()).all()

                return ChangeCorrelationReport(
                    id=latest_report.id,
                    organization_id=organization_id,
                    incident_id=incident_id,
                    version=latest_report.version,
                    is_current=True,
                    snapshot_hash=latest_report.snapshot_hash,
                    calculated_at=latest_report.calculated_at,
                    lookback_window_minutes=latest_report.lookback_window_minutes,
                    correlations=[IncidentChangeCorrelationResponse.model_validate(c) for c in corrs],
                    causal_candidates_count=latest_report.causal_candidates_count,
                    top_suspect=IncidentChangeCorrelationResponse.model_validate(corrs[0]) if corrs else None,
                    summary=latest_report.summary or f"Retrieved {len(corrs)} change correlations (cached).",
                )

    # 2. Define Lookback Window: [onset - window, onset + 15m]
    window_start = onset_time - timedelta(minutes=lookback_window_minutes)
    window_end = onset_time + timedelta(minutes=15)

    candidate_changes = db.query(ChangeEvent).filter(
        ChangeEvent.organization_id == organization_id,
        ChangeEvent.effective_at >= window_start,
        ChangeEvent.effective_at <= window_end,
    ).all()

    # 3. Score and evaluate each change event
    scored_items = []
    root_service_id = incident.service_id

    for change in candidate_changes:
        eff = change.effective_at
        if eff.tzinfo is None:
            eff = eff.replace(tzinfo=timezone.utc)

        time_delta_seconds = int((eff - onset_time).total_seconds())
        graph_dist = compute_graph_distance(db, organization_id, root_service_id, change.service_id)

        score = calculate_correlation_score(change.change_type, time_delta_seconds, graph_dist)

        # Causal candidate rule: score >= 0.40 AND effective_at <= incident onset (time_delta <= 0)
        is_causal = (score >= 0.40) and (time_delta_seconds <= 0)

        # Build explainable reasoning string
        delta_min = round(time_delta_seconds / 60.0, 1)
        timing_desc = f"{abs(delta_min)} min before onset" if delta_min <= 0 else f"{delta_min} min after onset"
        dist_desc = f"on root service" if graph_dist == 0 else f"{int(graph_dist)} hops away" if graph_dist.is_integer() else "unmapped service"
        reasoning = (
            f"{change.change_type.value.replace('_', ' ').title()} '{change.title}' took effect {timing_desc} "
            f"({dist_desc}). Correlation Score: {score:.4f} (Correlation, Not Proof)."
        )

        scored_items.append({
            "change": change,
            "time_delta_seconds": time_delta_seconds,
            "topological_distance": int(graph_dist) if graph_dist.is_integer() else 2,
            "correlation_score": score,
            "is_causal_candidate": is_causal,
            "reasoning": reasoning,
        })

    # Sort descending by correlation score, then ascending by absolute time delta
    scored_items.sort(key=lambda x: (-x["correlation_score"], abs(x["time_delta_seconds"])))

    # 4. Upsert correlations into database preserving human triage status
    saved_correlations = []
    for rank_idx, item in enumerate(scored_items, start=1):
        ch = item["change"]

        existing_corr = db.query(IncidentChangeCorrelation).filter(
            IncidentChangeCorrelation.organization_id == organization_id,
            IncidentChangeCorrelation.incident_id == incident_id,
            IncidentChangeCorrelation.change_event_id == ch.id,
        ).first()

        if existing_corr:
            existing_corr.time_delta_seconds = item["time_delta_seconds"]
            existing_corr.topological_distance = item["topological_distance"]
            existing_corr.correlation_score = item["correlation_score"]
            existing_corr.rank = rank_idx
            existing_corr.is_causal_candidate = item["is_causal_candidate"]
            existing_corr.reasoning = item["reasoning"]
            existing_corr.updated_at = datetime.now(timezone.utc)
            # Crucial rule: Never overwrite human triage status if set
            saved_correlations.append(existing_corr)
        else:
            new_corr = IncidentChangeCorrelation(
                organization_id=organization_id,
                incident_id=incident_id,
                change_event_id=ch.id,
                time_delta_seconds=item["time_delta_seconds"],
                topological_distance=item["topological_distance"],
                correlation_score=item["correlation_score"],
                rank=rank_idx,
                is_causal_candidate=item["is_causal_candidate"],
                triage_status=CorrelationStatus.COINCIDENTAL,
                reasoning=item["reasoning"],
                metadata_json={"triage_history": []},
            )
            db.add(new_corr)
            saved_correlations.append(new_corr)

    causal_count = sum(1 for c in saved_correlations if c.is_causal_candidate)
    top_suspect = saved_correlations[0] if saved_correlations else None

    # 5. Compute Transactional Version & Snapshot Hash
    max_version = db.query(func.max(IncidentChangeCorrelationReport.version)).filter(
        IncidentChangeCorrelationReport.organization_id == organization_id,
        IncidentChangeCorrelationReport.incident_id == incident_id,
    ).scalar() or 0
    new_version = max_version + 1

    snapshot_elements = [
        f"{item['change'].id}:{item['correlation_score']:.4f}:{item['time_delta_seconds']}:{item['topological_distance']}"
        for item in scored_items
    ]
    snapshot_raw = f"{incident_id}:v{new_version}:{','.join(snapshot_elements)}"
    snapshot_hash = hashlib.sha256(snapshot_raw.encode("utf-8")).hexdigest()

    # 6. Mark previous reports is_current=False
    db.query(IncidentChangeCorrelationReport).filter(
        IncidentChangeCorrelationReport.organization_id == organization_id,
        IncidentChangeCorrelationReport.incident_id == incident_id,
        IncidentChangeCorrelationReport.is_current == True,
    ).update({"is_current": False})

    # 7. Persist new report snapshot
    now_utc = datetime.now(timezone.utc)
    summary = f"Analyzed {len(saved_correlations)} correlated changes in {lookback_window_minutes}m window. Found {causal_count} causal candidates (version {new_version})."
    correlations_snapshot = [
        {
            "change_event_id": str(c.change_event_id),
            "rank": c.rank,
            "score": c.correlation_score,
            "time_delta_seconds": c.time_delta_seconds,
            "distance": c.topological_distance,
            "is_causal": c.is_causal_candidate,
            "triage_status": c.triage_status.value if hasattr(c.triage_status, "value") else str(c.triage_status),
        }
        for c in saved_correlations
    ]

    new_report = IncidentChangeCorrelationReport(
        organization_id=organization_id,
        incident_id=incident_id,
        version=new_version,
        is_current=True,
        calculated_at=now_utc,
        lookback_window_minutes=lookback_window_minutes,
        snapshot_hash=snapshot_hash,
        causal_candidates_count=causal_count,
        summary=summary,
        correlations_snapshot=correlations_snapshot,
        metadata_json={"total_changes_scanned": len(candidate_changes)},
    )
    db.add(new_report)

    db.commit()
    db.refresh(new_report)
    for c in saved_correlations:
        db.refresh(c)

    return ChangeCorrelationReport(
        id=new_report.id,
        organization_id=organization_id,
        incident_id=incident_id,
        version=new_version,
        is_current=True,
        snapshot_hash=snapshot_hash,
        calculated_at=now_utc,
        lookback_window_minutes=lookback_window_minutes,
        correlations=[IncidentChangeCorrelationResponse.model_validate(c) for c in saved_correlations],
        causal_candidates_count=causal_count,
        top_suspect=IncidentChangeCorrelationResponse.model_validate(top_suspect) if top_suspect else None,
        summary=summary,
    )


def triage_change_correlation(
    db: Session,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    correlation_id: uuid.UUID,
    user_id: Optional[uuid.UUID],
    triage_status: CorrelationStatus,
    reason: Optional[str] = None,
) -> IncidentChangeCorrelation:
    """
    Update human triage status on a correlation with auditable history.
    """
    corr = db.query(IncidentChangeCorrelation).filter(
        IncidentChangeCorrelation.organization_id == organization_id,
        IncidentChangeCorrelation.incident_id == incident_id,
        IncidentChangeCorrelation.id == correlation_id,
    ).first()

    if not corr:
        raise ValueError(f"Correlation {correlation_id} not found for incident {incident_id}")

    prev_status = corr.triage_status.value if hasattr(corr.triage_status, "value") else str(corr.triage_status)
    now_utc = datetime.now(timezone.utc)

    corr.previous_status = prev_status
    corr.triage_status = triage_status
    corr.triage_reason = reason
    corr.triaged_by_user_id = user_id
    corr.triaged_at = now_utc
    corr.updated_at = now_utc

    # Append to audit trail in metadata_json
    meta = corr.metadata_json or {}
    history = meta.get("triage_history", [])
    history.append({
        "previous_status": prev_status,
        "new_status": triage_status.value,
        "reason": reason,
        "user_id": str(user_id) if user_id else None,
        "timestamp": now_utc.isoformat(),
    })
    meta["triage_history"] = history
    corr.metadata_json = meta
    flag_modified(corr, "metadata_json")

    db.commit()
    db.refresh(corr)
    return corr
