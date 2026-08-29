"""Add Phase 5 autonomous monitoring, telemetry signals, and alert rule configs.

Revision ID: 025_add_phase5_monitoring
Revises: 024_add_phase4_deployments
Create Date: 2026-08-28 06:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "025_add_phase5_monitoring"
down_revision = "024_add_phase4_deployments"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    dialect = conn.dialect.name
    uuid_type = postgresql.UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)
    json_type = postgresql.JSONB if dialect == "postgresql" else sa.JSON
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    # 0. Controlled migration: clean PostgreSQL enum normalization to uppercase ('OWNER', 'ADMIN', 'MEMBER', 'VIEWER', 'OPERATOR')
    if dialect == "postgresql":
        if "user_organization_memberships" in tables:
            # The temporary type should never remove unrelated dependent objects.
            # If it already exists, a previous interrupted migration should be
            # repaired explicitly rather than using DROP ... CASCADE.
            op.execute("DROP TYPE IF EXISTS membershiprole_new")
            op.execute("CREATE TYPE membershiprole_new AS ENUM ('OWNER', 'ADMIN', 'MEMBER', 'VIEWER', 'OPERATOR')")
            op.execute("ALTER TABLE user_organization_memberships ALTER COLUMN role DROP DEFAULT")
            op.execute("ALTER TABLE user_organization_memberships ALTER COLUMN role TYPE membershiprole_new USING UPPER(role::text)::membershiprole_new")
            # The membership column now depends on membershiprole_new, so the
            # old type has no remaining dependency and can be dropped safely.
            op.execute("DROP TYPE IF EXISTS membershiprole")
            op.execute("ALTER TYPE membershiprole_new RENAME TO membershiprole")
            op.execute("ALTER TABLE user_organization_memberships ALTER COLUMN role SET DEFAULT 'MEMBER'::membershiprole")
        else:
            op.execute("DROP TYPE IF EXISTS membershiprole")
            op.execute("CREATE TYPE membershiprole AS ENUM ('OWNER', 'ADMIN', 'MEMBER', 'VIEWER', 'OPERATOR')")

    # 1. Update incidents table columns if missing
    if "incidents" in tables:
        inc_cols = [c["name"] for c in inspector.get_columns("incidents")]
        if "organization_id" not in inc_cols:
            op.add_column("incidents", sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True))
        if "environment_id" not in inc_cols:
            op.add_column("incidents", sa.Column("environment_id", uuid_type, sa.ForeignKey("environments.id", ondelete="SET NULL"), nullable=True, index=True))
        if "region_id" not in inc_cols:
            op.add_column("incidents", sa.Column("region_id", uuid_type, sa.ForeignKey("regions.id", ondelete="SET NULL"), nullable=True, index=True))
        if "signal_count" not in inc_cols:
            op.add_column("incidents", sa.Column("signal_count", sa.Integer, default=0, nullable=True))
        if "first_signal_at" not in inc_cols:
            op.add_column("incidents", sa.Column("first_signal_at", sa.DateTime(timezone=True), nullable=True))
        if "last_signal_at" not in inc_cols:
            op.add_column("incidents", sa.Column("last_signal_at", sa.DateTime(timezone=True), nullable=True))

    # 2. Update service_deployment_configs columns for persistent poller state
    if "service_deployment_configs" in tables:
        sdc_cols = [c["name"] for c in inspector.get_columns("service_deployment_configs")]
        if "consecutive_failures" not in sdc_cols:
            op.add_column("service_deployment_configs", sa.Column("consecutive_failures", sa.Integer, default=0, nullable=False, server_default="0"))
        if "last_probed_at" not in sdc_cols:
            op.add_column("service_deployment_configs", sa.Column("last_probed_at", sa.DateTime(timezone=True), nullable=True))
        if "last_probe_status_code" not in sdc_cols:
            op.add_column("service_deployment_configs", sa.Column("last_probe_status_code", sa.Integer, nullable=True))
        if "last_probe_latency_ms" not in sdc_cols:
            op.add_column("service_deployment_configs", sa.Column("last_probe_latency_ms", sa.Float, nullable=True))
        if "last_probe_is_healthy" not in sdc_cols:
            op.add_column("service_deployment_configs", sa.Column("last_probe_is_healthy", sa.Boolean, nullable=True))
        if "last_probe_error" not in sdc_cols:
            op.add_column("service_deployment_configs", sa.Column("last_probe_error", sa.Text, nullable=True))
        if "poller_lease_until" not in sdc_cols:
            op.add_column("service_deployment_configs", sa.Column("poller_lease_until", sa.DateTime(timezone=True), nullable=True))

    # 3. Update webhook_endpoints columns if auth_method missing
    if "webhook_endpoints" in tables:
        wh_cols = [c["name"] for c in inspector.get_columns("webhook_endpoints")]
        if "auth_method" not in wh_cols:
            op.add_column("webhook_endpoints", sa.Column("auth_method", sa.String(50), default="bearer", server_default="bearer", nullable=False))

    # 4. Create telemetry_signals table
    if "telemetry_signals" not in tables:
        op.create_table(
            "telemetry_signals",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("provider", sa.String(50), nullable=False, index=True),
            sa.Column("provider_event_id", sa.String(255), nullable=False, index=True),
            sa.Column("signal_type", sa.String(50), nullable=False, index=True),
            sa.Column("rule_name", sa.String(100), nullable=False, index=True),
            sa.Column("service_id", uuid_type, sa.ForeignKey("services.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("environment_id", uuid_type, sa.ForeignKey("environments.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("region_id", uuid_type, sa.ForeignKey("regions.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("metric_name", sa.String(100), nullable=True),
            sa.Column("metric_value", sa.Float, nullable=True),
            sa.Column("threshold_value", sa.Float, nullable=True),
            sa.Column("fingerprint", sa.String(64), nullable=False, index=True),
            sa.Column("correlation_key", sa.String(255), nullable=False, index=True),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("error_signature", sa.String(255), nullable=True),
            sa.Column("raw_payload", json_type, nullable=True),
            sa.Column("status", sa.String(50), default="ingested", nullable=False, index=True),
            sa.Column("incident_id", uuid_type, sa.ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, index=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("organization_id", "provider", "provider_event_id", name="uq_signal_provider_event"),
        )

    # 5. Create alert_rule_configs table
    if "alert_rule_configs" not in tables:
        op.create_table(
            "alert_rule_configs",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("rule_name", sa.String(100), nullable=False),
            sa.Column("is_enabled", sa.Boolean, default=True, nullable=False),
            sa.Column("threshold_value", sa.Float, nullable=True),
            sa.Column("window_minutes", sa.Integer, default=15, nullable=False),
            sa.Column("severity_override", sa.String(50), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
            sa.UniqueConstraint("organization_id", "rule_name", name="uq_alert_rule_org_name"),
        )

    # 6. Create active_incident_correlation_claims table
    if "active_incident_correlation_claims" not in tables:
        op.create_table(
            "active_incident_correlation_claims",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("correlation_key", sa.String(255), nullable=False),
            sa.Column("incident_id", uuid_type, sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("claimed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("organization_id", "correlation_key", name="uq_active_correlation_claim"),
        )

    # 7. Create health_check_logs table
    if "health_check_logs" not in tables:
        op.create_table(
            "health_check_logs",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("config_id", uuid_type, sa.ForeignKey("service_deployment_configs.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("service_id", uuid_type, sa.ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("environment_id", uuid_type, sa.ForeignKey("environments.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("region_id", uuid_type, sa.ForeignKey("regions.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("url", sa.String(500), nullable=False),
            sa.Column("status_code", sa.Integer, nullable=True),
            sa.Column("latency_ms", sa.Float, nullable=True),
            sa.Column("is_healthy", sa.Boolean, nullable=False),
            sa.Column("error_message", sa.Text, nullable=True),
            sa.Column("probed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
        )


def downgrade():
    op.drop_table("health_check_logs")
    op.drop_table("active_incident_correlation_claims")
    op.drop_table("alert_rule_configs")
    op.drop_table("telemetry_signals")
