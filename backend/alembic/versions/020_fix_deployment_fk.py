"""Convert Incident.deployment_id from VARCHAR to UUID FK."""
from alembic import op
import sqlalchemy as sa


revision = "020_fix_deployment_fk"
down_revision = "019_add_unique_constraints"
branch_labels = None
depends_on = None


def upgrade():
    # Drop the old VARCHAR column and recreate as UUID FK
    op.execute("ALTER TABLE incidents DROP COLUMN IF EXISTS deployment_id")
    op.execute("""
        ALTER TABLE incidents
        ADD COLUMN deployment_id UUID REFERENCES deployments(id)
    """)


def downgrade():
    op.execute("ALTER TABLE incidents DROP COLUMN IF EXISTS deployment_id")
    op.execute("""
        ALTER TABLE incidents
        ADD COLUMN deployment_id VARCHAR(255)
    """)
