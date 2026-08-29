"""Multi-Dimensional Blast Radius Analysis Engine (Phase 6)."""

import uuid
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Set, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.incident import (
    Incident, Service, Repository, ServiceRepository, ServiceDeploymentConfig,
    Environment, Region, TelemetrySignal, HealthCheckLog,
    GraphNode, GraphEdge, GraphNodeType, GraphEdgeType, ServiceCriticality,
    IncidentBlastRadiusReport
)
from app.services.graph_service import sync_catalog_to_graph

logger = logging.getLogger(__name__)

# Minimum cooldown interval between automatic recalculations for the same incident
DEBOUNCE_COOLDOWN_SECONDS = 60


def compute_graph_snapshot_hash(nodes: List[GraphNode], edges: List[GraphEdge]) -> str:
    """Computes a deterministic hash of the current graph topology state."""
    raw = "|".join(sorted([f"{n.identifier}:{n.tier or 'none'}" for n in nodes])) + "||" + \
          "|".join(sorted([f"{e.source_node_id}->{e.target_node_id}:{e.edge_type.value}:{e.criticality.value}" for e in edges]))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def calculate_blast_radius(
    db: Session,
    organization_id: uuid.UUID,
    root_service: Service,
    incident: Optional[Incident] = None,
    environment: Optional[Environment] = None,
    max_depth: int = 5,
    telemetry_window_minutes: int = 30,
) -> IncidentBlastRadiusReport:
    """
    Calculates multi-dimensional blast radius:
    - Downstream caller traversal (Customer & entrypoint impact).
    - Upstream dependency traversal (Infrastructure & root causes).
    - Observed vs. Inferred impact classification using live telemetry.
    - HARD vs. SOFT criticality numerical weighting.
    - Transparent customer traffic/user impact estimation.
    - Evidence-only vs. Remediation-target repository classification.
    - Immutable versioned report persistence.
    """
    # Ensure graph is synchronized
    all_nodes = db.query(GraphNode).filter(GraphNode.organization_id == organization_id).all()
    all_edges = db.query(GraphEdge).filter(
        GraphEdge.organization_id == organization_id,
        GraphEdge.is_stale.is_(False),
    ).all()

    if not all_nodes:
        sync_catalog_to_graph(db, organization_id)
        all_nodes = db.query(GraphNode).filter(GraphNode.organization_id == organization_id).all()
        all_edges = db.query(GraphEdge).filter(
            GraphEdge.organization_id == organization_id,
            GraphEdge.is_stale.is_(False),
        ).all()

    node_by_id = {n.id: n for n in all_nodes}
    svc_node = next((n for n in all_nodes if n.node_type == GraphNodeType.SERVICE and (n.entity_id == root_service.id or n.identifier == f"service:{root_service.id}")), None)

    # 1. Direct Entities
    direct_services = [{
        "service_id": str(root_service.id),
        "name": root_service.name,
        "tier": root_service.tier,
        "impact_type": "observed",
        "impact_level": "outage",
        "is_root": True,
    }]

    affected_repositories = []
    root_repos = db.query(ServiceRepository).filter(
        ServiceRepository.service_id == root_service.id,
        ServiceRepository.organization_id == organization_id,
    ).all()
    for sr in root_repos:
        repo = sr.repository
        if repo:
            affected_repositories.append({
                "repository_id": str(repo.id),
                "name": repo.name,
                "url": repo.github_url,
                "role": sr.role.value,
                "is_primary": sr.is_primary,
                "remediation_target": True,
                "evidence_only": False,
                "service_id": str(root_service.id),
            })

    # Endpoints directly on root service
    affected_endpoints = []
    ep_nodes = [n for n in all_nodes if n.node_type == GraphNodeType.ENDPOINT and n.entity_id == root_service.id]
    for ep in ep_nodes:
        meta = ep.metadata_json or {}
        affected_endpoints.append({
            "endpoint_id": str(ep.id),
            "name": ep.name,
            "method": meta.get("method", "GET"),
            "path": meta.get("path", ep.name),
            "service_id": str(root_service.id),
        })

    # Environments and Regions
    affected_environments = []
    affected_regions = []
    env_ids_seen: Set[uuid.UUID] = set()
    reg_ids_seen: Set[uuid.UUID] = set()

    dep_configs = db.query(ServiceDeploymentConfig).filter(
        ServiceDeploymentConfig.service_id == root_service.id,
        ServiceDeploymentConfig.organization_id == organization_id,
    ).all()
    for dc in dep_configs:
        if dc.environment and dc.environment.id not in env_ids_seen:
            env_ids_seen.add(dc.environment.id)
            affected_environments.append({
                "environment_id": str(dc.environment.id),
                "name": dc.environment.name,
                "env_type": dc.environment.env_type,
            })
        if dc.region and dc.region.id not in reg_ids_seen:
            reg_ids_seen.add(dc.region.id)
            affected_regions.append({
                "region_id": str(dc.region.id),
                "name": dc.region.name,
            })

    # Fallback to incident-scoped environment if specified
    if environment and environment.id not in env_ids_seen:
        affected_environments.append({
            "environment_id": str(environment.id),
            "name": environment.name,
            "env_type": environment.env_type,
        })

    # 2. Fetch Active Telemetry Signals (past 30m window)
    window_cutoff = datetime.now(timezone.utc) - timedelta(minutes=telemetry_window_minutes)
    recent_signals = db.query(TelemetrySignal).filter(
        TelemetrySignal.organization_id == organization_id,
        TelemetrySignal.observed_at >= window_cutoff,
    ).all()

    active_signals_by_service: Dict[uuid.UUID, List[Dict[str, Any]]] = {}
    for sig in recent_signals:
        if sig.service_id:
            active_signals_by_service.setdefault(sig.service_id, []).append({
                "signal_type": sig.signal_type.value if hasattr(sig.signal_type, "value") else str(sig.signal_type),
                "rule_name": sig.rule_name,
                "severity": "SEV-1" if "SEV-1" in sig.title else "SEV-2",
                "title": sig.title,
                "observed_at": sig.observed_at.isoformat() if sig.observed_at else None,
            })

    # 3. Downstream Traversal (Callers -> Customers)
    # Incoming CALLS edges where target is current service
    indirect_services: List[Dict[str, Any]] = []
    visited_downstream: Set[uuid.UUID] = set()
    if svc_node:
        visited_downstream.add(svc_node.id)

    # Queue: (node_id, current_distance, path_names, accumulated_criticality)
    queue: List[Tuple[uuid.UUID, int, List[str], ServiceCriticality]] = []
    if svc_node:
        queue.append((svc_node.id, 0, [root_service.name], ServiceCriticality.HARD))

    hard_dep_count = 0
    soft_dep_count = 0
    customer_facing_reached = False
    customer_facing_distance = 999

    while queue:
        curr_node_id, dist, path, acc_crit = queue.pop(0)
        if dist >= max_depth:
            continue

        # In-edges: callers that call curr_node
        incoming_edges = [e for e in all_edges if e.target_node_id == curr_node_id and e.edge_type in (GraphEdgeType.CALLS, GraphEdgeType.DEPENDS_ON)]
        for edge in incoming_edges:
            caller_node = node_by_id.get(edge.source_node_id)
            if not caller_node or caller_node.id in visited_downstream:
                continue

            visited_downstream.add(caller_node.id)
            caller_path = path + [caller_node.name]
            caller_crit = ServiceCriticality.HARD if (acc_crit == ServiceCriticality.HARD and edge.criticality == ServiceCriticality.HARD) else ServiceCriticality.SOFT

            if caller_crit == ServiceCriticality.HARD:
                hard_dep_count += 1
            else:
                soft_dep_count += 1

            # Check if caller has observed active telemetry anomalies
            caller_signals: List[Dict[str, Any]] = []
            if caller_node.entity_id:
                caller_signals = active_signals_by_service.get(caller_node.entity_id, [])

            impact_type = "observed" if len(caller_signals) > 0 else "inferred"

            # Numerical Impact Level
            if impact_type == "observed":
                impact_level = "outage" if caller_crit == ServiceCriticality.HARD else "degraded"
            else:
                impact_level = "outage" if caller_crit == ServiceCriticality.HARD else "degraded"

            # Check if caller is tier-1 customer facing
            if caller_node.tier in ("critical", "high") or any(word in caller_node.name.lower() for word in ("frontend", "gateway", "web", "ui", "api")):
                customer_facing_reached = True
                customer_facing_distance = min(customer_facing_distance, dist + 1)

            indirect_services.append({
                "service_id": str(caller_node.entity_id or caller_node.id),
                "name": caller_node.name,
                "tier": caller_node.tier,
                "impact_type": impact_type,
                "impact_level": impact_level,
                "criticality": caller_crit.value if hasattr(caller_crit, "value") else str(caller_crit),
                "distance": dist + 1,
                "path": caller_path,
                "observed_signals": caller_signals,
            })

            # Add caller's repositories as evidence-only
            if caller_node.entity_id:
                caller_repos = db.query(ServiceRepository).filter(
                    ServiceRepository.service_id == caller_node.entity_id,
                    ServiceRepository.organization_id == organization_id,
                ).all()
                for cr in caller_repos:
                    if cr.repository and not any(r["repository_id"] == str(cr.repository.id) for r in affected_repositories):
                        affected_repositories.append({
                            "repository_id": str(cr.repository.id),
                            "name": cr.repository.name,
                            "url": cr.repository.github_url,
                            "role": cr.role.value,
                            "is_primary": cr.is_primary,
                            "remediation_target": False,
                            "evidence_only": True,
                            "service_id": str(caller_node.entity_id),
                        })

            queue.append((caller_node.id, dist + 1, caller_path, caller_crit))

    # 4. Upstream Traversal (Dependencies -> Databases, Queues, Third-party)
    if svc_node:
        out_edges = [e for e in all_edges if e.source_node_id == svc_node.id]
        for oe in out_edges:
            target_node = node_by_id.get(oe.target_node_id)
            if target_node and target_node.id not in visited_downstream:
                if target_node.node_type in (GraphNodeType.DATABASE, GraphNodeType.QUEUE, GraphNodeType.EXTERNAL_PROVIDER) or oe.edge_type in (GraphEdgeType.STORES_IN, GraphEdgeType.PUBLISHES_TO, GraphEdgeType.DEPENDS_ON) or any(k in target_node.name.lower() for k in ("db", "database", "queue", "cache")):
                    indirect_services.append({
                        "service_id": str(target_node.entity_id or target_node.id),
                        "name": target_node.name,
                        "tier": target_node.tier,
                        "impact_type": "inferred",
                        "impact_level": "degraded" if oe.criticality == ServiceCriticality.SOFT else "outage",
                        "criticality": oe.criticality.value if hasattr(oe.criticality, "value") else str(oe.criticality),
                        "distance": 1,
                        "path": [root_service.name, target_node.name],
                        "observed_signals": [],
                    })

    # 5. Customer Traffic & User Impact Estimation
    observed_count = sum(1 for s in indirect_services if s["impact_type"] == "observed")
    has_measured = observed_count > 0

    if root_service.tier == "critical" or customer_facing_reached:
        base_traffic = 75.0 if customer_facing_distance <= 1 else 50.0
        base_user = 65.0 if customer_facing_distance <= 1 else 40.0
    elif root_service.tier == "high":
        base_traffic = 45.0
        base_user = 35.0
    elif root_service.tier == "low":
        base_traffic = 5.0
        base_user = 2.0
    else:
        base_traffic = 25.0
        base_user = 20.0

    # Adjust for soft vs hard dependencies
    if hard_dep_count == 0 and soft_dep_count > 0:
        base_traffic *= 0.25
        base_user *= 0.25

    traffic_percent = round(min(100.0, base_traffic + (observed_count * 5.0)), 1)
    user_percent = round(min(100.0, base_user + (observed_count * 4.0)), 1)

    customer_impact = {
        "traffic_percent": traffic_percent,
        "user_percent": user_percent,
        "traffic_impact_mode": "measured" if has_measured else "estimated",
        "traffic_confidence": "high" if has_measured else ("medium" if customer_facing_reached else "low"),
        "calculation_basis": (
            f"Measured from active telemetry across {observed_count} observed service anomalies with {hard_dep_count} hard and {soft_dep_count} soft dependencies."
            if has_measured else
            f"Structural graph traversal estimate: {len(indirect_services)} downstream services ({hard_dep_count} hard, {soft_dep_count} soft dependencies) reaching customer entrypoint at distance {customer_facing_distance}."
            if customer_facing_reached else
            f"Internal dependency estimate: {hard_dep_count} hard and {soft_dep_count} soft dependencies without customer-facing entrypoints."
        ),
    }

    criticality_summary = {
        "direct_service_count": len(direct_services),
        "indirect_service_count": len(indirect_services),
        "hard_dependencies": hard_dep_count,
        "soft_dependencies": soft_dep_count,
        "observed_anomalies": observed_count,
        "customer_facing_impact": customer_facing_reached,
    }

    unknowns = []
    if len(all_nodes) <= 1:
        unknowns.append("Service graph contains limited topology data. Run catalog sync or trace ingestion for higher fidelity.")
    if soft_dep_count > 0 and observed_count == 0:
        unknowns.append("Soft dependencies detected without active telemetry confirmation. Downstream services may be operating in fallback mode.")

    graph_hash = compute_graph_snapshot_hash(all_nodes, all_edges)

    # 6. Versioning & Report Persistence
    new_version = 1
    if incident:
        # Check existing reports
        prev_reports = db.query(IncidentBlastRadiusReport).filter(
            IncidentBlastRadiusReport.organization_id == organization_id,
            IncidentBlastRadiusReport.incident_id == incident.id,
        ).order_by(IncidentBlastRadiusReport.version.desc()).all()

        if prev_reports:
            new_version = prev_reports[0].version + 1
            for p in prev_reports:
                p.is_current = False

    report = IncidentBlastRadiusReport(
        organization_id=organization_id,
        incident_id=incident.id if incident else uuid.uuid4(),
        root_service_id=root_service.id,
        version=new_version,
        is_current=True,
        calculated_at=datetime.now(timezone.utc),
        engine_version="v1.0.0",
        telemetry_window_minutes=telemetry_window_minutes,
        graph_snapshot_hash=graph_hash,
        direct_services=direct_services,
        indirect_services=indirect_services,
        affected_endpoints=affected_endpoints,
        affected_repositories=affected_repositories,
        affected_environments=affected_environments,
        affected_regions=affected_regions,
        customer_impact=customer_impact,
        criticality_summary=criticality_summary,
        unknowns=unknowns,
    )

    if incident:
        db.add(report)
        db.commit()
        db.refresh(report)

    return report


def enqueue_blast_radius_recalculation(
    db: Session,
    incident_id: uuid.UUID,
    force: bool = False,
) -> Optional[IncidentBlastRadiusReport]:
    """
    Debounced handler to recalculate blast radius for an active incident.
    Enforces minimum 60s cooldown unless forced.
    """
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident or not incident.service_id:
        return None

    root_svc = db.query(Service).filter(Service.id == incident.service_id).first()
    if not root_svc:
        return None

    # Check cooldown
    if not force:
        latest_report = db.query(IncidentBlastRadiusReport).filter(
            IncidentBlastRadiusReport.incident_id == incident_id,
            IncidentBlastRadiusReport.is_current.is_(True),
        ).first()

        if latest_report:
            elapsed = (datetime.now(timezone.utc) - latest_report.calculated_at.replace(tzinfo=timezone.utc)).total_seconds()
            if elapsed < DEBOUNCE_COOLDOWN_SECONDS:
                logger.info(f"Blast radius recalculation debounced for incident {incident_id} ({elapsed:.1f}s < {DEBOUNCE_COOLDOWN_SECONDS}s).")
                return latest_report

    try:
        env = db.query(Environment).filter(Environment.id == incident.environment_id).first() if incident.environment_id else None
        report = calculate_blast_radius(
            db=db,
            organization_id=incident.organization_id,
            root_service=root_svc,
            incident=incident,
            environment=env,
        )
        return report
    except Exception as e:
        logger.warning(f"Background blast radius recalculation failed for incident {incident_id}: {e}")
        return None
