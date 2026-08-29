"""Add Phase 10 Post-Mortem and Incident Memory Schema

Revision ID: 030_add_phase10_memory
Revises: 029_add_phase9_evidence
Create Date: 2026-08-28 18:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '030_add_phase10_memory'
down_revision = '029_add_phase9_evidence'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    is_postgres = conn.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.String(36)
    json_type = postgresql.JSONB(astext_type=sa.Text()) if is_postgres else sa.JSON()

    # 1. Update PostgreSQL evidencesourcetype enum with 'PREVIOUS_INCIDENT' (Fail-Fast)
    if is_postgres:
        has_enum_val = conn.execute(sa.text("""
            SELECT EXISTS (
                SELECT 1 
                FROM pg_type t 
                JOIN pg_enum e ON t.oid = e.enumtypid 
                WHERE t.typname = 'evidencesourcetype' AND e.enumlabel = 'PREVIOUS_INCIDENT'
            );
        """)).scalar()
        if not has_enum_val:
            conn.execute(sa.text("ALTER TYPE evidencesourcetype ADD VALUE IF NOT EXISTS 'PREVIOUS_INCIDENT';"))

    # =========================================================================
    # 2. POST_MORTEMS TABLE
    # =========================================================================
    if "post_mortems" not in tables:
        op.create_table(
            "post_mortems",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("incident_id", uuid_type, sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("work_item_id", uuid_type, sa.ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True),
            sa.Column("author_id", uuid_type, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("signed_off_by_user_id", uuid_type, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("root_cause_summary", sa.Text(), nullable=False),
            sa.Column("impact_summary", sa.Text(), nullable=True),
            sa.Column("trigger_event", sa.Text(), nullable=True),
            sa.Column("detection_summary", sa.Text(), nullable=True),
            sa.Column("resolution_summary", sa.Text(), nullable=True),
            sa.Column("contributing_factors_json", json_type, nullable=True),
            sa.Column("timeline_summary_json", json_type, nullable=True),
            sa.Column("lessons_learned_json", json_type, nullable=True),
            sa.Column("time_to_detect_seconds", sa.Integer(), nullable=True),
            sa.Column("time_to_acknowledge_seconds", sa.Integer(), nullable=True),
            sa.Column("time_to_root_cause_seconds", sa.Integer(), nullable=True),
            sa.Column("time_to_mitigate_seconds", sa.Integer(), nullable=True),
            sa.Column("time_to_resolve_seconds", sa.Integer(), nullable=True),
            sa.Column("downtime_minutes", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("affected_user_count_estimate", sa.Integer(), nullable=True),
            sa.Column("slo_impact_percent", sa.Float(), nullable=True),
            sa.Column("resolution_type", sa.String(50), server_default="code_fix", nullable=False),
            sa.Column("severity_actual", sa.String(20), server_default="SEV-2", nullable=False),
            sa.Column("status", sa.String(50), server_default="draft", nullable=False),
            sa.Column("snapshot_hash", sa.String(64), nullable=True),
            sa.Column("abstained", sa.Boolean(), server_default="0", nullable=False),
            sa.Column("human_reviewed", sa.Boolean(), server_default="0", nullable=False),
            sa.Column("is_current", sa.Boolean(), server_default="1", nullable=False),
            sa.Column("version", sa.Integer(), server_default="1", nullable=False),
            sa.Column("memory_indexing_status", sa.String(50), server_default="pending", nullable=False),
            sa.Column("memory_indexing_error", sa.Text(), nullable=True),
            sa.Column("signed_off_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )

        op.create_unique_constraint("uq_post_mortems_org_incident_version", "post_mortems", ["organization_id", "incident_id", "version"])
        op.create_index("ix_post_mortems_org_incident", "post_mortems", ["organization_id", "incident_id"])
        op.create_index("ix_post_mortems_status", "post_mortems", ["status"])

    # Ensure partial unique index on current post-mortem using fresh inspector
    fresh_inspector = sa.inspect(conn)
    fresh_tables = fresh_inspector.get_table_names()
    pm_indexes = [idx["name"] for idx in fresh_inspector.get_indexes("post_mortems")] if "post_mortems" in fresh_tables else []
    if "uq_post_mortems_incident_current" not in pm_indexes:
        if is_postgres:
            conn.execute(sa.text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_post_mortems_incident_current 
                ON post_mortems (incident_id) 
                WHERE is_current = true;
            """))
        else:
            conn.execute(sa.text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_post_mortems_incident_current 
                ON post_mortems (incident_id) 
                WHERE is_current = 1;
            """))

    # =========================================================================
    # 3. POST_MORTEM_ACTION_ITEMS TABLE
    # =========================================================================
    fresh_inspector_2 = sa.inspect(conn)
    if "post_mortem_action_items" not in fresh_inspector_2.get_table_names():
        op.create_table(
            "post_mortem_action_items",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("post_mortem_id", uuid_type, sa.ForeignKey("post_mortems.id", ondelete="CASCADE"), nullable=False),
            sa.Column("incident_id", uuid_type, sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=True),
            sa.Column("assigned_to_user_id", uuid_type, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_by_user_id", uuid_type, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("category", sa.String(50), server_default="code_hardening", nullable=False),
            sa.Column("priority", sa.String(20), server_default="P2", nullable=False),
            sa.Column("status", sa.String(50), server_default="open", nullable=False),
            sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("external_issue_url", sa.String(500), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )

        op.create_index("ix_action_items_org_status", "post_mortem_action_items", ["organization_id", "status"])
        op.create_index("ix_action_items_post_mortem", "post_mortem_action_items", ["post_mortem_id"])


def downgrade():
    """
    Downgrade Phase 10 schema.

    NOTE ON POSTGRESQL ENUMS:
    PostgreSQL does not support removing values from an existing enum type via ALTER TYPE.
    Therefore, downgrading this migration drops the 'post_mortems' and 'post_mortem_action_items'
    tables, indexes, and constraints, but the 'PREVIOUS_INCIDENT' value remains safely in the
    'evidencesourcetype' enum without affecting other enum variants or existing tables.
    """
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    # 1. Drop post_mortem_action_items
    if "post_mortem_action_items" in tables:
        op.drop_table("post_mortem_action_items")

    # 2. Drop post_mortems
    fresh_inspector = sa.inspect(conn)
    if "post_mortems" in fresh_inspector.get_table_names():
        pm_indexes = [idx["name"] for idx in fresh_inspector.get_indexes("post_mortems")]
        if "uq_post_mortems_incident_current" in pm_indexes:
            conn.execute(sa.text("DROP INDEX IF EXISTS uq_post_mortems_incident_current;"))
        op.drop_table("post_mortems")
