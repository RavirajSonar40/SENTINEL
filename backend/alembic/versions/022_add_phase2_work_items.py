"""Add Phase 2 tables: environments, work_items, work_item_repositories, and users.organization_id.

Revision ID: 022_add_phase2_work_items
Revises: 021_add_evidence_columns
Create Date: 2026-08-28 03:40:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "022_add_phase2_work_items"
down_revision = "021_add_evidence_columns"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add organization_id to users
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    users_cols = [c["name"] for c in inspector.get_columns("users")]
    if "organization_id" not in users_cols:
        op.add_column(
            "users",
            sa.Column(
                "organization_id",
                postgresql.UUID(as_uuid=True) if conn.dialect.name == "postgresql" else sa.String(36),
                sa.ForeignKey("organizations.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index("ix_users_organization_id", "users", ["organization_id"])

    # 2. Create environments table
    tables = inspector.get_table_names()
    if "environments" not in tables:
        op.create_table(
            "environments",
            sa.Column("id", postgresql.UUID(as_uuid=True) if conn.dialect.name == "postgresql" else sa.String(36), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("env_type", sa.String(50), default="production", nullable=False),
            sa.Column("region", sa.String(50), nullable=True),
            sa.Column(
                "organization_id",
                postgresql.UUID(as_uuid=True) if conn.dialect.name == "postgresql" else sa.String(36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    # 3. Create work_items table
    if "work_items" not in tables:
        op.create_table(
            "work_items",
            sa.Column("id", postgresql.UUID(as_uuid=True) if conn.dialect.name == "postgresql" else sa.String(36), primary_key=True),
            sa.Column(
                "organization_id",
                postgresql.UUID(as_uuid=True) if conn.dialect.name == "postgresql" else sa.String(36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("idempotency_key", sa.String(255), nullable=True, index=True),
            sa.Column(
                "work_type",
                sa.Enum(
                    "DIRECT_TASK",
                    "BUG",
                    "FEATURE",
                    "PRODUCTION_INCIDENT",
                    "SECURITY_INCIDENT",
                    "NEEDS_CLARIFICATION",
                    name="worktype",
                ),
                nullable=False,
                index=True,
            ),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column(
                "status",
                sa.Enum(
                    "created",
                    "routed",
                    "in_progress",
                    "validated",
                    "draft_pr_created",
                    "resolved",
                    "blocked",
                    "cancelled",
                    name="workitemstatus",
                ),
                default="created",
                nullable=False,
                index=True,
            ),
            sa.Column("priority", sa.String(50), default="medium"),
            sa.Column("requester_id", postgresql.UUID(as_uuid=True) if conn.dialect.name == "postgresql" else sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("service_id", postgresql.UUID(as_uuid=True) if conn.dialect.name == "postgresql" else sa.String(36), sa.ForeignKey("services.id", ondelete="SET NULL"), nullable=True),
            sa.Column("environment_id", postgresql.UUID(as_uuid=True) if conn.dialect.name == "postgresql" else sa.String(36), sa.ForeignKey("environments.id", ondelete="SET NULL"), nullable=True),
            sa.Column("region_id", sa.String(50), nullable=True),
            sa.Column("target_files", sa.JSON, nullable=True),
            sa.Column("workflow", sa.String(100), nullable=False, default="repository_task"),
            sa.Column("confidence", sa.Float, default=1.0),
            sa.Column("requires_runtime_evidence", sa.Boolean, default=False),
            sa.Column("runtime_evidence_reason", sa.String(500), nullable=True),
            sa.Column("requires_code_change", sa.Boolean, default=True),
            sa.Column("envelope", sa.JSON, nullable=True),
            sa.Column("security_case_id", sa.String(100), nullable=True),
            sa.Column("evidence_retention_policy", sa.String(100), nullable=True),
            sa.Column("security_owner", sa.String(255), nullable=True),
            sa.Column("incident_id", postgresql.UUID(as_uuid=True) if conn.dialect.name == "postgresql" else sa.String(36), sa.ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
            sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_work_items_org_idempotency"),
        )

    # 4. Create work_item_repositories table
    if "work_item_repositories" not in tables:
        op.create_table(
            "work_item_repositories",
            sa.Column("id", postgresql.UUID(as_uuid=True) if conn.dialect.name == "postgresql" else sa.String(36), primary_key=True),
            sa.Column(
                "work_item_id",
                postgresql.UUID(as_uuid=True) if conn.dialect.name == "postgresql" else sa.String(36),
                sa.ForeignKey("work_items.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "repository_id",
                postgresql.UUID(as_uuid=True) if conn.dialect.name == "postgresql" else sa.String(36),
                sa.ForeignKey("repositories.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("role", sa.String(50), default="primary"),
            sa.Column("is_primary", sa.Boolean, default=True),
            sa.Column("selection_reason", sa.String(500), nullable=True),
            sa.Column("confidence", sa.Float, default=1.0),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("work_item_id", "repository_id", name="uq_work_item_repository_scope"),
        )


def downgrade():
    op.drop_table("work_item_repositories")
    op.drop_table("work_items")
    op.drop_table("environments")
    op.drop_column("users", "organization_id")
