"""Add fix metadata columns to proposed fixes."""
from alembic import op
import sqlalchemy as sa

revision = "016_add_fix_fields"
down_revision = "015_baseline"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE proposed_fixes ADD COLUMN IF NOT EXISTS investigation_id UUID REFERENCES investigations(id)")
    op.execute("ALTER TABLE proposed_fixes ADD COLUMN IF NOT EXISTS fix_type VARCHAR(100)")
    op.execute("ALTER TABLE proposed_fixes ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'generated'")


def downgrade():
    op.execute("ALTER TABLE proposed_fixes DROP COLUMN IF EXISTS status")
    op.execute("ALTER TABLE proposed_fixes DROP COLUMN IF EXISTS fix_type")
    op.execute("ALTER TABLE proposed_fixes DROP COLUMN IF EXISTS investigation_id")
