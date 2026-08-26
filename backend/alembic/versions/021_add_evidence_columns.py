"""Add commit_sha, observed_at, retrieval_method to evidence."""
from alembic import op
import sqlalchemy as sa


revision = "021_add_evidence_columns"
down_revision = "020_fix_deployment_fk"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("evidence", sa.Column("commit_sha", sa.String(40), nullable=True))
    op.add_column("evidence", sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("evidence", sa.Column("retrieval_method", sa.String(100), nullable=True))


def downgrade():
    op.drop_column("evidence", "retrieval_method")
    op.drop_column("evidence", "observed_at")
    op.drop_column("evidence", "commit_sha")
