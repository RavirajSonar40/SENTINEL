"""Service Graph & Topology Ingestion Engine (Phase 6)."""

import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import or_

from app.models.incident import (
    Service, Repository, ServiceRepository, ServiceOwnership,
    ServiceDependency, ServiceDeploymentConfig, Team, Environment, Region,
    GraphNode, GraphEdge, GraphNodeType, GraphEdgeType, GraphEdgeSource,
    ServiceCriticality, ServiceDependencyType
)
from app.schemas.graph import (
    GraphNodeResponse, GraphEdgeResponse, TopologyGraphResponse, TraceSpanItem
)

logger = logging.getLogger(__name__)

SENSITIVE_KEYS = {
    "authorization", "cookie", "token", "secret", "password",
    "api_key", "access_token", "private_key", "client_secret",
    "x-sentinel-signature", "x-hub-signature-256", "sentry-hook-signature",
    "session", "jwt", "bearer"
}


def sanitize_attributes(payload: Any) -> Any:
    """Recursively strip credentials, tokens, and cap sizes on span/manifest attributes."""
    if isinstance(payload, dict):
        sanitized = {}
        for k, v in payload.items():
            if any(sens in str(k).lower() for sens in SENSITIVE_KEYS):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_attributes(v)
        return sanitized
    elif isinstance(payload, list):
        return [sanitize_attributes(x) for x in payload[:50]]
    elif isinstance(payload, str):
        if len(payload) > 1000:
            return payload[:1000] + "... [truncated]"
        return payload
    return payload


def sync_catalog_to_graph(db: Session, organization_id: uuid.UUID) -> Dict[str, int]:
    """
    Synchronizes explicit catalog entities into the multi-entity System Graph.
    Uses stable identifiers and atomic upserts without overwriting manual corrections.
    """
    nodes_created = 0
    nodes_updated = 0
    edges_created = 0
    edges_updated = 0

    # 1. Sync Services
    services = db.query(Service).filter(Service.organization_id == organization_id).all()
    svc_node_map: Dict[uuid.UUID, GraphNode] = {}
    for svc in services:
        identifier = f"service:{svc.id}"
        node = db.query(GraphNode).filter(
            GraphNode.organization_id == organization_id,
            GraphNode.node_type == GraphNodeType.SERVICE,
            GraphNode.identifier == identifier,
        ).first()

        meta = {"slug": svc.slug, "language": getattr(svc, "language", None)}
        if not node:
            node = GraphNode(
                organization_id=organization_id,
                node_type=GraphNodeType.SERVICE,
                name=svc.name,
                identifier=identifier,
                tier=svc.tier,
                entity_id=svc.id,
                metadata_json=meta,
            )
            db.add(node)
            nodes_created += 1
        else:
            node.name = svc.name
            node.tier = svc.tier
            node.entity_id = svc.id
            node.metadata_json = meta
            node.updated_at = datetime.now(timezone.utc)
            nodes_updated += 1
        db.flush()
        svc_node_map[svc.id] = node

    # 2. Sync Repositories
    repos = db.query(Repository).filter(Repository.organization_id == organization_id).all()
    repo_node_map: Dict[uuid.UUID, GraphNode] = {}
    for repo in repos:
        identifier = f"repo:{repo.id}"
        node = db.query(GraphNode).filter(
            GraphNode.organization_id == organization_id,
            GraphNode.node_type == GraphNodeType.REPOSITORY,
            GraphNode.identifier == identifier,
        ).first()

        meta = {"github_url": repo.github_url, "default_branch": getattr(repo, "default_branch", "main")}
        if not node:
            node = GraphNode(
                organization_id=organization_id,
                node_type=GraphNodeType.REPOSITORY,
                name=repo.name,
                identifier=identifier,
                tier=None,
                entity_id=repo.id,
                metadata_json=meta,
            )
            db.add(node)
            nodes_created += 1
        else:
            node.name = repo.name
            node.entity_id = repo.id
            node.metadata_json = meta
            node.updated_at = datetime.now(timezone.utc)
            nodes_updated += 1
        db.flush()
        repo_node_map[repo.id] = node

    # 3. Sync Teams
    teams = db.query(Team).filter(Team.organization_id == organization_id).all()
    team_node_map: Dict[uuid.UUID, GraphNode] = {}
    for team in teams:
        identifier = f"team:{team.id}"
        node = db.query(GraphNode).filter(
            GraphNode.organization_id == organization_id,
            GraphNode.node_type == GraphNodeType.TEAM,
            GraphNode.identifier == identifier,
        ).first()

        meta = {"slug": team.slug}
        if not node:
            node = GraphNode(
                organization_id=organization_id,
                node_type=GraphNodeType.TEAM,
                name=team.name,
                identifier=identifier,
                tier=None,
                entity_id=team.id,
                metadata_json=meta,
            )
            db.add(node)
            nodes_created += 1
        else:
            node.name = team.name
            node.entity_id = team.id
            node.metadata_json = meta
            node.updated_at = datetime.now(timezone.utc)
            nodes_updated += 1
        db.flush()
        team_node_map[team.id] = node

    # 4. Sync Environments
    envs = db.query(Environment).filter(Environment.organization_id == organization_id).all()
    env_node_map: Dict[uuid.UUID, GraphNode] = {}
    for env in envs:
        identifier = f"env:{env.id}"
        node = db.query(GraphNode).filter(
            GraphNode.organization_id == organization_id,
            GraphNode.node_type == GraphNodeType.ENVIRONMENT,
            GraphNode.identifier == identifier,
        ).first()

        meta = {"env_type": env.env_type}
        if not node:
            node = GraphNode(
                organization_id=organization_id,
                node_type=GraphNodeType.ENVIRONMENT,
                name=env.name,
                identifier=identifier,
                tier=None,
                entity_id=env.id,
                metadata_json=meta,
            )
            db.add(node)
            nodes_created += 1
        else:
            node.name = env.name
            node.entity_id = env.id
            node.metadata_json = meta
            node.updated_at = datetime.now(timezone.utc)
            nodes_updated += 1
        db.flush()
        env_node_map[env.id] = node

    # 5. Sync Service <-> Repository Edges (IMPLEMENTED_BY)
    svc_repos = db.query(ServiceRepository).filter(ServiceRepository.organization_id == organization_id).all()
    for sr in svc_repos:
        s_node = svc_node_map.get(sr.service_id)
        r_node = repo_node_map.get(sr.repository_id)
        if s_node and r_node:
            edge = db.query(GraphEdge).filter(
                GraphEdge.organization_id == organization_id,
                GraphEdge.source_node_id == s_node.id,
                GraphEdge.target_node_id == r_node.id,
                GraphEdge.edge_type == GraphEdgeType.IMPLEMENTED_BY,
            ).first()

            if not edge:
                edge = GraphEdge(
                    organization_id=organization_id,
                    source_node_id=s_node.id,
                    target_node_id=r_node.id,
                    edge_type=GraphEdgeType.IMPLEMENTED_BY,
                    source=GraphEdgeSource.REPOSITORY_CONFIG,
                    confidence=1.0,
                    criticality=ServiceCriticality.HARD,
                    metadata_json={"role": sr.role.value, "is_primary": sr.is_primary},
                )
                db.add(edge)
                edges_created += 1
            elif edge.source != GraphEdgeSource.MANUAL_CORRECTION:
                edge.metadata_json = {"role": sr.role.value, "is_primary": sr.is_primary}
                edge.confidence = 1.0
                edge.updated_at = datetime.now(timezone.utc)
                edges_updated += 1

    # 6. Sync Service <-> Team Edges (OWNED_BY)
    svc_owners = db.query(ServiceOwnership).filter(ServiceOwnership.organization_id == organization_id).all()
    for so in svc_owners:
        s_node = svc_node_map.get(so.service_id)
        t_node = team_node_map.get(so.team_id)
        if s_node and t_node:
            edge = db.query(GraphEdge).filter(
                GraphEdge.organization_id == organization_id,
                GraphEdge.source_node_id == s_node.id,
                GraphEdge.target_node_id == t_node.id,
                GraphEdge.edge_type == GraphEdgeType.OWNED_BY,
            ).first()

            if not edge:
                edge = GraphEdge(
                    organization_id=organization_id,
                    source_node_id=s_node.id,
                    target_node_id=t_node.id,
                    edge_type=GraphEdgeType.OWNED_BY,
                    source=GraphEdgeSource.SERVICE_REGISTRATION,
                    confidence=1.0,
                    criticality=ServiceCriticality.HARD,
                    metadata_json={"ownership_type": so.ownership_type.value, "escalation_policy": so.escalation_policy},
                )
                db.add(edge)
                edges_created += 1
            elif edge.source != GraphEdgeSource.MANUAL_CORRECTION:
                edge.metadata_json = {"ownership_type": so.ownership_type.value, "escalation_policy": so.escalation_policy}
                edge.confidence = 1.0
                edge.updated_at = datetime.now(timezone.utc)
                edges_updated += 1

    # 7. Sync Service <-> Environment Deployment Edges (DEPLOYED_AS)
    dep_cfgs = db.query(ServiceDeploymentConfig).filter(ServiceDeploymentConfig.organization_id == organization_id).all()
    for dc in dep_cfgs:
        s_node = svc_node_map.get(dc.service_id)
        e_node = env_node_map.get(dc.environment_id)
        if s_node and e_node:
            edge = db.query(GraphEdge).filter(
                GraphEdge.organization_id == organization_id,
                GraphEdge.source_node_id == s_node.id,
                GraphEdge.target_node_id == e_node.id,
                GraphEdge.edge_type == GraphEdgeType.DEPLOYED_AS,
            ).first()

            if not edge:
                edge = GraphEdge(
                    organization_id=organization_id,
                    source_node_id=s_node.id,
                    target_node_id=e_node.id,
                    edge_type=GraphEdgeType.DEPLOYED_AS,
                    source=GraphEdgeSource.SERVICE_REGISTRATION,
                    confidence=1.0,
                    criticality=ServiceCriticality.HARD,
                    metadata_json={"health_check_url": dc.health_check_url, "is_active": dc.is_active},
                )
                db.add(edge)
                edges_created += 1

    # 8. Sync Service Dependencies (CALLS, STORES_IN, PUBLISHES_TO)
    deps = db.query(ServiceDependency).filter(ServiceDependency.organization_id == organization_id).all()
    for d in deps:
        s_node = svc_node_map.get(d.service_id)
        target_node = None

        if d.depends_on_service_id and d.depends_on_service_id in svc_node_map:
            target_node = svc_node_map[d.depends_on_service_id]
        elif d.dependency_type in (ServiceDependencyType.DATABASE, ServiceDependencyType.CACHE):
            # Database or cache infrastructure node
            db_identifier = f"database:{d.service_id}:{d.dependency_type.value}"
            target_node = db.query(GraphNode).filter(
                GraphNode.organization_id == organization_id,
                GraphNode.node_type == GraphNodeType.DATABASE,
                GraphNode.identifier == db_identifier,
            ).first()
            if not target_node:
                target_node = GraphNode(
                    organization_id=organization_id,
                    node_type=GraphNodeType.DATABASE,
                    name=f"{s_node.name if s_node else 'service'}-{d.dependency_type.value}",
                    identifier=db_identifier,
                    tier="critical",
                    entity_id=None,
                    metadata_json={"engine": d.dependency_type.value},
                )
                db.add(target_node)
                nodes_created += 1
                db.flush()
        elif d.dependency_type == ServiceDependencyType.ASYNCHRONOUS:
            # Queue node
            q_identifier = f"queue:{d.service_id}:events"
            target_node = db.query(GraphNode).filter(
                GraphNode.organization_id == organization_id,
                GraphNode.node_type == GraphNodeType.QUEUE,
                GraphNode.identifier == q_identifier,
            ).first()
            if not target_node:
                target_node = GraphNode(
                    organization_id=organization_id,
                    node_type=GraphNodeType.QUEUE,
                    name=f"{s_node.name if s_node else 'service'}-queue",
                    identifier=q_identifier,
                    tier="medium",
                    entity_id=None,
                    metadata_json={"type": "message_broker"},
                )
                db.add(target_node)
                nodes_created += 1
                db.flush()

        if s_node and target_node and s_node.id != target_node.id:
            edge_type = GraphEdgeType.CALLS
            if d.dependency_type in (ServiceDependencyType.DATABASE, ServiceDependencyType.CACHE):
                edge_type = GraphEdgeType.STORES_IN
            elif d.dependency_type == ServiceDependencyType.ASYNCHRONOUS:
                edge_type = GraphEdgeType.PUBLISHES_TO

            edge = db.query(GraphEdge).filter(
                GraphEdge.organization_id == organization_id,
                GraphEdge.source_node_id == s_node.id,
                GraphEdge.target_node_id == target_node.id,
                GraphEdge.edge_type == edge_type,
            ).first()

            if not edge:
                edge = GraphEdge(
                    organization_id=organization_id,
                    source_node_id=s_node.id,
                    target_node_id=target_node.id,
                    edge_type=edge_type,
                    source=GraphEdgeSource.SERVICE_REGISTRATION,
                    confidence=1.0,
                    criticality=d.criticality,
                    metadata_json={"dependency_type": d.dependency_type.value, "description": d.description},
                )
                db.add(edge)
                edges_created += 1
            elif edge.source != GraphEdgeSource.MANUAL_CORRECTION:
                edge.criticality = d.criticality
                edge.confidence = 1.0
                edge.updated_at = datetime.now(timezone.utc)
                edges_updated += 1

    db.commit()
    return {
        "nodes_created": nodes_created,
        "nodes_updated": nodes_updated,
        "edges_created": edges_created,
        "edges_updated": edges_updated,
    }


def ingest_trace_spans(
    db: Session,
    organization_id: uuid.UUID,
    spans: List[TraceSpanItem],
) -> Dict[str, Any]:
    """
    Ingests batch OpenTelemetry trace spans, discovers dynamic client->server relationships,
    updates observed p99 latency/error metrics, and computes exponential confidence scores.
    """
    if len(spans) > 500:
        raise ValueError("Maximum trace span batch size is 500.")

    edges_created = 0
    edges_updated = 0
    spans_processed = 0

    for span in spans:
        if not span.service_name or not span.peer_service:
            continue
        if span.service_name.strip() == span.peer_service.strip():
            continue

        caller_name = span.service_name.strip()
        callee_name = span.peer_service.strip()
        sanitized_attrs = sanitize_attributes(span.attributes or {})

        # Find or create caller node
        caller_id = f"service:name:{caller_name.lower()}"
        caller_node = db.query(GraphNode).filter(
            GraphNode.organization_id == organization_id,
            GraphNode.node_type == GraphNodeType.SERVICE,
            or_(GraphNode.name == caller_name, GraphNode.identifier == caller_id),
        ).first()

        if not caller_node:
            # Check if matching Service entity exists
            svc = db.query(Service).filter(
                Service.organization_id == organization_id,
                Service.name == caller_name,
            ).first()
            caller_node = GraphNode(
                organization_id=organization_id,
                node_type=GraphNodeType.SERVICE,
                name=caller_name,
                identifier=f"service:{svc.id}" if svc else caller_id,
                tier=svc.tier if svc else "medium",
                entity_id=svc.id if svc else None,
                metadata_json={"auto_discovered": True},
            )
            db.add(caller_node)
            db.flush()

        # Find or create callee node
        callee_id = f"service:name:{callee_name.lower()}"
        callee_node = db.query(GraphNode).filter(
            GraphNode.organization_id == organization_id,
            GraphNode.node_type == GraphNodeType.SERVICE,
            or_(GraphNode.name == callee_name, GraphNode.identifier == callee_id),
        ).first()

        if not callee_node:
            svc_callee = db.query(Service).filter(
                Service.organization_id == organization_id,
                Service.name == callee_name,
            ).first()
            callee_node = GraphNode(
                organization_id=organization_id,
                node_type=GraphNodeType.SERVICE,
                name=callee_name,
                identifier=f"service:{svc_callee.id}" if svc_callee else callee_id,
                tier=svc_callee.tier if svc_callee else "medium",
                entity_id=svc_callee.id if svc_callee else None,
                metadata_json={"auto_discovered": True},
            )
            db.add(callee_node)
            db.flush()

        # Check existing edge
        edge = db.query(GraphEdge).filter(
            GraphEdge.organization_id == organization_id,
            GraphEdge.source_node_id == caller_node.id,
            GraphEdge.target_node_id == callee_node.id,
            GraphEdge.edge_type == GraphEdgeType.CALLS,
        ).first()

        duration = float(span.duration_ms or 0.0)
        is_err = bool(span.is_error or (span.http_status_code and span.http_status_code >= 500))

        if not edge:
            meta = {
                "sample_count": 1,
                "error_count": 1 if is_err else 0,
                "p99_latency_ms": duration,
                "last_observed_at": datetime.now(timezone.utc).isoformat(),
                "endpoints": [span.http_url] if span.http_url else [],
                "attributes": sanitized_attrs,
            }
            edge = GraphEdge(
                organization_id=organization_id,
                source_node_id=caller_node.id,
                target_node_id=callee_node.id,
                edge_type=GraphEdgeType.CALLS,
                source=GraphEdgeSource.OPENTELEMETRY_TRACE,
                confidence=0.5,  # initial discovery baseline
                criticality=ServiceCriticality.HARD,
                is_stale=False,
                metadata_json=meta,
            )
            db.add(edge)
            edges_created += 1
        else:
            meta = edge.metadata_json or {}
            samples = int(meta.get("sample_count", 0)) + 1
            errors = int(meta.get("error_count", 0)) + (1 if is_err else 0)
            prev_lat = float(meta.get("p99_latency_ms", duration))
            # Moving exponential latency estimate
            new_lat = max(prev_lat, duration) if duration > prev_lat else (0.9 * prev_lat + 0.1 * duration)

            meta["sample_count"] = samples
            meta["error_count"] = errors
            meta["error_rate"] = round(errors / max(samples, 1), 4)
            meta["p99_latency_ms"] = round(new_lat, 2)
            meta["last_observed_at"] = datetime.now(timezone.utc).isoformat()
            if span.http_url and span.http_url not in meta.get("endpoints", []):
                meta["endpoints"] = (meta.get("endpoints", []) + [span.http_url])[:10]

            edge.metadata_json = meta
            flag_modified(edge, "metadata_json")
            edge.is_stale = False

            # Update confidence using exponential saturation formula if trace-derived
            if edge.source == GraphEdgeSource.OPENTELEMETRY_TRACE:
                prev_conf = float(edge.confidence)
                new_conf = min(0.95, prev_conf + 0.05 * (1.0 - prev_conf))
                edge.confidence = round(new_conf, 4)
            elif edge.source == GraphEdgeSource.MANUAL_CORRECTION:
                edge.confidence = 1.0

            edge.updated_at = datetime.now(timezone.utc)
            edges_updated += 1

        spans_processed += 1

    db.commit()
    return {
        "spans_processed": spans_processed,
        "edges_created": edges_created,
        "edges_updated": edges_updated,
    }


def import_manifest_spec(
    db: Session,
    organization_id: uuid.UUID,
    manifest_type: str,
    content: Dict[str, Any],
    service_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """
    Imports infrastructure and endpoint definitions from OpenAPI / K8s manifests.
    """
    sanitized = sanitize_attributes(content)
    nodes_created = 0
    edges_created = 0

    if manifest_type.lower() == "openapi" and service_id:
        svc = db.query(Service).filter(Service.id == service_id, Service.organization_id == organization_id).first()
        if svc:
            svc_node = db.query(GraphNode).filter(
                GraphNode.organization_id == organization_id,
                GraphNode.node_type == GraphNodeType.SERVICE,
                GraphNode.identifier == f"service:{svc.id}",
            ).first()

            paths = sanitized.get("paths", {})
            for path_str, methods in paths.items():
                if isinstance(methods, dict):
                    for method in methods.keys():
                        if method.upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                            ep_id = f"endpoint:{svc.id}:{method.upper()} {path_str}"
                            ep_node = db.query(GraphNode).filter(
                                GraphNode.organization_id == organization_id,
                                GraphNode.node_type == GraphNodeType.ENDPOINT,
                                GraphNode.identifier == ep_id,
                            ).first()

                            if not ep_node:
                                ep_node = GraphNode(
                                    organization_id=organization_id,
                                    node_type=GraphNodeType.ENDPOINT,
                                    name=f"{method.upper()} {path_str}",
                                    identifier=ep_id,
                                    tier=svc.tier,
                                    entity_id=svc.id,
                                    metadata_json={"method": method.upper(), "path": path_str},
                                )
                                db.add(ep_node)
                                nodes_created += 1
                                db.flush()

                            if svc_node:
                                edge = db.query(GraphEdge).filter(
                                    GraphEdge.organization_id == organization_id,
                                    GraphEdge.source_node_id == svc_node.id,
                                    GraphEdge.target_node_id == ep_node.id,
                                ).first()
                                if not edge:
                                    edge = GraphEdge(
                                        organization_id=organization_id,
                                        source_node_id=svc_node.id,
                                        target_node_id=ep_node.id,
                                        edge_type=GraphEdgeType.IMPLEMENTED_BY,
                                        source=GraphEdgeSource.API_SPEC,
                                        confidence=0.9,
                                        criticality=ServiceCriticality.HARD,
                                    )
                                    db.add(edge)
                                    edges_created += 1

    db.commit()
    return {"nodes_created": nodes_created, "edges_created": edges_created}


def apply_edge_decay(db: Session, organization_id: uuid.UUID, days_threshold: int = 7) -> int:
    """
    Decays confidence of trace/import derived edges not observed within the threshold window.
    Catalog and Manual Correction edges are completely exempt.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_threshold)
    edges = db.query(GraphEdge).filter(
        GraphEdge.organization_id == organization_id,
        GraphEdge.source.in_([GraphEdgeSource.OPENTELEMETRY_TRACE, GraphEdgeSource.IMPORT_ANALYSIS]),
        or_(GraphEdge.updated_at < cutoff, GraphEdge.updated_at.is_(None)),
    ).all()

    decayed = 0
    for edge in edges:
        edge.confidence = max(0.1, round(float(edge.confidence) - 0.05, 4))
        if edge.confidence <= 0.1:
            edge.is_stale = True
        decayed += 1

    db.commit()
    return decayed


def get_topology_graph(
    db: Session,
    organization_id: uuid.UUID,
    node_type: Optional[str] = None,
    tier: Optional[str] = None,
    include_stale: bool = False,
) -> TopologyGraphResponse:
    """Returns filtered system topology graph with summary counts."""
    q_nodes = db.query(GraphNode).filter(GraphNode.organization_id == organization_id)
    if node_type:
        try:
            nt = GraphNodeType(node_type.upper())
            q_nodes = q_nodes.filter(GraphNode.node_type == nt)
        except Exception:
            pass
    if tier:
        q_nodes = q_nodes.filter(GraphNode.tier == tier)

    nodes = q_nodes.all()
    node_ids = {n.id for n in nodes}

    q_edges = db.query(GraphEdge).filter(
        GraphEdge.organization_id == organization_id,
        GraphEdge.source_node_id.in_(node_ids),
        GraphEdge.target_node_id.in_(node_ids),
    )
    if not include_stale:
        q_edges = q_edges.filter(GraphEdge.is_stale.is_(False))

    edges = q_edges.all()

    by_type: Dict[str, int] = {}
    for n in nodes:
        t = n.node_type.value if hasattr(n.node_type, "value") else str(n.node_type)
        by_type[t] = by_type.get(t, 0) + 1

    return TopologyGraphResponse(
        nodes=[GraphNodeResponse.model_validate(n) for n in nodes],
        edges=[GraphEdgeResponse.model_validate(e) for e in edges],
        node_count=len(nodes),
        edge_count=len(edges),
        nodes_by_type=by_type,
    )
