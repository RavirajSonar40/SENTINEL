"""Add investigation_id, fix_type, status to proposed_fixes; add FixStatus enum."""
from alembic import op
import sqlalchemy as sa

revision = "016_add_fix_fields"
down_revision = "015_seed_data"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("proposed_fixes", sa.Column("investigation_id", sa.dialects.postgresql.UUID(), sa.ForeignKey("investigations.id"), nullable=True))
    op.add_column("proposed_fixes", sa.Column("fix_type", sa.String(100), nullable=True))
    op.add_column("proposed_fixes", sa.Column("status", sa.String(50), server_default="generated"))


def downgrade():
    op.drop_column("proposed_fixes", "status")
    op.drop_column("proposed_fixes", "fix_type")
    op.drop_column("proposed_fixes", "investigation_id")
