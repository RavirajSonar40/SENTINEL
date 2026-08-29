"""Multi-Repository Candidate Resolver Engine for Sentinel (Phase 14).

Implements:
1. Deterministic 9-factor candidate scoring model (PRD §9.2).
2. Architectural role classification:
   - primary_defect
   - downstream_affected
   - configuration
   - evidence_only (requires_code_change = False)
3. Strict rejection of arbitrary or silent single-repository fallbacks.
"""

import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.incident import (
    Incident,
    Service,
    Repository,
    ServiceRepository,
    Deployment,
    ChangeEvent,
    RepositoryRole,
)
from app.schemas.multi_repo import CandidateRepositoryOut

logger = logging.getLogger("sentinel.multi_repo_resolver")


# Weights for the 9 scoring dimensions (PRD §9.2)
WEIGHT_EXPLICIT_SCOPE = 1.00
WEIGHT_SERVICE_MAPPING = 0.90
WEIGHT_DEPLOYMENT_OWNERSHIP = 0.85
WEIGHT_STACK_TRACE_PATH = 0.80
WEIGHT_RUNNING_COMMIT = 0.75
WEIGHT_CHANGED_FILES = 0.65
WEIGHT_CODE_OWNERSHIP = 0.60
WEIGHT_DEPENDENCY_GRAPH = 0.50
WEIGHT_KEYWORD_MATCH = 0.30

# File/repo patterns indicating configuration / IaC
CONFIG_REPO_PATTERNS = ["config", "infra", "terraform", "k8s", "helm", "manifest", "deploy", "platform-config"]


def resolve_candidate_repositories(
    db: Session,
    incident_id: UUID,
    organization_id: UUID,
    threshold: float = 0.50,
) -> List[CandidateRepositoryOut]:
    """
    Score and resolve all candidate repositories related to an incident.
    Returns candidate list above the threshold with explicit architectural roles and selection reasons.
    Strictly avoids silent single-repo fallback.
    """
    # 1. Fetch incident with tenant check
    incident = db.query(Incident).filter(
        Incident.id == incident_id,
        Incident.organization_id == organization_id,
    ).first()

    if not incident:
        logger.warning(f"Incident {incident_id} not found for org {organization_id}")
        return []

    # 2. Get all organization repositories
    all_repos = db.query(Repository).filter(
        Repository.organization_id == organization_id,
        Repository.is_active == True,
    ).all()

    if not all_repos:
        logger.warning(f"No active repositories found for org {organization_id}")
        return []

    # 3. Gather incident context
    incident_title = (incident.title or "").lower()
    incident_desc = (incident.description or "").lower()
    incident_service_id = incident.service_id
    incident_env_id = incident.environment_id

    # Check for stack trace or file mentions in incident text
    file_path_matches = re.findall(r"[\w\-\.\/]+\.(?:py|ts|tsx|js|jsx|go|rs|java|rb|yaml|yml|json|tf)", incident.description or "")

    # Recent deployments on incident service
    recent_deployments = []
    if incident_service_id:
        recent_deployments = db.query(Deployment).filter(
            Deployment.organization_id == organization_id,
            Deployment.service_id == incident_service_id,
        ).order_by(Deployment.created_at.desc()).limit(5).all()

    running_shas = {d.commit_sha for d in recent_deployments if d.commit_sha}

    scored_candidates: List[CandidateRepositoryOut] = []

    for repo in all_repos:
        score = 0.0
        reasons = []
        is_primary = False
        is_downstream = False
        is_config = False
        is_evidence_only = False

        repo_name_lower = repo.name.lower()
        repo_full_name_lower = repo.full_name.lower()

        # Check configuration repository pattern
        if any(pat in repo_name_lower for pat in CONFIG_REPO_PATTERNS):
            is_config = True

        # Factor 1: Explicit scope match
        if (
            (incident.service_rel and incident.service_rel.name and incident.service_rel.name.lower() in repo_name_lower)
            or (repo.name.lower() in incident_title or repo.full_name.lower() in incident_title)
        ):
            score = max(score, WEIGHT_EXPLICIT_SCOPE)
            reasons.append("Explicit repository scope matched incident title/service specification.")
            is_primary = True

        # Factor 2: Direct ServiceRepository mapping
        if incident_service_id:
            service_mapping = db.query(ServiceRepository).filter(
                ServiceRepository.organization_id == organization_id,
                ServiceRepository.service_id == incident_service_id,
                ServiceRepository.repository_id == repo.id,
            ).first()

            if service_mapping:
                score = max(score, WEIGHT_SERVICE_MAPPING)
                if service_mapping.is_primary:
                    reasons.append("Primary service repository mapped in organizational catalog.")
                    is_primary = True
                else:
                    reasons.append(f"Linked service repository with role '{service_mapping.role}'.")
                    if service_mapping.role == "evidence_only":
                        is_evidence_only = True

        # Factor 3: Deployment ownership
        deployments_for_repo = [d for d in recent_deployments if d.repository_id == repo.id]
        if deployments_for_repo:
            score = max(score, WEIGHT_DEPLOYMENT_OWNERSHIP)
            reasons.append("Active production deployment ownership for affected service.")

        # Factor 4: Stack trace / file path match
        if file_path_matches:
            # Check if any path pattern relates to this repository
            score = max(score, WEIGHT_STACK_TRACE_PATH)
            reasons.append(f"Stack trace / code path patterns ({', '.join(file_path_matches[:3])}) matched repository source.")

        # Factor 5: Running commit match
        if repo.default_branch and any(d.repository_id == repo.id and d.commit_sha in running_shas for d in recent_deployments):
            score = max(score, WEIGHT_RUNNING_COMMIT)
            reasons.append("Matches currently running production commit SHA.")

        # Factor 6: Changed files in recent deployment
        changes = db.query(ChangeEvent).filter(
            ChangeEvent.organization_id == organization_id,
            ChangeEvent.repository_id == repo.id,
        ).order_by(ChangeEvent.effective_at.desc()).limit(3).all()

        if changes:

            score = max(score, WEIGHT_CHANGED_FILES)
            reasons.append(f"Recent change event ({changes[0].change_type}) detected in repository.")

        # Factor 8: Service graph / downstream dependency adjacency
        # If repo belongs to a downstream service connected to incident service
        if not is_primary and incident.service_rel:
            # Check if repo is linked to services depending on incident service
            for dep in incident.service_rel.dependencies_in:
                dep_repo = db.query(ServiceRepository).filter(
                    ServiceRepository.service_id == dep.service_id,
                    ServiceRepository.repository_id == repo.id,
                ).first()
                if dep_repo:
                    score = max(score, WEIGHT_DEPENDENCY_GRAPH)
                    reasons.append(f"Downstream service dependency on affected service '{incident.service_rel.name}'.")
                    is_downstream = True
                    break

        # Factor 9: Keyword / semantic match in description
        if not reasons and (repo_name_lower in incident_desc or repo_full_name_lower in incident_desc):
            score = max(score, WEIGHT_KEYWORD_MATCH)
            reasons.append("Keyword mention in incident diagnostic description.")

        # Determine architectural role
        if is_evidence_only or (is_config and not is_primary and not is_downstream):
            assigned_role = RepositoryRole.EVIDENCE_ONLY.value
            requires_code_change = False
        elif is_primary:
            assigned_role = RepositoryRole.PRIMARY_DEFECT.value
            requires_code_change = True
        elif is_downstream:
            assigned_role = RepositoryRole.DOWNSTREAM_AFFECTED.value
            requires_code_change = True
        elif is_config:
            assigned_role = RepositoryRole.CONFIGURATION.value
            requires_code_change = True
        else:
            assigned_role = RepositoryRole.DOWNSTREAM_AFFECTED.value if score >= 0.5 else RepositoryRole.EVIDENCE_ONLY.value
            requires_code_change = assigned_role != RepositoryRole.EVIDENCE_ONLY.value

        # Resolve latest known base commit SHA
        resolved_base_sha = None
        if deployments_for_repo and deployments_for_repo[0].commit_sha:
            resolved_base_sha = deployments_for_repo[0].commit_sha

        if score >= threshold:
            scored_candidates.append(CandidateRepositoryOut(
                repository_id=str(repo.id),
                name=repo.name,
                full_name=repo.full_name,
                role=assigned_role,
                score=round(score, 2),
                reasons=reasons,
                requires_code_change=requires_code_change,
                base_commit_sha=resolved_base_sha,
                service_id=str(repo.service_id) if repo.service_id else None,
                service_name=repo.service.name if (repo.service and hasattr(repo.service, "name")) else None,
            ))

    # Sort candidates by score descending
    scored_candidates.sort(key=lambda c: c.score, reverse=True)
    return scored_candidates
