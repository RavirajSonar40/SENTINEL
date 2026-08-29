"""REST API Routes for System Service Graph & Blast Radius Analysis (Phase 6)."""

import uuid
from typing import Optional, List, Dict, Any, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query, status, Header, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import require_role
from app.models.incident import (
    Organization, UserOrganizationMembership, MembershipRole,
    GraphNode, GraphEdge, GraphNodeType, GraphEdgeType, GraphEdgeSource,
    Incident, Service, Environment, IncidentBlastRadiusReport, WebhookEndpoint
)
from app.core.crypto import verify_hmac_sha256, decrypt_secret
import secrets
from app.schemas.graph import (
    GraphNodeCreate, GraphNodeUpdate, GraphNodeResponse,
    GraphEdgeCreate, GraphEdgeUpdate, GraphEdgeResponse,
    TopologyGraphResponse, TraceSpanIngestRequest, ManifestImportRequest,
    BlastRadiusSimulationRequest, IncidentBlastRadiusReportResponse
)
from app.services.graph_service import (
    sync_catalog_to_graph, ingest_trace_spans, import_manifest_spec,
    get_topology_graph
)
from app.services.blast_radius_service import (
    calculate_blast_radius, enqueue_blast_radius_recalculation
)

router = APIRouter(prefix="/graph", tags=["Service Graph & Blast Radius"])


# ============================================================================
# 1. SYSTEM TOPOLOGY & GRAPH CRUD
# ============================================================================

@router.get("/topology", response_model=TopologyGraphResponse)
async def get_topology(
    node_type: Optional[str] = Query(None, description="Filter by node type (SERVICE, DATABASE, etc.)"),
    tier: Optional[str] = Query(None, description="Filter by tier (critical, high, medium, low)"),
    include_stale: bool = Query(False, description="Include stale inferred edges"),
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """Retrieve filtered organization system topology graph."""
    org, _ = auth_ctx
    return get_topology_graph(
        db=db,
        organization_id=org.id,
        node_type=node_type,
        tier=tier,
        include_stale=include_stale,
    )


@router.post("/nodes", response_model=GraphNodeResponse, status_code=status.HTTP_201_CREATED)
async def create_graph_node(
    data: GraphNodeCreate,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """Create custom/infrastructure node. Requires ADMIN role."""
    org, _ = auth_ctx

    existing = db.query(GraphNode).filter(
        GraphNode.organization_id == org.id,
        GraphNode.node_type == data.node_type,
        GraphNode.identifier == data.identifier,
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Node with identifier '{data.identifier}' already exists in this organization."
        )

    node = GraphNode(
        organization_id=org.id,
        node_type=data.node_type,
        name=data.name,
        identifier=data.identifier,
        tier=data.tier,
        entity_id=data.entity_id,
        metadata_json=data.metadata_json,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return GraphNodeResponse.model_validate(node)


@router.get("/nodes/{node_id}", response_model=GraphNodeResponse)
async def get_graph_node(
    node_id: uuid.UUID,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """Get single graph node by ID. Scoped strictly to organization."""
    org, _ = auth_ctx
    node = db.query(GraphNode).filter(
        GraphNode.id == node_id,
        GraphNode.organization_id == org.id,
    ).first()
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Graph node not found.")
    return GraphNodeResponse.model_validate(node)


@router.post("/edges", response_model=GraphEdgeResponse, status_code=status.HTTP_201_CREATED)
async def create_or_update_edge(
    data: GraphEdgeCreate,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """
    Create or manually correct a graph edge with confidence.
    Enforces cross-tenant isolation: both nodes must belong to the caller's organization.
    """
    org, _ = auth_ctx

    # Verify source & target exist in caller's organization
    src = db.query(GraphNode).filter(GraphNode.id == data.source_node_id, GraphNode.organization_id == org.id).first()
    tgt = db.query(GraphNode).filter(GraphNode.id == data.target_node_id, GraphNode.organization_id == org.id).first()
    if not src or not tgt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source and target nodes must both exist within your organization."
        )

    edge = db.query(GraphEdge).filter(
        GraphEdge.organization_id == org.id,
        GraphEdge.source_node_id == src.id,
        GraphEdge.target_node_id == tgt.id,
        GraphEdge.edge_type == data.edge_type,
    ).first()

    if not edge:
        edge = GraphEdge(
            organization_id=org.id,
            source_node_id=src.id,
            target_node_id=tgt.id,
            edge_type=data.edge_type,
            source=data.source,
            confidence=data.confidence,
            criticality=data.criticality,
            metadata_json=data.metadata_json,
        )
        db.add(edge)
    else:
        edge.source = data.source
        edge.confidence = data.confidence
        edge.criticality = data.criticality
        edge.metadata_json = data.metadata_json
        edge.is_stale = False

    db.commit()
    db.refresh(edge)
    return GraphEdgeResponse.model_validate(edge)


@router.delete("/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_graph_edge(
    edge_id: uuid.UUID,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """Delete a graph edge. Requires ADMIN role."""
    org, _ = auth_ctx
    edge = db.query(GraphEdge).filter(
        GraphEdge.id == edge_id,
        GraphEdge.organization_id == org.id,
    ).first()
    if not edge:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Graph edge not found.")
    db.delete(edge)
    db.commit()
    return None


@router.post("/sync-catalog")
async def trigger_catalog_sync(
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.OPERATOR)),
    db: Session = Depends(get_db),
):
    """Synchronize catalog entities into system graph. Requires OPERATOR role."""
    org, _ = auth_ctx
    stats = sync_catalog_to_graph(db, org.id)
    return {"status": "synchronized", "stats": stats}


# ============================================================================
# 2. SECURE TRACE & MANIFEST INGESTION
# ============================================================================

@router.post("/traces/ingest")
async def ingest_traces(
    payload: TraceSpanIngestRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
    x_sentinel_key_id: Optional[str] = Header(None),
    x_sentinel_signature: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """
    Secure trace span batch ingestion for dynamic call graph discovery.
    Supports either Bearer token / HMAC against WebhookEndpoint or User Auth session.
    """
    # 1. Attempt token-based webhook authentication
    org_id = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "").strip()
        endpoints = db.query(WebhookEndpoint).filter(
            WebhookEndpoint.is_active.is_(True),
            WebhookEndpoint.provider.in_(["opentelemetry", "generic"]),
        ).all()
        for ep in endpoints:
            try:
                secret = decrypt_secret(ep.encrypted_secret)
                if secrets.compare_digest(token, secret):
                    org_id = ep.organization_id
                    break
            except Exception:
                continue

    if not org_id and x_sentinel_key_id and x_sentinel_signature:
        body = await request.body()
        ep = db.query(WebhookEndpoint).filter(
            WebhookEndpoint.key_id == x_sentinel_key_id,
            WebhookEndpoint.is_active.is_(True),
        ).first()
        if ep:
            try:
                secret = decrypt_secret(ep.encrypted_secret)
                if verify_hmac_sha256(secret, body, x_sentinel_signature):
                    org_id = ep.organization_id
            except Exception:
                pass

    if not org_id:
        # Fallback to standard User session auth
        try:
            from app.routes.catalog import get_current_org_membership
            from app.core.auth import get_current_user
            user = await get_current_user(request, db)
            org, mem = await get_current_org_membership(request, user, db)
            if mem.role in (MembershipRole.OPERATOR, MembershipRole.ADMIN, MembershipRole.OWNER):
                org_id = org.id
        except Exception:
            pass

    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed. Provide valid Webhook token or OPERATOR credentials."
        )

    res = ingest_trace_spans(db, org_id, payload.spans)
    return {"status": "ingested", **res}


@router.post("/manifests/import")
async def import_manifest(
    data: ManifestImportRequest,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.OPERATOR)),
    db: Session = Depends(get_db),
):
    """Import OpenAPI or infrastructure manifest into graph. Requires OPERATOR role."""
    org, _ = auth_ctx
    res = import_manifest_spec(
        db=db,
        organization_id=org.id,
        manifest_type=data.manifest_type,
        content=data.content,
        service_id=data.service_id,
    )
    return {"status": "imported", **res}


# ============================================================================
# 3. BLAST RADIUS SIMULATION & INCIDENT REPORTS
# ============================================================================

@router.post("/blast-radius")
async def simulate_blast_radius(
    data: BlastRadiusSimulationRequest,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.OPERATOR)),
    db: Session = Depends(get_db),
):
    """
    On-demand blast radius simulation for any service without mutating incidents.
    Calculates downstream customer impact, upstream dependencies, and evidence-only repos.
    """
    org, _ = auth_ctx
    svc = db.query(Service).filter(Service.id == data.service_id, Service.organization_id == org.id).first()
    if not svc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found.")

    env = db.query(Environment).filter(Environment.id == data.environment_id, Environment.organization_id == org.id).first() if data.environment_id else None

    report = calculate_blast_radius(
        db=db,
        organization_id=org.id,
        root_service=svc,
        incident=None,
        environment=env,
        max_depth=data.max_depth,
    )
    return report


@router.get("/incidents/{incident_id}/blast-radius", response_model=IncidentBlastRadiusReportResponse)
async def get_incident_blast_radius(
    incident_id: uuid.UUID,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.VIEWER)),
    db: Session = Depends(get_db),
):
    """Get the current blast radius report for an active incident."""
    org, _ = auth_ctx
    incident = db.query(Incident).filter(Incident.id == incident_id, Incident.organization_id == org.id).first()
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found.")

    report = db.query(IncidentBlastRadiusReport).filter(
        IncidentBlastRadiusReport.incident_id == incident.id,
        IncidentBlastRadiusReport.organization_id == org.id,
        IncidentBlastRadiusReport.is_current.is_(True),
    ).first()

    if not report and incident.service_id:
        svc = db.query(Service).filter(Service.id == incident.service_id).first()
        if svc:
            report = calculate_blast_radius(db, org.id, svc, incident=incident)

    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blast radius report not available for this incident.")

    return IncidentBlastRadiusReportResponse.model_validate(report)


@router.post("/incidents/{incident_id}/blast-radius/recalculate", response_model=IncidentBlastRadiusReportResponse)
async def force_recalculate_blast_radius(
    incident_id: uuid.UUID,
    auth_ctx: Tuple[Organization, UserOrganizationMembership] = Depends(require_role(MembershipRole.OPERATOR)),
    db: Session = Depends(get_db),
):
    """Force on-demand recalculation of blast radius for an incident. Requires OPERATOR role."""
    org, _ = auth_ctx
    incident = db.query(Incident).filter(Incident.id == incident_id, Incident.organization_id == org.id).first()
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found.")

    report = enqueue_blast_radius_recalculation(db, incident.id, force=True)
    if not report:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unable to recalculate blast radius for this incident.")

    return IncidentBlastRadiusReportResponse.model_validate(report)
