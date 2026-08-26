"""Add incident_number_seq for atomic incident numbering."""
from alembic import op


revision = "018_add_incident_number_seq"
down_revision = "017_add_fix_repository_patch"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DO $$
        DECLARE
            max_num INTEGER;
        BEGIN
            SELECT COALESCE(MAX(number), 0) INTO max_num FROM incidents;
            CREATE SEQUENCE IF NOT EXISTS incident_number_seq START WITH 1;
            PERFORM setval('incident_number_seq', max_num);
        END $$;
    """)


def downgrade():
    op.execute("DROP SEQUENCE IF EXISTS incident_number_seq")
