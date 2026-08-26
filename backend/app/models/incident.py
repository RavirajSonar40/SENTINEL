from sqlalchemy import (
    Column, String, DateTime, ForeignKey, Text, Integer, Float,
    Enum as SAEnum, JSON, Boolean, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum

from app.core.database import Base


# ============================================================================
# ENUMS — Incident Lifecycle (PRD §9)
# ============================================================================

class IncidentStatus(str, enum.Enum):
    DETECTED = "detected"
    CREATED = "created"
    INVESTIGATION_QUEUED = "investigation_queued"
    INVESTIGATING = "investigating"
    ROOT_CAUSE_ANALYSIS = "root_cause_analysis"
    ROOT_CAUSE_IDENTIFIED = "root_cause_identified"
    FIX_GENERATED = "fix_generated"
    FIX_VALIDATING = "fix_validating"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REMEDIATION = "remediation"
    DRAFT_PR_CREATED = "draft_pr_created"
    RESOLVED = "resolved"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    INVESTIGATION_FAILED = "investigation_failed"
    FIX_GENERATION_FAILED = "fix_generation_failed"
    VALIDATION_FAILED = "validation_failed"
    HUMAN_REJECTED = "human_rejected"
    CANCELLED = "cancelled"


class IncidentSource(str, enum.Enum):
    MANUAL = "manual"
    ALERT = "alert"
    PROMETHEUS = "prometheus"
    SENTRY = "sentry"
    WEBHOOK = "webhook"
    DEPLOYMENT_REGRESSION = "deployment_regression"


class IncidentSeverity(str, enum.Enum):
    SEV1 = "SEV-1"
    SEV2 = "SEV-2"
    SEV3 = "SEV-3"
    SEV4 = "SEV-4"


class InvestigationStatus(str, enum.Enum):
    PLANNING = "planning"
    COLLECTING_EVIDENCE = "collecting_evidence"
    ANALYZING = "analyzing"
    GENERATING_HYPOTHESES = "generating_hypotheses"
    EVALUATING_HYPOTHESES = "evaluating_hypotheses"
    ROOT_CAUSE_ANALYSIS = "root_cause_analysis"
    GENERATING_FIX = "generating_fix"
    VALIDATING_FIX = "validating_fix"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    SKIPPED = "skipped"


class EvidenceSourceType(str, enum.Enum):
    COMMIT = "commit"
    DIFF = "diff"
    FILE = "file"
    FUNCTION = "function"
    LOG = "log"
    METRIC = "metric"
    TRACE = "trace"
    ALERT = "alert"
    DEPLOYMENT = "deployment"
    DOCUMENTATION = "documentation"
    RUNBOOK = "runbook"
    PREVIOUS_INCIDENT = "previous_incident"
    PR = "pull_request"
    ISSUE = "issue"


class HypothesisStatus(str, enum.Enum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    REJECTED = "rejected"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class Confidence(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"


class FixStatus(str, enum.Enum):
    GENERATED = "generated"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    MERGED = "merged"


class ValidationStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class ServiceHealth(str, enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


# ============================================================================
# CORE ENTITIES
# ============================================================================

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="admin")
    is_active = Column(String(1), default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    repositories = relationship("Repository", back_populates="owner")
    incidents = relationship("Incident", back_populates="creator")
    approvals = relationship("Approval", back_populates="user")


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    services = relationship("Service", back_populates="organization")


class Service(Base):
    __tablename__ = "services"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    health = Column(SAEnum(ServiceHealth), default=ServiceHealth.UNKNOWN)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True)
    metadata_json = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="services")
    repositories = relationship("Repository", back_populates="service")
    incidents = relationship("Incident", back_populates="service_rel")
    deployments = relationship("Deployment", back_populates="service")


class Repository(Base):
    __tablename__ = "repositories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    full_name = Column(String(500), nullable=False, unique=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id"), nullable=True)
    installation_id = Column(UUID(as_uuid=True), ForeignKey("github_installations.id"), nullable=True)
    default_branch = Column(String(100), default="main")
    github_url = Column(String(500), nullable=True)
    sync_status = Column(String(50), default="pending")
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)
    metadata_json = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    owner = relationship("User", back_populates="repositories")
    service = relationship("Service", back_populates="repositories")
    scopes = relationship("RepositoryScope", back_populates="repository")
    installation = relationship("GitHubInstallation", back_populates="repositories")


class RepositoryScope(Base):
    __tablename__ = "repository_scopes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    incident = relationship("Incident", back_populates="scopes")
    repository = relationship("Repository", back_populates="scopes")


# ============================================================================
# INCIDENT (PRD §7-9)
# ============================================================================

class Incident(Base):
    __tablename__ = "incidents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    number = Column(Integer, unique=True, nullable=False)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    severity = Column(SAEnum(IncidentSeverity), nullable=False)
    status = Column(SAEnum(IncidentStatus), default=IncidentStatus.CREATED)
    source = Column(SAEnum(IncidentSource), default=IncidentSource.MANUAL)

    service_name = Column(String(255), nullable=True)
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id"), nullable=True)

    detected_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    creator_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    alert_id = Column(String(255), nullable=True)
    deployment_id = Column(String(255), nullable=True)

    confidence = Column(SAEnum(Confidence), nullable=True)
    root_cause_summary = Column(Text, nullable=True)

    error_signature = Column(String(500), nullable=True)
    external_id = Column(String(255), nullable=True)
    external_url = Column(String(500), nullable=True)
    signal_count = Column(Integer, default=0)
    first_signal_at = Column(DateTime(timezone=True), nullable=True)
    last_signal_at = Column(DateTime(timezone=True), nullable=True)

    creator = relationship("User", back_populates="incidents")
    service_rel = relationship("Service", back_populates="incidents")
    scopes = relationship("RepositoryScope", back_populates="incident", cascade="all, delete-orphan")
    signals = relationship("IncidentSignal", back_populates="incident", cascade="all, delete-orphan")
    investigations = relationship("Investigation", back_populates="incident", cascade="all, delete-orphan")
    evidence_items = relationship("Evidence", back_populates="incident", cascade="all, delete-orphan")
    hypotheses = relationship("Hypothesis", back_populates="incident", cascade="all, delete-orphan")
    root_causes = relationship("RootCause", back_populates="incident", cascade="all, delete-orphan")
    proposed_fixes = relationship("ProposedFix", back_populates="incident", cascade="all, delete-orphan")
    audit_events = relationship("AuditEvent", back_populates="incident", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_incidents_status", "status"),
        Index("ix_incidents_service", "service_name"),
        Index("ix_incidents_created", "created_at"),
    )


class IncidentSignal(Base):
    __tablename__ = "incident_signals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False)
    source = Column(String(100), nullable=False)
    signal_type = Column(String(100), nullable=False)
    content = Column(JSON, nullable=True)
    fingerprint = Column(String(255), nullable=True)
    received_at = Column(DateTime(timezone=True), server_default=func.now())

    incident = relationship("Incident", back_populates="signals")


# ============================================================================
# DEPLOYMENT (PRD §55)
# ============================================================================

class Deployment(Base):
    __tablename__ = "deployments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id"), nullable=False)
    version = Column(String(100), nullable=False)
    commit_sha = Column(String(40), nullable=True)
    deployed_at = Column(DateTime(timezone=True), nullable=False)
    deployed_by = Column(String(255), nullable=True)
    metadata_json = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    service = relationship("Service", back_populates="deployments")


# ============================================================================
# INVESTIGATION (PRD §10-11)
# ============================================================================

class Investigation(Base):
    __tablename__ = "investigations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False)
    status = Column(SAEnum(InvestigationStatus), default=InvestigationStatus.PLANNING)

    current_step = Column(String(255), nullable=True)
    progress_percent = Column(Integer, default=0)

    root_cause_found = Column(Boolean, default=False)
    confidence = Column(SAEnum(Confidence), nullable=True)

    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    llm_model = Column(String(100), nullable=True)
    total_tokens = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)

    plan_json = Column("plan", JSON, nullable=True)

    incident = relationship("Incident", back_populates="investigations")
    tasks = relationship("InvestigationTask", back_populates="investigation",
                         cascade="all, delete-orphan", order_by="InvestigationTask.order")


class InvestigationTask(Base):
    __tablename__ = "investigation_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("investigations.id"), nullable=False)
    task_type = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(SAEnum(TaskStatus), default=TaskStatus.PENDING)
    order = Column(Integer, default=0)

    tool_name = Column(String(100), nullable=True)
    tool_input = Column(JSON, nullable=True)
    tool_output = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)

    attempt = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    investigation = relationship("Investigation", back_populates="tasks")


# ============================================================================
# EVIDENCE (PRD §13-14)
# ============================================================================

class Evidence(Base):
    __tablename__ = "evidence"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("investigations.id"), nullable=True)

    source_type = Column(SAEnum(EvidenceSourceType), nullable=False)
    source_id = Column(String(255), nullable=True)
    repository = Column(String(255), nullable=True)
    file_path = Column(String(500), nullable=True)
    line_start = Column(Integer, nullable=True)
    line_end = Column(Integer, nullable=True)

    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)

    timestamp = Column(DateTime(timezone=True), nullable=True)

    source_url = Column(String(500), nullable=True)

    relevance_score = Column(Float, nullable=True)
    metadata_json = Column("metadata", JSON, nullable=True)

    collected_at = Column(DateTime(timezone=True), server_default=func.now())

    incident = relationship("Incident", back_populates="evidence_items")
    hypothesis_links = relationship("HypothesisEvidence", back_populates="evidence")

    __table_args__ = (
        Index("ix_evidence_incident", "incident_id"),
        Index("ix_evidence_source_type", "source_type"),
    )


# ============================================================================
# HYPOTHESIS (PRD §20-22)
# ============================================================================

class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("investigations.id"), nullable=True)

    label = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(SAEnum(HypothesisStatus), default=HypothesisStatus.PROPOSED)
    confidence = Column(SAEnum(Confidence), default=Confidence.INSUFFICIENT)

    supporting_evidence_count = Column(Integer, default=0)
    contradicting_evidence_count = Column(Integer, default=0)
    missing_evidence_count = Column(Integer, default=0)
    evaluation_notes = Column(Text, nullable=True)

    rejection_reason = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    evaluated_at = Column(DateTime(timezone=True), nullable=True)

    incident = relationship("Incident", back_populates="hypotheses")
    evidence_links = relationship("HypothesisEvidence", back_populates="hypothesis",
                                  cascade="all, delete-orphan")


class HypothesisEvidence(Base):
    __tablename__ = "hypothesis_evidence"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hypothesis_id = Column(UUID(as_uuid=True), ForeignKey("hypotheses.id"), nullable=False)
    evidence_id = Column(UUID(as_uuid=True), ForeignKey("evidence.id"), nullable=False)
    link_type = Column(String(50), nullable=False)
    notes = Column(Text, nullable=True)

    hypothesis = relationship("Hypothesis", back_populates="evidence_links")
    evidence = relationship("Evidence", back_populates="hypothesis_links")


# ============================================================================
# ROOT CAUSE (PRD §23-24)
# ============================================================================

class RootCause(Base):
    __tablename__ = "root_causes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("investigations.id"), nullable=True)

    summary = Column(Text, nullable=False)
    affected_component = Column(String(255), nullable=True)
    causal_explanation = Column(Text, nullable=False)
    confidence = Column(SAEnum(Confidence), nullable=False)

    supporting_evidence_ids = Column(JSON, nullable=True)
    contradicting_evidence_ids = Column(JSON, nullable=True)

    timeline = Column(JSON, nullable=True)

    relevant_commits = Column(JSON, nullable=True)
    relevant_files = Column(JSON, nullable=True)

    identified_at = Column(DateTime(timezone=True), server_default=func.now())

    incident = relationship("Incident", back_populates="root_causes")


# ============================================================================
# FIX / REMEDIATION (PRD §25-27)
# ============================================================================

class ProposedFix(Base):
    __tablename__ = "proposed_fixes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("investigations.id"), nullable=True)
    root_cause_id = Column(UUID(as_uuid=True), ForeignKey("root_causes.id"), nullable=True)

    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=False)
    fix_type = Column(String(100), nullable=True)
    problem = Column(Text, nullable=True)
    root_cause = Column(Text, nullable=True)
    proposed_change = Column(Text, nullable=False)
    expected_behavior = Column(Text, nullable=True)
    risk = Column(Text, nullable=True)
    validation_strategy = Column(Text, nullable=True)
    status = Column(String(50), default=FixStatus.GENERATED.value)

    repository = Column(String(500), nullable=True)
    diff = Column(Text, nullable=True)
    patch_json = Column(JSON, nullable=True)

    branch_name = Column(String(255), nullable=True)
    pr_number = Column(Integer, nullable=True)
    pr_url = Column(String(500), nullable=True)

    generated_at = Column(DateTime(timezone=True), server_default=func.now())

    incident = relationship("Incident", back_populates="proposed_fixes")
    root_cause = relationship("RootCause")
    files = relationship("FixFile", back_populates="fix", cascade="all, delete-orphan")
    validations = relationship("ValidationRun", back_populates="fix", cascade="all, delete-orphan")


class FixFile(Base):
    __tablename__ = "fix_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fix_id = Column(UUID(as_uuid=True), ForeignKey("proposed_fixes.id"), nullable=False)
    file_path = Column(String(500), nullable=False)
    change_type = Column(String(50), nullable=False)
    additions = Column(Integer, default=0)
    deletions = Column(Integer, default=0)
    patch = Column(Text, nullable=True)

    fix = relationship("ProposedFix", back_populates="files")


# ============================================================================
# VALIDATION (PRD §27)
# ============================================================================

class ValidationRun(Base):
    __tablename__ = "validation_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fix_id = Column(UUID(as_uuid=True), ForeignKey("proposed_fixes.id"), nullable=False)
    status = Column(SAEnum(ValidationStatus), default=ValidationStatus.PENDING)

    total_checks = Column(Integer, default=0)
    passed_checks = Column(Integer, default=0)
    failed_checks = Column(Integer, default=0)

    lint_result = Column(JSON, nullable=True)
    test_result = Column(JSON, nullable=True)
    build_result = Column(JSON, nullable=True)
    security_result = Column(JSON, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    fix = relationship("ProposedFix", back_populates="validations")


# ============================================================================
# APPROVAL (PRD §28)
# ============================================================================

class Approval(Base):
    __tablename__ = "approvals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False)
    fix_id = Column(UUID(as_uuid=True), ForeignKey("proposed_fixes.id"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    status = Column(SAEnum(ApprovalStatus), default=ApprovalStatus.PENDING)
    notes = Column(Text, nullable=True)
    modified_diff = Column(Text, nullable=True)

    requested_at = Column(DateTime(timezone=True), server_default=func.now())
    decided_at = Column(DateTime(timezone=True), nullable=True)

    incident = relationship("Incident")
    fix = relationship("ProposedFix")
    user = relationship("User", back_populates="approvals")


# ============================================================================
# AUDIT (PRD §49)
# ============================================================================

class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    event_type = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    metadata_json = Column("metadata", JSON, nullable=True)

    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    incident = relationship("Incident", back_populates="audit_events")


# ============================================================================
# AGENT RUNS (PRD §40)
# ============================================================================

class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("investigations.id"), nullable=True)

    model = Column(String(100), nullable=False)
    tokens_input = Column(Integer, default=0)
    tokens_output = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    latency_ms = Column(Integer, default=0)

    tool_name = Column(String(100), nullable=True)
    tool_input = Column(JSON, nullable=True)
    tool_output = Column(JSON, nullable=True)
    success = Column(Boolean, default=True)
    error = Column(Text, nullable=True)

    timestamp = Column(DateTime(timezone=True), server_default=func.now())


# ============================================================================
# GITHUB INTEGRATION (PRD §3, §36)
# ============================================================================

class GitHubInstallation(Base):
    """GitHub App installation per organization."""
    __tablename__ = "github_installations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    installation_id = Column(String(100), unique=True, nullable=False)
    account_type = Column(String(50), nullable=False)
    account_login = Column(String(255), nullable=False)
    account_id = Column(String(100), nullable=False)
    target_type = Column(String(50), nullable=False)
    permissions = Column(JSON, nullable=True)
    repository_selection = Column(String(50), nullable=True)
    tokens_encrypted = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    repositories = relationship("Repository", back_populates="installation")


class GitHubRepositorySync(Base):
    """Track repository sync status."""
    __tablename__ = "github_repo_syncs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    installation_id = Column(UUID(as_uuid=True), ForeignKey("github_installations.id"), nullable=False)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id"), nullable=False)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    sync_status = Column(String(50), default="pending")
    commits_synced = Column(Integer, default=0)
    branches_synced = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    installation = relationship("GitHubInstallation")


class GitHubWebhookEvent(Base):
    """Store incoming GitHub webhook events for processing."""
    __tablename__ = "github_webhook_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    delivery_id = Column(String(100), unique=True, nullable=False)
    event_type = Column(String(100), nullable=False)
    action = Column(String(50), nullable=True)
    payload = Column(JSON, nullable=False)
    processed = Column(Boolean, default=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)
    received_at = Column(DateTime(timezone=True), server_default=func.now())