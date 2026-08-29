"""
Role-Based Access Control and Multi-Tenant Scoping Engine for Sentinel.
"""

from typing import Tuple, Optional, Any
from uuid import UUID
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.incident import User, Organization, MembershipRole, UserOrganizationMembership

ROLE_HIERARCHY = {
    MembershipRole.VIEWER: 1,
    MembershipRole.MEMBER: 2,
    MembershipRole.OPERATOR: 3,
    MembershipRole.SECURITY_OFFICER: 4,
    MembershipRole.ADMIN: 4,
    MembershipRole.OWNER: 5,
}


def get_active_membership(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Tuple[Organization, UserOrganizationMembership]:
    """
    Resolve active organization and verified membership for the authenticated user.
    Never trusts client-provided organization IDs.
    """
    membership = None

    # 1. If active organization context is set on user, find that specific membership
    if current_user.organization_id:
        membership = (
            db.query(UserOrganizationMembership)
            .filter(
                UserOrganizationMembership.user_id == current_user.id,
                UserOrganizationMembership.organization_id == current_user.organization_id,
            )
            .first()
        )

    # 2. If no active context or membership not found, find first valid membership
    if not membership:
        membership = (
            db.query(UserOrganizationMembership)
            .filter(UserOrganizationMembership.user_id == current_user.id)
            .first()
        )
        if membership:
            current_user.organization_id = membership.organization_id
            db.commit()

    # 3. If user has no memberships at all
    if not membership:
        # Check if legacy organization relationship exists
        if current_user.organization_id:
            org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
            if org:
                # Bootstrap membership for legacy user
                initial_role = MembershipRole.ADMIN if current_user.role == "admin" else MembershipRole.MEMBER
                membership = UserOrganizationMembership(
                    user_id=current_user.id,
                    organization_id=org.id,
                    role=initial_role,
                )
                db.add(membership)
                db.commit()
                db.refresh(membership)
                return org, membership

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not belong to any organization. Please create or join an organization.",
        )

    org = db.query(Organization).filter(Organization.id == membership.organization_id).first()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active organization not found.")

    return org, membership


def require_role(min_role: MembershipRole):
    """Factory dependency enforcing minimum role in active organization."""
    def dependency(
        context: Tuple[Organization, UserOrganizationMembership] = Depends(get_active_membership),
    ) -> Tuple[Organization, UserOrganizationMembership]:
        org, membership = context
        user_level = ROLE_HIERARCHY.get(membership.role, 0)
        required_level = ROLE_HIERARCHY.get(min_role, 99)
        if user_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires '{min_role.value}' role or higher. Your role is '{membership.role.value}'.",
            )
        return org, membership

    return dependency


# Standard Role Dependencies
require_viewer = require_role(MembershipRole.VIEWER)
require_member = require_role(MembershipRole.MEMBER)
require_operator = require_role(MembershipRole.OPERATOR)
require_admin = require_role(MembershipRole.ADMIN)
require_owner = require_role(MembershipRole.OWNER)


def require_security_officer(
    context: Tuple[Organization, UserOrganizationMembership] = Depends(get_active_membership),
) -> Tuple[Organization, UserOrganizationMembership]:
    """Dependency requiring SECURITY_OFFICER, ADMIN, or OWNER role in active organization."""
    org, membership = context
    allowed_roles = {
        MembershipRole.SECURITY_OFFICER,
        MembershipRole.SECURITY_OFFICER.value,
        MembershipRole.ADMIN,
        MembershipRole.ADMIN.value,
        MembershipRole.OWNER,
        MembershipRole.OWNER.value,
    }
    role_val = membership.role.value if hasattr(membership.role, "value") else str(membership.role)
    if membership.role not in allowed_roles and role_val not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Operation requires 'security_officer', 'admin', or 'owner' role. Your role is '{role_val}'.",
        )
    return org, membership



def validate_org_entity(entity: Optional[Any], organization_id: Any, entity_name: str = "Resource") -> None:
    """
    Ensure the queried entity exists and belongs to the caller's active organization.
    Returns 404 instead of 403 on tenant mismatch to avoid leaking entity existence.
    """
    if entity is None or getattr(entity, "organization_id", None) != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{entity_name} not found.",
        )
