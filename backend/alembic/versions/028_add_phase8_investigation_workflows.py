"""Add Phase 8 Investigation Workflows and Multi-Tenant Isolation

Revision ID: 028_add_phase8_workflows
Revises: 027_add_phase7_changes
Create Date: 2026-08-28 12:35:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '028_add_phase8_workflows'
down_revision = '027_add_phase7_changes'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    # Determine UUID and JSON types
    is_postgres = conn.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.String(36)
    json_type = postgresql.JSONB(astext_type=sa.Text()) if is_postgres else sa.JSON()

    if "investigations" in tables:
        inv_cols = [c["name"] for c in inspector.get_columns("investigations")]

        # 1. Add organization_id as nullable first for safe backfill
        if "organization_id" not in inv_cols:
            op.add_column("investigations", sa.Column("organization_id", uuid_type, nullable=True))

            # 2. Backfill organization_id from linked incidents
            if is_postgres:
                conn.execute(sa.text("""
                    UPDATE investigations 
                    SET organization_id = incidents.organization_id 
                    FROM incidents 
                    WHERE investigations.incident_id = incidents.id AND incidents.organization_id IS NOT NULL
                """))
            else:
                conn.execute(sa.text("""
                    UPDATE investigations 
                    SET organization_id = (SELECT organization_id FROM incidents WHERE incidents.id = investigations.incident_id)
                    WHERE investigations.incident_id IN (SELECT id FROM incidents WHERE organization_id IS NOT NULL)
                """))

            # 3. Check for remaining unowned investigations
            remaining_orphans = conn.execute(sa.text("SELECT id FROM investigations WHERE organization_id IS NULL")).fetchall()
            if remaining_orphans:
                orphan_ids = [str(r[0]) for r in remaining_orphans]
                raise RuntimeError(
                    f"Migration 028 aborted: {len(remaining_orphans)} orphaned investigation rows found without valid organization mapping: {orphan_ids[:10]}... "
                    f"Automatic tenant fallback assignment is strictly forbidden to prevent data corruption and cross-tenant data leaks. "
                    f"Manual tenant ownership remediation is required before applying the NOT NULL constraint."
                )

            # 4. Enforce NOT NULL and create index / foreign key
            if is_postgres:
                op.alter_column("investigations", "organization_id", nullable=False)
                op.create_foreign_key("fk_investigations_org", "investigations", "organizations", ["organization_id"], ["id"], ondelete="CASCADE")
            op.create_index("ix_investigations_org", "investigations", ["organization_id"])

        # Add new workflow fields to investigations
        if "work_item_id" not in inv_cols:
            op.add_column("investigations", sa.Column("work_item_id", uuid_type, nullable=True))
            if is_postgres:
                op.create_foreign_key("fk_investigations_work_item", "investigations", "work_items", ["work_item_id"], ["id"], ondelete="SET NULL")
            op.create_index("ix_investigations_work_item", "investigations", ["work_item_id"])

        if "workflow_type" not in inv_cols:
            op.add_column("investigations", sa.Column("workflow_type", sa.String(50), default="production_incident", nullable=False, server_default="production_incident"))
            op.create_index("ix_investigations_workflow_type", "investigations", ["workflow_type"])

        if "abstained" not in inv_cols:
            op.add_column("investigations", sa.Column("abstained", sa.Boolean(), default=False, nullable=False, server_default="false"))
            op.create_index("ix_investigations_abstained", "investigations", ["abstained"])

        if "abstention_reason" not in inv_cols:
            op.add_column("investigations", sa.Column("abstention_reason", sa.Text(), nullable=True))

        if "security_case_id" not in inv_cols:
            op.add_column("investigations", sa.Column("security_case_id", sa.String(100), nullable=True))
            op.create_index("ix_investigations_security_case_id", "investigations", ["security_case_id"])

        if "current_step_index" not in inv_cols:
            op.add_column("investigations", sa.Column("current_step_index", sa.Integer(), default=0, nullable=False, server_default="0"))

        if "total_steps" not in inv_cols:
            op.add_column("investigations", sa.Column("total_steps", sa.Integer(), default=1, nullable=False, server_default="1"))

        if "logs_json" not in inv_cols:
            op.add_column("investigations", sa.Column("logs_json", json_type, nullable=True))

        if "evidence_snapshot_id" not in inv_cols:
            op.add_column("investigations", sa.Column("evidence_snapshot_id", sa.String(64), nullable=True))

        if "started_by_user_id" not in inv_cols:
            op.add_column("investigations", sa.Column("started_by_user_id", uuid_type, nullable=True))
            if is_postgres:
                op.create_foreign_key("fk_investigations_started_by", "investigations", "users", ["started_by_user_id"], ["id"], ondelete="SET NULL")

    # Update investigation_tasks
    if "investigation_tasks" in tables:
        task_cols = [c["name"] for c in inspector.get_columns("investigation_tasks")]

        if "step_name" not in task_cols:
            op.add_column("investigation_tasks", sa.Column("step_name", sa.String(100), default="execution_step", nullable=False, server_default="execution_step"))

        if "result_json" not in task_cols:
            op.add_column("investigation_tasks", sa.Column("result_json", json_type, nullable=True))

        if "duration_ms" not in task_cols:
            op.add_column("investigation_tasks", sa.Column("duration_ms", sa.Integer(), default=0, nullable=False, server_default="0"))

        if "stepped_by_user_id" not in task_cols:
            op.add_column("investigation_tasks", sa.Column("stepped_by_user_id", uuid_type, nullable=True))
            if is_postgres:
                op.create_foreign_key("fk_inv_tasks_stepped_by", "investigation_tasks", "users", ["stepped_by_user_id"], ["id"], ondelete="SET NULL")


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "investigation_tasks" in tables:
        task_cols = [c["name"] for c in inspector.get_columns("investigation_tasks")]
        for col in ["stepped_by_user_id", "duration_ms", "result_json", "step_name"]:
            if col in task_cols:
                op.drop_column("investigation_tasks", col)

    if "investigations" in tables:
        inv_cols = [c["name"] for c in inspector.get_columns("investigations")]
        for col in [
            "started_by_user_id", "evidence_snapshot_id", "logs_json",
            "total_steps", "current_step_index", "security_case_id",
            "abstention_reason", "abstained", "workflow_type",
            "work_item_id", "organization_id"
        ]:
            if col in inv_cols:
                op.drop_column("investigations", col)
