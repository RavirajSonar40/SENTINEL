"""Add Phase 13 Policy Gateway & Approvals Schema

Revision ID: 033_add_phase13_policy_gateway
Revises: 032_add_phase12_isolated_validation
Create Date: 2026-08-29 04:50:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = '033_add_phase13_policy_gateway'
down_revision = '032_add_phase12_isolated_validation'
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
    # 1. POSTGRESQL ENUM UPDATES (If running on PostgreSQL)
    # =========================================================================
    if is_postgres:
        # Add security_officer to membershiprole enum if needed
        try:
            conn.execute(sa.text("ALTER TYPE membershiprole ADD VALUE IF NOT EXISTS 'security_officer'"))
        except Exception:
            pass

        # Update approvalstatus enum values if exists
        try:
            conn.execute(sa.text("ALTER TYPE approvalstatus ADD VALUE IF NOT EXISTS 'changes_requested'"))
            conn.execute(sa.text("ALTER TYPE approvalstatus ADD VALUE IF NOT EXISTS 'invalidated_stale'"))
            conn.execute(sa.text("ALTER TYPE approvalstatus ADD VALUE IF NOT EXISTS 'cancelled'"))
            conn.execute(sa.text("ALTER TYPE approvalstatus ADD VALUE IF NOT EXISTS 'expired'"))
        except Exception:
            pass

    # =========================================================================
    # 2. ENHANCE APPROVALS TABLE
    # =========================================================================
    if "approvals" in tables:
        app_cols = [c["name"] for c in inspector.get_columns("approvals")]

        if "organization_id" not in app_cols:
            op.add_column("approvals", sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True))

            # Backfill organization_id from incidents
            if "incidents" in tables:
                if is_postgres:
                    conn.execute(sa.text("""
                        UPDATE approvals 
                        SET organization_id = incidents.organization_id 
                        FROM incidents 
                        WHERE approvals.incident_id = incidents.id AND approvals.organization_id IS NULL
                    """))
                else:
                    conn.execute(sa.text("""
                        UPDATE approvals 
                        SET organization_id = (SELECT organization_id FROM incidents WHERE incidents.id = approvals.incident_id)
                        WHERE organization_id IS NULL
                    """))

            # Backfill organization_id from proposed_fixes
            if "proposed_fixes" in tables:
                if is_postgres:
                    conn.execute(sa.text("""
                        UPDATE approvals 
                        SET organization_id = proposed_fixes.organization_id 
                        FROM proposed_fixes 
                        WHERE approvals.fix_id = proposed_fixes.id AND approvals.organization_id IS NULL
                    """))
                else:
                    conn.execute(sa.text("""
                        UPDATE approvals 
                        SET organization_id = (SELECT organization_id FROM proposed_fixes WHERE proposed_fixes.id = approvals.fix_id)
                        WHERE organization_id IS NULL
                    """))

            # Backfill organization_id from users
            if "users" in tables:
                if is_postgres:
                    conn.execute(sa.text("""
                        UPDATE approvals 
                        SET organization_id = users.organization_id 
                        FROM users 
                        WHERE approvals.user_id = users.id AND approvals.organization_id IS NULL AND users.organization_id IS NOT NULL
                    """))
                else:
                    conn.execute(sa.text("""
                        UPDATE approvals 
                        SET organization_id = (SELECT organization_id FROM users WHERE users.id = approvals.user_id AND users.organization_id IS NOT NULL)
                        WHERE organization_id IS NULL
                    """))

        # Zero-Deletion Fail-Fast Integrity Checks:
        orphans = conn.execute(sa.text("SELECT id FROM approvals WHERE organization_id IS NULL")).fetchall()
        if orphans:
            orphan_ids = [str(r[0]) for r in orphans]
            raise RuntimeError(
                f"Migration 033 aborted: Found orphaned approvals without valid organization ownership: {orphan_ids}. "
                f"Manual ownership remediation required. Sentinel zero-deletion policy strictly prohibits deleting unowned records."
            )

        # Enforce NOT NULL on organization_id
        if is_postgres:
            op.alter_column("approvals", "organization_id", nullable=False)
        else:
            with op.batch_alter_table("approvals") as batch_op:
                batch_op.alter_column("organization_id", nullable=False)

        # Add remaining enhanced columns
        if "work_item_id" not in app_cols:
            op.add_column("approvals", sa.Column("work_item_id", uuid_type, sa.ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True))

        if "action_type" not in app_cols:
            op.add_column("approvals", sa.Column("action_type", sa.String(50), server_default="create_draft_pr", nullable=False))

        if "risk_level" not in app_cols:
            op.add_column("approvals", sa.Column("risk_level", sa.String(20), server_default="low", nullable=False))

        if "patch_version" not in app_cols:
            op.add_column("approvals", sa.Column("patch_version", sa.Integer, server_default="1", nullable=False))

        if "snapshot_hash" not in app_cols:
            op.add_column("approvals", sa.Column("snapshot_hash", sa.String(64), nullable=True))

        if "base_commit_sha" not in app_cols:
            op.add_column("approvals", sa.Column("base_commit_sha", sa.String(40), nullable=True))

        if "validation_run_id" not in app_cols:
            op.add_column("approvals", sa.Column("validation_run_id", uuid_type, sa.ForeignKey("validation_runs.id", ondelete="SET NULL"), nullable=True))

        if "required_approvals" not in app_cols:
            op.add_column("approvals", sa.Column("required_approvals", sa.Integer, server_default="1", nullable=False))

        if "approvals_received" not in app_cols:
            op.add_column("approvals", sa.Column("approvals_received", sa.Integer, server_default="0", nullable=False))

        if "compliance_checklist_json" not in app_cols:
            op.add_column("approvals", sa.Column("compliance_checklist_json", json_type, nullable=True))

        if "decisions_json" not in app_cols:
            op.add_column("approvals", sa.Column("decisions_json", json_type, nullable=True))

        if "expires_at" not in app_cols:
            op.add_column("approvals", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))

        if "updated_at" not in app_cols:
            op.add_column("approvals", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

        # Indexes
        app_indexes = [idx["name"] for idx in inspector.get_indexes("approvals")]
        if "ix_approvals_org" not in app_indexes:
            op.create_index("ix_approvals_org", "approvals", ["organization_id"])
        if "ix_approvals_fix" not in app_indexes:
            op.create_index("ix_approvals_fix", "approvals", ["fix_id"])
        if "ix_approvals_status" not in app_indexes:
            op.create_index("ix_approvals_status", "approvals", ["status"])

    # =========================================================================
    # 3. CREATE APPROVAL_DECISIONS TABLE
    # =========================================================================
    if "approval_decisions" not in tables:
        op.create_table(
            "approval_decisions",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("approval_id", uuid_type, sa.ForeignKey("approvals.id", ondelete="CASCADE"), nullable=False),
            sa.Column("approver_id", uuid_type, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("decision", sa.String(50), nullable=False),
            sa.Column("role", sa.String(50), nullable=True),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("approval_id", "approver_id", name="uq_approval_decision_user"),
        )
        op.create_index("ix_app_dec_app_id", "approval_decisions", ["approval_id"])
        op.create_index("ix_app_dec_user_id", "approval_decisions", ["approver_id"])
        op.create_index("ix_app_dec_org_id", "approval_decisions", ["organization_id"])

    # =========================================================================
    # 4. CREATE POLICY_RULES TABLE
    # =========================================================================
    if "policy_rules" not in tables:
        op.create_table(
            "policy_rules",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("action_type", sa.String(50), nullable=False),
            sa.Column("decision", sa.String(50), nullable=False),
            sa.Column("conditions_json", json_type, nullable=True),
            sa.Column("required_approvals_count", sa.Integer, server_default="1", nullable=False),
            sa.Column("required_roles_json", json_type, nullable=True),
            sa.Column("priority", sa.Integer, server_default="100", nullable=False),
            sa.Column("is_active", sa.Boolean, server_default=sa.text("true" if is_postgres else "1"), nullable=False),
            sa.Column("is_mandatory", sa.Boolean, server_default=sa.text("false" if is_postgres else "0"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_policy_rules_org", "policy_rules", ["organization_id"])
        op.create_index("ix_policy_rules_action", "policy_rules", ["action_type"])

    # =========================================================================
    # 5. CREATE POLICY_EVALUATIONS TABLE
    # =========================================================================
    if "policy_evaluations" not in tables:
        op.create_table(
            "policy_evaluations",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("action_type", sa.String(50), nullable=False),
            sa.Column("target_entity_type", sa.String(50), nullable=False),
            sa.Column("target_entity_id", uuid_type, nullable=True),
            sa.Column("patch_version", sa.Integer, nullable=True),
            sa.Column("snapshot_hash", sa.String(64), nullable=True),
            sa.Column("decision", sa.String(50), nullable=False),
            sa.Column("matched_rule_id", uuid_type, sa.ForeignKey("policy_rules.id", ondelete="SET NULL"), nullable=True),
            sa.Column("reasons_json", json_type, nullable=True),
            sa.Column("context_snapshot_json", json_type, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_policy_eval_org", "policy_evaluations", ["organization_id"])
        op.create_index("ix_policy_eval_action", "policy_evaluations", ["action_type"])
        op.create_index("ix_policy_eval_user", "policy_evaluations", ["user_id"])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    is_postgres = conn.dialect.name == "postgresql"

    if "policy_evaluations" in tables:
        op.drop_table("policy_evaluations")

    if "policy_rules" in tables:
        op.drop_table("policy_rules")

    if "approval_decisions" in tables:
        op.drop_table("approval_decisions")

    if "approvals" in tables:
        app_cols = [c["name"] for c in inspector.get_columns("approvals")]
        cols_to_drop = [
            "organization_id", "work_item_id", "action_type", "risk_level",
            "patch_version", "snapshot_hash", "base_commit_sha", "validation_run_id",
            "required_approvals", "approvals_received", "compliance_checklist_json",
            "decisions_json", "expires_at", "updated_at",
        ]
        present_cols = [col for col in cols_to_drop if col in app_cols]
        if present_cols:
            if is_postgres:
                for col in present_cols:
                    op.drop_column("approvals", col)
            else:
                with op.batch_alter_table("approvals") as batch_op:
                    for col in present_cols:
                        batch_op.drop_column(col)
