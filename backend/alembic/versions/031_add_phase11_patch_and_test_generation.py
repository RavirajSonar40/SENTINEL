"""Add Phase 11 Patch Generation, Generated Tests and Version Audit Schema

Revision ID: 031_add_phase11_patch_test
Revises: 030_add_phase10_memory
Create Date: 2026-08-28 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '031_add_phase11_patch_test'
down_revision = '030_add_phase10_memory'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    is_postgres = conn.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.String(36)
    json_type = postgresql.JSONB(astext_type=sa.Text()) if is_postgres else sa.JSON()

    # =========================================================================
    # 1. ENHANCE PROPOSED_FIXES TABLE
    # =========================================================================
    if "proposed_fixes" in tables:
        fix_cols = [c["name"] for c in inspector.get_columns("proposed_fixes")]

        if "organization_id" not in fix_cols:
            op.add_column("proposed_fixes", sa.Column("organization_id", uuid_type, nullable=True))
            if "incidents" in tables:
                if is_postgres:
                    conn.execute(sa.text("""
                        UPDATE proposed_fixes 
                        SET organization_id = incidents.organization_id 
                        FROM incidents 
                        WHERE proposed_fixes.incident_id = incidents.id AND incidents.organization_id IS NOT NULL
                    """))
                else:
                    conn.execute(sa.text("""
                        UPDATE proposed_fixes 
                        SET organization_id = (SELECT organization_id FROM incidents WHERE incidents.id = proposed_fixes.incident_id)
                        WHERE proposed_fixes.incident_id IN (SELECT id FROM incidents WHERE organization_id IS NOT NULL)
                    """))

        if "repository_id" not in fix_cols:
            op.add_column("proposed_fixes", sa.Column("repository_id", uuid_type, sa.ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True))

        if "work_item_id" not in fix_cols:
            op.add_column("proposed_fixes", sa.Column("work_item_id", uuid_type, sa.ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True))

        if "base_commit_sha" not in fix_cols:
            op.add_column("proposed_fixes", sa.Column("base_commit_sha", sa.String(40), nullable=True))

        if "target_branch" not in fix_cols:
            op.add_column("proposed_fixes", sa.Column("target_branch", sa.String(255), server_default="main", nullable=True))

        if "patch_schema_version" not in fix_cols:
            op.add_column("proposed_fixes", sa.Column("patch_schema_version", sa.Integer(), server_default="1", nullable=False))

        if "version" not in fix_cols:
            op.add_column("proposed_fixes", sa.Column("version", sa.Integer(), server_default="1", nullable=False))

        if "tests_to_add_json" not in fix_cols:
            op.add_column("proposed_fixes", sa.Column("tests_to_add_json", json_type, nullable=True))

        if "tests_to_run_json" not in fix_cols:
            op.add_column("proposed_fixes", sa.Column("tests_to_run_json", json_type, nullable=True))

        if "regression_test_status" not in fix_cols:
            op.add_column("proposed_fixes", sa.Column("regression_test_status", sa.String(50), server_default="pending", nullable=False))

        if "rollback_plan" not in fix_cols:
            op.add_column("proposed_fixes", sa.Column("rollback_plan", sa.Text(), nullable=True))

        if "is_rejected" not in fix_cols:
            op.add_column("proposed_fixes", sa.Column("is_rejected", sa.Boolean(), server_default="0", nullable=False))

        if "rejection_reason" not in fix_cols:
            op.add_column("proposed_fixes", sa.Column("rejection_reason", sa.Text(), nullable=True))

        if "scope_files_json" not in fix_cols:
            op.add_column("proposed_fixes", sa.Column("scope_files_json", json_type, nullable=True))

        if "snapshot_hash" not in fix_cols:
            op.add_column("proposed_fixes", sa.Column("snapshot_hash", sa.String(64), nullable=True))

        if "updated_at" not in fix_cols:
            op.add_column("proposed_fixes", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

        # Check existing indexes using fresh inspector
        fresh_inspector = sa.inspect(conn)
        existing_fix_indexes = [idx["name"] for idx in fresh_inspector.get_indexes("proposed_fixes")]
        if "ix_proposed_fixes_org_status" not in existing_fix_indexes:
            op.create_index("ix_proposed_fixes_org_status", "proposed_fixes", ["organization_id", "status"])
        if "ix_proposed_fixes_work_item" not in existing_fix_indexes:
            op.create_index("ix_proposed_fixes_work_item", "proposed_fixes", ["work_item_id"])

    # =========================================================================
    # 2. GENERATED_TESTS TABLE
    # =========================================================================
    fresh_inspector_2 = sa.inspect(conn)
    if "generated_tests" not in fresh_inspector_2.get_table_names():
        op.create_table(
            "generated_tests",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("fix_id", uuid_type, sa.ForeignKey("proposed_fixes.id", ondelete="CASCADE"), nullable=False),
            sa.Column("file_path", sa.String(500), nullable=False),
            sa.Column("test_type", sa.String(50), server_default="regression", nullable=False),
            sa.Column("framework", sa.String(50), server_default="pytest", nullable=False),
            sa.Column("test_name", sa.String(255), nullable=False),
            sa.Column("test_code", sa.Text(), nullable=False),
            sa.Column("target_symbol", sa.String(255), nullable=True),
            sa.Column("pre_patch_result", sa.String(50), nullable=True),
            sa.Column("post_patch_result", sa.String(50), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        )
        op.create_index("ix_generated_tests_fix_id", "generated_tests", ["fix_id"])
        op.create_index("ix_generated_tests_org", "generated_tests", ["organization_id"])

    # =========================================================================
    # 3. PATCH_VERSIONS TABLE (Manual Edit & Audit Ledger)
    # =========================================================================
    fresh_inspector_3 = sa.inspect(conn)
    if "patch_versions" not in fresh_inspector_3.get_table_names():
        op.create_table(
            "patch_versions",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("fix_id", uuid_type, sa.ForeignKey("proposed_fixes.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version_number", sa.Integer(), server_default="1", nullable=False),
            sa.Column("editor_user_id", uuid_type, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("patch_data_json", json_type, nullable=False),
            sa.Column("diff_content", sa.Text(), nullable=True),
            sa.Column("previous_snapshot_hash", sa.String(64), nullable=True),
            sa.Column("new_snapshot_hash", sa.String(64), nullable=False),
            sa.Column("revalidation_status", sa.String(50), server_default="pending", nullable=False),
            sa.Column("revalidation_details_json", json_type, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        )
        op.create_index("ix_patch_versions_fix_ver", "patch_versions", ["fix_id", "version_number"])
        op.create_index("ix_patch_versions_org", "patch_versions", ["organization_id"])


def downgrade():
    """Downgrade Phase 11 patch generation schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    # 1. Drop patch_versions
    if "patch_versions" in tables:
        op.drop_table("patch_versions")

    # 2. Drop generated_tests
    fresh_inspector = sa.inspect(conn)
    if "generated_tests" in fresh_inspector.get_table_names():
        op.drop_table("generated_tests")

    # 3. Drop added columns from proposed_fixes
    fresh_inspector_2 = sa.inspect(conn)
    if "proposed_fixes" in fresh_inspector_2.get_table_names():
        existing_cols = [c["name"] for c in fresh_inspector_2.get_columns("proposed_fixes")]
        cols_to_drop = [
            "updated_at", "snapshot_hash", "scope_files_json", "rejection_reason",
            "is_rejected", "rollback_plan", "regression_test_status", "tests_to_run_json",
            "tests_to_add_json", "version", "patch_schema_version", "target_branch",
            "base_commit_sha", "work_item_id", "repository_id", "organization_id"
        ]
        for col in cols_to_drop:
            if col in existing_cols:
                try:
                    op.drop_column("proposed_fixes", col)
                except Exception:
                    pass
