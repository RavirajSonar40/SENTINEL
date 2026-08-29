"""Add Phase 3 catalog: user_organization_memberships, teams, team_members, regions, service_repositories, service_dependencies, service_ownerships, service_deployment_configs, repositories.organization_id, services.tier.

Revision ID: 023_add_phase3_catalog
Revises: 022_add_phase2_work_items
Create Date: 2026-08-28 04:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

revision = "023_add_phase3_catalog"
down_revision = "022_add_phase2_work_items"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    dialect = conn.dialect.name
    uuid_type = postgresql.UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    # 1. user_organization_memberships
    if "user_organization_memberships" not in tables:
        op.create_table(
            "user_organization_memberships",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column(
                "role",
                sa.Enum("OWNER", "ADMIN", "MEMBER", "VIEWER", name="membershiprole"),
                default="MEMBER",
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "organization_id", name="uq_user_org_membership"),
        )

    # 2. teams
    if "teams" not in tables:
        op.create_table(
            "teams",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(255), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("organization_id", "slug", name="uq_team_org_slug"),
        )

    # 3. team_members
    if "team_members" not in tables:
        op.create_table(
            "team_members",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("team_id", uuid_type, sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("role", sa.String(50), default="member", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("team_id", "user_id", name="uq_team_member"),
        )

    # 4. regions
    if "regions" not in tables:
        op.create_table(
            "regions",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("cloud_provider", sa.String(50), default="aws", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("organization_id", "code", name="uq_region_org_code"),
        )

    # 5. Add services.tier if missing
    services_cols = [c["name"] for c in inspector.get_columns("services")]
    if "tier" not in services_cols:
        op.add_column("services", sa.Column("tier", sa.String(50), server_default="medium", nullable=False))
    if "slug" not in services_cols:
        op.add_column("services", sa.Column("slug", sa.String(255), nullable=True))

    # 6. Backfill and alter repositories.organization_id
    repos_cols = [c["name"] for c in inspector.get_columns("repositories")]
    if "organization_id" not in repos_cols:
        op.add_column(
            "repositories",
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
        )
        op.create_index("ix_repositories_organization_id", "repositories", ["organization_id"])

        # Deterministic backfill
        # 1. Backfill from repository owner's organization.
        conn.execute(sa.text("""
            UPDATE repositories
            SET organization_id = users.organization_id
            FROM users
            WHERE repositories.owner_id = users.id AND users.organization_id IS NOT NULL
        """))

        # 2. Check if remaining unowned repositories exist.
        remaining = conn.execute(sa.text("SELECT COUNT(*) FROM repositories WHERE organization_id IS NULL")).scalar()
        if remaining and remaining > 0:
            # Assign to an existing organization only when the legacy database
            # has exactly one organization. Multiple organizations make the
            # ownership ambiguous and must fail rather than leak data across tenants.
            organizations = conn.execute(sa.text("SELECT id FROM organizations ORDER BY id")).fetchall()
            if len(organizations) == 1:
                conn.execute(
                    sa.text("UPDATE repositories SET organization_id = :org_id WHERE organization_id IS NULL"),
                    {"org_id": organizations[0][0]},
                )
            else:
                raise RuntimeError(
                    "Cannot safely backfill repositories.organization_id: "
                    f"{remaining} repositories remain unowned across {len(organizations)} organizations. "
                    "Assign repository ownership before rerunning migration 023."
                )

        # If dialect supports not null alter
        if dialect == "postgresql":
            op.alter_column("repositories", "organization_id", nullable=False)

    # 7. service_repositories
    if "service_repositories" not in tables:
        op.create_table(
            "service_repositories",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("service_id", uuid_type, sa.ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("repository_id", uuid_type, sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column(
                "role",
                sa.Enum("application", "configuration", "infrastructure", "dependency", name="servicerepositoryrole"),
                default="application",
                nullable=False,
            ),
            sa.Column("is_primary", sa.Boolean, default=False, nullable=False),
            sa.Column("confidence", sa.Float, default=1.0, nullable=False),
            sa.Column("source", sa.String(100), default="manual", nullable=False),
            sa.Column("selection_reason", sa.String(500), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("service_id", "repository_id", "role", name="uq_service_repo_role"),
        )
        if dialect == "postgresql":
            op.create_index("uq_service_primary_repo", "service_repositories", ["service_id"], unique=True, postgresql_where=sa.text("is_primary = true"))

    # 8. service_dependencies
    if "service_dependencies" not in tables:
        op.create_table(
            "service_dependencies",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("service_id", uuid_type, sa.ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("depends_on_service_id", uuid_type, sa.ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column(
                "dependency_type",
                sa.Enum("synchronous", "asynchronous", "database", "cache", "external", name="servicedependencytype"),
                default="synchronous",
                nullable=False,
            ),
            sa.Column(
                "criticality",
                sa.Enum("hard", "soft", name="servicecriticality"),
                default="hard",
                nullable=False,
            ),
            sa.Column("description", sa.String(500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("service_id", "depends_on_service_id", name="uq_service_dependency"),
        )

    # 9. service_ownerships
    if "service_ownerships" not in tables:
        op.create_table(
            "service_ownerships",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("service_id", uuid_type, sa.ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("team_id", uuid_type, sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True),
            sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True),
            sa.Column(
                "ownership_type",
                sa.Enum("primary_owner", "secondary_owner", "oncall", name="ownershiptype"),
                default="primary_owner",
                nullable=False,
            ),
            sa.Column("escalation_policy", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.CheckConstraint(
                "(team_id IS NOT NULL AND user_id IS NULL) OR (team_id IS NULL AND user_id IS NOT NULL)",
                name="ck_service_ownership_exclusive_owner",
            ),
        )
        if dialect == "postgresql":
            op.create_index("uq_service_primary_owner", "service_ownerships", ["service_id"], unique=True, postgresql_where=sa.text("ownership_type = 'primary_owner'"))

    # 10. service_deployment_configs
    if "service_deployment_configs" not in tables:
        op.create_table(
            "service_deployment_configs",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("service_id", uuid_type, sa.ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("environment_id", uuid_type, sa.ForeignKey("environments.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("region_id", uuid_type, sa.ForeignKey("regions.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("health_check_url", sa.String(500), nullable=True),
            sa.Column("health_check_interval_seconds", sa.Integer, default=30, nullable=False),
            sa.Column("observability_identifiers", sa.JSON, nullable=True),
            sa.Column("current_commit_sha", sa.String(40), nullable=True),
            sa.Column("current_version", sa.String(100), nullable=True),
            sa.Column("is_active", sa.Boolean, default=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
            sa.UniqueConstraint("service_id", "environment_id", "region_id", name="uq_service_env_region"),
        )
        if dialect == "postgresql":
            op.create_index("uq_service_env_global", "service_deployment_configs", ["service_id", "environment_id"], unique=True, postgresql_where=sa.text("region_id IS NULL"))


def downgrade():
    op.drop_table("service_deployment_configs")
    op.drop_table("service_ownerships")
    op.drop_table("service_dependencies")
    op.drop_table("service_repositories")
    op.drop_column("repositories", "organization_id")
    op.drop_column("services", "tier")
    op.drop_column("services", "slug")
    op.drop_table("regions")
    op.drop_table("team_members")
    op.drop_table("teams")
    op.drop_table("user_organization_memberships")
