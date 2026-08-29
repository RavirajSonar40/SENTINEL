"""Add Phase 14 Multi-Repository Remediation Schema

Revision ID: 034_add_phase14_multi_repo
Revises: 033_add_phase13_policy_gateway
Create Date: 2026-08-29 05:40:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = '034_add_phase14_multi_repo'
down_revision = '033_add_phase13_policy_gateway'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    is_postgres = conn.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.String(36)
    json_type = postgresql.JSON(astext_type=sa.Text()) if is_postgres else sa.JSON()

    # =========================================================================
    # 1. ENHANCE INVESTIGATIONS TABLE (Parent-Child Hierarchy & Base SHA)
    # =========================================================================
    if "investigations" in tables:
        inv_cols = [c["name"] for c in inspector.get_columns("investigations")]
        inv_indexes = [idx["name"] for idx in inspector.get_indexes("investigations")]

        if is_postgres:
            inv_constraints = [c["name"] for c in inspector.get_unique_constraints("investigations")]

            if "parent_investigation_id" not in inv_cols:
                op.add_column("investigations", sa.Column("parent_investigation_id", uuid_type, sa.ForeignKey("investigations.id", ondelete="CASCADE", name="fk_investigations_parent"), nullable=True))
            if "ix_investigations_parent" not in inv_indexes:
                op.create_index("ix_investigations_parent", "investigations", ["parent_investigation_id"])

            if "repository_id" not in inv_cols:
                op.add_column("investigations", sa.Column("repository_id", uuid_type, sa.ForeignKey("repositories.id", ondelete="SET NULL", name="fk_investigations_repo"), nullable=True))
            if "ix_investigations_repository" not in inv_indexes:
                op.create_index("ix_investigations_repository", "investigations", ["repository_id"])

            if "repository_role" not in inv_cols:
                op.add_column("investigations", sa.Column("repository_role", sa.String(50), nullable=True))

            if "base_commit_sha" not in inv_cols:
                op.add_column("investigations", sa.Column("base_commit_sha", sa.String(40), nullable=True))

            if "is_parent" not in inv_cols:
                op.add_column("investigations", sa.Column("is_parent", sa.Boolean(), server_default=sa.text("false"), nullable=False))

            if "idempotency_key" not in inv_cols:
                op.add_column("investigations", sa.Column("idempotency_key", sa.String(255), nullable=True))
            if "ix_investigations_idempotency" not in inv_indexes:
                op.create_index("ix_investigations_idempotency", "investigations", ["idempotency_key"])

            if "uq_parent_child_repo" not in inv_constraints:
                op.create_unique_constraint("uq_parent_child_repo", "investigations", ["parent_investigation_id", "repository_id"])
            if "uq_investigation_org_idempotency_key" not in inv_constraints:
                op.create_unique_constraint("uq_investigation_org_idempotency_key", "investigations", ["organization_id", "idempotency_key"])
        else:
            with op.batch_alter_table("investigations") as batch_op:
                if "parent_investigation_id" not in inv_cols:
                    batch_op.add_column(sa.Column("parent_investigation_id", uuid_type, sa.ForeignKey("investigations.id", ondelete="CASCADE", name="fk_investigations_parent"), nullable=True))
                if "repository_id" not in inv_cols:
                    batch_op.add_column(sa.Column("repository_id", uuid_type, sa.ForeignKey("repositories.id", ondelete="SET NULL", name="fk_investigations_repo"), nullable=True))
                if "repository_role" not in inv_cols:
                    batch_op.add_column(sa.Column("repository_role", sa.String(50), nullable=True))
                if "base_commit_sha" not in inv_cols:
                    batch_op.add_column(sa.Column("base_commit_sha", sa.String(40), nullable=True))
                if "is_parent" not in inv_cols:
                    batch_op.add_column(sa.Column("is_parent", sa.Boolean(), server_default=sa.text("0"), nullable=False))
                if "idempotency_key" not in inv_cols:
                    batch_op.add_column(sa.Column("idempotency_key", sa.String(255), nullable=True))

            # Create indexes on newly added columns in SQLite
            inv_indexes_now = [idx["name"] for idx in inspector.get_indexes("investigations")]
            if "ix_investigations_parent" not in inv_indexes_now:
                op.create_index("ix_investigations_parent", "investigations", ["parent_investigation_id"])
            if "ix_investigations_repository" not in inv_indexes_now:
                op.create_index("ix_investigations_repository", "investigations", ["repository_id"])
            if "ix_investigations_idempotency" not in inv_indexes_now:
                op.create_index("ix_investigations_idempotency", "investigations", ["idempotency_key"])
            if "uq_parent_child_repo" not in inv_indexes_now:
                op.create_index("uq_parent_child_repo", "investigations", ["parent_investigation_id", "repository_id"], unique=True)
            if "uq_investigation_org_idempotency_key" not in inv_indexes_now:
                op.create_index("uq_investigation_org_idempotency_key", "investigations", ["organization_id", "idempotency_key"], unique=True)

    # =========================================================================
    # 2. CREATE REMEDIATION_PLANS TABLE
    # =========================================================================
    if "remediation_plans" not in tables:
        op.create_table(
            "remediation_plans",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("incident_id", uuid_type, sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("parent_investigation_id", uuid_type, sa.ForeignKey("investigations.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(50), server_default="draft", nullable=False),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("dependency_order_json", json_type, nullable=True),
            sa.Column("cycle_detected", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("cycle_details_json", json_type, nullable=True),
            sa.Column("cross_repo_rollback_plan", sa.Text(), nullable=True),
            sa.Column("idempotency_key", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
            sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_remediation_plan_org_idempotency_key"),
        )
        op.create_index("ix_remediation_plans_org", "remediation_plans", ["organization_id"])
        op.create_index("ix_remediation_plans_incident", "remediation_plans", ["incident_id"])
        op.create_index("ix_remediation_plans_status", "remediation_plans", ["status"])
        op.create_index("ix_remediation_plans_idempotency", "remediation_plans", ["idempotency_key"])

    # =========================================================================
    # 3. CREATE REMEDIATION_PLAN_ITEMS TABLE
    # =========================================================================
    if "remediation_plan_items" not in tables:
        op.create_table(
            "remediation_plan_items",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("plan_id", uuid_type, sa.ForeignKey("remediation_plans.id", ondelete="CASCADE"), nullable=False),
            sa.Column("repository_id", uuid_type, sa.ForeignKey("repositories.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("repository_role", sa.String(50), server_default="primary_defect", nullable=False),
            sa.Column("investigation_id", uuid_type, sa.ForeignKey("investigations.id", ondelete="SET NULL"), nullable=True),
            sa.Column("fix_id", uuid_type, sa.ForeignKey("proposed_fixes.id", ondelete="SET NULL"), nullable=True),
            sa.Column("execution_order", sa.Integer(), server_default="1", nullable=False),
            sa.Column("requires_code_change", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            sa.Column("validation_run_id", uuid_type, sa.ForeignKey("validation_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("validation_status", sa.String(50), server_default="pending", nullable=False),
            sa.Column("approval_id", uuid_type, sa.ForeignKey("approvals.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approval_status", sa.String(50), server_default="pending", nullable=False),
            sa.Column("patch_version", sa.Integer(), nullable=True),
            sa.Column("snapshot_hash", sa.String(64), nullable=True),
            sa.Column("base_commit_sha", sa.String(40), nullable=True),
            sa.Column("pr_idempotency_key", sa.String(255), nullable=True),
            sa.Column("pr_status", sa.String(50), server_default="pending", nullable=False),
            sa.Column("pr_url", sa.String(500), nullable=True),
            sa.Column("pr_number", sa.Integer(), nullable=True),
            sa.Column("commit_sha", sa.String(40), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
            sa.UniqueConstraint("plan_id", "repository_id", name="uq_plan_repo"),
            sa.UniqueConstraint("organization_id", "pr_idempotency_key", name="uq_remediation_item_org_pr_idempotency"),
        )
        op.create_index("ix_remediation_plan_items_org", "remediation_plan_items", ["organization_id"])
        op.create_index("ix_remediation_plan_items_plan", "remediation_plan_items", ["plan_id"])
        op.create_index("ix_remediation_plan_items_repo", "remediation_plan_items", ["repository_id"])
        op.create_index("ix_remediation_plan_items_pr_idempotency", "remediation_plan_items", ["pr_idempotency_key"])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    is_postgres = conn.dialect.name == "postgresql"

    # 1. Drop remediation_plan_items table
    if "remediation_plan_items" in tables:
        op.drop_table("remediation_plan_items")

    # 2. Drop remediation_plans table
    if "remediation_plans" in tables:
        op.drop_table("remediation_plans")

    # 3. Clean up investigations constraints, indexes, and columns
    if "investigations" in tables:
        inv_indexes = [idx["name"] for idx in inspector.get_indexes("investigations")]
        inv_cols = [c["name"] for c in inspector.get_columns("investigations")]

        cols_to_drop = [
            "idempotency_key",
            "is_parent",
            "base_commit_sha",
            "repository_role",
            "repository_id",
            "parent_investigation_id",
        ]
        present_cols = [col for col in cols_to_drop if col in inv_cols]

        if is_postgres:
            inv_constraints = [c["name"] for c in inspector.get_unique_constraints("investigations")]
            if "uq_investigation_org_idempotency_key" in inv_constraints:
                op.drop_constraint("uq_investigation_org_idempotency_key", "investigations", type_="unique")
            if "uq_parent_child_repo" in inv_constraints:
                op.drop_constraint("uq_parent_child_repo", "investigations", type_="unique")

            if "ix_investigations_idempotency" in inv_indexes:
                op.drop_index("ix_investigations_idempotency", table_name="investigations")
            if "ix_investigations_repository" in inv_indexes:
                op.drop_index("ix_investigations_repository", table_name="investigations")
            if "ix_investigations_parent" in inv_indexes:
                op.drop_index("ix_investigations_parent", table_name="investigations")

            for col in present_cols:
                op.drop_column("investigations", col)
        else:
            # In SQLite, drop all related indexes before dropping columns
            indexes_to_drop = [
                "ix_investigations_parent",
                "ix_investigations_parent_investigation_id",
                "ix_investigations_repository",
                "ix_investigations_repository_id",
                "ix_investigations_idempotency",
                "ix_investigations_idempotency_key",
                "uq_parent_child_repo",
                "uq_investigation_org_idempotency_key",
            ]
            for idx_name in indexes_to_drop:
                if idx_name in inv_indexes:
                    op.drop_index(idx_name, table_name="investigations")

            with op.batch_alter_table("investigations") as batch_op:
                for col in present_cols:
                    batch_op.drop_column(col)
