"""Add Phase 9 Evidence, Hypotheses and Root Cause Schema

Revision ID: 029_add_phase9_evidence
Revises: 028_add_phase8_workflows
Create Date: 2026-08-28 14:35:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '029_add_phase9_evidence'
down_revision = '028_add_phase8_workflows'
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
    # 1. EVIDENCE TABLE ENHANCEMENTS
    # =========================================================================
    if "evidence" in tables:
        ev_cols = [c["name"] for c in inspector.get_columns("evidence")]

        # Add organization_id as nullable first for safe backfill
        if "organization_id" not in ev_cols:
            op.add_column("evidence", sa.Column("organization_id", uuid_type, nullable=True))

            # Backfill from linked incidents if table exists
            if "incidents" in tables:
                if is_postgres:
                    conn.execute(sa.text("""
                        UPDATE evidence 
                        SET organization_id = incidents.organization_id 
                        FROM incidents 
                        WHERE evidence.incident_id = incidents.id AND incidents.organization_id IS NOT NULL
                    """))
                else:
                    conn.execute(sa.text("""
                        UPDATE evidence 
                        SET organization_id = (SELECT organization_id FROM incidents WHERE incidents.id = evidence.incident_id)
                        WHERE evidence.incident_id IN (SELECT id FROM incidents WHERE organization_id IS NOT NULL)
                    """))

            # Fail-fast orphan check
            remaining_orphans = conn.execute(sa.text("SELECT id FROM evidence WHERE organization_id IS NULL")).fetchall()
            if remaining_orphans:
                orphan_ids = [str(r[0]) for r in remaining_orphans]
                raise RuntimeError(
                    f"Migration 029 aborted: {len(remaining_orphans)} orphaned evidence rows found without valid organization mapping: {orphan_ids[:10]}... "
                    f"Automatic tenant assignment or silent deletion is strictly forbidden. "
                    f"Manual tenant ownership remediation is required before applying the NOT NULL constraint."
                )

            # Enforce NOT NULL and add foreign key / indexes
            if is_postgres:
                op.alter_column("evidence", "organization_id", nullable=False)
                op.create_foreign_key(
                    "fk_evidence_organization_id",
                    "evidence", "organizations",
                    ["organization_id"], ["id"],
                    ondelete="CASCADE"
                )
            op.create_index("ix_evidence_org_incident", "evidence", ["organization_id", "incident_id"])

        if "work_item_id" not in ev_cols:
            op.add_column("evidence", sa.Column("work_item_id", uuid_type, nullable=True))
        if "category_type" not in ev_cols:
            op.add_column("evidence", sa.Column("category_type", sa.String(50), nullable=False, server_default="fact"))
            op.create_index("ix_evidence_category_type", "evidence", ["category_type"])
        if "evidence_family" not in ev_cols:
            op.add_column("evidence", sa.Column("evidence_family", sa.String(50), nullable=True))
        if "service" not in ev_cols:
            op.add_column("evidence", sa.Column("service", sa.String(255), nullable=True))
        if "environment" not in ev_cols:
            op.add_column("evidence", sa.Column("environment", sa.String(100), nullable=True))
        if "region" not in ev_cols:
            op.add_column("evidence", sa.Column("region", sa.String(100), nullable=True))
        if "content_hash" not in ev_cols:
            op.add_column("evidence", sa.Column("content_hash", sa.String(64), nullable=True))
            op.create_index("ix_evidence_content_hash", "evidence", ["content_hash"])
        if "is_redacted" not in ev_cols:
            op.add_column("evidence", sa.Column("is_redacted", sa.Boolean(), server_default="0", nullable=False))
        if "payload_size_bytes" not in ev_cols:
            op.add_column("evidence", sa.Column("payload_size_bytes", sa.Integer(), server_default="0", nullable=False))
        if "trust_level" not in ev_cols:
            op.add_column("evidence", sa.Column("trust_level", sa.String(50), server_default="unverified", nullable=False))
        if "verification_status" not in ev_cols:
            op.add_column("evidence", sa.Column("verification_status", sa.String(50), server_default="verified", nullable=False))
        if "submitted_by_user_id" not in ev_cols:
            op.add_column("evidence", sa.Column("submitted_by_user_id", uuid_type, nullable=True))
        if "verified_by_user_id" not in ev_cols:
            op.add_column("evidence", sa.Column("verified_by_user_id", uuid_type, nullable=True))
        if "verified_at" not in ev_cols:
            op.add_column("evidence", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
        if "version" not in ev_cols:
            op.add_column("evidence", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
        if "superseded_by_id" not in ev_cols:
            op.add_column("evidence", sa.Column("superseded_by_id", uuid_type, nullable=True))

    # =========================================================================
    # 2. HYPOTHESES TABLE ENHANCEMENTS
    # =========================================================================
    if "hypotheses" in tables:
        hyp_cols = [c["name"] for c in inspector.get_columns("hypotheses")]

        if "organization_id" not in hyp_cols:
            op.add_column("hypotheses", sa.Column("organization_id", uuid_type, nullable=True))

            if "incidents" in tables:
                if is_postgres:
                    conn.execute(sa.text("""
                        UPDATE hypotheses 
                        SET organization_id = incidents.organization_id 
                        FROM incidents 
                        WHERE hypotheses.incident_id = incidents.id AND incidents.organization_id IS NOT NULL
                    """))
                else:
                    conn.execute(sa.text("""
                        UPDATE hypotheses 
                        SET organization_id = (SELECT organization_id FROM incidents WHERE incidents.id = hypotheses.incident_id)
                        WHERE hypotheses.incident_id IN (SELECT id FROM incidents WHERE organization_id IS NOT NULL)
                    """))

            remaining_orphans = conn.execute(sa.text("SELECT id FROM hypotheses WHERE organization_id IS NULL")).fetchall()
            if remaining_orphans:
                orphan_ids = [str(r[0]) for r in remaining_orphans]
                raise RuntimeError(
                    f"Migration 029 aborted: {len(remaining_orphans)} orphaned hypotheses rows found without valid organization mapping: {orphan_ids[:10]}... "
                    f"Manual tenant ownership remediation required."
                )

            if is_postgres:
                op.alter_column("hypotheses", "organization_id", nullable=False)
                op.create_foreign_key(
                    "fk_hypotheses_organization_id",
                    "hypotheses", "organizations",
                    ["organization_id"], ["id"],
                    ondelete="CASCADE"
                )
            op.create_index("ix_hypotheses_org_incident", "hypotheses", ["organization_id", "incident_id"])

        if "work_item_id" not in hyp_cols:
            op.add_column("hypotheses", sa.Column("work_item_id", uuid_type, nullable=True))
        if "temporal_fit" not in hyp_cols:
            op.add_column("hypotheses", sa.Column("temporal_fit", sa.Boolean(), server_default="1", nullable=False))
        if "temporal_fit_score" not in hyp_cols:
            op.add_column("hypotheses", sa.Column("temporal_fit_score", sa.Float(), server_default="1.0", nullable=False))
        if "code_path_fit" not in hyp_cols:
            op.add_column("hypotheses", sa.Column("code_path_fit", sa.Boolean(), server_default="1", nullable=False))
        if "code_path_fit_score" not in hyp_cols:
            op.add_column("hypotheses", sa.Column("code_path_fit_score", sa.Float(), server_default="1.0", nullable=False))
        if "operational_fit" not in hyp_cols:
            op.add_column("hypotheses", sa.Column("operational_fit", sa.Boolean(), server_default="1", nullable=False))
        if "operational_fit_score" not in hyp_cols:
            op.add_column("hypotheses", sa.Column("operational_fit_score", sa.Float(), server_default="1.0", nullable=False))
        if "distinct_families_count" not in hyp_cols:
            op.add_column("hypotheses", sa.Column("distinct_families_count", sa.Integer(), server_default="0", nullable=False))
        if "supporting_evidence_ids" not in hyp_cols:
            op.add_column("hypotheses", sa.Column("supporting_evidence_ids", json_type, nullable=True))
        if "contradicting_evidence_ids" not in hyp_cols:
            op.add_column("hypotheses", sa.Column("contradicting_evidence_ids", json_type, nullable=True))
        if "missing_evidence_json" not in hyp_cols:
            op.add_column("hypotheses", sa.Column("missing_evidence_json", json_type, nullable=True))
        if "disproof_attempt_notes" not in hyp_cols:
            op.add_column("hypotheses", sa.Column("disproof_attempt_notes", sa.Text(), nullable=True))
        if "disproven_at" not in hyp_cols:
            op.add_column("hypotheses", sa.Column("disproven_at", sa.DateTime(timezone=True), nullable=True))
        if "human_triaged" not in hyp_cols:
            op.add_column("hypotheses", sa.Column("human_triaged", sa.Boolean(), server_default="0", nullable=False))
        if "human_triage_notes" not in hyp_cols:
            op.add_column("hypotheses", sa.Column("human_triage_notes", sa.Text(), nullable=True))
        if "triaged_by_user_id" not in hyp_cols:
            op.add_column("hypotheses", sa.Column("triaged_by_user_id", uuid_type, nullable=True))

    # =========================================================================
    # 3. ROOT CAUSES TABLE ENHANCEMENTS
    # =========================================================================
    if "root_causes" in tables:
        rc_cols = [c["name"] for c in inspector.get_columns("root_causes")]

        if "organization_id" not in rc_cols:
            op.add_column("root_causes", sa.Column("organization_id", uuid_type, nullable=True))

            if "incidents" in tables:
                if is_postgres:
                    conn.execute(sa.text("""
                        UPDATE root_causes 
                        SET organization_id = incidents.organization_id 
                        FROM incidents 
                        WHERE root_causes.incident_id = incidents.id AND incidents.organization_id IS NOT NULL
                    """))
                else:
                    conn.execute(sa.text("""
                        UPDATE root_causes 
                        SET organization_id = (SELECT organization_id FROM incidents WHERE incidents.id = root_causes.incident_id)
                        WHERE root_causes.incident_id IN (SELECT id FROM incidents WHERE organization_id IS NOT NULL)
                    """))

            remaining_orphans = conn.execute(sa.text("SELECT id FROM root_causes WHERE organization_id IS NULL")).fetchall()
            if remaining_orphans:
                orphan_ids = [str(r[0]) for r in remaining_orphans]
                raise RuntimeError(
                    f"Migration 029 aborted: {len(remaining_orphans)} orphaned root_causes rows found without valid organization mapping: {orphan_ids[:10]}... "
                    f"Manual tenant ownership remediation required."
                )

            if is_postgres:
                op.alter_column("root_causes", "organization_id", nullable=False)
                op.create_foreign_key(
                    "fk_root_causes_organization_id",
                    "root_causes", "organizations",
                    ["organization_id"], ["id"],
                    ondelete="CASCADE"
                )
            op.create_index("ix_root_causes_org_incident", "root_causes", ["organization_id", "incident_id"])

        if "work_item_id" not in rc_cols:
            op.add_column("root_causes", sa.Column("work_item_id", uuid_type, nullable=True))
        if "evidence_sources_count" not in rc_cols:
            op.add_column("root_causes", sa.Column("evidence_sources_count", sa.Integer(), server_default="0", nullable=False))
        if "distinct_families_count" not in rc_cols:
            op.add_column("root_causes", sa.Column("distinct_families_count", sa.Integer(), server_default="0", nullable=False))
        if "disproof_summary" not in rc_cols:
            op.add_column("root_causes", sa.Column("disproof_summary", sa.Text(), nullable=True))
        if "abstained" not in rc_cols:
            op.add_column("root_causes", sa.Column("abstained", sa.Boolean(), server_default="0", nullable=False))
        if "abstention_reason" not in rc_cols:
            op.add_column("root_causes", sa.Column("abstention_reason", sa.Text(), nullable=True))
        if "missing_evidence_json" not in rc_cols:
            op.add_column("root_causes", sa.Column("missing_evidence_json", json_type, nullable=True))
        if "evaluation_version" not in rc_cols:
            op.add_column("root_causes", sa.Column("evaluation_version", sa.Integer(), server_default="1", nullable=False))
        if "snapshot_hash" not in rc_cols:
            op.add_column("root_causes", sa.Column("snapshot_hash", sa.String(64), nullable=True))
        if "is_current" not in rc_cols:
            op.add_column("root_causes", sa.Column("is_current", sa.Boolean(), server_default="1", nullable=False))
            op.create_index("ix_root_causes_is_current", "root_causes", ["is_current"])

        # Independent creation of unique partial index on active root cause per incident
        rc_indexes = [idx["name"] for idx in inspector.get_indexes("root_causes")]
        if "uq_root_causes_incident_current" not in rc_indexes:
            if is_postgres:
                conn.execute(sa.text("""
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_root_causes_incident_current
                    ON root_causes (incident_id)
                    WHERE is_current = true;
                """))
            else:
                conn.execute(sa.text("""
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_root_causes_incident_current
                    ON root_causes (incident_id)
                    WHERE is_current = 1;
                """))

        if "human_overridden" not in rc_cols:
            op.add_column("root_causes", sa.Column("human_overridden", sa.Boolean(), server_default="0", nullable=False))
        if "human_override_notes" not in rc_cols:
            op.add_column("root_causes", sa.Column("human_override_notes", sa.Text(), nullable=True))
        if "overridden_by_user_id" not in rc_cols:
            op.add_column("root_causes", sa.Column("overridden_by_user_id", uuid_type, nullable=True))

    # =========================================================================
    # 4. HYPOTHESIS EVIDENCE ASSOCIATION TABLE
    # =========================================================================
    if "hypothesis_evidence" in tables:
        he_cols = [c["name"] for c in inspector.get_columns("hypothesis_evidence")]
        if "confidence_weight" not in he_cols:
            op.add_column("hypothesis_evidence", sa.Column("confidence_weight", sa.Float(), server_default="1.0", nullable=False))

    # =========================================================================
    # 5. DATABASE-LEVEL IMMUTABILITY TRIGGERS
    # =========================================================================
    if "evidence" in tables:
        if is_postgres:
            conn.execute(sa.text("""
                CREATE OR REPLACE FUNCTION prevent_evidence_update_fn()
                RETURNS TRIGGER AS $$
                BEGIN
                    IF (OLD.title IS DISTINCT FROM NEW.title OR
                        OLD.content IS DISTINCT FROM NEW.content OR
                        OLD.content_hash IS DISTINCT FROM NEW.content_hash OR
                        OLD.source_type IS DISTINCT FROM NEW.source_type OR
                        OLD.category_type IS DISTINCT FROM NEW.category_type OR
                        OLD.service IS DISTINCT FROM NEW.service OR
                        OLD.repository IS DISTINCT FROM NEW.repository OR
                        OLD.commit_sha IS DISTINCT FROM NEW.commit_sha OR
                        OLD.file_path IS DISTINCT FROM NEW.file_path OR
                        OLD.payload_size_bytes IS DISTINCT FROM NEW.payload_size_bytes OR
                        OLD.organization_id IS DISTINCT FROM NEW.organization_id OR
                        OLD.incident_id IS DISTINCT FROM NEW.incident_id OR
                        OLD.observed_at IS DISTINCT FROM NEW.observed_at) THEN
                        RAISE EXCEPTION 'Evidence records are immutable and append-only. Direct SQL UPDATE blocked on table evidence.';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;

                DROP TRIGGER IF EXISTS trg_evidence_prevent_update ON evidence;
                CREATE TRIGGER trg_evidence_prevent_update
                BEFORE UPDATE ON evidence
                FOR EACH ROW
                EXECUTE FUNCTION prevent_evidence_update_fn();

                CREATE OR REPLACE FUNCTION prevent_evidence_delete_fn()
                RETURNS TRIGGER AS $$
                BEGIN
                    RAISE EXCEPTION 'Evidence records are immutable and cannot be deleted. Direct SQL DELETE blocked on table evidence.';
                END;
                $$ LANGUAGE plpgsql;

                DROP TRIGGER IF EXISTS trg_evidence_prevent_delete ON evidence;
                CREATE TRIGGER trg_evidence_prevent_delete
                BEFORE DELETE ON evidence
                FOR EACH ROW
                EXECUTE FUNCTION prevent_evidence_delete_fn();
            """))
        else:
            conn.execute(sa.text("""
                CREATE TRIGGER IF NOT EXISTS trg_evidence_prevent_update
                BEFORE UPDATE ON evidence
                FOR EACH ROW
                WHEN (
                    OLD.title IS NOT NEW.title OR
                    OLD.content IS NOT NEW.content OR
                    OLD.content_hash IS NOT NEW.content_hash OR
                    OLD.source_type IS NOT NEW.source_type OR
                    OLD.category_type IS NOT NEW.category_type OR
                    OLD.service IS NOT NEW.service OR
                    OLD.repository IS NOT NEW.repository OR
                    OLD.commit_sha IS NOT NEW.commit_sha OR
                    OLD.file_path IS NOT NEW.file_path OR
                    OLD.payload_size_bytes IS NOT NEW.payload_size_bytes OR
                    OLD.organization_id IS NOT NEW.organization_id OR
                    OLD.incident_id IS NOT NEW.incident_id OR
                    OLD.observed_at IS NOT NEW.observed_at
                )
                BEGIN
                    SELECT RAISE(ABORT, 'Evidence records are immutable and append-only. Direct SQL UPDATE blocked on table evidence.');
                END;
            """))
            conn.execute(sa.text("""
                CREATE TRIGGER IF NOT EXISTS trg_evidence_prevent_delete
                BEFORE DELETE ON evidence
                FOR EACH ROW
                BEGIN
                    SELECT RAISE(ABORT, 'Evidence records are immutable and cannot be deleted. Direct SQL DELETE blocked on table evidence.');
                END;
            """))


def downgrade():
    conn = op.get_bind()
    is_postgres = conn.dialect.name == "postgresql"
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    # 1. Drop Database-Level Immutability Triggers & Functions
    if "evidence" in tables:
        if is_postgres:
            conn.execute(sa.text("DROP TRIGGER IF EXISTS trg_evidence_prevent_update ON evidence;"))
            conn.execute(sa.text("DROP TRIGGER IF EXISTS trg_evidence_prevent_delete ON evidence;"))
            conn.execute(sa.text("DROP FUNCTION IF EXISTS prevent_evidence_update_fn();"))
            conn.execute(sa.text("DROP FUNCTION IF EXISTS prevent_evidence_delete_fn();"))
        else:
            conn.execute(sa.text("DROP TRIGGER IF EXISTS trg_evidence_prevent_update;"))
            conn.execute(sa.text("DROP TRIGGER IF EXISTS trg_evidence_prevent_delete;"))

    # 2. Hypothesis Evidence Table Columns
    if "hypothesis_evidence" in tables:
        he_cols = [c["name"] for c in inspector.get_columns("hypothesis_evidence")]
        if "confidence_weight" in he_cols:
            with op.batch_alter_table("hypothesis_evidence") as batch_op:
                batch_op.drop_column("confidence_weight")

    # 3. Root Causes Table Columns & Indexes
    if "root_causes" in tables:
        rc_cols = [c["name"] for c in inspector.get_columns("root_causes")]
        rc_drop_list = [
            c for c in [
                "overridden_by_user_id",
                "human_override_notes",
                "human_overridden",
                "is_current",
                "snapshot_hash",
                "evaluation_version",
                "missing_evidence_json",
                "abstention_reason",
                "abstained",
                "disproof_summary",
                "distinct_families_count",
                "evidence_sources_count",
                "work_item_id",
                "organization_id",
            ] if c in rc_cols
        ]

        rc_indexes = inspector.get_indexes("root_causes")
        for idx in rc_indexes:
            idx_cols = set(idx.get("column_names") or [])
            if idx_cols.intersection(set(rc_drop_list)) or idx.get("name") == "uq_root_causes_incident_current":
                try:
                    op.drop_index(idx["name"], table_name="root_causes")
                except Exception:
                    conn.execute(sa.text(f"DROP INDEX IF EXISTS {idx['name']};"))

        if is_postgres:
            fks = [fk["name"] for fk in inspector.get_foreign_keys("root_causes")]
            if "fk_root_causes_organization_id" in fks:
                op.drop_constraint("fk_root_causes_organization_id", "root_causes", type_="foreignkey")

        if rc_drop_list:
            with op.batch_alter_table("root_causes") as batch_op:
                for c in rc_drop_list:
                    batch_op.drop_column(c)

    # 4. Hypotheses Table Columns & Indexes
    if "hypotheses" in tables:
        hyp_cols = [c["name"] for c in inspector.get_columns("hypotheses")]
        hyp_drop_list = [
            c for c in [
                "triaged_by_user_id",
                "human_triage_notes",
                "human_triaged",
                "disproven_at",
                "disproof_attempt_notes",
                "missing_evidence_json",
                "contradicting_evidence_ids",
                "supporting_evidence_ids",
                "distinct_families_count",
                "operational_fit_score",
                "operational_fit",
                "code_path_fit_score",
                "code_path_fit",
                "temporal_fit_score",
                "temporal_fit",
                "work_item_id",
                "organization_id",
            ] if c in hyp_cols
        ]

        hyp_indexes = inspector.get_indexes("hypotheses")
        for idx in hyp_indexes:
            idx_cols = set(idx.get("column_names") or [])
            if idx_cols.intersection(set(hyp_drop_list)):
                try:
                    op.drop_index(idx["name"], table_name="hypotheses")
                except Exception:
                    conn.execute(sa.text(f"DROP INDEX IF EXISTS {idx['name']};"))

        if is_postgres:
            fks = [fk["name"] for fk in inspector.get_foreign_keys("hypotheses")]
            if "fk_hypotheses_organization_id" in fks:
                op.drop_constraint("fk_hypotheses_organization_id", "hypotheses", type_="foreignkey")

        if hyp_drop_list:
            with op.batch_alter_table("hypotheses") as batch_op:
                for c in hyp_drop_list:
                    batch_op.drop_column(c)

    # 5. Evidence Table Columns & Indexes
    if "evidence" in tables:
        ev_cols = [c["name"] for c in inspector.get_columns("evidence")]
        ev_drop_list = [
            c for c in [
                "superseded_by_id",
                "version",
                "verified_at",
                "verified_by_user_id",
                "submitted_by_user_id",
                "verification_status",
                "trust_level",
                "payload_size_bytes",
                "is_redacted",
                "content_hash",
                "region",
                "environment",
                "service",
                "evidence_family",
                "category_type",
                "work_item_id",
                "organization_id",
            ] if c in ev_cols
        ]

        ev_indexes = inspector.get_indexes("evidence")
        for idx in ev_indexes:
            idx_cols = set(idx.get("column_names") or [])
            if idx_cols.intersection(set(ev_drop_list)):
                try:
                    op.drop_index(idx["name"], table_name="evidence")
                except Exception:
                    conn.execute(sa.text(f"DROP INDEX IF EXISTS {idx['name']};"))

        if is_postgres:
            fks = [fk["name"] for fk in inspector.get_foreign_keys("evidence")]
            if "fk_evidence_organization_id" in fks:
                op.drop_constraint("fk_evidence_organization_id", "evidence", type_="foreignkey")

        if ev_drop_list:
            with op.batch_alter_table("evidence") as batch_op:
                for c in ev_drop_list:
                    batch_op.drop_column(c)


