"""Add Phase 17 Security Incident Mode Schema, Immutability Triggers & Forensic Tables

Revision ID: 036_add_phase17_security_incident_workflow
Revises: 035_add_phase16_advanced_reliability
Create Date: 2026-08-29 07:35:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = '036_add_phase17_security_incident_workflow'
down_revision = '035_add_phase16_advanced_reliability'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    is_postgres = conn.dialect.name == "postgresql"
    is_sqlite = conn.dialect.name == "sqlite"
    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.String(36)

    # 1. SECURITY_CASES TABLE
    if "security_cases" not in tables:
        op.create_table(
            "security_cases",
            sa.Column("id", uuid_type, primary_key=True, default=uuid.uuid4),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("incident_id", uuid_type, sa.ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("work_item_id", uuid_type, sa.ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True),
            sa.Column("case_number", sa.String(50), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("category", sa.String(50), nullable=False, server_default="CUSTOM"),
            sa.Column("severity", sa.String(20), nullable=False, server_default="HIGH"),
            sa.Column("status", sa.String(30), nullable=False, server_default="DETECTED"),
            sa.Column("containment_status", sa.String(30), nullable=False, server_default="NOT_STARTED"),
            sa.Column("scope_summary_json", sa.JSON(), nullable=True),
            sa.Column("security_lead_id", uuid_type, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_by_user_id", uuid_type, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("resolution_summary", sa.Text(), nullable=True),
            sa.Column("contained_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("organization_id", "case_number", name="uq_security_case_org_number"),
        )
        op.create_index("ix_security_cases_org_status", "security_cases", ["organization_id", "status"])

    # 2. SECURITY_EVIDENCE_SNAPSHOTS TABLE
    if "security_evidence_snapshots" not in tables:
        op.create_table(
            "security_evidence_snapshots",
            sa.Column("id", uuid_type, primary_key=True, default=uuid.uuid4),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("security_case_id", uuid_type, sa.ForeignKey("security_cases.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("manifest_hash", sa.String(64), nullable=False),
            sa.Column("manifest_json", sa.JSON(), nullable=False),
            sa.Column("completeness_status", sa.String(30), nullable=False, server_default="COMPLETE"),
            sa.Column("captured_by_user_id", uuid_type, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("sealed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("security_case_id", name="uq_sec_evidence_case"),
        )

    # 3. SECURITY_CONTAINMENT_ACTIONS TABLE
    if "security_containment_actions" not in tables:
        op.create_table(
            "security_containment_actions",
            sa.Column("id", uuid_type, primary_key=True, default=uuid.uuid4),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("security_case_id", uuid_type, sa.ForeignKey("security_cases.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("idempotency_key", sa.String(100), nullable=True, index=True),
            sa.Column("action_type", sa.String(50), nullable=False),
            sa.Column("target_type", sa.String(50), nullable=False),
            sa.Column("target_id", sa.String(255), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("parameters_json", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="PROPOSED"),
            sa.Column("is_automated_blocked", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("proposed_by_user_id", uuid_type, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approver_1_user_id", uuid_type, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approver_1_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("approver_2_user_id", uuid_type, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approver_2_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("approval_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("execution_lease_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("execution_output", sa.Text(), nullable=True),
            sa.Column("rollback_status", sa.String(30), nullable=False, server_default="NOT_APPLICABLE"),
            sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_sec_action_org_idempotency"),
        )
        op.create_index("ix_sec_actions_case_status", "security_containment_actions", ["security_case_id", "status"])

    # 4. SECURITY_FORENSIC_AUDIT_CHAIN TABLE
    if "security_forensic_audit_chain" not in tables:
        op.create_table(
            "security_forensic_audit_chain",
            sa.Column("id", uuid_type, primary_key=True, default=uuid.uuid4),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("security_case_id", uuid_type, sa.ForeignKey("security_cases.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("sequence_number", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(50), nullable=False),
            sa.Column("actor_id", uuid_type, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("actor_name", sa.String(255), nullable=True),
            sa.Column("payload_json", sa.JSON(), nullable=True),
            sa.Column("previous_hash", sa.String(64), nullable=False),
            sa.Column("current_hash", sa.String(64), nullable=False),
            sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("security_case_id", "sequence_number", name="uq_sec_audit_case_seq"),
        )

    # 5. DATABASE-LEVEL IMMUTABILITY TRIGGERS (PostgreSQL & SQLite)
    if is_postgres:
        # Create function and triggers for Postgres
        conn.execute(sa.text("""
            CREATE OR REPLACE FUNCTION prevent_immutable_record_mutation()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'Record in % is cryptographically immutable and cannot be updated or deleted.', TG_TABLE_NAME;
            END;
            $$ LANGUAGE plpgsql;
        """))
        conn.execute(sa.text("""
            DROP TRIGGER IF EXISTS trg_guard_security_evidence ON security_evidence_snapshots;
            CREATE TRIGGER trg_guard_security_evidence
            BEFORE UPDATE OR DELETE ON security_evidence_snapshots
            FOR EACH ROW EXECUTE FUNCTION prevent_immutable_record_mutation();
        """))
        conn.execute(sa.text("""
            DROP TRIGGER IF EXISTS trg_guard_security_audit ON security_forensic_audit_chain;
            CREATE TRIGGER trg_guard_security_audit
            BEFORE UPDATE OR DELETE ON security_forensic_audit_chain
            FOR EACH ROW EXECUTE FUNCTION prevent_immutable_record_mutation();
        """))
    elif is_sqlite:
        conn.execute(sa.text("""
            CREATE TRIGGER IF NOT EXISTS trg_guard_sec_evidence_upd
            BEFORE UPDATE ON security_evidence_snapshots
            BEGIN
                SELECT RAISE(ABORT, 'SecurityEvidenceSnapshot is cryptographically immutable and cannot be updated.');
            END;
        """))
        conn.execute(sa.text("""
            CREATE TRIGGER IF NOT EXISTS trg_guard_sec_evidence_del
            BEFORE DELETE ON security_evidence_snapshots
            BEGIN
                SELECT RAISE(ABORT, 'SecurityEvidenceSnapshot is cryptographically immutable and cannot be deleted.');
            END;
        """))
        conn.execute(sa.text("""
            CREATE TRIGGER IF NOT EXISTS trg_guard_sec_audit_upd
            BEFORE UPDATE ON security_forensic_audit_chain
            BEGIN
                SELECT RAISE(ABORT, 'SecurityForensicAuditChain is append-only and cannot be updated.');
            END;
        """))
        conn.execute(sa.text("""
            CREATE TRIGGER IF NOT EXISTS trg_guard_sec_audit_del
            BEFORE DELETE ON security_forensic_audit_chain
            BEGIN
                SELECT RAISE(ABORT, 'SecurityForensicAuditChain is append-only and cannot be deleted.');
            END;
        """))


def downgrade():
    conn = op.get_bind()
    is_postgres = conn.dialect.name == "postgresql"
    is_sqlite = conn.dialect.name == "sqlite"

    # Drop triggers first
    if is_postgres:
        conn.execute(sa.text("DROP TRIGGER IF EXISTS trg_guard_security_evidence ON security_evidence_snapshots;"))
        conn.execute(sa.text("DROP TRIGGER IF EXISTS trg_guard_security_audit ON security_forensic_audit_chain;"))
        conn.execute(sa.text("DROP FUNCTION IF EXISTS prevent_immutable_record_mutation();"))
    elif is_sqlite:
        conn.execute(sa.text("DROP TRIGGER IF EXISTS trg_guard_sec_evidence_upd;"))
        conn.execute(sa.text("DROP TRIGGER IF EXISTS trg_guard_sec_evidence_del;"))
        conn.execute(sa.text("DROP TRIGGER IF EXISTS trg_guard_sec_audit_upd;"))
        conn.execute(sa.text("DROP TRIGGER IF EXISTS trg_guard_sec_audit_del;"))

    op.drop_table("security_forensic_audit_chain", if_exists=True)
    op.drop_table("security_containment_actions", if_exists=True)
    op.drop_table("security_evidence_snapshots", if_exists=True)
    op.drop_table("security_cases", if_exists=True)
