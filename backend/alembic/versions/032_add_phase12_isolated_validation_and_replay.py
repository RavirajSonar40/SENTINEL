"""Add Phase 12 Isolated Validation & Replay Schema

Revision ID: 032_add_phase12_isolated_validation
Revises: 031_add_phase11_patch_test
Create Date: 2026-08-28 22:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '032_add_phase12_isolated_validation'
down_revision = '031_add_phase11_patch_test'
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
    # 1. ENHANCE VALIDATION_RUNS TABLE WITH STRICT ZERO-DELETION BACKFILL
    # =========================================================================
    if "validation_runs" in tables:
        val_cols = [c["name"] for c in inspector.get_columns("validation_runs")]

        # Add organization_id as nullable first for backfill
        if "organization_id" not in val_cols:
            op.add_column("validation_runs", sa.Column("organization_id", uuid_type, nullable=True))
            if "proposed_fixes" in tables:
                if is_postgres:
                    conn.execute(sa.text("""
                        UPDATE validation_runs 
                        SET organization_id = proposed_fixes.organization_id 
                        FROM proposed_fixes 
                        WHERE validation_runs.fix_id = proposed_fixes.id AND proposed_fixes.organization_id IS NOT NULL
                    """))
                else:
                    conn.execute(sa.text("""
                        UPDATE validation_runs 
                        SET organization_id = (SELECT organization_id FROM proposed_fixes WHERE proposed_fixes.id = validation_runs.fix_id)
                        WHERE validation_runs.fix_id IN (SELECT id FROM proposed_fixes WHERE organization_id IS NOT NULL)
                    """))

        # Add base_commit_sha as nullable first for backfill
        if "base_commit_sha" not in val_cols:
            op.add_column("validation_runs", sa.Column("base_commit_sha", sa.String(64), nullable=True))
            if "proposed_fixes" in tables:
                if is_postgres:
                    conn.execute(sa.text("""
                        UPDATE validation_runs 
                        SET base_commit_sha = proposed_fixes.base_commit_sha 
                        FROM proposed_fixes 
                        WHERE validation_runs.fix_id = proposed_fixes.id AND proposed_fixes.base_commit_sha IS NOT NULL
                    """))
                else:
                    conn.execute(sa.text("""
                        UPDATE validation_runs 
                        SET base_commit_sha = (SELECT base_commit_sha FROM proposed_fixes WHERE proposed_fixes.id = validation_runs.fix_id AND proposed_fixes.base_commit_sha IS NOT NULL)
                        WHERE validation_runs.fix_id IN (SELECT id FROM proposed_fixes WHERE base_commit_sha IS NOT NULL)
                    """))

        # Add workspace_id as nullable first for backfill
        if "workspace_id" not in val_cols:
            op.add_column("validation_runs", sa.Column("workspace_id", sa.String(64), nullable=True))
            if is_postgres:
                conn.execute(sa.text("UPDATE validation_runs SET workspace_id = 'ws_legacy_' || id::text WHERE workspace_id IS NULL"))
            else:
                conn.execute(sa.text("UPDATE validation_runs SET workspace_id = 'ws_legacy_' || CAST(id AS TEXT) WHERE workspace_id IS NULL"))

        # FAIL-FAST ZERO-DELETION & EXACT GIT COMMIT GUARANTEE CHECKS:
        # 1. Organization ownership check (zero-deletion policy)
        orphans = conn.execute(sa.text("SELECT id FROM validation_runs WHERE organization_id IS NULL")).fetchall()
        if orphans:
            orphan_ids = [str(r[0]) for r in orphans]
            raise RuntimeError(
                f"Migration 032 aborted: Found orphaned validation_runs without valid organization ownership: {orphan_ids}. "
                f"Manual ownership remediation required. Sentinel zero-deletion policy strictly prohibits deleting unowned records."
            )

        # 2. Exact Git Base Commit SHA check (must match ^[0-9a-fA-F]{40}$ and not be all zeroes)
        import re
        GIT_SHA_REGEX = re.compile(r"^[0-9a-fA-F]{40}$")
        ZERO_SHA = "0000000000000000000000000000000000000000"

        invalid_sha_ids = []
        all_val_rows = conn.execute(sa.text("SELECT id, base_commit_sha FROM validation_runs")).fetchall()
        for row in all_val_rows:
            r_id = str(row[0])
            r_sha = row[1]
            if (
                not r_sha
                or not isinstance(r_sha, str)
                or not GIT_SHA_REGEX.fullmatch(r_sha)
                or r_sha == ZERO_SHA
            ):
                invalid_sha_ids.append(r_id)

        if invalid_sha_ids:
            raise RuntimeError(
                f"Migration 032 aborted: Found validation_runs with missing, malformed, or synthetic base_commit_sha: {invalid_sha_ids}. "
                f"Exact Git commit guarantee strictly requires a valid 40-character hexadecimal Git commit SHA (^[0-9a-fA-F]{{40}}$) and prohibits "
                f"synthetic fallback, snapshot hashes, empty strings, or all-zero commit SHAs. "
                f"Manual remediation or explicit legacy quarantine required before applying NOT NULL constraint."
            )

        # Now enforce NOT NULL constraints fail-fast (no silent try-except suppression)
        if is_postgres:
            op.alter_column("validation_runs", "organization_id", nullable=False)
            op.alter_column("validation_runs", "base_commit_sha", nullable=False)
            op.alter_column("validation_runs", "workspace_id", nullable=False)
        else:
            with op.batch_alter_table("validation_runs") as batch_op:
                batch_op.alter_column("organization_id", nullable=False)
                batch_op.alter_column("base_commit_sha", nullable=False)
                batch_op.alter_column("workspace_id", nullable=False)

        # Add remaining columns
        if "repository_id" not in val_cols:
            op.add_column("validation_runs", sa.Column("repository_id", uuid_type, sa.ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True))
            if "proposed_fixes" in tables:
                if is_postgres:
                    conn.execute(sa.text("""
                        UPDATE validation_runs 
                        SET repository_id = proposed_fixes.repository_id 
                        FROM proposed_fixes 
                        WHERE validation_runs.fix_id = proposed_fixes.id
                    """))
                else:
                    conn.execute(sa.text("""
                        UPDATE validation_runs 
                        SET repository_id = (SELECT repository_id FROM proposed_fixes WHERE proposed_fixes.id = validation_runs.fix_id)
                    """))

        if "verified_base_sha" not in val_cols:
            op.add_column("validation_runs", sa.Column("verified_base_sha", sa.String(64), nullable=True))

        if "compilation_status" not in val_cols:
            op.add_column("validation_runs", sa.Column("compilation_status", sa.String(20), server_default="pending", nullable=True))

        if "tests_status" not in val_cols:
            op.add_column("validation_runs", sa.Column("tests_status", sa.String(20), server_default="pending", nullable=True))

        if "original_failure_reproduced" not in val_cols:
            op.add_column("validation_runs", sa.Column("original_failure_reproduced", sa.String(10), server_default="n/a", nullable=True))

        if "failure_absent_after_patch" not in val_cols:
            op.add_column("validation_runs", sa.Column("failure_absent_after_patch", sa.String(10), server_default="n/a", nullable=True))

        if "scenario_replay_status" not in val_cols:
            op.add_column("validation_runs", sa.Column("scenario_replay_status", sa.String(20), server_default="n/a", nullable=True))

        if "production_outcome" not in val_cols:
            op.add_column("validation_runs", sa.Column("production_outcome", sa.String(50), server_default="unknown until deployed", nullable=True))

        if "overall_status" not in val_cols:
            op.add_column("validation_runs", sa.Column("overall_status", sa.String(20), server_default="pending", nullable=True))

        if "summary_report_json" not in val_cols:
            op.add_column("validation_runs", sa.Column("summary_report_json", json_type, nullable=True))

        # Indexes
        val_indexes = [idx["name"] for idx in inspector.get_indexes("validation_runs")]
        if "ix_val_runs_fix_org" not in val_indexes:
            op.create_index("ix_val_runs_fix_org", "validation_runs", ["fix_id", "organization_id"])
        if "ix_val_runs_repo" not in val_indexes:
            op.create_index("ix_val_runs_repo", "validation_runs", ["repository_id"])

    # =========================================================================
    # 2. CREATE VALIDATION_CHECK_RUNS TABLE
    # =========================================================================
    if "validation_check_runs" not in tables:
        op.create_table(
            "validation_check_runs",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("validation_run_id", uuid_type, sa.ForeignKey("validation_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("check_type", sa.String(50), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("command_json", json_type, nullable=False),
            sa.Column("status", sa.String(20), server_default="pending", nullable=False),
            sa.Column("exit_code", sa.Integer(), nullable=True),
            sa.Column("stdout", sa.Text(), nullable=True),
            sa.Column("stderr", sa.Text(), nullable=True),
            sa.Column("duration_ms", sa.Float(), server_default="0.0", nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_val_check_runs_run_org", "validation_check_runs", ["validation_run_id", "organization_id"])
        op.create_index("ix_val_check_runs_type", "validation_check_runs", ["check_type"])

    # =========================================================================
    # 3. DATABASE-LEVEL PRODUCTION OUTCOME IMMUTABILITY TRIGGER
    # =========================================================================
    if is_postgres:
        conn.execute(sa.text("""
            CREATE OR REPLACE FUNCTION protect_validation_production_outcome()
            RETURNS TRIGGER AS $$
            BEGIN
                IF OLD.production_outcome = 'unknown until deployed' AND NEW.production_outcome <> 'unknown until deployed' THEN
                    IF current_setting('sentinel.telemetry_authorized', true) IS NULL OR current_setting('sentinel.telemetry_authorized', true) <> 'true' THEN
                        RAISE EXCEPTION 'production_outcome is immutable during validation; updates require authorized telemetry session (sentinel.telemetry_authorized=true)'
                        USING ERRCODE = '42501';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """))
        conn.execute(sa.text("DROP TRIGGER IF EXISTS trg_protect_validation_production_outcome ON validation_runs"))
        conn.execute(sa.text("""
            CREATE TRIGGER trg_protect_validation_production_outcome
            BEFORE UPDATE OF production_outcome ON validation_runs
            FOR EACH ROW
            EXECUTE FUNCTION protect_validation_production_outcome();
        """))
    else:
        # SQLite BEFORE UPDATE Trigger (Strictly Test-Only Environment)
        # Note: SQLite lacks session parameter reflection (current_setting), so it enforces
        # strict unconditional immutability during test executions. Production environments
        # run on PostgreSQL where trusted telemetry sessions can modify production_outcome
        # via sentinel.telemetry_authorized=true.
        conn.execute(sa.text("""
            CREATE TRIGGER IF NOT EXISTS trg_protect_validation_production_outcome
            BEFORE UPDATE OF production_outcome ON validation_runs
            FOR EACH ROW
            WHEN OLD.production_outcome = 'unknown until deployed' AND NEW.production_outcome != 'unknown until deployed'
            BEGIN
                SELECT RAISE(ABORT, 'production_outcome is immutable during validation');
            END;
        """))


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    is_postgres = conn.dialect.name == "postgresql"

    # Drop triggers
    if is_postgres:
        conn.execute(sa.text("DROP TRIGGER IF EXISTS trg_protect_validation_production_outcome ON validation_runs"))
        conn.execute(sa.text("DROP FUNCTION IF EXISTS protect_validation_production_outcome()"))
    else:
        conn.execute(sa.text("DROP TRIGGER IF EXISTS trg_protect_validation_production_outcome"))

    if "validation_check_runs" in tables:
        op.drop_table("validation_check_runs")

    if "validation_runs" in tables:
        val_cols = [c["name"] for c in inspector.get_columns("validation_runs")]
        cols_to_drop = [
            "organization_id", "repository_id", "base_commit_sha", "verified_base_sha",
            "workspace_id", "compilation_status", "tests_status", "original_failure_reproduced",
            "failure_absent_after_patch", "scenario_replay_status", "production_outcome",
            "overall_status", "summary_report_json",
        ]
        present_cols = [col for col in cols_to_drop if col in val_cols]
        if present_cols:
            if is_postgres:
                for col in present_cols:
                    op.drop_column("validation_runs", col)
            else:
                with op.batch_alter_table("validation_runs") as batch_op:
                    for col in present_cols:
                        batch_op.drop_column(col)
