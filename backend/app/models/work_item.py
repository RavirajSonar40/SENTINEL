"""
Sentinel Work Item and Work Item Repository Database Models.

Implements Phase 2: Work Items & Intent Routing.
Defines WorkType, WorkItemStatus, WorkItem, and WorkItemRepository.
"""

import enum
import uuid
from sqlalchemy import (
    Column,
    String,
    Text,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    Enum as SAEnum,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class WorkType(str, enum.Enum):
    """Supported work item categories."""
    DIRECT_TASK = "DIRECT_TASK"
    BUG = "BUG"
    FEATURE = "FEATURE"
    PRODUCTION_INCIDENT = "PRODUCTION_INCIDENT"
    SECURITY_INCIDENT = "SECURITY_INCIDENT"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


class WorkItemStatus(str, enum.Enum):
    """Lifecycle status for a work item."""
    CREATED = "created"
    ROUTED = "routed"
    IN_PROGRESS = "in_progress"
    VALIDATED = "validated"
    DRAFT_PR_CREATED = "draft_pr_created"
    RESOLVED = "resolved"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class WorkItem(Base):
    """
    Primary unit of work in Sentinel.
    Enforces non-null organization tenant isolation and multi-repository scoping.
    """
    __tablename__ = "work_items"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_work_items_org_idempotency"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idempotency_key = Column(String(255), nullable=True, index=True)

    work_type = Column(SAEnum(WorkType), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(SAEnum(WorkItemStatus), default=WorkItemStatus.CREATED, nullable=False, index=True)
    priority = Column(String(50), default="medium")

    # Ownership and Scoping Foreign Keys
    requester_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id", ondelete="SET NULL"), nullable=True)
    environment_id = Column(UUID(as_uuid=True), ForeignKey("environments.id", ondelete="SET NULL"), nullable=True)
    region_id = Column(String(50), nullable=True)

    # Routing Envelope & Target Scope
    target_files = Column(JSON, default=list)
    workflow = Column(String(100), nullable=False, default="repository_task")
    confidence = Column(Float, default=1.0)
    requires_runtime_evidence = Column(Boolean, default=False)
    runtime_evidence_reason = Column(String(500), nullable=True)
    requires_code_change = Column(Boolean, default=True)
    envelope = Column(JSON, default=dict)

    # Security Incident Isolation Fields
    security_case_id = Column(String(100), nullable=True)
    evidence_retention_policy = Column(String(100), nullable=True)
    security_owner = Column(String(255), nullable=True)

    # Linked specialized records
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    organization = relationship("Organization")
    requester = relationship("User")
    service = relationship("Service")
    environment = relationship("Environment")
    incident = relationship("Incident")
    repositories = relationship("WorkItemRepository", back_populates="work_item", cascade="all, delete-orphan")


class WorkItemRepository(Base):
    """
    Multi-repository scoping relationship for WorkItems.
    """
    __tablename__ = "work_item_repositories"
    __table_args__ = (
        UniqueConstraint("work_item_id", "repository_id", name="uq_work_item_repository_scope"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    work_item_id = Column(
        UUID(as_uuid=True),
        ForeignKey("work_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    repository_id = Column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(50), default="primary")  # primary, evidence_only, downstream, configuration
    is_primary = Column(Boolean, default=True)
    selection_reason = Column(String(500), nullable=True)
    confidence = Column(Float, default=1.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    work_item = relationship("WorkItem", back_populates="repositories")
    repository = relationship("Repository")
