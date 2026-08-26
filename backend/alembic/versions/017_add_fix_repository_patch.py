"""Add repository and generated patch data to proposed fixes."""
from alembic import op
import sqlalchemy as sa


revision = "017_add_fix_repository_patch"
down_revision = "016_add_fix_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("proposed_fixes", sa.Column("repository", sa.String(500), nullable=True))
    op.add_column("proposed_fixes", sa.Column("patch_json", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("proposed_fixes", "patch_json")
    op.drop_column("proposed_fixes", "repository")