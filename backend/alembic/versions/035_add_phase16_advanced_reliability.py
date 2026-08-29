"""Add Phase 16 Advanced Reliability, SLO Tracking & Predictive Anomaly Schema

Revision ID: 035_add_phase16_advanced_reliability
Revises: 034_add_phase14_multi_repo
Create Date: 2026-08-29 07:10:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = '035_add_phase16_advanced_reliability'
down_revision = '034_add_phase14_multi_repo'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    is_postgres = conn.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.String(36)

    # 1. SLO_CONFIGS TABLE
    if "slo_configs" not in tables:
        op.create_table(
            "slo_configs",
            sa.Column("id", uuid_type, primary_key=True, default=uuid.uuid4),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("service_id", uuid_type, sa.ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("target_percent", sa.Float(), nullable=False, server_default="99.9"),
            sa.Column("sli_type", sa.String(50), nullable=False, server_default="availability"),
            sa.Column("threshold_value", sa.Float(), nullable=True),
            sa.Column("window_days", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("organization_id", "service_id", "name", name="uq_slo_org_service_name"),
        )
        op.create_index("ix_slo_configs_org_service", "slo_configs", ["organization_id", "service_id"])

    # 2. SLO_BURN_RATE_SNAPSHOTS TABLE
    if "slo_burn_rate_snapshots" not in tables:
        op.create_table(
            "slo_burn_rate_snapshots",
            sa.Column("id", uuid_type, primary_key=True, default=uuid.uuid4),
            sa.Column("slo_id", uuid_type, sa.ForeignKey("slo_configs.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("compliance_percent", sa.Float(), nullable=True),
            sa.Column("burn_rate_1h", sa.Float(), nullable=True),
            sa.Column("burn_rate_6h", sa.Float(), nullable=True),
            sa.Column("burn_rate_24h", sa.Float(), nullable=True),
            sa.Column("budget_remaining_percent", sa.Float(), nullable=True),
            sa.Column("time_to_exhaustion_hours", sa.Float(), nullable=True),
            sa.Column("captured_hour", sa.DateTime(timezone=True), nullable=False, index=True),
            sa.Column("status", sa.String(50), nullable=False, server_default="healthy"),
            sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("slo_id", "captured_hour", name="uq_slo_snapshot_hour"),
        )
        op.create_index("ix_slo_snapshots_slo_hour", "slo_burn_rate_snapshots", ["slo_id", "captured_hour"])

    # 3. PREDICTIVE_ANOMALIES TABLE
    if "predictive_anomalies" not in tables:
        op.create_table(
            "predictive_anomalies",
            sa.Column("id", uuid_type, primary_key=True, default=uuid.uuid4),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("service_id", uuid_type, sa.ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("metric_name", sa.String(100), nullable=False, index=True),
            sa.Column("current_value", sa.Float(), nullable=False),
            sa.Column("threshold_value", sa.Float(), nullable=False),
            sa.Column("projected_breach_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("time_to_breach_minutes", sa.Float(), nullable=False),
            sa.Column("growth_rate_per_minute", sa.Float(), nullable=False),
            sa.Column("r_squared", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("confidence_score", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("severity", sa.String(50), nullable=False, server_default="WARNING"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("status", sa.String(50), nullable=False, server_default="ACTIVE"),
            sa.Column("recommendation", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_predictive_anomalies_org_metric", "predictive_anomalies", ["organization_id", "metric_name", "status"])

    # 4. BUSINESS_IMPACT_CONFIGS TABLE
    if "business_impact_configs" not in tables:
        op.create_table(
            "business_impact_configs",
            sa.Column("id", uuid_type, primary_key=True, default=uuid.uuid4),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("service_id", uuid_type, sa.ForeignKey("services.id", ondelete="CASCADE"), nullable=True, index=True),
            sa.Column("tier", sa.String(50), nullable=True),
            sa.Column("hourly_revenue_rate_usd", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("active_users_baseline", sa.Integer(), nullable=False, server_default="1000"),
            sa.Column("currency", sa.String(10), nullable=False, server_default="USD"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("organization_id", "service_id", name="uq_business_impact_org_service"),
        )
        op.create_index("ix_business_impact_org_service", "business_impact_configs", ["organization_id", "service_id"])

    # 5. INCIDENT_BUSINESS_IMPACTS TABLE
    if "incident_business_impacts" not in tables:
        op.create_table(
            "incident_business_impacts",
            sa.Column("id", uuid_type, primary_key=True, default=uuid.uuid4),
            sa.Column("incident_id", uuid_type, sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, unique=True, index=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("estimated_financial_loss_usd", sa.Float(), nullable=True),
            sa.Column("affected_user_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("degradation_factor", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("sla_breach_detected", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("currency", sa.String(10), nullable=False, server_default="USD"),
            sa.Column("is_estimated_default", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("calculated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_incident_impact_org_incident", "incident_business_impacts", ["organization_id", "incident_id"])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "incident_business_impacts" in tables:
        op.drop_index("ix_incident_impact_org_incident", table_name="incident_business_impacts")
        op.drop_table("incident_business_impacts")

    if "business_impact_configs" in tables:
        op.drop_constraint("uq_business_impact_org_service", "business_impact_configs", type_="unique")
        op.drop_index("ix_business_impact_org_service", table_name="business_impact_configs")
        op.drop_table("business_impact_configs")

    if "predictive_anomalies" in tables:
        op.drop_index("ix_predictive_anomalies_org_metric", table_name="predictive_anomalies")
        op.drop_table("predictive_anomalies")

    if "slo_burn_rate_snapshots" in tables:
        op.drop_constraint("uq_slo_snapshot_hour", "slo_burn_rate_snapshots", type_="unique")
        op.drop_index("ix_slo_snapshots_slo_hour", table_name="slo_burn_rate_snapshots")
        op.drop_table("slo_burn_rate_snapshots")

    if "slo_configs" in tables:
        op.drop_constraint("uq_slo_org_service_name", "slo_configs", type_="unique")
        op.drop_index("ix_slo_configs_org_service", table_name="slo_configs")
        op.drop_table("slo_configs")
