"""Add repository and generated patch data to proposed fixes."""
from alembic import op
import sqlalchemy as sa


revision = "017_add_fix_repository_patch"
down_revision = "016_add_fix_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE proposed_fixes ADD COLUMN IF NOT EXISTS repository VARCHAR(500)")
    op.execute("ALTER TABLE proposed_fixes ADD COLUMN IF NOT EXISTS patch_json JSONB")


def downgrade():
    op.execute("ALTER TABLE proposed_fixes DROP COLUMN IF EXISTS patch_json")
    op.execute("ALTER TABLE proposed_fixes DROP COLUMN IF EXISTS repository")