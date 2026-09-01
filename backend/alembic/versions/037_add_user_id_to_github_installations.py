"""Add user_id to github_installations for per-user token resolution

Revision ID: 037_add_user_id_to_github_installations
Revises: 036_add_phase17_security_incident_workflow
Create Date: 2026-09-01 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '037_add_user_id_to_github_installations'
down_revision = '036_add_phase17_security_incident_workflow'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    is_postgres = conn.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.String(36)

    # Add user_id column to github_installations
    op.add_column('github_installations', sa.Column('user_id', uuid_type, sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True))


def downgrade():
    op.drop_column('github_installations', 'user_id')
