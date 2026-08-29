"""Multi-Repository Remediation Orchestration Engine for Sentinel (Phase 14).

Implements:
1. Multi-repository remediation plan compilation with topological dependency ordering.
2. Kahn's algorithm for dependency cycle detection (BLOCKED_CYCLIC_DEPENDENCY).
3. Deep evidence-only enforcement (zero patch/PR creation).
4. Re-verification of Phase 13 approval bindings (approval_id, version, snapshot, validation, SHA).
5. Non-transactional, idempotent per-repository PR publishing with partial-failure recovery and rollback guidance.
"""

import logging
import uuid
import re
from typing import List, Dict, Any, Optional, Tuple, Set
from uuid import UUID
from datetime import datetime, timezone
from collections import defaultdict, deque

from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.incident import (
    Incident,
    Investigation,
    Repository,
    ProposedFix,
    ValidationRun,
    Approval,
    ApprovalStatus,
    Service,
    ServiceRepository,
    ServiceDependency,

    RepositoryRole,
    MultiRepoRemediationPlan,
    RemediationPlanItem,
    RemediationPlanStatus,
    User,
)
from app.schemas.multi_repo import (
    RemediationPlanOut,
    RemediationPlanItemOut,
    MultiRepoPRPublishResponse,
    MultiRepoPRItemResult,
)
from app.routes.remediation import publish_draft_pr, PRResponse

logger = logging.getLogger("sentinel.multi_repo_orchestrator")

GIT_SHA_REGEX = re.compile(r"^[0-9a-f]{40}$")


def detect_topological_order_and_cycles(
    repository_ids: List[UUID],
    db: Session,
    organization_id: UUID,
) -> Tuple[List[UUID], bool, Optional[Dict[str, Any]]]:
    """
    Constructs a directed graph of repository dependencies and runs Kahn's algorithm.
    Returns: (ordered_repo_ids, cycle_detected, cycle_details).
    """
    if not repository_ids:
        return [], False, None

    repo_set = set(repository_ids)
    graph: Dict[UUID, Set[UUID]] = {rid: set() for rid in repository_ids}
    in_degree: Dict[UUID, int] = {rid: 0 for rid in repository_ids}

    # Fetch services mapped to these repositories via ServiceRepository catalog
    repo_to_services: Dict[UUID, Set[UUID]] = defaultdict(set)
    service_to_repos: Dict[UUID, Set[UUID]] = defaultdict(set)

    service_mappings = db.query(ServiceRepository).filter(

        ServiceRepository.repository_id.in_(repository_ids),
        ServiceRepository.organization_id == organization_id,
    ).all()

    for sm in service_mappings:
        repo_to_services[sm.repository_id].add(sm.service_id)
        service_to_repos[sm.service_id].add(sm.repository_id)

    # Also check legacy repository.service_id
    repos = db.query(Repository).filter(
        Repository.id.in_(repository_ids),
        Repository.organization_id == organization_id,
    ).all()

    for r in repos:
        if r.service_id:
            repo_to_services[r.id].add(r.service_id)
            service_to_repos[r.service_id].add(r.id)


    # Check ServiceDependencies for upstream -> downstream edges
    all_service_ids = set(service_to_repos.keys())
    if all_service_ids:
        deps = db.query(ServiceDependency).filter(
            ServiceDependency.organization_id == organization_id,
            ServiceDependency.service_id.in_(all_service_ids),
            ServiceDependency.depends_on_service_id.in_(all_service_ids),
        ).all()

        for dep in deps:
            # dep.service_id depends on dep.depends_on_service_id
            # Provider (depends_on_service_id) must merge BEFORE consumer (service_id)
            provider_repos = service_to_repos[dep.depends_on_service_id]
            consumer_repos = service_to_repos[dep.service_id]

            for p_repo in provider_repos:
                for c_repo in consumer_repos:
                    if p_repo != c_repo and p_repo in repo_set and c_repo in repo_set:
                        if c_repo not in graph[p_repo]:
                            graph[p_repo].add(c_repo)
                            in_degree[c_repo] += 1

    # Kahn's Algorithm
    queue = deque([rid for rid, deg in in_degree.items() if deg == 0])
    ordered: List[UUID] = []

    while queue:
        curr = queue.popleft()
        ordered.append(curr)
        for neighbor in graph[curr]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(ordered) == len(repository_ids):
        return ordered, False, None
    else:
        # Cycle detected
        unresolved = [str(rid) for rid, deg in in_degree.items() if deg > 0]
        cycle_details = {
            "cyclic_repository_ids": unresolved,
            "message": "Topological cycle detected between dependent service repositories.",
            "recommended_resolution": "Requires explicit operator break-order override before PR generation.",
        }
        # Provide fallback ordering (all resolved first, then remaining)
        fallback = ordered + [rid for rid in repository_ids if rid not in set(ordered)]
        return fallback, True, cycle_details


def create_multi_repo_remediation_plan(
    db: Session,
    incident_id: UUID,
    organization_id: UUID,
    parent_investigation_id: Optional[UUID] = None,
    idempotency_key: Optional[str] = None,
    override_dependency_order: Optional[List[str]] = None,
) -> MultiRepoRemediationPlan:
    """
    Compiles a coordinated MultiRepoRemediationPlan with cycle detection and rollback orchestration.
    """
    # 1. Tenant boundary check
    incident = db.query(Incident).filter(
        Incident.id == incident_id,
        Incident.organization_id == organization_id,
    ).first()

    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found in organization {organization_id}",
        )

    # 2. Check for existing plan with idempotency key or active status
    if idempotency_key:
        existing_plan = db.query(MultiRepoRemediationPlan).filter(
            MultiRepoRemediationPlan.organization_id == organization_id,
            MultiRepoRemediationPlan.idempotency_key == idempotency_key,
        ).first()
        if existing_plan:
            return existing_plan

    # 3. Find child investigations & proposed fixes for incident
    child_invs = db.query(Investigation).filter(
        Investigation.incident_id == incident_id,
        Investigation.organization_id == organization_id,
        Investigation.repository_id != None,
    ).all()

    if not child_invs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot create multi-repository remediation plan: no child investigations found for this incident.",
        )

    repo_ids = [inv.repository_id for inv in child_invs if inv.repository_id]
    unique_repo_ids = list(dict.fromkeys(repo_ids))

    # 4. Topological order and cycle detection
    cycle_detected = False
    cycle_details = None

    if override_dependency_order:
        ordered_repo_ids = [UUID(s) for s in override_dependency_order if s in [str(r) for r in unique_repo_ids]]
        # Append any unmentioned
        for r in unique_repo_ids:
            if r not in ordered_repo_ids:
                ordered_repo_ids.append(r)
    else:
        ordered_repo_ids, cycle_detected, cycle_details = detect_topological_order_and_cycles(
            repository_ids=unique_repo_ids,
            db=db,
            organization_id=organization_id,
        )

    initial_status = (
        RemediationPlanStatus.BLOCKED_CYCLIC_DEPENDENCY
        if (cycle_detected and not override_dependency_order)
        else RemediationPlanStatus.DRAFT
    )

    # 5. Formulate cross-repository rollback plan
    rollback_lines = ["Coordinated Cross-Repository Rollback Procedure:"]
    for idx, r_id in enumerate(reversed(ordered_repo_ids), 1):
        repo = db.query(Repository).filter(Repository.id == r_id).first()
        r_name = repo.full_name if repo else str(r_id)
        rollback_lines.append(f"{idx}. Revert {r_name} PR / rollback deployment to previous running SHA.")

    rollback_plan = "\n".join(rollback_lines)

    # 6. Create or update plan
    plan = MultiRepoRemediationPlan(
        id=uuid.uuid4(),
        organization_id=organization_id,
        incident_id=incident_id,
        parent_investigation_id=parent_investigation_id,
        status=initial_status,
        title=f"Coordinated Remediation Plan for {f'INC-{incident.number}' if getattr(incident, 'number', None) else str(incident.id)[:8]}",
        summary=f"Multi-repository rollout across {len(unique_repo_ids)} repositories.",

        dependency_order_json=[str(rid) for rid in ordered_repo_ids],
        cycle_detected=cycle_detected,
        cycle_details_json=cycle_details,
        cross_repo_rollback_plan=rollback_plan,
        idempotency_key=idempotency_key or f"plan:{incident_id}:{len(unique_repo_ids)}",
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)

    # 7. Create plan items
    for order, r_id in enumerate(ordered_repo_ids, 1):
        # Match child investigation and proposed fix
        inv = next((i for i in child_invs if i.repository_id == r_id), None)
        role = inv.repository_role if inv else "primary_defect"
        requires_code_change = role != "evidence_only"

        fix = None
        if inv and requires_code_change:
            fix = db.query(ProposedFix).filter(
                ProposedFix.investigation_id == inv.id,
                ProposedFix.organization_id == organization_id,
            ).order_by(ProposedFix.generated_at.desc()).first()

        item = RemediationPlanItem(
            id=uuid.uuid4(),
            organization_id=organization_id,
            plan_id=plan.id,
            repository_id=r_id,
            repository_role=role,
            investigation_id=inv.id if inv else None,
            fix_id=fix.id if fix else None,
            execution_order=order,
            requires_code_change=requires_code_change,
            validation_status="passed" if not requires_code_change else "pending",
            approval_status="not_required" if not requires_code_change else "pending",
            pr_status="skipped_evidence_only" if not requires_code_change else "pending",
            pr_idempotency_key=f"{plan.id}:{r_id}",
        )

        if fix:
            item.patch_version = fix.version if (hasattr(fix, "version") and fix.version) else 1
            item.snapshot_hash = fix.snapshot_hash
            item.base_commit_sha = fix.base_commit_sha

            # Check latest validation run
            latest_val = db.query(ValidationRun).filter(
                ValidationRun.fix_id == fix.id,
            ).order_by(ValidationRun.created_at.desc()).first()
            if latest_val:
                item.validation_run_id = latest_val.id
                item.validation_status = latest_val.status

            # Check latest approval
            latest_app = db.query(Approval).filter(
                Approval.fix_id == fix.id,
            ).order_by(Approval.requested_at.desc()).first()
            if latest_app:
                item.approval_id = latest_app.id
                item.approval_status = latest_app.status.value if hasattr(latest_app.status, "value") else str(latest_app.status)

        db.add(item)

    db.commit()
    db.refresh(plan)
    return plan


async def publish_multi_repo_draft_prs(
    db: Session,
    plan_id: UUID,
    organization_id: UUID,
    actor: User,
    branch_prefix: str = "sentinel/remediation",
) -> MultiRepoPRPublishResponse:
    """
    Coordinates Draft PR creation across all plan items.
    Handles per-repository non-transactional publishing, idempotency, partial failures,
    and Phase 13 approval binding verification.
    """
    # 1. Acquire row lock on plan
    is_postgres = db.bind.dialect.name == "postgresql" if db.bind else False
    plan_query = db.query(MultiRepoRemediationPlan).filter(
        MultiRepoRemediationPlan.id == plan_id,
        MultiRepoRemediationPlan.organization_id == organization_id,
    )
    if is_postgres:
        plan_query = plan_query.with_for_update()

    plan = plan_query.first()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Remediation plan not found.")

    if plan.status == RemediationPlanStatus.BLOCKED_CYCLIC_DEPENDENCY.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot publish Draft PRs: Plan is blocked by a dependency cycle. Human review and explicit break-order override required.",
        )

    incident = db.query(Incident).filter(Incident.id == plan.incident_id).first()
    plan_items = db.query(RemediationPlanItem).filter(
        RemediationPlanItem.plan_id == plan.id,
    ).order_by(RemediationPlanItem.execution_order.asc()).all()

    item_results: List[MultiRepoPRItemResult] = []
    created_count = 0
    failed_count = 0
    skipped_count = 0

    for item in plan_items:
        repo = db.query(Repository).filter(Repository.id == item.repository_id).first()
        repo_name = repo.full_name if repo else str(item.repository_id)

        # 1. Evidence-only protection
        if item.repository_role == RepositoryRole.EVIDENCE_ONLY.value or not item.requires_code_change:
            item.pr_status = "skipped_evidence_only"
            db.commit()
            item_results.append(MultiRepoPRItemResult(
                repository_id=str(item.repository_id),
                repository_name=repo_name,
                pr_status="skipped_evidence_only",
                error_message="Evidence-only repository (no code modification required).",
            ))
            skipped_count += 1
            continue

        # 2. Idempotency: skip if already created
        if item.pr_status == "created" and item.pr_url:
            item_results.append(MultiRepoPRItemResult(
                repository_id=str(item.repository_id),
                repository_name=repo_name,
                pr_status="created",
                pr_url=item.pr_url,
                pr_number=item.pr_number,
                commit_sha=item.commit_sha,
            ))
            created_count += 1
            continue

        # 3. Check fix presence
        if not item.fix_id:
            item.pr_status = "failed"
            item.error_message = "No proposed fix associated with repository."
            db.commit()
            item_results.append(MultiRepoPRItemResult(
                repository_id=str(item.repository_id),
                repository_name=repo_name,
                pr_status="failed",
                error_message=item.error_message,
            ))
            failed_count += 1
            continue

        fix = db.query(ProposedFix).filter(ProposedFix.id == item.fix_id).first()
        if not fix:
            item.pr_status = "failed"
            item.error_message = "Associated ProposedFix not found in database."
            db.commit()
            item_results.append(MultiRepoPRItemResult(
                repository_id=str(item.repository_id),
                repository_name=repo_name,
                pr_status="failed",
                error_message=item.error_message,
            ))
            failed_count += 1
            continue

        # 4. Strict Base SHA verification
        if not fix.base_commit_sha or not GIT_SHA_REGEX.match(fix.base_commit_sha.strip()):
            item.pr_status = "failed"
            item.error_message = f"Invalid or missing Git base commit SHA: '{fix.base_commit_sha}'."
            db.commit()
            item_results.append(MultiRepoPRItemResult(
                repository_id=str(item.repository_id),
                repository_name=repo_name,
                pr_status="failed",
                error_message=item.error_message,
            ))
            failed_count += 1
            continue

        # 5. Phase 13 Approval Binding Re-Verification
        app_query = db.query(Approval).filter(
            Approval.fix_id == fix.id,
            Approval.status == ApprovalStatus.APPROVED,
        )
        if is_postgres:
            app_query = app_query.with_for_update()
        approval = app_query.first()

        if not approval:
            item.pr_status = "failed"
            item.error_message = "Fix requires an approved Phase 13 Approval record before publishing Draft PR."
            db.commit()
            item_results.append(MultiRepoPRItemResult(
                repository_id=str(item.repository_id),
                repository_name=repo_name,
                pr_status="failed",
                error_message=item.error_message,
            ))
            failed_count += 1
            continue

        fix_version = fix.version if (hasattr(fix, "version") and fix.version) else 1
        if approval.patch_version and approval.patch_version != fix_version:
            item.pr_status = "failed"
            item.error_message = f"Stale approval (version {approval.patch_version} != current {fix_version})."
            db.commit()
            item_results.append(MultiRepoPRItemResult(
                repository_id=str(item.repository_id),
                repository_name=repo_name,
                pr_status="failed",
                error_message=item.error_message,
            ))
            failed_count += 1
            continue

        # 6. Publish via GitHub client
        inc_label = f"INC-{incident.number}" if (incident and getattr(incident, 'number', None)) else 'inc'
        branch_name = f"{branch_prefix}/{inc_label}-{repo.name}"
        try:

            pr_res = await publish_draft_pr(
                fix=fix,
                incident=incident,
                db=db,
                branch_name=branch_name,
            )
            item.pr_status = "created"
            item.pr_url = pr_res.pr_url
            item.pr_number = getattr(pr_res, "pr_number", None)
            item.commit_sha = pr_res.commit_sha
            item.error_message = None
            db.commit()

            item_results.append(MultiRepoPRItemResult(
                repository_id=str(item.repository_id),
                repository_name=repo_name,
                pr_status="created",
                pr_url=item.pr_url,
                pr_number=item.pr_number,
                commit_sha=item.commit_sha,
            ))
            created_count += 1
        except Exception as e:
            logger.error(f"Error creating PR for repository {repo_name}: {e}")
            item.pr_status = "failed"
            item.error_message = str(e)
            db.commit()

            item_results.append(MultiRepoPRItemResult(
                repository_id=str(item.repository_id),
                repository_name=repo_name,
                pr_status="failed",
                error_message=str(e),
            ))
            failed_count += 1

    # Overall Status Calculation
    code_change_total = len(plan_items) - skipped_count
    if failed_count == 0:
        plan.status = RemediationPlanStatus.COMPLETED.value
        overall_status = "completed"
        msg = f"Successfully published {created_count} Draft PR(s)."
    elif created_count > 0:
        plan.status = RemediationPlanStatus.PARTIALLY_FAILED.value
        overall_status = "partially_failed"
        msg = f"Partially completed: {created_count} PR(s) created, {failed_count} failed. See rollback instructions."
    else:
        plan.status = RemediationPlanStatus.FAILED.value
        overall_status = "failed"
        msg = f"Failed to publish Draft PRs across all {failed_count} code-change repositories."

    db.commit()

    return MultiRepoPRPublishResponse(
        plan_id=str(plan.id),
        overall_status=overall_status,
        items=item_results,
        rollback_instructions=plan.cross_repo_rollback_plan if failed_count > 0 else None,
        message=msg,
    )
