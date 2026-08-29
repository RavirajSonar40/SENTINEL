"""
Multi-Source Evidence Harvester Engine (Phase 9).

Ingests, sanitizes, categorizes, hashes, and persists immutable evidence items across:
- Phase 4 Deployments
- Phase 5 Monitoring & Telemetry Alerts
- Phase 6 Service Graph & Blast Radius
- Phase 7 Change Intelligence
- Phase 8 Workspace Sandboxes & Code Files
- Human Operator Manual Submissions
"""
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.incident import (
    Incident,
    Evidence,
    EvidenceSourceType,
    EvidenceCategoryType,
    EvidenceFamily,
    EvidenceTrustLevel,
    EvidenceVerificationStatus,
    Service,
    Repository,
    Deployment,
    TelemetrySignal,
    HealthCheckLog,
    ChangeEvent,
    IncidentChangeCorrelationReport,
)
from app.services.workspace_manager import redact_text_credentials

logger = logging.getLogger("sentinel.evidence_harvester")

# Maximum Size Constraints
MAX_PAYLOAD_BYTES = 65536      # 64 KB
MAX_LOG_LINES = 200
MAX_CODE_LINES = 100
MAX_EVIDENCE_PER_INCIDENT = 250


def compute_canonical_content_hash(payload: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash from canonically-ordered JSON payload."""
    canonical_json = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def classify_evidence_family(
    source_type: EvidenceSourceType,
    trust_level: Optional[EvidenceTrustLevel] = None,
    verification_status: Optional[EvidenceVerificationStatus] = None,
) -> Optional[EvidenceFamily]:
    """Map source types to orthogonal Evidence Families for corroboration enforcement."""
    st = source_type.value if hasattr(source_type, "value") else str(source_type)
    st = st.lower()

    if st in ("deployments", "deployment", "changes", "commit", "diff", "pull_request", "pr"):
        return EvidenceFamily.FAMILY_CODE_CHANGE
    elif st in ("telemetry", "logs", "log", "metrics", "metric", "traces", "trace", "alert", "alerts"):
        return EvidenceFamily.FAMILY_RUNTIME_TELEMETRY
    elif st in ("graph", "service_graph", "blast_radius"):
        return EvidenceFamily.FAMILY_TOPOLOGY_GRAPH
    elif st in ("workspace", "file", "files", "function", "functions", "dependencies", "previous_incident", "documentation", "runbook"):
        return EvidenceFamily.FAMILY_WORKSPACE_STATIC
    elif st in ("manual", "operator_note"):
        if verification_status == EvidenceVerificationStatus.VERIFIED or str(verification_status) == "verified":
            return EvidenceFamily.FAMILY_VERIFIED_HUMAN
        return None
    return None


def sanitize_and_truncate_content(
    raw_content: Optional[str],
    source_type: EvidenceSourceType,
) -> (str, int, bool):
    """Sanitize secrets, truncate to safety limits, and report payload size."""
    if not raw_content:
        return "", 0, False

    # 1. Recursive Secret Redaction
    redacted = redact_text_credentials(raw_content)
    is_redacted = redacted != raw_content

    # 2. Line Limits based on source category
    lines = redacted.splitlines()
    st = source_type.value if hasattr(source_type, "value") else str(source_type)
    st = st.lower()

    if st in ("logs", "log", "trace", "traces") and len(lines) > MAX_LOG_LINES:
        redacted = "\n".join(lines[:MAX_LOG_LINES]) + f"\n... [Truncated {len(lines) - MAX_LOG_LINES} lines]"
    elif st in ("file", "files", "workspace") and len(lines) > MAX_CODE_LINES:
        redacted = "\n".join(lines[:MAX_CODE_LINES]) + f"\n... [Truncated {len(lines) - MAX_CODE_LINES} lines]"

    # 3. Byte Limit
    encoded = redacted.encode("utf-8")
    if len(encoded) > MAX_PAYLOAD_BYTES:
        redacted = encoded[:MAX_PAYLOAD_BYTES].decode("utf-8", errors="ignore") + "\n... [Payload byte cap reached (64KB)]"

    payload_size = len(redacted.encode("utf-8"))
    return redacted, payload_size, is_redacted


def create_evidence_item(
    db: Session,
    organization_id: uuid.UUID,
    title: str,
    source_type: EvidenceSourceType,
    category_type: EvidenceCategoryType = EvidenceCategoryType.FACT,
    incident_id: Optional[uuid.UUID] = None,
    investigation_id: Optional[uuid.UUID] = None,
    work_item_id: Optional[uuid.UUID] = None,
    content: Optional[str] = None,
    summary: Optional[str] = None,
    source_id: Optional[str] = None,
    service: Optional[str] = None,
    environment: Optional[str] = None,
    region: Optional[str] = None,
    repository: Optional[str] = None,
    commit_sha: Optional[str] = None,
    file_path: Optional[str] = None,
    line_start: Optional[int] = None,
    line_end: Optional[int] = None,
    source_url: Optional[str] = None,
    observed_at: Optional[datetime] = None,
    relevance_score: float = 1.0,
    retrieval_method: str = "automated_harvester",
    metadata: Optional[Dict[str, Any]] = None,
    trust_level: EvidenceTrustLevel = EvidenceTrustLevel.UNVERIFIED,
    verification_status: EvidenceVerificationStatus = EvidenceVerificationStatus.VERIFIED,
    submitted_by_user_id: Optional[uuid.UUID] = None,
) -> Optional[Evidence]:
    """Create and persist an immutable, append-only Evidence record."""
    # Check max evidence capacity
    if incident_id:
        existing_count = db.query(func.count(Evidence.id)).filter(
            Evidence.organization_id == organization_id,
            Evidence.incident_id == incident_id,
        ).scalar() or 0
        if existing_count >= MAX_EVIDENCE_PER_INCIDENT:
            logger.warning(f"Incident {incident_id} evidence cap ({MAX_EVIDENCE_PER_INCIDENT}) reached; dropping item.")
            return None

    # Sanitize and truncate content
    clean_content, payload_size, is_redacted = sanitize_and_truncate_content(content, source_type)

    # Classify Evidence Family
    family = classify_evidence_family(source_type, trust_level, verification_status)

    # Deterministic Canonical Hash for Provenance
    canonical_payload = {
        "title": title,
        "source_type": source_type.value if hasattr(source_type, "value") else str(source_type),
        "source_id": source_id,
        "content": clean_content,
        "service": service,
        "repository": repository,
        "commit_sha": commit_sha,
        "file_path": file_path,
        "observed_at": observed_at.isoformat() if observed_at else None,
    }
    content_hash = compute_canonical_content_hash(canonical_payload)

    # Deduplication check: if exact content hash exists for this incident, return existing
    if incident_id:
        existing_dup = db.query(Evidence).filter(
            Evidence.organization_id == organization_id,
            Evidence.incident_id == incident_id,
            Evidence.content_hash == content_hash,
        ).first()
        if existing_dup:
            return existing_dup

    evidence = Evidence(
        organization_id=organization_id,
        incident_id=incident_id,
        investigation_id=investigation_id,
        work_item_id=work_item_id,
        source_type=source_type,
        category_type=category_type,
        evidence_family=family,
        source_id=source_id,
        service=service,
        environment=environment,
        region=region,
        repository=repository,
        commit_sha=commit_sha,
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        title=title[:500],
        content=clean_content,
        summary=summary[:2000] if summary else None,
        content_hash=content_hash,
        is_redacted=is_redacted,
        payload_size_bytes=payload_size,
        trust_level=trust_level,
        verification_status=verification_status,
        submitted_by_user_id=submitted_by_user_id,
        observed_at=observed_at or datetime.now(timezone.utc),
        timestamp=observed_at or datetime.now(timezone.utc),
        source_url=source_url,
        relevance_score=relevance_score,
        retrieval_method=retrieval_method,
        metadata_json=metadata,
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return evidence


def create_evidence_correction(
    db: Session,
    organization_id: uuid.UUID,
    supersedes_evidence_id: uuid.UUID,
    title: str,
    content: Optional[str] = None,
    summary: Optional[str] = None,
    correction_reason: Optional[str] = None,
    user_id: Optional[uuid.UUID] = None,
) -> Optional[Evidence]:
    """Create a new versioned evidence record that immutably supersedes an existing one."""
    old_ev = db.query(Evidence).filter(
        Evidence.organization_id == organization_id,
        Evidence.id == supersedes_evidence_id,
    ).first()
    if not old_ev:
        return None

    new_ev = create_evidence_item(
        db=db,
        organization_id=organization_id,
        incident_id=old_ev.incident_id,
        investigation_id=old_ev.investigation_id,
        work_item_id=old_ev.work_item_id,
        title=title,
        source_type=old_ev.source_type,
        category_type=old_ev.category_type,
        content=content if content is not None else old_ev.content,
        summary=summary if summary is not None else old_ev.summary,
        service=old_ev.service,
        environment=old_ev.environment,
        region=old_ev.region,
        repository=old_ev.repository,
        commit_sha=old_ev.commit_sha,
        file_path=old_ev.file_path,
        observed_at=old_ev.observed_at,
        retrieval_method=f"correction_v{old_ev.version+1}",
        metadata={"correction_reason": correction_reason, "superseded_id": str(old_ev.id)},
        trust_level=EvidenceTrustLevel.VERIFIED_BY_OPERATOR,
        verification_status=EvidenceVerificationStatus.VERIFIED,
        submitted_by_user_id=user_id,
    )
    if not new_ev:
        return None

    old_ev.superseded_by_id = new_ev.id
    new_ev.version = old_ev.version + 1
    db.commit()
    db.refresh(new_ev)
    return new_ev


def harvest_incident_evidence(
    db: Session,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    investigation_id: Optional[uuid.UUID] = None,
    lookback_window_minutes: int = 120,
) -> List[Evidence]:
    """
    Harvest and synthesize evidence across all subsystems for an incident:
    1. Deployments (Phase 4)
    2. Telemetry & Alerts (Phase 5)
    3. Service Graph & Blast Radius (Phase 6)
    4. Change Intelligence & Correlations (Phase 7)
    5. Workspace Code & Configurations (Phase 8)
    """
    incident = db.query(Incident).filter(
        Incident.organization_id == organization_id,
        Incident.id == incident_id,
    ).first()
    if not incident:
        return []

    svc_name = incident.service_name or (incident.service_rel.name if incident.service_rel else None)
    incident_time = incident.detected_at or incident.created_at or datetime.now(timezone.utc)
    lookback_start = incident_time - timedelta(minutes=lookback_window_minutes)

    harvested: List[Evidence] = []

    # 1. Harvest Phase 4 Deployments
    deployments = db.query(Deployment).filter(
        Deployment.organization_id == organization_id,
        Deployment.created_at >= lookback_start,
    ).all()
    for d in deployments:
        is_direct_svc = (svc_name and d.service_rel and d.service_rel.name == svc_name)
        rel_score = 0.95 if is_direct_svc else 0.65
        ev = create_evidence_item(
            db=db,
            organization_id=organization_id,
            incident_id=incident.id,
            investigation_id=investigation_id,
            title=f"Deployment {d.version} on service {d.service_rel.name if d.service_rel else 'unknown'}",
            source_type=EvidenceSourceType.DEPLOYMENTS,
            category_type=EvidenceCategoryType.FACT,
            source_id=str(d.id),
            service=d.service_rel.name if d.service_rel else None,
            environment=d.environment_rel.name if d.environment_rel else None,
            commit_sha=d.commit_sha,
            content=f"Deployment Status: {d.status}\nDeployed At: {d.created_at}\nCommit: {d.commit_sha}",
            summary=f"Deployment {d.version} completed {d.status} on {d.environment_rel.name if d.environment_rel else 'env'}.",
            observed_at=d.created_at,
            relevance_score=rel_score,
            retrieval_method="deployment_harvester",
        )
        if ev:
            harvested.append(ev)

    # 2. Harvest Phase 5 Telemetry Signals & Health Check Anomalies
    signals = db.query(TelemetrySignal).filter(
        TelemetrySignal.organization_id == organization_id,
        TelemetrySignal.created_at >= lookback_start,
    ).all()
    for sig in signals:
        sig_svc_name = sig.service.name if sig.service else None
        sig_env_name = sig.environment.name if sig.environment else None
        ev = create_evidence_item(
            db=db,
            organization_id=organization_id,
            incident_id=incident.id,
            investigation_id=investigation_id,
            title=f"Telemetry Alert: {sig.title or sig.metric_name or sig.signal_type}",
            source_type=EvidenceSourceType.TELEMETRY,
            category_type=EvidenceCategoryType.FACT,
            source_id=str(sig.id),
            service=sig_svc_name,
            environment=sig_env_name,
            content=f"Metric: {sig.metric_name}\nValue: {sig.metric_value}\nThreshold: {sig.threshold_value}\nRule: {sig.rule_name}\nPayload: {json.dumps(sig.raw_payload or {})}",
            summary=f"Telemetry signal {sig.title or sig.metric_name} triggered {sig.signal_type}.",
            observed_at=sig.observed_at or sig.created_at,
            relevance_score=0.90 if sig_svc_name == svc_name else 0.70,
            retrieval_method="telemetry_harvester",
        )
        if ev:
            harvested.append(ev)

    # 3. Harvest Phase 7 Change Intelligence Suspects
    correlations = db.query(IncidentChangeCorrelationReport).filter(
        IncidentChangeCorrelationReport.organization_id == organization_id,
        IncidentChangeCorrelationReport.incident_id == incident.id,
        IncidentChangeCorrelationReport.is_current == True,
    ).first()
    if correlations and correlations.correlations_snapshot:
        for idx, change in enumerate(correlations.correlations_snapshot[:5]):
            score = change.get("score", change.get("composite_score", 0.0))
            change_event_id = change.get("change_event_id")
            change_event = None
            if change_event_id:
                try:
                    change_event = db.query(ChangeEvent).filter(ChangeEvent.id == uuid.UUID(change_event_id)).first()
                except Exception:
                    pass
            
            title = f"Suspect Change #{idx+1}: {change_event.title if change_event else change.get('title', 'Change Event')}"
            diff_text = str(change_event.diff_summary) if (change_event and change_event.diff_summary) else ""
            ev = create_evidence_item(
                db=db,
                organization_id=organization_id,
                incident_id=incident.id,
                investigation_id=investigation_id,
                title=title,
                source_type=EvidenceSourceType.CHANGES,
                category_type=EvidenceCategoryType.INFERENCE,
                source_id=str(change_event_id or ""),
                commit_sha=change_event.commit_sha if change_event else change.get("commit_sha"),
                file_path=",".join([str(c) for c in (change_event.affected_components or [])[:3]]) if change_event else None,
                content=f"Score: {score:.2f}\nAuthor: {change_event.author if change_event else change.get('author')}\nAffected Components: {change_event.affected_components if change_event else []}\nDiff Summary: {diff_text}",
                summary=f"Change Intelligence scored this change {score:.2f} (Rank #{change.get('rank', idx+1)}).",
                observed_at=change_event.effective_at if (change_event and change_event.effective_at) else incident_time,
                relevance_score=score,
                retrieval_method="change_intelligence_harvester",
            )
            if ev:
                harvested.append(ev)

    # 4. Harvest Phase 10 Historical Incidents Memory
    try:
        from app.services.historical import search_similar_incidents
        search_query = f"{incident.title} {svc_name or ''} {incident.description or ''}"
        similar_past = search_similar_incidents(
            query=search_query,
            organization_id=str(organization_id),
            service=svc_name,
            limit=3,
        )
        for past in similar_past:
            if past.get("id") and (str(incident.id) in str(past.get("id")) or past.get("id") == str(incident.id)):
                continue
            past_ev = create_evidence_item(
                db=db,
                organization_id=organization_id,
                incident_id=incident.id,
                investigation_id=investigation_id,
                title=f"Historical Incident: {past.get('title', 'Similar Incident')}",
                source_type=EvidenceSourceType.PREVIOUS_INCIDENT,
                category_type=EvidenceCategoryType.FACT,
                source_id=str(past.get("id", "")),
                service=past.get("service"),
                content=f"Title: {past.get('title')}\nService: {past.get('service')}\nRoot Cause: {past.get('root_cause')}\nResolution: {past.get('resolution')}\nSimilarity Score: {past.get('score', 0.0):.2f}",
                summary=f"Historical incident memory match with root cause: {past.get('root_cause')[:200] if past.get('root_cause') else 'N/A'}",
                observed_at=incident_time,
                relevance_score=past.get("score", 0.7),
                retrieval_method="incident_memory_rag",
            )
            if past_ev:
                harvested.append(past_ev)
    except Exception as exc:
        logger.warning(f"Error harvesting historical incident memory evidence: {exc}")

    # Return all current evidence items for this incident
    all_evidence = db.query(Evidence).filter(
        Evidence.organization_id == organization_id,
        Evidence.incident_id == incident.id,
    ).order_by(Evidence.collected_at.asc()).all()
    return all_evidence
