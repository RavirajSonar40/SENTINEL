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

    # Deduplicate fingerprints before creating unique index
    op.execute("""
        DELETE FROM incident_signals
        WHERE id IN (
            SELECT a.id FROM incident_signals a
            JOIN incident_signals b ON a.fingerprint = b.fingerprint
            WHERE a.fingerprint IS NOT NULL AND a.id > b.id
        )
    """)

    # Partial unique index on fingerprint per incident (only non-null, non-empty values)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_incident_signals_fingerprint
        ON incident_signals (incident_id, fingerprint)
        WHERE fingerprint IS NOT NULL AND fingerprint != ''
    """)


def downgrade():
    op.execute("ALTER TABLE repository_scopes DROP CONSTRAINT IF EXISTS uq_repository_scope_incident_repo")
    op.execute("DROP INDEX IF EXISTS ix_incident_signals_fingerprint")
