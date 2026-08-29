"""Add Phase 4 deployment inventory and webhook endpoints.

Revision ID: 024_add_phase4_deployments
Revises: 023_add_phase3_catalog
Create Date: 2026-08-28 05:15:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "024_add_phase4_deployments"
down_revision = "023_add_phase3_catalog"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    dialect = conn.dialect.name
    uuid_type = postgresql.UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)
    json_type = postgresql.JSONB if dialect == "postgresql" else sa.JSON
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    # 1. Update or create deployments table
    if "deployments" not in tables:
        op.create_table(
            "deployments",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("service_id", uuid_type, sa.ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("environment_id", uuid_type, sa.ForeignKey("environments.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("region_id", uuid_type, sa.ForeignKey("regions.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("repository_id", uuid_type, sa.ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("commit_sha", sa.String(40), nullable=False, index=True),
            sa.Column("commit_message", sa.Text, nullable=True),
            sa.Column("version", sa.String(100), nullable=True),
            sa.Column("provider", sa.String(50), default="manual", nullable=False),
            sa.Column("provider_event_id", sa.String(255), nullable=True, index=True),
            sa.Column("external_deployment_id", sa.String(255), nullable=True),
            sa.Column("status", sa.String(50), default="pending", nullable=False, index=True),
            sa.Column("url", sa.String(1000), nullable=True),
            sa.Column("deployed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_seconds", sa.Float, nullable=True),
            sa.Column("deployed_by", sa.String(255), nullable=True),
            sa.Column("metadata", json_type, default=dict, nullable=True),
            sa.Column("is_current", sa.Boolean, default=False, nullable=False, index=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        )
    else:
        # Existing table — add missing columns safely
        dep_cols = [c["name"] for c in inspector.get_columns("deployments")]
        if "organization_id" not in dep_cols:
            op.add_column("deployments", sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True))
        if "environment_id" not in dep_cols:
            op.add_column("deployments", sa.Column("environment_id", uuid_type, sa.ForeignKey("environments.id", ondelete="CASCADE"), nullable=True, index=True))
        if "region_id" not in dep_cols:
            op.add_column("deployments", sa.Column("region_id", uuid_type, sa.ForeignKey("regions.id", ondelete="SET NULL"), nullable=True, index=True))
        if "repository_id" not in dep_cols:
            op.add_column("deployments", sa.Column("repository_id", uuid_type, sa.ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True, index=True))
        if "commit_message" not in dep_cols:
            op.add_column("deployments", sa.Column("commit_message", sa.Text, nullable=True))
        if "provider" not in dep_cols:
            op.add_column("deployments", sa.Column("provider", sa.String(50), default="manual", nullable=True))
        if "provider_event_id" not in dep_cols:
            op.add_column("deployments", sa.Column("provider_event_id", sa.String(255), nullable=True, index=True))
        if "external_deployment_id" not in dep_cols:
            op.add_column("deployments", sa.Column("external_deployment_id", sa.String(255), nullable=True))
        if "status" not in dep_cols:
            op.add_column("deployments", sa.Column("status", sa.String(50), default="pending", nullable=True, index=True))
        if "url" not in dep_cols:
            op.add_column("deployments", sa.Column("url", sa.String(1000), nullable=True))
        if "started_at" not in dep_cols:
            op.add_column("deployments", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        if "finished_at" not in dep_cols:
            op.add_column("deployments", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
        if "duration_seconds" not in dep_cols:
            op.add_column("deployments", sa.Column("duration_seconds", sa.Float, nullable=True))
        if "is_current" not in dep_cols:
            op.add_column("deployments", sa.Column("is_current", sa.Boolean, default=False, nullable=True, index=True))
        if "updated_at" not in dep_cols:
            op.add_column("deployments", sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()))

    # 2. webhook_endpoints table
    if "webhook_endpoints" not in tables:
        op.create_table(
            "webhook_endpoints",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("provider", sa.String(50), default="generic", server_default="generic", nullable=False),
            sa.Column("key_id", sa.String(64), unique=True, nullable=False, index=True),
            sa.Column("encrypted_secret", sa.Text, nullable=False),
            sa.Column("is_active", sa.Boolean, default=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
            sa.UniqueConstraint("organization_id", "name", name="uq_webhook_endpoint_org_name"),
        )

    # 3. PostgreSQL partial unique indexes
    if dialect == "postgresql":
        op.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_deployment_current_regional
            ON deployments (service_id, environment_id, region_id)
            WHERE is_current = true AND region_id IS NOT NULL;
            """
        )
        op.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_deployment_current_global
            ON deployments (service_id, environment_id)
            WHERE is_current = true AND region_id IS NULL;
            """
        )
        op.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_deployment_provider_event
            ON deployments (organization_id, provider, provider_event_id)
            WHERE provider_event_id IS NOT NULL;
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_deployment_window
            ON deployments (organization_id, service_id, environment_id, deployed_at);
            """
        )


def downgrade():
    conn = op.get_bind()
    dialect = conn.dialect.name
    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_deployment_window;")
        op.execute("DROP INDEX IF EXISTS uq_deployment_provider_event;")
        op.execute("DROP INDEX IF EXISTS uq_deployment_current_global;")
        op.execute("DROP INDEX IF EXISTS uq_deployment_current_regional;")

    op.drop_table("webhook_endpoints")
    op.drop_table("deployments")
