"""Add unique constraints for repository scopes and incident signal fingerprints."""
from alembic import op


revision = "019_add_unique_constraints"
down_revision = "018_add_incident_number_seq"
branch_labels = None
depends_on = None


def upgrade():
    # Unique constraint on (incident_id, repository_id) for dedup
    op.execute("""
        ALTER TABLE repository_scopes
        ADD CONSTRAINT uq_repository_scope_incident_repo
        UNIQUE (incident_id, repository_id)
    """)

    # Partial unique index on fingerprint (only non-null values)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_incident_signals_fingerprint
        ON incident_signals (fingerprint)
        WHERE fingerprint IS NOT NULL
    """)


def downgrade():
    op.execute("ALTER TABLE repository_scopes DROP CONSTRAINT IF EXISTS uq_repository_scope_incident_repo")
    op.execute("DROP INDEX IF EXISTS ix_incident_signals_fingerprint")
