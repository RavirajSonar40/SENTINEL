"""Add Phase 7 Change Intelligence Ledger and Incident Correlation models.

Revision ID: 027_add_phase7_changes
Revises: 026_add_phase6_service_graph
Create Date: 2026-08-28 08:50:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "027_add_phase7_changes"
down_revision = "026_add_phase6_service_graph"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    dialect = conn.dialect.name
    uuid_type = postgresql.UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)
    json_type = postgresql.JSONB if dialect == "postgresql" else sa.JSON
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    # 1. Create change_events table
    if "change_events" not in tables:
        op.create_table(
            "change_events",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("service_id", uuid_type, sa.ForeignKey("services.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("environment_id", uuid_type, sa.ForeignKey("environments.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("repository_id", uuid_type, sa.ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("deployment_id", uuid_type, sa.ForeignKey("deployments.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("provider", sa.String(50), default="manual", nullable=False, index=True),
            sa.Column("provider_event_id", sa.String(255), nullable=True, index=True),
            sa.Column("auth_source", sa.String(50), nullable=True),
            sa.Column("integration_id", uuid_type, nullable=True),
            sa.Column("change_type", sa.String(50), nullable=False, index=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("external_id", sa.String(255), nullable=False, index=True),
            sa.Column("commit_sha", sa.String(100), nullable=True, index=True),
            sa.Column("author", sa.String(255), nullable=True),
            sa.Column("risk_level", sa.String(50), default="LOW", nullable=False),
            sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False, index=True),
            sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("source_url", sa.String(500), nullable=True),
            sa.Column("affected_components", json_type, nullable=True),
            sa.Column("diff_summary", json_type, nullable=True),
            sa.Column("metadata_json", json_type, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("organization_id", "provider", "change_type", "external_id", name="uq_change_event_idempotency"),
        )
        op.create_index("ix_change_events_org_effective", "change_events", ["organization_id", "effective_at"])
        op.create_index("ix_change_events_service_effective", "change_events", ["organization_id", "service_id", "effective_at"])
        op.create_index("ix_change_events_type_effective", "change_events", ["organization_id", "change_type", "effective_at"])

    # 2. Create incident_change_correlations table
    if "incident_change_correlations" not in tables:
        op.create_table(
            "incident_change_correlations",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("incident_id", uuid_type, sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("change_event_id", uuid_type, sa.ForeignKey("change_events.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("time_delta_seconds", sa.Integer, nullable=False),
            sa.Column("topological_distance", sa.Integer, default=0, nullable=False),
            sa.Column("correlation_score", sa.Float, nullable=False),
            sa.Column("rank", sa.Integer, default=1, nullable=False),
            sa.Column("is_causal_candidate", sa.Boolean, default=False, nullable=False, index=True),
            sa.Column("triage_status", sa.String(50), default="COINCIDENTAL", nullable=False, index=True),
            sa.Column("triage_reason", sa.Text, nullable=True),
            sa.Column("triaged_by_user_id", uuid_type, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("triaged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("previous_status", sa.String(50), nullable=True),
            sa.Column("reasoning", sa.Text, nullable=True),
            sa.Column("metadata_json", json_type, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("organization_id", "incident_id", "change_event_id", name="uq_incident_change_correlation"),
        )
        op.create_index("ix_incident_correlations_rank", "incident_change_correlations", ["organization_id", "incident_id", "rank"])
        op.create_index("ix_incident_correlations_score", "incident_change_correlations", ["organization_id", "incident_id", "correlation_score"])

    # 3. Create incident_change_correlation_reports table
    if "incident_change_correlation_reports" not in tables:
        op.create_table(
            "incident_change_correlation_reports",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("incident_id", uuid_type, sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("version", sa.Integer, default=1, nullable=False),
            sa.Column("is_current", sa.Boolean, default=True, nullable=False, index=True),
            sa.Column("calculated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("lookback_window_minutes", sa.Integer, default=120, nullable=False),
            sa.Column("snapshot_hash", sa.String(64), nullable=True),
            sa.Column("causal_candidates_count", sa.Integer, default=0, nullable=False),
            sa.Column("summary", sa.Text, nullable=True),
            sa.Column("correlations_snapshot", json_type, nullable=True),
            sa.Column("metadata_json", json_type, nullable=True),
        )
        op.create_index("ix_change_corr_report_incident", "incident_change_correlation_reports", ["organization_id", "incident_id", "version"])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    if "incident_change_correlation_reports" in tables:
        op.drop_table("incident_change_correlation_reports")
    if "incident_change_correlations" in tables:
        op.drop_table("incident_change_correlations")
    if "change_events" in tables:
        op.drop_table("change_events")
