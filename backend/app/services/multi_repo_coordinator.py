"""Multi-Repository Investigation Coordinator Service for Sentinel (Phase 14).

Implements:
1. Parent-child investigation fan-out per affected repository.
2. Unique child investigation enforcement (no duplicates per (parent_id, repo_id)).
3. Strict Git base commit SHA validation before entering remediation.
4. Cross-repository incident correlation synthesis.
"""

import logging
import re
import uuid
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.incident import (
    Incident,
    Investigation,
    InvestigationStatus,
    Repository,
    RepositoryRole,
    User,
)
from app.schemas.multi_repo import (
    ChildInvestigationOut,
    CandidateRepositoryOut,
)
from app.services.multi_repo_resolver import resolve_candidate_repositories

logger = logging.getLogger("sentinel.multi_repo_coordinator")

GIT_SHA_REGEX = re.compile(r"^[0-9a-f]{40}$")
ZERO_SHA = "0" * 40


def fan_out_child_investigations(
    db: Session,
    incident_id: UUID,
    organization_id: UUID,
    actor: Optional[User] = None,
    candidate_repo_ids: Optional[List[str]] = None,
    idempotency_key: Optional[str] = None,
) -> Tuple[Investigation, List[Investigation]]:
    """
    Idempotently spawns or retrieves child investigations for all candidate repositories of an incident.
    Enforces parent-child hierarchy and unique constraint (parent_investigation_id, repository_id).
    """
    # 1. Tenant boundary check on incident
    incident = db.query(Incident).filter(
        Incident.id == incident_id,
        Incident.organization_id == organization_id,
    ).first()

    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found in organization {organization_id}",
        )

    # 2. Get or create parent investigation
    parent_inv = db.query(Investigation).filter(
        Investigation.incident_id == incident_id,
        Investigation.organization_id == organization_id,
        Investigation.parent_investigation_id == None,
        Investigation.is_parent == True,
    ).first()

    if not parent_inv:
        # Check if there's any root investigation for this incident
        parent_inv = db.query(Investigation).filter(
            Investigation.incident_id == incident_id,
            Investigation.organization_id == organization_id,
            Investigation.parent_investigation_id == None,
        ).first()

    if not parent_inv:
        parent_inv = Investigation(
            id=uuid.uuid4(),
            organization_id=organization_id,
            incident_id=incident_id,
            workflow_type="production_incident",
            status=InvestigationStatus.RUNNING,
            is_parent=True,

            current_step="Multi-Repository Fan-Out Coordination",
            started_by_user_id=actor.id if actor else None,
            started_at=datetime.now(timezone.utc),
            idempotency_key=idempotency_key,
        )
        db.add(parent_inv)
        db.commit()
        db.refresh(parent_inv)
    else:
        if not parent_inv.is_parent:
            parent_inv.is_parent = True
            db.commit()
            db.refresh(parent_inv)

    # 3. Resolve candidate repositories
    candidates = resolve_candidate_repositories(
        db=db,
        incident_id=incident_id,
        organization_id=organization_id,
        threshold=0.30,
    )

    if candidate_repo_ids:
        # Filter to requested candidates
        cand_set = set(candidate_repo_ids)
        candidates = [c for c in candidates if c.repository_id in cand_set]

    if not candidates:
        logger.warning(f"No candidate repositories resolved for incident {incident_id}")
        return parent_inv, []

    child_investigations: List[Investigation] = []

    for candidate in candidates:
        try:
            repo_uuid = UUID(candidate.repository_id)
        except (ValueError, TypeError):
            continue

        # Check for existing child investigation for this (parent_id, repo_id)
        existing_child = db.query(Investigation).filter(
            Investigation.parent_investigation_id == parent_inv.id,
            Investigation.repository_id == repo_uuid,
        ).first()

        if existing_child:
            # Update role or base SHA if discovered
            if not existing_child.repository_role:
                existing_child.repository_role = candidate.role
            if candidate.base_commit_sha and not existing_child.base_commit_sha:
                existing_child.base_commit_sha = candidate.base_commit_sha
            db.commit()
            db.refresh(existing_child)
            child_investigations.append(existing_child)
            continue

        # Create new child investigation
        child_inv = Investigation(
            id=uuid.uuid4(),
            organization_id=organization_id,
            incident_id=incident_id,
            parent_investigation_id=parent_inv.id,
            repository_id=repo_uuid,
            repository_role=candidate.role,
            base_commit_sha=candidate.base_commit_sha,
            workflow_type="repository_task" if candidate.role != "primary_defect" else "bug",
            status=InvestigationStatus.CREATED,
            is_parent=False,
            current_step=f"Initialized child investigation for {candidate.name} ({candidate.role})",
            started_by_user_id=actor.id if actor else None,
            started_at=datetime.now(timezone.utc),
            idempotency_key=f"{parent_inv.id}:{candidate.repository_id}",
        )
        db.add(child_inv)
        db.commit()
        db.refresh(child_inv)
        child_investigations.append(child_inv)

    return parent_inv, child_investigations


def validate_child_base_sha_for_remediation(child_investigation: Investigation) -> str:
    """
    Enforces that a child investigation entering remediation/validation/PR has a verified 40-char SHA.
    Raises HTTPException(400) if missing or invalid.
    """
    base_sha = child_investigation.base_commit_sha
    if not base_sha or not isinstance(base_sha, str) or not GIT_SHA_REGEX.match(base_sha.strip()) or base_sha.strip() == ZERO_SHA:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Child investigation {child_investigation.id} cannot enter remediation without a verified 40-character hexadecimal Git base commit SHA. Current: '{base_sha}'",
        )
    return base_sha.strip()
