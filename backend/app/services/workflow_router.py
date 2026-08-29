"""
Workflow Routing and State Transition Engine for Sentinel Work Items.

Dispatches work items to type-specific execution pipelines, enforces tenant and
environment scoping, and enforces state machine transitions.
"""

import uuid
import logging
from typing import Optional, Dict, Any, Tuple
from pydantic import BaseModel
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models.work_item import WorkItem, WorkType, WorkItemStatus
from app.models.incident import Incident, IncidentSeverity, IncidentStatus, IncidentSource, Service, Environment
from app.schemas.work_item import WorkTypeEnvelope
from app.services.task_queue import submit_task

logger = logging.getLogger("sentinel.workflow_router")

# Complete State Machine Transition Rules
VALID_WORK_ITEM_TRANSITIONS = {
    WorkItemStatus.CREATED: {WorkItemStatus.ROUTED, WorkItemStatus.BLOCKED, WorkItemStatus.CANCELLED},
    WorkItemStatus.ROUTED: {WorkItemStatus.IN_PROGRESS, WorkItemStatus.BLOCKED, WorkItemStatus.CANCELLED},
    WorkItemStatus.IN_PROGRESS: {WorkItemStatus.VALIDATED, WorkItemStatus.BLOCKED, WorkItemStatus.CANCELLED},
    WorkItemStatus.VALIDATED: {WorkItemStatus.DRAFT_PR_CREATED, WorkItemStatus.BLOCKED},
    WorkItemStatus.DRAFT_PR_CREATED: {WorkItemStatus.RESOLVED},
    WorkItemStatus.BLOCKED: {WorkItemStatus.ROUTED, WorkItemStatus.IN_PROGRESS, WorkItemStatus.CANCELLED},
    WorkItemStatus.RESOLVED: set(),
    WorkItemStatus.CANCELLED: set(),
}

# Client-allowed transitions (Clients cannot directly force VALIDATED, DRAFT_PR_CREATED, or RESOLVED)
CLIENT_PERMITTED_TRANSITIONS = {
    (WorkItemStatus.BLOCKED, WorkItemStatus.ROUTED),
    (WorkItemStatus.CREATED, WorkItemStatus.CANCELLED),
    (WorkItemStatus.ROUTED, WorkItemStatus.CANCELLED),
    (WorkItemStatus.IN_PROGRESS, WorkItemStatus.CANCELLED),
    (WorkItemStatus.BLOCKED, WorkItemStatus.CANCELLED),
}


class WorkflowDecision(BaseModel):
    """Result of workflow routing dispatch."""
    work_item_id: str
    status: WorkItemStatus
    workflow: str
    skip_incident_hypotheses: bool
    requires_runtime_evidence: bool
    incident_id: Optional[str] = None
    job_id: Optional[str] = None
    action_taken: str


def validate_status_transition(
    current_status: WorkItemStatus,
    new_status: WorkItemStatus,
    is_client_request: bool = True,
) -> None:
    """Validate status transition against state machine rules."""
    allowed = VALID_WORK_ITEM_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Invalid status transition from '{current_status.value}' to '{new_status.value}'.",
        )

    if is_client_request and (current_status, new_status) not in CLIENT_PERMITTED_TRANSITIONS:
        raise HTTPException(
            status_code=403,
            detail=f"Direct transition from '{current_status.value}' to '{new_status.value}' is restricted to system workflows.",
        )


def validate_cross_org_entities(
    db: Session,
    organization_id: Any,
    service_id: Optional[Any] = None,
    environment_id: Optional[Any] = None,
) -> None:
    """Verify that linked service and environment belong to the work item's organization."""
    if service_id:
        svc = db.query(Service).filter(Service.id == service_id).first()
        if not svc:
            raise HTTPException(status_code=404, detail="Referenced service not found.")
        if svc.organization_id != organization_id:
            raise HTTPException(
                status_code=400,
                detail="Service does not belong to the user's organization.",
            )

    if environment_id:
        env = db.query(Environment).filter(Environment.id == environment_id).first()
        if not env:
            raise HTTPException(status_code=404, detail="Referenced environment not found.")
        if env.organization_id != organization_id:
            raise HTTPException(
                status_code=400,
                detail="Environment does not belong to the user's organization.",
            )


def _resolve_incident_source(title: str, description: Optional[str]) -> IncidentSource:
    """Derive appropriate automated incident source from telemetry text or alerts."""
    text_lower = f"{title} {description or ''}".lower()
    if "prometheus" in text_lower or "metric" in text_lower or "cpu" in text_lower:
        return IncidentSource.PROMETHEUS
    if "sentry" in text_lower or "stacktrace" in text_lower or "exception" in text_lower:
        return IncidentSource.SENTRY
    if "webhook" in text_lower:
        return IncidentSource.WEBHOOK
    if "regression" in text_lower or "deploy" in text_lower:
        return IncidentSource.DEPLOYMENT_REGRESSION
    return IncidentSource.ALERT


async def route_work_item(
    work_item: WorkItem,
    envelope: WorkTypeEnvelope,
    db: Session,
) -> WorkflowDecision:
    """
    Route work item to the appropriate workflow and dispatch asynchronous jobs.
    """
    # 1. Cross-organization validation
    validate_cross_org_entities(
        db=db,
        organization_id=work_item.organization_id,
        service_id=work_item.service_id,
        environment_id=work_item.environment_id,
    )

    work_type = envelope.work_type
    job_id = None
    incident_id = None

    # 2. NEEDS_CLARIFICATION / BLOCKED
    if work_type == WorkType.NEEDS_CLARIFICATION or envelope.confidence < 0.70:
        work_item.status = WorkItemStatus.BLOCKED
        work_item.workflow = "clarification"
        db.commit()
        return WorkflowDecision(
            work_item_id=str(work_item.id),
            status=WorkItemStatus.BLOCKED,
            workflow="clarification",
            skip_incident_hypotheses=True,
            requires_runtime_evidence=False,
            action_taken="Blocked pending human clarification",
        )

    # 3. SECURITY_INCIDENT (Strict security quarantine; zero autonomous mutation)
    if work_type == WorkType.SECURITY_INCIDENT:
        work_item.status = WorkItemStatus.BLOCKED
        work_item.workflow = "security_incident"
        work_item.security_case_id = f"SEC-{str(uuid.uuid4())[:8].upper()}"
        work_item.evidence_retention_policy = "strict_preserve"
        db.commit()
        return WorkflowDecision(
            work_item_id=str(work_item.id),
            status=WorkItemStatus.BLOCKED,
            workflow="security_incident",
            skip_incident_hypotheses=False,
            requires_runtime_evidence=True,
            action_taken="Security case quarantined; requires authorized security review",
        )

    # 4. DIRECT_TASK (Fast-track repository task; zero incident hypotheses)
    if work_type == WorkType.DIRECT_TASK:
        work_item.status = WorkItemStatus.ROUTED
        work_item.workflow = "repository_task"
        # Enqueue lightweight repository task
        task = await submit_task(
            task_type="repository_task",
            payload={
                "work_item_id": str(work_item.id),
                "target_files": envelope.target_files,
                "title": work_item.title,
                "description": work_item.description,
            },
        )
        job_id = task.id
        db.commit()
        return WorkflowDecision(
            work_item_id=str(work_item.id),
            status=WorkItemStatus.ROUTED,
            workflow="repository_task",
            skip_incident_hypotheses=True,
            requires_runtime_evidence=False,
            job_id=job_id,
            action_taken="Fast-tracked direct repository file task",
        )

    # 5. PRODUCTION_INCIDENT (Correlate telemetry & enqueue incident investigation)
    if work_type == WorkType.PRODUCTION_INCIDENT:
        # Atomic sequence allocation for incident numbers
        try:
            from sqlalchemy import text
            next_num = db.execute(text("SELECT nextval('incident_number_seq')")).scalar()
            if not next_num:
                from sqlalchemy import func
                next_num = (db.query(func.max(Incident.number)).scalar() or 1000) + 1
        except Exception:
            from sqlalchemy import func
            next_num = (db.query(func.max(Incident.number)).scalar() or 1000) + 1

        source = _resolve_incident_source(work_item.title, work_item.description)
        incident = Incident(
            number=next_num,
            title=work_item.title,
            description=work_item.description,
            severity=IncidentSeverity.SEV2,
            status=IncidentStatus.DETECTED,
            source=source,
            service_id=work_item.service_id,
            creator_id=work_item.requester_id,
        )
        db.add(incident)
        db.flush()

        work_item.incident_id = incident.id
        work_item.status = WorkItemStatus.ROUTED
        work_item.workflow = "production_incident"

        # Submit asynchronous investigation job to task queue
        task = await submit_task(
            task_type="investigate_incident",
            payload={
                "work_item_id": str(work_item.id),
                "incident_id": str(incident.id),
            },
        )
        job_id = task.id
        incident_id = str(incident.id)
        db.commit()

        return WorkflowDecision(
            work_item_id=str(work_item.id),
            status=WorkItemStatus.ROUTED,
            workflow="production_incident",
            skip_incident_hypotheses=False,
            requires_runtime_evidence=True,
            incident_id=incident_id,
            job_id=job_id,
            action_taken=f"Created linked incident #{incident.number} ({source.value}) and submitted asynchronous investigation",
        )

    # 6. BUG or FEATURE (Standard software development pipelines)
    work_item.status = WorkItemStatus.ROUTED
    work_item.workflow = "bug" if work_type == WorkType.BUG else "feature"
    task = await submit_task(
        task_type=work_item.workflow,
        payload={
            "work_item_id": str(work_item.id),
            "title": work_item.title,
            "requires_runtime_evidence": envelope.requires_runtime_evidence,
        },
    )
    job_id = task.id
    db.commit()

    return WorkflowDecision(
        work_item_id=str(work_item.id),
        status=WorkItemStatus.ROUTED,
        workflow=work_item.workflow,
        skip_incident_hypotheses=(not envelope.requires_runtime_evidence),
        requires_runtime_evidence=envelope.requires_runtime_evidence,
        job_id=job_id,
        action_taken=f"Enqueued {work_item.workflow} workflow job",
    )
