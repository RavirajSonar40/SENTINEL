"""Add Phase 6 System Service Graph, dynamic topology edges, and incident blast radius reports.

Revision ID: 026_add_phase6_service_graph
Revises: 025_add_phase5_monitoring
Create Date: 2026-08-28 07:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "026_add_phase6_service_graph"
down_revision = "025_add_phase5_monitoring"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    dialect = conn.dialect.name
    uuid_type = postgresql.UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)
    json_type = postgresql.JSONB if dialect == "postgresql" else sa.JSON
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    # 1. Create graph_nodes table
    if "graph_nodes" not in tables:
        op.create_table(
            "graph_nodes",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("node_type", sa.String(50), nullable=False, index=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("identifier", sa.String(500), nullable=False, index=True),
            sa.Column("tier", sa.String(50), nullable=True),
            sa.Column("entity_id", uuid_type, nullable=True, index=True),
            sa.Column("metadata_json", json_type, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("organization_id", "node_type", "identifier", name="uq_graph_node_identifier"),
        )
        op.create_index("ix_graph_nodes_org_type", "graph_nodes", ["organization_id", "node_type"])
        op.create_index("ix_graph_nodes_entity", "graph_nodes", ["organization_id", "entity_id"])

    # 2. Create graph_edges table
    if "graph_edges" not in tables:
        op.create_table(
            "graph_edges",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("source_node_id", uuid_type, sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("target_node_id", uuid_type, sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("edge_type", sa.String(50), nullable=False, index=True),
            sa.Column("source", sa.String(50), default="SERVICE_REGISTRATION", nullable=False, index=True),
            sa.Column("confidence", sa.Float, default=1.0, nullable=False),
            sa.Column("criticality", sa.String(50), default="HARD", nullable=False),
            sa.Column("is_stale", sa.Boolean, default=False, nullable=False),
            sa.Column("metadata_json", json_type, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("organization_id", "source_node_id", "target_node_id", "edge_type", "source", name="uq_graph_edge"),
        )
        op.create_index("ix_graph_edges_src", "graph_edges", ["organization_id", "source_node_id"])
        op.create_index("ix_graph_edges_tgt", "graph_edges", ["organization_id", "target_node_id"])

    # 3. Create incident_blast_radius_reports table
    if "incident_blast_radius_reports" not in tables:
        op.create_table(
            "incident_blast_radius_reports",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("incident_id", uuid_type, sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("root_service_id", uuid_type, sa.ForeignKey("services.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("version", sa.Integer, default=1, nullable=False),
            sa.Column("is_current", sa.Boolean, default=True, nullable=False, index=True),
            sa.Column("calculated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("engine_version", sa.String(50), default="v1.0.0", nullable=False),
            sa.Column("telemetry_window_minutes", sa.Integer, default=30, nullable=False),
            sa.Column("graph_snapshot_hash", sa.String(64), nullable=True),
            sa.Column("direct_services", json_type, nullable=True),
            sa.Column("indirect_services", json_type, nullable=True),
            sa.Column("affected_endpoints", json_type, nullable=True),
            sa.Column("affected_repositories", json_type, nullable=True),
            sa.Column("affected_environments", json_type, nullable=True),
            sa.Column("affected_regions", json_type, nullable=True),
            sa.Column("customer_impact", json_type, nullable=True),
            sa.Column("criticality_summary", json_type, nullable=True),
            sa.Column("unknowns", json_type, nullable=True),
        )
        op.create_index("ix_blast_radius_incident", "incident_blast_radius_reports", ["organization_id", "incident_id", "version"])


def downgrade():
    op.drop_table("incident_blast_radius_reports")
    op.drop_table("graph_edges")
    op.drop_table("graph_nodes")
