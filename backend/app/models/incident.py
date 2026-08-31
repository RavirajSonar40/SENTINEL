import sqlalchemy as sa
from sqlalchemy import (
    Column, String, DateTime, ForeignKey, Text, Integer, Float,
    Enum as SAEnum, JSON, Boolean, Index, UniqueConstraint, CheckConstraint, event, text
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, backref
from sqlalchemy.orm.attributes import get_history

from sqlalchemy.sql import func
import uuid
import enum
from datetime import datetime, timezone

from app.core.database import Base



def SAEnumVal(enum_cls, **kwargs):
    """Ensure SQLAlchemy uses lowercase .value when saving enum to PostgreSQL / SQLite."""
    return SAEnum(enum_cls, values_callable=lambda obj: [e.value for e in obj], **kwargs)


# ============================================================================
# ENUMS — Incident Lifecycle & Organization Catalog (PRD §9, §3)
# ============================================================================

class MembershipRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    SECURITY_OFFICER = "security_officer"
    OPERATOR = "operator"
    MEMBER = "member"
    VIEWER = "viewer"


class ActionType(str, enum.Enum):
    READ_TELEMETRY = "read_telemetry"
    WRITE_PRODUCTION = "write_production"
    READ_REPOSITORY = "read_repository"
    CREATE_BRANCH = "create_branch"
    CREATE_DRAFT_PR = "create_draft_pr"
    MERGE_PR = "merge_pr"
    DEPLOY = "deploy"
    MODIFY_SECRETS = "modify_secrets"
    MODIFY_INFRASTRUCTURE = "modify_infrastructure"
    DATABASE_MIGRATION = "database_migration"
    SECURITY_CHANGE = "security_change"
    APPLY_REMEDIATION = "apply_remediation"


class PolicyDecision(str, enum.Enum):
    ALLOW = "allow"
    BLOCK = "block"
    REQUIRE_HUMAN = "require_human"
    MULTI_APPROVAL = "multi_approval"
    SECURITY_APPROVAL = "security_approval"


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"



class ServiceRepositoryRole(str, enum.Enum):
    APPLICATION = "application"
    CONFIGURATION = "configuration"
    INFRASTRUCTURE = "infrastructure"
    DEPENDENCY = "dependency"


class ServiceDependencyType(str, enum.Enum):
    SYNCHRONOUS = "synchronous"
    ASYNCHRONOUS = "asynchronous"
    DATABASE = "database"
    CACHE = "cache"
    EXTERNAL = "external"


class ServiceCriticality(str, enum.Enum):
    HARD = "hard"
    SOFT = "soft"


class OwnershipType(str, enum.Enum):
    PRIMARY_OWNER = "primary_owner"
    SECONDARY_OWNER = "secondary_owner"
    ONCALL = "oncall"


class RepositoryRole(str, enum.Enum):
    PRIMARY_DEFECT = "primary_defect"
    DOWNSTREAM_AFFECTED = "downstream_affected"
    CONFIGURATION = "configuration"
    EVIDENCE_ONLY = "evidence_only"


class RemediationPlanStatus(str, enum.Enum):
    DRAFT = "draft"
    VALIDATING = "validating"
    VALIDATED = "validated"
    BLOCKED_CYCLIC_DEPENDENCY = "blocked_cyclic_dependency"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    PARTIALLY_FAILED = "partially_failed"
    FAILED = "failed"



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
    AUTO_DETECTION = "auto_detection"
    HEALTH_CHECK = "health_check"


class IncidentSeverity(str, enum.Enum):
    SEV1 = "SEV-1"
    SEV2 = "SEV-2"
    SEV3 = "SEV-3"
    SEV4 = "SEV-4"


class InvestigationStatus(str, enum.Enum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_FOR_INPUT = "waiting_for_input"
    ABSTAINED = "abstained"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"

    # Legacy & sub-step compatibility aliases
    PLANNING = "planning"
    COLLECTING_EVIDENCE = "collecting_evidence"
    ANALYZING = "analyzing"
    GENERATING_HYPOTHESES = "generating_hypotheses"
    EVALUATING_HYPOTHESES = "evaluating_hypotheses"
    ROOT_CAUSE_ANALYSIS = "root_cause_analysis"
    GENERATING_FIX = "generating_fix"
    VALIDATING_FIX = "validating_fix"


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    SKIPPED = "skipped"


class EvidenceCategoryType(str, enum.Enum):
    FACT = "fact"
    INFERENCE = "inference"
    CONCLUSION = "conclusion"


class EvidenceTrustLevel(str, enum.Enum):
    UNVERIFIED = "unverified"
    VERIFIED_BY_OPERATOR = "verified_by_operator"
    VERIFIED_BY_ADMIN = "verified_by_admin"


class EvidenceVerificationStatus(str, enum.Enum):
    PENDING_REVIEW = "pending_review"
    VERIFIED = "verified"
    REJECTED = "rejected"


class EvidenceFamily(str, enum.Enum):
    FAMILY_RUNTIME_TELEMETRY = "runtime_telemetry"
    FAMILY_CODE_CHANGE = "code_change"
    FAMILY_TOPOLOGY_GRAPH = "topology_graph"
    FAMILY_WORKSPACE_STATIC = "workspace_static"
    FAMILY_VERIFIED_HUMAN = "verified_human"


class EvidenceSourceType(str, enum.Enum):
    DEPLOYMENTS = "deployments"
    TELEMETRY = "telemetry"
    LOGS = "logs"
    GRAPH = "graph"
    CHANGES = "changes"
    WORKSPACE = "workspace"
    MANUAL = "manual"
    # Fine-grained aliases
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
    DISPROVEN = "disproven"
    ACCEPTED = "accepted"
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
    CHANGES_REQUESTED = "changes_requested"
    INVALIDATED_STALE = "invalidated_stale"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    MODIFIED = "modified"  # backward compat alias for changes_requested


class FixStatus(str, enum.Enum):
    GENERATED = "generated"
    VALIDATED = "validated"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    DRAFT_PR_CREATED = "draft_pr_created"
    MERGED = "merged"
    MERGED_EXTERNALLY = "merged_externally"



class ValidationStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class ValidationCheckType(str, enum.Enum):
    COMPILATION = "compilation"
    REPRODUCTION = "reproduction"
    REGRESSION = "regression"
    TARGETED_TESTS = "targeted_tests"
    FULL_SUITE = "full_suite"
    LINT = "lint"
    TYPE_CHECK = "type_check"
    BUILD = "build"
    SECURITY = "security"
    SCENARIO_REPLAY = "scenario_replay"


class ValidationCheckStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"
    ERROR = "error"


class ServiceHealth(str, enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


# ============================================================================
# INCIDENT MEMORY & POST-MORTEM ENUMS (Phase 10)
# ============================================================================

class PostMortemStatus(str, enum.Enum):
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class MemoryIndexingStatus(str, enum.Enum):
    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"


class ActionItemStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    WONT_FIX = "wont_fix"


class ActionItemPriority(str, enum.Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class ActionItemCategory(str, enum.Enum):
    CODE_HARDENING = "code_hardening"
    MONITORING_GAP = "monitoring_gap"
    ARCHITECTURAL_DEBT = "architectural_debt"
    RUNBOOK_IMPROVEMENT = "runbook_improvement"
    INFRASTRUCTURE_RESILIENCE = "infrastructure_resilience"


# ============================================================================
# PATCH & TEST GENERATION ENUMS (Phase 11)
# ============================================================================

class TestType(str, enum.Enum):
    __test__ = False
    UNIT = "unit"
    REGRESSION = "regression"
    INTEGRATION = "integration"


class RegressionTestStatus(str, enum.Enum):
    PENDING = "pending"
    REPRODUCED_AND_FIXED = "reproduced_and_fixed"
    FAILED_PRE_CHECK = "failed_pre_check"
    FAILED_POST_CHECK = "failed_post_check"
    NOT_APPLICABLE = "not_applicable"


class RevalidationStatus(str, enum.Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class DeploymentStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"


class DeploymentProvider(str, enum.Enum):
    MANUAL = "manual"
    GITHUB = "github"
    GENERIC_WEBHOOK = "generic_webhook"
    ARGO_CD = "argo_cd"
    KUBERNETES = "kubernetes"
    GITLAB = "gitlab"


class SignalProvider(str, enum.Enum):
    PROMETHEUS = "prometheus"
    SENTRY = "sentry"
    HEALTH_CHECK = "health_check"
    GENERIC = "generic"
    DATADOG = "datadog"
    CLOUDWATCH = "cloudwatch"


class SignalType(str, enum.Enum):
    CPU_THRESHOLD = "CPU_THRESHOLD"
    MEMORY_THRESHOLD = "MEMORY_THRESHOLD"
    ERROR_RATE = "ERROR_RATE"
    LATENCY_SPIKE = "LATENCY_SPIKE"
    HEALTH_CHECK_FAILURE = "HEALTH_CHECK_FAILURE"
    CRASH_LOOP = "CRASH_LOOP"
    RESTART_SPIKE = "RESTART_SPIKE"
    DISK_THRESHOLD = "DISK_THRESHOLD"
    QUEUE_BACKLOG = "QUEUE_BACKLOG"
    DATABASE_SATURATION = "DATABASE_SATURATION"
    DEPLOYMENT_REGRESSION = "DEPLOYMENT_REGRESSION"
    REPEATED_EXCEPTION = "REPEATED_EXCEPTION"


class SignalStatus(str, enum.Enum):
    INGESTED = "ingested"
    CORRELATED = "correlated"
    TRIGGERED_INCIDENT = "triggered_incident"
    RESOLVED = "resolved"
    SUPPRESSED_NON_PROD = "suppressed_non_prod"


class GraphNodeType(str, enum.Enum):
    SERVICE = "SERVICE"
    REPOSITORY = "REPOSITORY"
    ENDPOINT = "ENDPOINT"
    ENVIRONMENT = "ENVIRONMENT"
    REGION = "REGION"
    DATABASE = "DATABASE"
    QUEUE = "QUEUE"
    EXTERNAL_PROVIDER = "EXTERNAL_PROVIDER"
    TEAM = "TEAM"
    DEPLOYMENT = "DEPLOYMENT"


class GraphEdgeType(str, enum.Enum):
    CALLS = "CALLS"
    DEPENDS_ON = "DEPENDS_ON"
    IMPLEMENTED_BY = "IMPLEMENTED_BY"
    DEPLOYED_AS = "DEPLOYED_AS"
    OWNED_BY = "OWNED_BY"
    STORES_IN = "STORES_IN"
    PUBLISHES_TO = "PUBLISHES_TO"
    CONSUMES_FROM = "CONSUMES_FROM"


class GraphEdgeSource(str, enum.Enum):
    SERVICE_REGISTRATION = "SERVICE_REGISTRATION"
    REPOSITORY_CONFIG = "REPOSITORY_CONFIG"
    K8S_HELM = "K8S_HELM"
    TERRAFORM = "TERRAFORM"
    API_SPEC = "API_SPEC"
    OPENTELEMETRY_TRACE = "OPENTELEMETRY_TRACE"
    IMPORT_ANALYSIS = "IMPORT_ANALYSIS"
    DEPLOYMENT_METADATA = "DEPLOYMENT_METADATA"
    CODEOWNERS = "CODEOWNERS"
    MANUAL_CORRECTION = "MANUAL_CORRECTION"


# ============================================================================
# CHANGE INTELLIGENCE ENUMS (Phase 7)
# ============================================================================

class ChangeType(str, enum.Enum):
    CODE_COMMIT = "CODE_COMMIT"
    PULL_REQUEST = "PULL_REQUEST"
    CONFIGURATION = "CONFIGURATION"
    ENVIRONMENT_VARIABLE = "ENVIRONMENT_VARIABLE"
    DEPENDENCY_UPGRADE = "DEPENDENCY_UPGRADE"
    DATABASE_MIGRATION = "DATABASE_MIGRATION"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    FEATURE_FLAG = "FEATURE_FLAG"
    API_CONTRACT = "API_CONTRACT"
    DEPLOYMENT = "DEPLOYMENT"
    SCALING_CHANGE = "SCALING_CHANGE"


class ChangeRiskLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CorrelationStatus(str, enum.Enum):
    SUSPECTED_ROOT_CAUSE = "SUSPECTED_ROOT_CAUSE"
    CONTRIBUTING_FACTOR = "CONTRIBUTING_FACTOR"
    COINCIDENTAL = "COINCIDENTAL"
    DISMISSED = "DISMISSED"


# ============================================================================
# CORE ORGANIZATION & CATALOG ENTITIES (Phase 3)
# ============================================================================

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="admin")
    is_active = Column(String(1), default="1")
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    organization = relationship("Organization", back_populates="users")
    memberships = relationship("UserOrganizationMembership", back_populates="user", cascade="all, delete-orphan")
    team_memberships = relationship("TeamMember", back_populates="user", cascade="all, delete-orphan")
    repositories = relationship("Repository", back_populates="owner")
    incidents = relationship("Incident", back_populates="creator")
    approvals = relationship("Approval", back_populates="user")
    service_ownerships = relationship("ServiceOwnership", back_populates="user")


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    users = relationship("User", back_populates="organization")
    memberships = relationship("UserOrganizationMembership", back_populates="organization", cascade="all, delete-orphan")
    teams = relationship("Team", back_populates="organization", cascade="all, delete-orphan")
    regions = relationship("Region", back_populates="organization", cascade="all, delete-orphan")
    services = relationship("Service", back_populates="organization", cascade="all, delete-orphan")
    environments = relationship("Environment", back_populates="organization", cascade="all, delete-orphan")
    repositories = relationship("Repository", back_populates="organization", cascade="all, delete-orphan")
    service_repositories = relationship("ServiceRepository", back_populates="organization", cascade="all, delete-orphan")
    service_dependencies = relationship("ServiceDependency", back_populates="organization", cascade="all, delete-orphan")
    service_ownerships = relationship("ServiceOwnership", back_populates="organization", cascade="all, delete-orphan")
    deployment_configs = relationship("ServiceDeploymentConfig", back_populates="organization", cascade="all, delete-orphan")
    deployments = relationship("Deployment", back_populates="organization", cascade="all, delete-orphan")
    webhook_endpoints = relationship("WebhookEndpoint", back_populates="organization", cascade="all, delete-orphan")
    incidents = relationship("Incident", back_populates="organization", cascade="all, delete-orphan")
    telemetry_signals = relationship("TelemetrySignal", back_populates="organization", cascade="all, delete-orphan")
    alert_rule_configs = relationship("AlertRuleConfig", back_populates="organization", cascade="all, delete-orphan")
    health_check_logs = relationship("HealthCheckLog", back_populates="organization", cascade="all, delete-orphan")
    graph_nodes = relationship("GraphNode", back_populates="organization", cascade="all, delete-orphan")
    graph_edges = relationship("GraphEdge", back_populates="organization", cascade="all, delete-orphan")
    blast_radius_reports = relationship("IncidentBlastRadiusReport", back_populates="organization", cascade="all, delete-orphan")
    change_events = relationship("ChangeEvent", back_populates="organization", cascade="all, delete-orphan")
    change_correlations = relationship("IncidentChangeCorrelation", back_populates="organization", cascade="all, delete-orphan")
    change_correlation_reports = relationship("IncidentChangeCorrelationReport", back_populates="organization", cascade="all, delete-orphan")
    investigations = relationship("Investigation", back_populates="organization", cascade="all, delete-orphan")
    evidence_items = relationship("Evidence", back_populates="organization", cascade="all, delete-orphan")
    hypotheses = relationship("Hypothesis", back_populates="organization", cascade="all, delete-orphan")
    root_causes = relationship("RootCause", back_populates="organization", cascade="all, delete-orphan")
    post_mortems = relationship("PostMortem", back_populates="organization", cascade="all, delete-orphan")
    post_mortem_action_items = relationship("PostMortemActionItem", back_populates="organization", cascade="all, delete-orphan")


class UserOrganizationMembership(Base):
    """Authority for multi-tenant user memberships and roles."""
    __tablename__ = "user_organization_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_user_org_membership"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(SAEnum(MembershipRole), default=MembershipRole.MEMBER, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="memberships")
    organization = relationship("Organization", back_populates="memberships")


class Team(Base):
    """Team within an organization for service ownership and escalation."""
    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_team_org_slug"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    organization = relationship("Organization", back_populates="teams")
    members = relationship("TeamMember", back_populates="team", cascade="all, delete-orphan")
    service_ownerships = relationship("ServiceOwnership", back_populates="team")


class TeamMember(Base):
    """Membership of users in teams."""
    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_member"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(50), default="member", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    team = relationship("Team", back_populates="members")
    user = relationship("User", back_populates="team_memberships")


class Region(Base):
    """Geographic or cloud region."""
    __tablename__ = "regions"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_region_org_code"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    code = Column(String(50), nullable=False)  # us-east-1, ap-south-1
    cloud_provider = Column(String(50), default="aws", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    organization = relationship("Organization", back_populates="regions")
    deployment_configs = relationship("ServiceDeploymentConfig", back_populates="region")
    deployments = relationship("Deployment", back_populates="region")
    incidents = relationship("Incident", back_populates="region")
    telemetry_signals = relationship("TelemetrySignal", back_populates="region")
    health_check_logs = relationship("HealthCheckLog", back_populates="region")


class Environment(Base):
    __tablename__ = "environments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)  # production, staging, preview, development
    env_type = Column(String(50), default="production", nullable=False)
    region = Column(String(50), nullable=True)  # legacy field
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    organization = relationship("Organization", back_populates="environments")
    deployment_configs = relationship("ServiceDeploymentConfig", back_populates="environment")
    deployments = relationship("Deployment", back_populates="environment")
    incidents = relationship("Incident", back_populates="environment")
    telemetry_signals = relationship("TelemetrySignal", back_populates="environment")
    health_check_logs = relationship("HealthCheckLog", back_populates="environment")


class Service(Base):
    __tablename__ = "services"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    tier = Column(String(50), default="medium", nullable=False)  # critical, high, medium, low
    health = Column(SAEnum(ServiceHealth), default=ServiceHealth.UNKNOWN)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    metadata_json = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="services")
    repositories = relationship("Repository", back_populates="service")  # legacy 1-to-many
    service_repositories = relationship("ServiceRepository", back_populates="service", cascade="all, delete-orphan")
    dependencies_out = relationship("ServiceDependency", foreign_keys="ServiceDependency.service_id", back_populates="service", cascade="all, delete-orphan")
    dependencies_in = relationship("ServiceDependency", foreign_keys="ServiceDependency.depends_on_service_id", back_populates="depends_on_service", cascade="all, delete-orphan")
    ownerships = relationship("ServiceOwnership", back_populates="service", cascade="all, delete-orphan")
    deployment_configs = relationship("ServiceDeploymentConfig", back_populates="service", cascade="all, delete-orphan")
    incidents = relationship("Incident", back_populates="service_rel")
    deployments = relationship("Deployment", back_populates="service")
    telemetry_signals = relationship("TelemetrySignal", back_populates="service")
    health_check_logs = relationship("HealthCheckLog", back_populates="service")
    change_events = relationship("ChangeEvent", back_populates="service", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_service_org_name"),
    )


class Repository(Base):
    __tablename__ = "repositories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    full_name = Column(String(500), nullable=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id", ondelete="SET NULL"), nullable=True)  # legacy field
    installation_id = Column(UUID(as_uuid=True), ForeignKey("github_installations.id", ondelete="SET NULL"), nullable=True)
    default_branch = Column(String(100), default="main")
    language = Column(String(100), nullable=True)
    github_url = Column(String(500), nullable=True)
    sync_status = Column(String(50), default="pending")
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)
    metadata_json = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    owner = relationship("User", back_populates="repositories")
    organization = relationship("Organization", back_populates="repositories")
    service = relationship("Service", back_populates="repositories")
    service_repositories = relationship("ServiceRepository", back_populates="repository", cascade="all, delete-orphan")
    work_item_repositories = relationship("WorkItemRepository", back_populates="repository", cascade="all, delete-orphan")
    deployments = relationship("Deployment", back_populates="repository")
    scopes = relationship("RepositoryScope", back_populates="repository")
    installation = relationship("GitHubInstallation", back_populates="repositories")
    change_events = relationship("ChangeEvent", back_populates="repository", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("organization_id", "full_name", name="uq_repo_org_full_name"),
    )


class ServiceRepository(Base):
    """Multi-repository topology mapping for services."""
    __tablename__ = "service_repositories"
    __table_args__ = (
        UniqueConstraint("service_id", "repository_id", "role", name="uq_service_repo_role"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(SAEnum(ServiceRepositoryRole), default=ServiceRepositoryRole.APPLICATION, nullable=False)
    is_primary = Column(Boolean, default=False, nullable=False)
    confidence = Column(Float, default=1.0, nullable=False)
    source = Column(String(100), default="manual", nullable=False)
    selection_reason = Column(String(500), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    organization = relationship("Organization", back_populates="service_repositories")
    service = relationship("Service", back_populates="service_repositories")
    repository = relationship("Repository", back_populates="service_repositories")


class ServiceDependency(Base):
    """Directional service dependency graph."""
    __tablename__ = "service_dependencies"
    __table_args__ = (
        UniqueConstraint("service_id", "depends_on_service_id", name="uq_service_dependency"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    # Caller / dependent service (downstream)
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True)
    # Provider / dependency service (upstream)
    depends_on_service_id = Column(UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True)
    dependency_type = Column(SAEnum(ServiceDependencyType), default=ServiceDependencyType.SYNCHRONOUS, nullable=False)
    criticality = Column(SAEnum(ServiceCriticality), default=ServiceCriticality.HARD, nullable=False)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    organization = relationship("Organization", back_populates="service_dependencies")
    service = relationship("Service", foreign_keys=[service_id], back_populates="dependencies_out")
    depends_on_service = relationship("Service", foreign_keys=[depends_on_service_id], back_populates="dependencies_in")


class ServiceOwnership(Base):
    """Ownership assignment for services (team or individual user)."""
    __tablename__ = "service_ownerships"
    __table_args__ = (
        CheckConstraint(
            "(team_id IS NOT NULL AND user_id IS NULL) OR (team_id IS NULL AND user_id IS NOT NULL)",
            name="ck_service_ownership_exclusive_owner",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    ownership_type = Column(SAEnum(OwnershipType), default=OwnershipType.PRIMARY_OWNER, nullable=False)
    escalation_policy = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    organization = relationship("Organization", back_populates="service_ownerships")
    service = relationship("Service", back_populates="ownerships")
    team = relationship("Team", back_populates="service_ownerships")
    user = relationship("User", back_populates="service_ownerships")


class ServiceDeploymentConfig(Base):
    """Environment and observability configuration per service."""
    __tablename__ = "service_deployment_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True)
    environment_id = Column(UUID(as_uuid=True), ForeignKey("environments.id", ondelete="CASCADE"), nullable=False, index=True)
    region_id = Column(UUID(as_uuid=True), ForeignKey("regions.id", ondelete="SET NULL"), nullable=True, index=True)
    health_check_url = Column(String(500), nullable=True)
    health_check_interval_seconds = Column(Integer, default=30)
    observability_identifiers = Column(JSON, nullable=True)  # prometheus_job, sentry_project, datadog_service
    current_commit_sha = Column(String(40), nullable=True)
    current_version = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)

    # Health check poller state persistence
    consecutive_failures = Column(Integer, default=0, nullable=False)
    last_probed_at = Column(DateTime(timezone=True), nullable=True)
    last_probe_status_code = Column(Integer, nullable=True)
    last_probe_latency_ms = Column(Float, nullable=True)
    last_probe_is_healthy = Column(Boolean, nullable=True)
    last_probe_error = Column(Text, nullable=True)
    poller_lease_until = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="deployment_configs")
    service = relationship("Service", back_populates="deployment_configs")
    environment = relationship("Environment", back_populates="deployment_configs")
    region = relationship("Region", back_populates="deployment_configs")
    health_check_logs = relationship("HealthCheckLog", back_populates="deployment_config", cascade="all, delete-orphan")


class RepositoryScope(Base):
    __tablename__ = "repository_scopes"
    __table_args__ = (
        UniqueConstraint("incident_id", "repository_id", name="uq_repository_scope_incident_repo"),
    )

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

    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    service_name = Column(String(255), nullable=True)
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id"), nullable=True)
    environment_id = Column(UUID(as_uuid=True), ForeignKey("environments.id", ondelete="SET NULL"), nullable=True, index=True)
    region_id = Column(UUID(as_uuid=True), ForeignKey("regions.id", ondelete="SET NULL"), nullable=True, index=True)

    detected_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    creator_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    alert_id = Column(String(255), nullable=True)
    deployment_id = Column(UUID(as_uuid=True), ForeignKey("deployments.id"), nullable=True)

    confidence = Column(SAEnum(Confidence), nullable=True)
    root_cause_summary = Column(Text, nullable=True)

    error_signature = Column(String(500), nullable=True)
    external_id = Column(String(255), nullable=True)
    external_url = Column(String(500), nullable=True)
    signal_count = Column(Integer, default=0)
    first_signal_at = Column(DateTime(timezone=True), nullable=True)
    last_signal_at = Column(DateTime(timezone=True), nullable=True)

    creator = relationship("User", back_populates="incidents")
    organization = relationship("Organization", back_populates="incidents")
    service_rel = relationship("Service", back_populates="incidents")
    environment = relationship("Environment", back_populates="incidents")
    region = relationship("Region", back_populates="incidents")
    deployment = relationship("Deployment", back_populates="incident")
    scopes = relationship("RepositoryScope", back_populates="incident", cascade="all, delete-orphan")
    signals = relationship("IncidentSignal", back_populates="incident", cascade="all, delete-orphan")
    telemetry_signals = relationship("TelemetrySignal", back_populates="incident", cascade="all, delete-orphan")
    correlation_claim = relationship("ActiveIncidentCorrelationClaim", back_populates="incident", uselist=False, cascade="all, delete-orphan")
    investigations = relationship("Investigation", back_populates="incident", cascade="all, delete-orphan")
    evidence_items = relationship("Evidence", back_populates="incident", cascade="all, delete-orphan")
    hypotheses = relationship("Hypothesis", back_populates="incident", cascade="all, delete-orphan")
    root_causes = relationship("RootCause", back_populates="incident", cascade="all, delete-orphan")
    proposed_fixes = relationship("ProposedFix", back_populates="incident", cascade="all, delete-orphan")
    audit_events = relationship("AuditEvent", back_populates="incident", cascade="all, delete-orphan")
    blast_radius_reports = relationship("IncidentBlastRadiusReport", back_populates="incident", cascade="all, delete-orphan")
    change_correlations = relationship("IncidentChangeCorrelation", back_populates="incident", cascade="all, delete-orphan")
    change_correlation_reports = relationship("IncidentChangeCorrelationReport", back_populates="incident", cascade="all, delete-orphan")
    post_mortems = relationship("PostMortem", back_populates="incident", cascade="all, delete-orphan")
    post_mortem_action_items = relationship("PostMortemActionItem", back_populates="incident", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_incidents_status", "status"),
        Index("ix_incidents_service", "service_name"),
        Index("ix_incidents_created", "created_at"),
        Index("ix_incidents_org_env", "organization_id", "environment_id"),
    )


class IncidentSignal(Base):
    __tablename__ = "incident_signals"
    __table_args__ = (
        Index("ix_incident_signals_fingerprint", "fingerprint", unique=True, postgresql_where="fingerprint IS NOT NULL"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False)
    source = Column(String(100), nullable=False)
    signal_type = Column(String(100), nullable=False)
    content = Column(JSON, nullable=True)
    fingerprint = Column(String(255), nullable=True)
    received_at = Column(DateTime(timezone=True), server_default=func.now())

    incident = relationship("Incident", back_populates="signals")


# ============================================================================
# DEPLOYMENT INVENTORY & WEBHOOKS (Phase 4)
# ============================================================================

class Deployment(Base):
    """
    Dynamic release event and deployment ledger record.
    Answers: what is deployed, where it is deployed, which commit is running, and lifecycle timing.
    """
    __tablename__ = "deployments"
    __table_args__ = (
        Index("ix_deployment_target_regional", "service_id", "environment_id", "region_id"),
        Index("ix_deployment_target_global", "service_id", "environment_id"),
        Index("ix_deployment_provider_event", "organization_id", "provider", "provider_event_id"),
        Index("ix_deployment_window", "organization_id", "service_id", "environment_id", "deployed_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True)
    environment_id = Column(UUID(as_uuid=True), ForeignKey("environments.id", ondelete="CASCADE"), nullable=False, index=True)
    region_id = Column(UUID(as_uuid=True), ForeignKey("regions.id", ondelete="SET NULL"), nullable=True, index=True)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True, index=True)

    commit_sha = Column(String(40), nullable=False, index=True)
    commit_message = Column(Text, nullable=True)
    version = Column(String(100), nullable=True)
    provider = Column(String(50), default="manual", nullable=False)
    provider_event_id = Column(String(255), nullable=True, index=True)
    external_deployment_id = Column(String(255), nullable=True)

    status = Column(SAEnum(DeploymentStatus), default=DeploymentStatus.PENDING, nullable=False, index=True)
    url = Column(String(1000), nullable=True)

    deployed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Float, nullable=True)

    deployed_by = Column(String(255), nullable=True)
    metadata_json = Column("metadata", JSON, default=dict, nullable=True)
    is_current = Column(Boolean, default=False, nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="deployments")
    service = relationship("Service", back_populates="deployments")
    environment = relationship("Environment", back_populates="deployments")
    region = relationship("Region", back_populates="deployments")
    repository = relationship("Repository", back_populates="deployments")
    incident = relationship("Incident", back_populates="deployment")


class WebhookEndpoint(Base):
    """
    Registered webhook endpoint for generic signed CI/CD pipelines and deployment ingestion.
    Stores encrypted secret for constant-time HMAC-SHA256 signature verification.
    """
    __tablename__ = "webhook_endpoints"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_webhook_endpoint_org_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    provider = Column(String(50), default="generic", nullable=False)
    auth_method = Column(String(50), default="bearer", nullable=False)
    key_id = Column(String(64), unique=True, nullable=False, index=True)
    encrypted_secret = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="webhook_endpoints")


# ============================================================================
# AUTONOMOUS MONITORING, DETECTION & TELEMETRY SIGNALS (Phase 5)
# ============================================================================

class TelemetrySignal(Base):
    """
    Ingested telemetry alert or anomaly signal from Prometheus, Sentry, Generic webhooks, or Health checks.
    """
    __tablename__ = "telemetry_signals"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider", "provider_event_id", name="uq_signal_provider_event"),
        Index("ix_signals_correlation", "organization_id", "correlation_key", "observed_at"),
        Index("ix_signals_target", "service_id", "environment_id", "observed_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(SAEnum(SignalProvider), nullable=False, index=True)
    provider_event_id = Column(String(255), nullable=False, index=True)
    signal_type = Column(SAEnum(SignalType), nullable=False, index=True)
    rule_name = Column(String(100), nullable=False, index=True)

    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id", ondelete="SET NULL"), nullable=True, index=True)
    environment_id = Column(UUID(as_uuid=True), ForeignKey("environments.id", ondelete="SET NULL"), nullable=True, index=True)
    region_id = Column(UUID(as_uuid=True), ForeignKey("regions.id", ondelete="SET NULL"), nullable=True, index=True)

    metric_name = Column(String(100), nullable=True)
    metric_value = Column(Float, nullable=True)
    threshold_value = Column(Float, nullable=True)

    fingerprint = Column(String(64), nullable=False, index=True)
    correlation_key = Column(String(255), nullable=False, index=True)

    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    error_signature = Column(String(255), nullable=True)
    raw_payload = Column(JSON, nullable=True)

    status = Column(SAEnum(SignalStatus), default=SignalStatus.INGESTED, nullable=False, index=True)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True)

    observed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    organization = relationship("Organization", back_populates="telemetry_signals")
    service = relationship("Service", back_populates="telemetry_signals")
    environment = relationship("Environment", back_populates="telemetry_signals")
    region = relationship("Region", back_populates="telemetry_signals")
    incident = relationship("Incident", back_populates="telemetry_signals")


class AlertRuleConfig(Base):
    """
    Per-organization configuration and threshold overrides for detection rules.
    """
    __tablename__ = "alert_rule_configs"
    __table_args__ = (
        UniqueConstraint("organization_id", "rule_name", name="uq_alert_rule_org_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_name = Column(String(100), nullable=False)
    is_enabled = Column(Boolean, default=True, nullable=False)
    threshold_value = Column(Float, nullable=True)
    window_minutes = Column(Integer, default=15, nullable=False)
    severity_override = Column(String(50), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="alert_rule_configs")


class ActiveIncidentCorrelationClaim(Base):
    """
    Database-level concurrency and race protection claim for active incident correlation keys.
    """
    __tablename__ = "active_incident_correlation_claims"
    __table_args__ = (
        UniqueConstraint("organization_id", "correlation_key", name="uq_active_correlation_claim"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    correlation_key = Column(String(255), nullable=False)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    claimed_at = Column(DateTime(timezone=True), server_default=func.now())

    incident = relationship("Incident", back_populates="correlation_claim")


class HealthCheckLog(Base):
    """
    Historical probe execution log for service health check polling.
    """
    __tablename__ = "health_check_logs"
    __table_args__ = (
        Index("ix_health_check_logs_probed", "service_id", "environment_id", "probed_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    config_id = Column(UUID(as_uuid=True), ForeignKey("service_deployment_configs.id", ondelete="CASCADE"), nullable=False, index=True)
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True)
    environment_id = Column(UUID(as_uuid=True), ForeignKey("environments.id", ondelete="CASCADE"), nullable=False, index=True)
    region_id = Column(UUID(as_uuid=True), ForeignKey("regions.id", ondelete="SET NULL"), nullable=True, index=True)

    url = Column(String(500), nullable=False)
    status_code = Column(Integer, nullable=True)
    latency_ms = Column(Float, nullable=True)
    is_healthy = Column(Boolean, nullable=False)
    error_message = Column(Text, nullable=True)
    probed_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    organization = relationship("Organization", back_populates="health_check_logs")
    deployment_config = relationship("ServiceDeploymentConfig", back_populates="health_check_logs")
    service = relationship("Service", back_populates="health_check_logs")
    environment = relationship("Environment", back_populates="health_check_logs")
    region = relationship("Region", back_populates="health_check_logs")


# ============================================================================
# SYSTEM SERVICE GRAPH & BLAST RADIUS (Phase 6)
# ============================================================================

class GraphNode(Base):
    """Multi-entity topology node representing services, repos, endpoints, databases, queues, etc."""
    __tablename__ = "graph_nodes"
    __table_args__ = (
        UniqueConstraint("organization_id", "node_type", "identifier", name="uq_graph_node_identifier"),
        Index("ix_graph_nodes_org_type", "organization_id", "node_type"),
        Index("ix_graph_nodes_entity", "organization_id", "entity_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    node_type = Column(SAEnum(GraphNodeType), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    identifier = Column(String(500), nullable=False, index=True)
    tier = Column(String(50), nullable=True)  # critical, high, medium, low
    entity_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # catalog entity ID (service_id, repo_id, team_id, etc.)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="graph_nodes")
    out_edges = relationship("GraphEdge", foreign_keys="GraphEdge.source_node_id", back_populates="source_node", cascade="all, delete-orphan")
    in_edges = relationship("GraphEdge", foreign_keys="GraphEdge.target_node_id", back_populates="target_node", cascade="all, delete-orphan")


class GraphEdge(Base):
    """Directed, attributed relationship between two graph topology nodes."""
    __tablename__ = "graph_edges"
    __table_args__ = (
        UniqueConstraint("organization_id", "source_node_id", "target_node_id", "edge_type", "source", name="uq_graph_edge"),
        Index("ix_graph_edges_src", "organization_id", "source_node_id"),
        Index("ix_graph_edges_tgt", "organization_id", "target_node_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    source_node_id = Column(UUID(as_uuid=True), ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    target_node_id = Column(UUID(as_uuid=True), ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    edge_type = Column(SAEnum(GraphEdgeType), nullable=False, index=True)
    source = Column(SAEnum(GraphEdgeSource), default=GraphEdgeSource.SERVICE_REGISTRATION, nullable=False, index=True)
    confidence = Column(Float, default=1.0, nullable=False)
    criticality = Column(SAEnum(ServiceCriticality), default=ServiceCriticality.HARD, nullable=False)
    is_stale = Column(Boolean, default=False, nullable=False)
    metadata_json = Column(JSON, nullable=True)  # observed_latency_p99_ms, error_rate, sample_count, last_observed_at
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="graph_edges")
    source_node = relationship("GraphNode", foreign_keys=[source_node_id], back_populates="out_edges")
    target_node = relationship("GraphNode", foreign_keys=[target_node_id], back_populates="in_edges")


class IncidentBlastRadiusReport(Base):
    """Immutable versioned blast radius analysis report snapshot for an incident."""
    __tablename__ = "incident_blast_radius_reports"
    __table_args__ = (
        Index("ix_blast_radius_incident", "organization_id", "incident_id", "version"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    root_service_id = Column(UUID(as_uuid=True), ForeignKey("services.id", ondelete="SET NULL"), nullable=True, index=True)

    version = Column(Integer, default=1, nullable=False)
    is_current = Column(Boolean, default=True, nullable=False, index=True)
    calculated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    engine_version = Column(String(50), default="v1.0.0", nullable=False)
    telemetry_window_minutes = Column(Integer, default=30, nullable=False)
    graph_snapshot_hash = Column(String(64), nullable=True)

    direct_services = Column(JSON, nullable=True)
    indirect_services = Column(JSON, nullable=True)
    affected_endpoints = Column(JSON, nullable=True)
    affected_repositories = Column(JSON, nullable=True)
    affected_environments = Column(JSON, nullable=True)
    affected_regions = Column(JSON, nullable=True)
    customer_impact = Column(JSON, nullable=True)  # {traffic_percent, user_percent, mode, confidence, calculation_basis}
    criticality_summary = Column(JSON, nullable=True)
    unknowns = Column(JSON, nullable=True)

    organization = relationship("Organization", back_populates="blast_radius_reports")
    incident = relationship("Incident", back_populates="blast_radius_reports")
    root_service = relationship("Service")


# ============================================================================
# CHANGE INTELLIGENCE & INCIDENT CORRELATION (Phase 7)
# ============================================================================

class ChangeEvent(Base):
    """
    Unified Change Intelligence record capturing code, configuration,
    infrastructure, feature flag, migration, and runtime changes.
    """
    __tablename__ = "change_events"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider", "change_type", "external_id", name="uq_change_event_idempotency"),
        Index("ix_change_events_org_effective", "organization_id", "effective_at"),
        Index("ix_change_events_service_effective", "organization_id", "service_id", "effective_at"),
        Index("ix_change_events_type_effective", "organization_id", "change_type", "effective_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id", ondelete="SET NULL"), nullable=True, index=True)
    environment_id = Column(UUID(as_uuid=True), ForeignKey("environments.id", ondelete="SET NULL"), nullable=True, index=True)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True, index=True)
    deployment_id = Column(UUID(as_uuid=True), ForeignKey("deployments.id", ondelete="SET NULL"), nullable=True, index=True)

    provider = Column(String(50), default="manual", nullable=False, index=True)
    provider_event_id = Column(String(255), nullable=True, index=True)
    auth_source = Column(String(50), nullable=True)
    integration_id = Column(UUID(as_uuid=True), nullable=True)

    change_type = Column(SAEnum(ChangeType, name="changetype", values_callable=lambda x: [e.name for e in x]), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    external_id = Column(String(255), nullable=False, index=True)
    commit_sha = Column(String(100), nullable=True, index=True)
    author = Column(String(255), nullable=True)
    risk_level = Column(SAEnum(ChangeRiskLevel, name="changerisklevel", values_callable=lambda x: [e.name for e in x]), default=ChangeRiskLevel.LOW, nullable=False)

    effective_at = Column(DateTime(timezone=True), nullable=False, index=True)
    observed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    source_url = Column(String(500), nullable=True)

    affected_components = Column(JSON, default=list, nullable=True)
    diff_summary = Column(JSON, default=dict, nullable=True)
    metadata_json = Column(JSON, default=dict, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    organization = relationship("Organization", back_populates="change_events")
    service = relationship("Service", back_populates="change_events")
    environment = relationship("Environment")
    repository = relationship("Repository", back_populates="change_events")
    deployment = relationship("Deployment")
    correlations = relationship("IncidentChangeCorrelation", back_populates="change_event", cascade="all, delete-orphan")


class IncidentChangeCorrelation(Base):
    """
    Directional, scored correlation link between an incident and a change event.
    """
    __tablename__ = "incident_change_correlations"
    __table_args__ = (
        UniqueConstraint("organization_id", "incident_id", "change_event_id", name="uq_incident_change_correlation"),
        Index("ix_incident_correlations_rank", "organization_id", "incident_id", "rank"),
        Index("ix_incident_correlations_score", "organization_id", "incident_id", "correlation_score"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    change_event_id = Column(UUID(as_uuid=True), ForeignKey("change_events.id", ondelete="CASCADE"), nullable=False, index=True)

    time_delta_seconds = Column(Integer, nullable=False)
    topological_distance = Column(Integer, default=0, nullable=False)
    correlation_score = Column(Float, nullable=False)
    rank = Column(Integer, default=1, nullable=False)

    is_causal_candidate = Column(Boolean, default=False, nullable=False, index=True)
    triage_status = Column(SAEnum(CorrelationStatus, name="correlationstatus", values_callable=lambda x: [e.name for e in x]), default=CorrelationStatus.COINCIDENTAL, nullable=False, index=True)
    triage_reason = Column(Text, nullable=True)
    triaged_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    triaged_at = Column(DateTime(timezone=True), nullable=True)
    previous_status = Column(String(50), nullable=True)

    reasoning = Column(Text, nullable=True)
    metadata_json = Column(JSON, default=dict, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="change_correlations")
    incident = relationship("Incident", back_populates="change_correlations")
    change_event = relationship("ChangeEvent", back_populates="correlations")
    triaged_by = relationship("User")


class IncidentChangeCorrelationReport(Base):
    """
    Immutable versioned change correlation analysis report snapshot for an incident.
    """
    __tablename__ = "incident_change_correlation_reports"
    __table_args__ = (
        Index("ix_change_corr_report_incident", "organization_id", "incident_id", "version"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)

    version = Column(Integer, default=1, nullable=False)
    is_current = Column(Boolean, default=True, nullable=False, index=True)
    calculated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    lookback_window_minutes = Column(Integer, default=120, nullable=False)
    snapshot_hash = Column(String(64), nullable=True)

    causal_candidates_count = Column(Integer, default=0, nullable=False)
    summary = Column(Text, nullable=True)
    correlations_snapshot = Column(JSON, nullable=True)
    metadata_json = Column(JSON, default=dict, nullable=True)

    organization = relationship("Organization", back_populates="change_correlation_reports")
    incident = relationship("Incident", back_populates="change_correlation_reports")


# ============================================================================
# INVESTIGATION (PRD §10-11)
# ============================================================================
# INVESTIGATION (PRD §10-11 & Phase 8 Workflows)
# ============================================================================

class Investigation(Base):
    __tablename__ = "investigations"
    __table_args__ = (
        Index("ix_investigations_org_status", "organization_id", "status"),
        Index("ix_investigations_incident", "organization_id", "incident_id"),
        Index("ix_investigations_work_item", "organization_id", "work_item_id"),
        UniqueConstraint("parent_investigation_id", "repository_id", name="uq_parent_child_repo"),
        UniqueConstraint("organization_id", "idempotency_key", name="uq_investigation_org_idempotency_key"),
    )


    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=True, index=True)
    work_item_id = Column(UUID(as_uuid=True), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True, index=True)
    parent_investigation_id = Column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=True, index=True)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True, index=True)

    repository_role = Column(String(50), nullable=True)  # primary_defect, downstream_affected, configuration, evidence_only
    base_commit_sha = Column(String(40), nullable=True)  # Nullable during initial discovery; verified 40-char SHA required for remediation
    is_parent = Column(Boolean, default=False, nullable=False)
    idempotency_key = Column(String(255), nullable=True, index=True)

    workflow_type = Column(String(50), default="production_incident", nullable=False, index=True)
    status = Column(SAEnum(InvestigationStatus, name="investigationstatus", values_callable=lambda x: [e.name for e in x]), default=InvestigationStatus.CREATED, nullable=False, index=True)

    current_step = Column(String(255), nullable=True)
    current_step_index = Column(Integer, default=0, nullable=False)
    total_steps = Column(Integer, default=1, nullable=False)
    progress_percent = Column(Integer, default=0, nullable=False)

    root_cause_found = Column(Boolean, default=False, nullable=False)
    abstained = Column(Boolean, default=False, nullable=False, index=True)
    abstention_reason = Column(Text, nullable=True)
    security_case_id = Column(String(100), nullable=True, index=True)
    confidence = Column(SAEnum(Confidence), nullable=True)

    llm_model = Column(String(100), nullable=True)
    total_tokens = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)

    plan_json = Column("plan", JSON, nullable=True)
    logs_json = Column(JSON, default=list, nullable=True)
    evidence_snapshot_id = Column(String(64), nullable=True)
    started_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="investigations")
    incident = relationship("Incident", back_populates="investigations")
    work_item = relationship("WorkItem")
    started_by = relationship("User")
    repository = relationship("Repository")
    children = relationship(
        "Investigation",
        backref=backref("parent", remote_side=[id]),
        cascade="all, delete-orphan",
        foreign_keys=[parent_investigation_id],
    )
    tasks = relationship("InvestigationTask", back_populates="investigation",
                         cascade="all, delete-orphan", order_by="InvestigationTask.order")
    evidence = relationship("Evidence", backref="investigation", cascade="all, delete-orphan",
                           foreign_keys="Evidence.investigation_id")
    hypotheses = relationship("Hypothesis", backref="investigation", cascade="all, delete-orphan",
                             foreign_keys="Hypothesis.investigation_id")
    root_causes = relationship("RootCause", backref="investigation", cascade="all, delete-orphan",
                              foreign_keys="RootCause.investigation_id")
    proposed_fixes = relationship("ProposedFix", backref="investigation", cascade="all, delete-orphan",
                                 foreign_keys="ProposedFix.investigation_id")



class InvestigationTask(Base):
    __tablename__ = "investigation_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True)
    step_name = Column(String(100), nullable=False, default="execution_step")
    task_type = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(SAEnum(TaskStatus), default=TaskStatus.PENDING, nullable=False)
    order = Column(Integer, default=0, nullable=False)

    tool_name = Column(String(100), nullable=True)
    tool_input = Column(JSON, nullable=True)
    tool_output = Column(JSON, nullable=True)
    result_json = Column(JSON, nullable=True)
    duration_ms = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)

    stepped_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    attempt = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    investigation = relationship("Investigation", back_populates="tasks")
    stepped_by = relationship("User")


# ============================================================================
# EVIDENCE (Phase 9 — Multi-Source Evidence Ledger)
# ============================================================================

class Evidence(Base):
    __tablename__ = "evidence"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=True, index=True)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="SET NULL"), nullable=True, index=True)
    work_item_id = Column(UUID(as_uuid=True), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True, index=True)

    source_type = Column(SAEnum(EvidenceSourceType), nullable=False)
    category_type = Column(SAEnum(EvidenceCategoryType), default=EvidenceCategoryType.FACT, nullable=False)
    evidence_family = Column(SAEnum(EvidenceFamily), nullable=True)

    source_id = Column(String(255), nullable=True)
    service = Column(String(255), nullable=True)
    environment = Column(String(100), nullable=True)
    region = Column(String(100), nullable=True)
    repository = Column(String(255), nullable=True)
    commit_sha = Column(String(40), nullable=True)
    file_path = Column(String(500), nullable=True)
    line_start = Column(Integer, nullable=True)
    line_end = Column(Integer, nullable=True)

    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)

    content_hash = Column(String(64), nullable=True)
    is_redacted = Column(Boolean, default=False)
    payload_size_bytes = Column(Integer, default=0)

    trust_level = Column(SAEnum(EvidenceTrustLevel), default=EvidenceTrustLevel.UNVERIFIED, nullable=False)
    verification_status = Column(SAEnum(EvidenceVerificationStatus), default=EvidenceVerificationStatus.VERIFIED, nullable=False)
    submitted_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    verified_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)

    version = Column(Integer, default=1, nullable=False)
    superseded_by_id = Column(UUID(as_uuid=True), ForeignKey("evidence.id", ondelete="SET NULL"), nullable=True)

    observed_at = Column(DateTime(timezone=True), nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=True)
    source_url = Column(String(500), nullable=True)

    relevance_score = Column(Float, nullable=True)
    retrieval_method = Column(String(100), nullable=True)
    metadata_json = Column("metadata", JSON, nullable=True)

    collected_at = Column(DateTime(timezone=True), server_default=func.now())

    organization = relationship("Organization", back_populates="evidence_items")
    incident = relationship("Incident", back_populates="evidence_items")
    hypothesis_links = relationship("HypothesisEvidence", back_populates="evidence", cascade="all, delete-orphan")
    submitted_by = relationship("User", foreign_keys=[submitted_by_user_id])
    verified_by = relationship("User", foreign_keys=[verified_by_user_id])

    __table_args__ = (
        Index("ix_evidence_org_incident", "organization_id", "incident_id"),
        Index("ix_evidence_source_type", "source_type"),
        Index("ix_evidence_category_type", "category_type"),
        Index("ix_evidence_content_hash", "content_hash"),
    )


@event.listens_for(Evidence.__table__, "after_create")
def create_evidence_immutability_triggers(target, connection, **kw):
    """Register PostgreSQL and SQLite database-level triggers to block direct SQL UPDATE and DELETE."""
    dialect_name = connection.dialect.name
    if dialect_name == "postgresql":
        connection.execute(sa.text("""
            CREATE OR REPLACE FUNCTION prevent_evidence_update_fn()
            RETURNS TRIGGER AS $$
            BEGIN
                IF (OLD.title IS DISTINCT FROM NEW.title OR
                    OLD.content IS DISTINCT FROM NEW.content OR
                    OLD.content_hash IS DISTINCT FROM NEW.content_hash OR
                    OLD.source_type IS DISTINCT FROM NEW.source_type OR
                    OLD.category_type IS DISTINCT FROM NEW.category_type OR
                    OLD.service IS DISTINCT FROM NEW.service OR
                    OLD.repository IS DISTINCT FROM NEW.repository OR
                    OLD.commit_sha IS DISTINCT FROM NEW.commit_sha OR
                    OLD.file_path IS DISTINCT FROM NEW.file_path OR
                    OLD.payload_size_bytes IS DISTINCT FROM NEW.payload_size_bytes OR
                    OLD.organization_id IS DISTINCT FROM NEW.organization_id OR
                    OLD.incident_id IS DISTINCT FROM NEW.incident_id OR
                    OLD.observed_at IS DISTINCT FROM NEW.observed_at) THEN
                    RAISE EXCEPTION 'Evidence records are immutable and append-only. Direct SQL UPDATE blocked on table evidence.';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS trg_evidence_prevent_update ON evidence;
            CREATE TRIGGER trg_evidence_prevent_update
            BEFORE UPDATE ON evidence
            FOR EACH ROW
            EXECUTE FUNCTION prevent_evidence_update_fn();

            CREATE OR REPLACE FUNCTION prevent_evidence_delete_fn()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'Evidence records are immutable and cannot be deleted. Direct SQL DELETE blocked on table evidence.';
            END;
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS trg_evidence_prevent_delete ON evidence;
            CREATE TRIGGER trg_evidence_prevent_delete
            BEFORE DELETE ON evidence
            FOR EACH ROW
            EXECUTE FUNCTION prevent_evidence_delete_fn();
        """))
    elif dialect_name == "sqlite":
        connection.execute(sa.text("""
            CREATE TRIGGER IF NOT EXISTS trg_evidence_prevent_update
            BEFORE UPDATE ON evidence
            FOR EACH ROW
            WHEN (
                OLD.title IS NOT NEW.title OR
                OLD.content IS NOT NEW.content OR
                OLD.content_hash IS NOT NEW.content_hash OR
                OLD.source_type IS NOT NEW.source_type OR
                OLD.category_type IS NOT NEW.category_type OR
                OLD.service IS NOT NEW.service OR
                OLD.repository IS NOT NEW.repository OR
                OLD.commit_sha IS NOT NEW.commit_sha OR
                OLD.file_path IS NOT NEW.file_path OR
                OLD.payload_size_bytes IS NOT NEW.payload_size_bytes OR
                OLD.organization_id IS NOT NEW.organization_id OR
                OLD.incident_id IS NOT NEW.incident_id OR
                OLD.observed_at IS NOT NEW.observed_at
            )
            BEGIN
                SELECT RAISE(ABORT, 'Evidence records are immutable and append-only. Direct SQL UPDATE blocked on table evidence.');
            END;
        """))
        connection.execute(sa.text("""
            CREATE TRIGGER IF NOT EXISTS trg_evidence_prevent_delete
            BEFORE DELETE ON evidence
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'Evidence records are immutable and cannot be deleted. Direct SQL DELETE blocked on table evidence.');
            END;
        """))


@event.listens_for(Evidence, "before_update")
def enforce_evidence_immutability(mapper, connection, target):
    """Enforce append-only evidence immutability at the ORM layer."""
    immutable_fields = [
        "content", "content_hash", "source_type", "category_type",
        "incident_id", "organization_id", "observed_at", "repository", "commit_sha"
    ]
    for field_name in immutable_fields:
        hist = get_history(target, field_name)
        if hist.has_changes():
            raise ValueError(
                f"Evidence record is immutable. Field '{field_name}' cannot be modified. "
                f"Create a new evidence version with superseded_by_id instead."
            )


@event.listens_for(Evidence, "before_delete")
def block_evidence_deletion(mapper, connection, target):
    """Enforce append-only evidence retention at the ORM layer."""
    if not getattr(target, "_admin_delete_allowed", False):
        raise ValueError(
            "Evidence records are append-only and cannot be deleted. "
            "Deletion is restricted to authorized administrative compliance actions."
        )


# ============================================================================
# HYPOTHESIS (Phase 9 — Competing Hypothesis Matrix)
# ============================================================================

class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=True, index=True)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="SET NULL"), nullable=True, index=True)
    work_item_id = Column(UUID(as_uuid=True), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True, index=True)

    label = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(SAEnum(HypothesisStatus), default=HypothesisStatus.PROPOSED, nullable=False)
    confidence = Column(SAEnum(Confidence), default=Confidence.INSUFFICIENT, nullable=False)

    temporal_fit = Column(Boolean, default=True, nullable=False)
    temporal_fit_score = Column(Float, default=1.0, nullable=False)
    code_path_fit = Column(Boolean, default=True, nullable=False)
    code_path_fit_score = Column(Float, default=1.0, nullable=False)
    operational_fit = Column(Boolean, default=True, nullable=False)
    operational_fit_score = Column(Float, default=1.0, nullable=False)

    distinct_families_count = Column(Integer, default=0, nullable=False)
    supporting_evidence_count = Column(Integer, default=0, nullable=False)
    contradicting_evidence_count = Column(Integer, default=0, nullable=False)
    missing_evidence_count = Column(Integer, default=0, nullable=False)

    supporting_evidence_ids = Column(JSON, default=list, nullable=True)
    contradicting_evidence_ids = Column(JSON, default=list, nullable=True)
    missing_evidence_json = Column(JSON, default=list, nullable=True)

    disproof_attempt_notes = Column(Text, nullable=True)
    disproven_at = Column(DateTime(timezone=True), nullable=True)

    human_triaged = Column(Boolean, default=False, nullable=False)
    human_triage_notes = Column(Text, nullable=True)
    triaged_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    evaluation_notes = Column(Text, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    evaluated_at = Column(DateTime(timezone=True), nullable=True)

    organization = relationship("Organization", back_populates="hypotheses")
    incident = relationship("Incident", back_populates="hypotheses")
    evidence_links = relationship("HypothesisEvidence", back_populates="hypothesis", cascade="all, delete-orphan")
    triaged_by = relationship("User")

    __table_args__ = (
        Index("ix_hypotheses_org_incident", "organization_id", "incident_id"),
        Index("ix_hypotheses_status", "status"),
    )


class HypothesisEvidence(Base):
    __tablename__ = "hypothesis_evidence"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hypothesis_id = Column(UUID(as_uuid=True), ForeignKey("hypotheses.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_id = Column(UUID(as_uuid=True), ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False, index=True)
    link_type = Column(String(50), nullable=False)  # "supporting", "contradicting", "correlated", "neutral"
    confidence_weight = Column(Float, default=1.0)
    notes = Column(Text, nullable=True)

    hypothesis = relationship("Hypothesis", back_populates="evidence_links")
    evidence = relationship("Evidence", back_populates="hypothesis_links")


# ============================================================================
# ROOT CAUSE (Phase 9 — Root Cause Analysis & Abstention)
# ============================================================================

class RootCause(Base):
    __tablename__ = "root_causes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=True, index=True)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="SET NULL"), nullable=True, index=True)
    work_item_id = Column(UUID(as_uuid=True), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True, index=True)

    summary = Column(Text, nullable=False)
    affected_component = Column(String(255), nullable=True)
    causal_explanation = Column(Text, nullable=False)
    confidence = Column(SAEnum(Confidence), nullable=False)

    supporting_evidence_ids = Column(JSON, default=list, nullable=True)
    contradicting_evidence_ids = Column(JSON, default=list, nullable=True)
    evidence_sources_count = Column(Integer, default=0, nullable=False)
    distinct_families_count = Column(Integer, default=0, nullable=False)
    disproof_summary = Column(Text, nullable=True)

    timeline = Column(JSON, nullable=True)
    relevant_commits = Column(JSON, nullable=True)
    relevant_files = Column(JSON, nullable=True)

    abstained = Column(Boolean, default=False, nullable=False)
    abstention_reason = Column(Text, nullable=True)
    missing_evidence_json = Column(JSON, default=list, nullable=True)

    evaluation_version = Column(Integer, default=1, nullable=False)
    snapshot_hash = Column(String(64), nullable=True)
    is_current = Column(Boolean, default=True, nullable=False)

    human_overridden = Column(Boolean, default=False, nullable=False)
    human_override_notes = Column(Text, nullable=True)
    overridden_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    identified_at = Column(DateTime(timezone=True), server_default=func.now())

    organization = relationship("Organization", back_populates="root_causes")
    incident = relationship("Incident", back_populates="root_causes")
    overridden_by = relationship("User")

    __table_args__ = (
        Index("ix_root_causes_org_incident", "organization_id", "incident_id"),
        Index("ix_root_causes_is_current", "is_current"),
        Index(
            "uq_root_causes_incident_current",
            "incident_id",
            unique=True,
            sqlite_where=text("is_current = 1"),
            postgresql_where=text("is_current = true"),
        ),
    )


# ============================================================================
# INCIDENT MEMORY & POST-MORTEM (Phase 10)
# ============================================================================

class PostMortem(Base):
    """
    Blameless SRE Post-Mortem record synthesizing incident facts, timeline,
    root cause causality, and preventive action items.
    """
    __tablename__ = "post_mortems"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    work_item_id = Column(UUID(as_uuid=True), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True, index=True)
    author_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    signed_off_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    title = Column(String(500), nullable=False)
    summary = Column(Text, nullable=False)
    root_cause_summary = Column(Text, nullable=False)
    impact_summary = Column(Text, nullable=True)
    trigger_event = Column(Text, nullable=True)
    detection_summary = Column(Text, nullable=True)
    resolution_summary = Column(Text, nullable=True)

    contributing_factors_json = Column(JSON, default=list, nullable=True)
    timeline_summary_json = Column(JSON, default=list, nullable=True)
    lessons_learned_json = Column(JSON, default=list, nullable=True)

    time_to_detect_seconds = Column(Integer, nullable=True)
    time_to_acknowledge_seconds = Column(Integer, nullable=True)
    time_to_root_cause_seconds = Column(Integer, nullable=True)
    time_to_mitigate_seconds = Column(Integer, nullable=True)
    time_to_resolve_seconds = Column(Integer, nullable=True)
    downtime_minutes = Column(Float, default=0.0)
    affected_user_count_estimate = Column(Integer, nullable=True)
    slo_impact_percent = Column(Float, nullable=True)

    resolution_type = Column(String(50), default="code_fix")
    severity_actual = Column(String(20), default="SEV-2")
    status = Column(SAEnum(PostMortemStatus), default=PostMortemStatus.DRAFT, nullable=False)
    snapshot_hash = Column(String(64), nullable=True)
    abstained = Column(Boolean, default=False, nullable=False)
    human_reviewed = Column(Boolean, default=False, nullable=False)
    is_current = Column(Boolean, default=True, nullable=False)
    version = Column(Integer, default=1, nullable=False)

    memory_indexing_status = Column(SAEnum(MemoryIndexingStatus), default=MemoryIndexingStatus.PENDING, nullable=False)
    memory_indexing_error = Column(Text, nullable=True)

    signed_off_at = Column(DateTime(timezone=True), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="post_mortems")
    incident = relationship("Incident", back_populates="post_mortems")
    work_item = relationship("WorkItem")
    author = relationship("User", foreign_keys=[author_id])
    signed_off_by = relationship("User", foreign_keys=[signed_off_by_user_id])
    action_items = relationship("PostMortemActionItem", back_populates="post_mortem", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("organization_id", "incident_id", "version", name="uq_post_mortems_org_incident_version"),
        Index("ix_post_mortems_org_incident", "organization_id", "incident_id"),
        Index("ix_post_mortems_status", "status"),
        Index(
            "uq_post_mortems_incident_current",
            "incident_id",
            unique=True,
            sqlite_where=text("is_current = 1"),
            postgresql_where=text("is_current = true"),
        ),
    )


class PostMortemActionItem(Base):
    """
    Action item / preventive follow-up task stemming from an incident post-mortem.
    """
    __tablename__ = "post_mortem_action_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    post_mortem_id = Column(UUID(as_uuid=True), ForeignKey("post_mortems.id", ondelete="CASCADE"), nullable=False, index=True)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=True, index=True)
    assigned_to_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(SAEnum(ActionItemCategory), default=ActionItemCategory.CODE_HARDENING, nullable=False)
    priority = Column(SAEnum(ActionItemPriority), default=ActionItemPriority.P2, nullable=False)
    status = Column(SAEnum(ActionItemStatus), default=ActionItemStatus.OPEN, nullable=False)

    due_date = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    external_issue_url = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="post_mortem_action_items")
    post_mortem = relationship("PostMortem", back_populates="action_items")
    incident = relationship("Incident", back_populates="post_mortem_action_items")
    assigned_to = relationship("User", foreign_keys=[assigned_to_user_id])
    created_by = relationship("User", foreign_keys=[created_by_user_id])

    __table_args__ = (
        Index("ix_action_items_org_status", "organization_id", "status"),
        Index("ix_action_items_post_mortem", "post_mortem_id"),
    )


# ============================================================================
# FIX / REMEDIATION (PRD §25-27, Phase 11)
# ============================================================================

class ProposedFix(Base):
    __tablename__ = "proposed_fixes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="SET NULL"), nullable=True, index=True)
    work_item_id = Column(UUID(as_uuid=True), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True, index=True)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True, index=True)
    root_cause_id = Column(UUID(as_uuid=True), ForeignKey("root_causes.id", ondelete="SET NULL"), nullable=True)

    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=False)
    fix_type = Column(String(100), nullable=True)
    problem = Column(Text, nullable=True)
    root_cause = Column(Text, nullable=True)
    proposed_change = Column(Text, nullable=False)
    expected_behavior = Column(Text, nullable=True)
    risk = Column(Text, nullable=True)
    validation_strategy = Column(Text, nullable=True)
    status = Column(String(50), default=FixStatus.GENERATED.value, nullable=False)

    repository = Column(String(500), nullable=True)
    base_commit_sha = Column(String(40), nullable=True)
    target_branch = Column(String(255), nullable=True, default="main")
    diff = Column(Text, nullable=True)
    patch_json = Column(JSON, nullable=True)
    scope_files_json = Column(JSON, nullable=True)
    tests_to_add_json = Column(JSON, nullable=True)
    tests_to_run_json = Column(JSON, nullable=True)
    rollback_plan = Column(Text, nullable=True)
    regression_test_status = Column(String(50), default=RegressionTestStatus.PENDING.value, nullable=False)
    
    is_rejected = Column(Boolean, default=False, nullable=False)
    rejection_reason = Column(Text, nullable=True)
    snapshot_hash = Column(String(64), nullable=True)
    patch_schema_version = Column(Integer, default=1, nullable=False)
    version = Column(Integer, default=1, nullable=False)

    branch_name = Column(String(255), nullable=True)
    pr_number = Column(Integer, nullable=True)
    pr_url = Column(String(500), nullable=True)

    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization")
    incident = relationship("Incident", back_populates="proposed_fixes")
    work_item = relationship("WorkItem")
    repository_rel = relationship("Repository")
    root_cause = relationship("RootCause")
    files = relationship("FixFile", back_populates="fix", cascade="all, delete-orphan")
    validations = relationship("ValidationRun", back_populates="fix", cascade="all, delete-orphan")
    generated_tests = relationship("GeneratedTest", back_populates="fix", cascade="all, delete-orphan")
    versions = relationship("PatchVersion", back_populates="fix", cascade="all, delete-orphan")
    approvals = relationship("Approval", back_populates="fix", cascade="all, delete-orphan")



class GeneratedTest(Base):
    __tablename__ = "generated_tests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    fix_id = Column(UUID(as_uuid=True), ForeignKey("proposed_fixes.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path = Column(String(500), nullable=False)
    test_type = Column(SAEnum(TestType), default=TestType.REGRESSION, nullable=False)
    framework = Column(String(50), default="pytest", nullable=False)
    test_name = Column(String(255), nullable=False)
    test_code = Column(Text, nullable=False)
    target_symbol = Column(String(255), nullable=True)
    pre_patch_result = Column(String(50), nullable=True)
    post_patch_result = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    organization = relationship("Organization")
    fix = relationship("ProposedFix", back_populates="generated_tests")


class PatchVersion(Base):
    __tablename__ = "patch_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    fix_id = Column(UUID(as_uuid=True), ForeignKey("proposed_fixes.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, default=1, nullable=False)
    editor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    patch_data_json = Column(JSON, nullable=False)
    diff_content = Column(Text, nullable=True)
    previous_snapshot_hash = Column(String(64), nullable=True)
    new_snapshot_hash = Column(String(64), nullable=False)
    revalidation_status = Column(String(50), default=RevalidationStatus.PENDING.value, nullable=False)
    revalidation_details_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    organization = relationship("Organization")
    fix = relationship("ProposedFix", back_populates="versions")
    editor = relationship("User")


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
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True, index=True)
    base_commit_sha = Column(String(64), nullable=False)
    verified_base_sha = Column(String(64), nullable=True)
    workspace_id = Column(String(64), nullable=False)
    status = Column(SAEnum(ValidationStatus), default=ValidationStatus.PENDING)

    total_checks = Column(Integer, default=0)
    passed_checks = Column(Integer, default=0)
    failed_checks = Column(Integer, default=0)

    compilation_status = Column(String(20), default="pending")
    tests_status = Column(String(20), default="pending")
    original_failure_reproduced = Column(String(10), default="n/a")
    failure_absent_after_patch = Column(String(10), default="n/a")
    scenario_replay_status = Column(String(20), default="n/a")
    production_outcome = Column(String(50), default="unknown until deployed")
    overall_status = Column(String(20), default="pending")

    lint_result = Column(JSON, nullable=True)
    test_result = Column(JSON, nullable=True)
    build_result = Column(JSON, nullable=True)
    security_result = Column(JSON, nullable=True)
    summary_report_json = Column(JSON, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    fix = relationship("ProposedFix", back_populates="validations")
    organization = relationship("Organization")
    repository = relationship("Repository")
    check_runs = relationship("ValidationCheckRun", back_populates="validation_run", cascade="all, delete-orphan", order_by="ValidationCheckRun.started_at")


class ValidationCheckRun(Base):
    __tablename__ = "validation_check_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    validation_run_id = Column(UUID(as_uuid=True), ForeignKey("validation_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    check_type = Column(SAEnum(ValidationCheckType), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    command_json = Column(JSON, nullable=False)
    status = Column(SAEnum(ValidationCheckStatus), default=ValidationCheckStatus.PENDING)
    exit_code = Column(Integer, nullable=True)
    stdout = Column(Text, nullable=True)
    stderr = Column(Text, nullable=True)
    duration_ms = Column(Float, default=0.0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    validation_run = relationship("ValidationRun", back_populates="check_runs")
    organization = relationship("Organization")


# ============================================================================
# APPROVAL & POLICY GATEWAY (PRD §28, §63)
# ============================================================================

class Approval(Base):
    __tablename__ = "approvals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True)

    fix_id = Column(UUID(as_uuid=True), ForeignKey("proposed_fixes.id", ondelete="CASCADE"), nullable=True, index=True)
    work_item_id = Column(UUID(as_uuid=True), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    action_type = Column(String(50), default="create_draft_pr", nullable=False, index=True)
    status = Column(SAEnumVal(ApprovalStatus), default=ApprovalStatus.PENDING, nullable=False, index=True)
    risk_level = Column(String(20), default="low", nullable=False)

    patch_version = Column(Integer, default=1, nullable=False)
    snapshot_hash = Column(String(64), nullable=True)
    base_commit_sha = Column(String(40), nullable=True)
    validation_run_id = Column(UUID(as_uuid=True), ForeignKey("validation_runs.id", ondelete="SET NULL"), nullable=True, index=True)

    required_approvals = Column(Integer, default=1, nullable=False)
    approvals_received = Column(Integer, default=0, nullable=False)

    compliance_checklist_json = Column(JSON, nullable=True)
    decisions_json = Column(JSON, nullable=True)

    notes = Column(Text, nullable=True)
    modified_diff = Column(Text, nullable=True)

    requested_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization")
    incident = relationship("Incident")
    fix = relationship("ProposedFix", back_populates="approvals")
    work_item = relationship("WorkItem")
    user = relationship("User", back_populates="approvals")
    validation_run = relationship("ValidationRun")
    decisions = relationship("ApprovalDecision", back_populates="approval", cascade="all, delete-orphan")


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"
    __table_args__ = (
        UniqueConstraint("approval_id", "approver_id", name="uq_approval_decision_user"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    approval_id = Column(UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="CASCADE"), nullable=False, index=True)
    approver_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    decision = Column(String(50), nullable=False)
    role = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    approval = relationship("Approval", back_populates="decisions")
    approver = relationship("User")
    organization = relationship("Organization")


class PolicyRule(Base):
    __tablename__ = "policy_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    action_type = Column(String(50), nullable=False, index=True)
    decision = Column(String(50), nullable=False)

    conditions_json = Column(JSON, nullable=True)
    required_approvals_count = Column(Integer, default=1, nullable=False)
    required_roles_json = Column(JSON, nullable=True)
    priority = Column(Integer, default=100, nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)
    is_mandatory = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization")


class PolicyEvaluation(Base):
    __tablename__ = "policy_evaluations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    action_type = Column(String(50), nullable=False, index=True)
    target_entity_type = Column(String(50), nullable=False)
    target_entity_id = Column(UUID(as_uuid=True), nullable=True)

    patch_version = Column(Integer, nullable=True)
    snapshot_hash = Column(String(64), nullable=True)

    decision = Column(String(50), nullable=False)
    matched_rule_id = Column(UUID(as_uuid=True), ForeignKey("policy_rules.id", ondelete="SET NULL"), nullable=True)

    reasons_json = Column(JSON, nullable=True)
    context_snapshot_json = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    organization = relationship("Organization")
    user = relationship("User")
    matched_rule = relationship("PolicyRule")



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


# ============================================================================
# MULTI-REPOSITORY REMEDIATION (PRD §9, §15.3, Phase 14)
# ============================================================================

class MultiRepoRemediationPlan(Base):
    """Coordinated multi-repository remediation plan for cross-service incidents."""
    __tablename__ = "remediation_plans"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_remediation_plan_org_idempotency_key"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_investigation_id = Column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="SET NULL"), nullable=True, index=True)

    status = Column(SAEnumVal(RemediationPlanStatus), default=RemediationPlanStatus.DRAFT, nullable=False, index=True)
    title = Column(String(500), nullable=False)
    summary = Column(Text, nullable=False)
    
    dependency_order_json = Column(JSON, default=list, nullable=True)
    cycle_detected = Column(Boolean, default=False, nullable=False)
    cycle_details_json = Column(JSON, nullable=True)
    cross_repo_rollback_plan = Column(Text, nullable=True)
    idempotency_key = Column(String(255), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization")
    incident = relationship("Incident")
    parent_investigation = relationship("Investigation")
    items = relationship("RemediationPlanItem", back_populates="plan", cascade="all, delete-orphan", order_by="RemediationPlanItem.execution_order")


class RemediationPlanItem(Base):
    """Individual repository remediation item within a coordinated plan."""
    __tablename__ = "remediation_plan_items"
    __table_args__ = (
        UniqueConstraint("plan_id", "repository_id", name="uq_plan_repo"),
        UniqueConstraint("organization_id", "pr_idempotency_key", name="uq_remediation_item_org_pr_idempotency"),
    )


    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("remediation_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="RESTRICT"), nullable=False, index=True)
    repository_role = Column(String(50), default="primary_defect", nullable=False)

    investigation_id = Column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="SET NULL"), nullable=True)
    fix_id = Column(UUID(as_uuid=True), ForeignKey("proposed_fixes.id", ondelete="SET NULL"), nullable=True)
    execution_order = Column(Integer, default=1, nullable=False)
    requires_code_change = Column(Boolean, default=True, nullable=False)

    validation_run_id = Column(UUID(as_uuid=True), ForeignKey("validation_runs.id", ondelete="SET NULL"), nullable=True)
    validation_status = Column(String(50), default="pending", nullable=False)
    
    approval_id = Column(UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="SET NULL"), nullable=True)
    approval_status = Column(String(50), default="pending", nullable=False)
    patch_version = Column(Integer, nullable=True)
    snapshot_hash = Column(String(64), nullable=True)
    base_commit_sha = Column(String(40), nullable=True)

    pr_idempotency_key = Column(String(255), nullable=True, index=True)
    pr_status = Column(String(50), default="pending", nullable=False)  # pending, created, failed, skipped_evidence_only
    pr_url = Column(String(500), nullable=True)
    pr_number = Column(Integer, nullable=True)
    commit_sha = Column(String(40), nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization")
    plan = relationship("MultiRepoRemediationPlan", back_populates="items")
    repository = relationship("Repository")
    investigation = relationship("Investigation")
    fix = relationship("ProposedFix")
    validation_run = relationship("ValidationRun")
    approval = relationship("Approval")


# =============================================================================
# PHASE 16: ADVANCED RELIABILITY, SLO TRACKING & PREDICTION MODELS
# =============================================================================

class SLOConfig(Base):
    """Service Level Objective configuration per service."""
    __tablename__ = "slo_configs"
    __table_args__ = (
        UniqueConstraint("organization_id", "service_id", "name", name="uq_slo_org_service_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String(200), nullable=False)
    target_percent = Column(Float, default=99.9, nullable=False)  # e.g. 99.9%
    sli_type = Column(String(50), default="availability", nullable=False)  # availability, latency, error_rate
    threshold_value = Column(Float, nullable=True)  # e.g. 200.0 ms for latency, 0.1 % for error rate
    window_days = Column(Integer, default=30, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization")
    service = relationship("Service")
    snapshots = relationship("SLOBurnRateSnapshot", back_populates="slo", cascade="all, delete-orphan")


class SLOBurnRateSnapshot(Base):
    """Hourly multi-window error budget burn rate snapshot for an SLO."""
    __tablename__ = "slo_burn_rate_snapshots"
    __table_args__ = (
        UniqueConstraint("slo_id", "captured_hour", name="uq_slo_snapshot_hour"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slo_id = Column(UUID(as_uuid=True), ForeignKey("slo_configs.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    compliance_percent = Column(Float, nullable=True)
    burn_rate_1h = Column(Float, nullable=True)
    burn_rate_6h = Column(Float, nullable=True)
    burn_rate_24h = Column(Float, nullable=True)
    budget_remaining_percent = Column(Float, nullable=True)
    time_to_exhaustion_hours = Column(Float, nullable=True)
    captured_hour = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(String(50), default="healthy", nullable=False)  # healthy, warning, critical_burn, exhausted, insufficient_data

    captured_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    slo = relationship("SLOConfig", back_populates="snapshots")
    organization = relationship("Organization")


class PredictiveAnomaly(Base):
    """Statistically projected resource exhaustion or telemetry anomaly."""
    __tablename__ = "predictive_anomalies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True)

    metric_name = Column(String(100), nullable=False, index=True)
    current_value = Column(Float, nullable=False)
    threshold_value = Column(Float, nullable=False)
    projected_breach_at = Column(DateTime(timezone=True), nullable=True)
    time_to_breach_minutes = Column(Float, nullable=False)
    growth_rate_per_minute = Column(Float, nullable=False)
    r_squared = Column(Float, nullable=False, default=1.0)
    confidence_score = Column(Float, nullable=False, default=1.0)
    severity = Column(String(50), default="WARNING", nullable=False)  # WARNING, CRITICAL, CRITICAL_BREACH_ACTIVE
    is_active = Column(Boolean, default=True, nullable=False)
    status = Column(String(50), default="ACTIVE", nullable=False)  # ACTIVE, ACKNOWLEDGED, RESOLVED
    recommendation = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization")
    service = relationship("Service")


class BusinessImpactConfig(Base):
    """Configured financial revenue baseline and user weightings per service."""
    __tablename__ = "business_impact_configs"
    __table_args__ = (
        UniqueConstraint("organization_id", "service_id", name="uq_business_impact_org_service"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"), nullable=True, index=True)

    tier = Column(String(50), nullable=True)  # tier_1, tier_2, tier_3 or None for org default
    hourly_revenue_rate_usd = Column(Float, nullable=False, default=0.0)
    active_users_baseline = Column(Integer, nullable=False, default=1000)
    currency = Column(String(10), default="USD", nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization")
    service = relationship("Service")


class IncidentBusinessImpact(Base):
    """Financial loss and customer impact quantification for an incident."""
    __tablename__ = "incident_business_impacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    estimated_financial_loss_usd = Column(Float, nullable=True)
    affected_user_count = Column(Integer, nullable=False, default=0)
    degradation_factor = Column(Float, nullable=False, default=1.0)
    sla_breach_detected = Column(Boolean, default=False, nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    is_estimated_default = Column(Boolean, default=False, nullable=False)

    calculated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    incident = relationship("Incident")
    organization = relationship("Organization")


# ============================================================================
# SECURITY INCIDENT RESPONSE & FORENSIC QUARANTINE (Phase 17)
# ============================================================================

class SecurityCase(Base):
    """
    Dedicated Security Incident Case.
    Enforces forensic evidence preservation, scoped blast-radius containment,
    security ownership routing, and zero autonomous production mutation.
    """
    __tablename__ = "security_cases"
    __table_args__ = (
        UniqueConstraint("organization_id", "case_number", name="uq_security_case_org_number"),
        Index("ix_security_cases_org_status", "organization_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True)
    work_item_id = Column(UUID(as_uuid=True), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True)

    case_number = Column(String(50), nullable=False)  # e.g., SEC-2026-0042
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=False, default="CUSTOM")  # CREDENTIAL_LEAK, SUSPICIOUS_AUTH, PRIVILEGE_ESCALATION, UNUSUAL_DATA_ACCESS, VULNERABLE_DEPENDENCY, MALWARE_SUSPECTED, CUSTOM
    severity = Column(String(20), nullable=False, default="HIGH")  # CRITICAL, HIGH, MEDIUM, LOW
    status = Column(String(30), nullable=False, default="DETECTED")  # DETECTED, CONTAINING, CONTAINED, INVESTIGATING, REMEDIATING, RESOLVED, CLOSED
    containment_status = Column(String(30), nullable=False, default="NOT_STARTED")  # NOT_STARTED, PROPOSED, APPROVED, EXECUTING, CONTAINED, FAILED

    scope_summary_json = Column(JSON, nullable=True)
    security_lead_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolution_summary = Column(Text, nullable=True)

    contained_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization")
    incident = relationship("Incident")
    security_lead = relationship("User", foreign_keys=[security_lead_id])
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    evidence_snapshot = relationship("SecurityEvidenceSnapshot", back_populates="security_case", uselist=False, cascade="all, delete-orphan")
    containment_actions = relationship("SecurityContainmentAction", back_populates="security_case", cascade="all, delete-orphan", order_by="SecurityContainmentAction.created_at.desc()")
    audit_chain_entries = relationship("SecurityForensicAuditChain", back_populates="security_case", cascade="all, delete-orphan", order_by="SecurityForensicAuditChain.sequence_number.asc()")


class SecurityEvidenceSnapshot(Base):
    """
    Cryptographically sealed, immutable forensic snapshot manifest.
    Contains captured logs, telemetry signals, commit diffs, and environment references.
    Protected against updates and deletions at database trigger and application levels.
    """
    __tablename__ = "security_evidence_snapshots"
    __table_args__ = (
        UniqueConstraint("security_case_id", name="uq_sec_evidence_case"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    security_case_id = Column(UUID(as_uuid=True), ForeignKey("security_cases.id", ondelete="CASCADE"), nullable=False, index=True)

    manifest_hash = Column(String(64), nullable=False)  # SHA-256 digest
    manifest_json = Column(JSON, nullable=False)
    completeness_status = Column(String(30), nullable=False, default="COMPLETE")  # COMPLETE, PARTIAL_SIGNAL_TIMEOUT, DEGRADED
    captured_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    sealed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    organization = relationship("Organization")
    security_case = relationship("SecurityCase", back_populates="evidence_snapshot")
    captured_by = relationship("User")


class SecurityContainmentAction(Base):
    """
    Structured, scoped containment action requiring explicit dual sign-off.
    Autonomous mutation without 2 distinct officer approvals is strictly prohibited.
    """
    __tablename__ = "security_containment_actions"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_sec_action_org_idempotency"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    security_case_id = Column(UUID(as_uuid=True), ForeignKey("security_cases.id", ondelete="CASCADE"), nullable=False, index=True)

    idempotency_key = Column(String(100), nullable=True, index=True)
    action_type = Column(String(50), nullable=False)  # REVOKE_CREDENTIAL, QUARANTINE_SERVICE, BLOCK_IDENTITY, LOCK_DEPENDENCY, ROTATE_SECRET, CUSTOM_PLAYBOOK
    target_type = Column(String(50), nullable=False)  # service, user, secret, repository, network_ip
    target_id = Column(String(255), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    parameters_json = Column(JSON, nullable=True)

    status = Column(String(30), nullable=False, default="PROPOSED")  # PROPOSED, PENDING_SECOND_APPROVAL, APPROVED, REJECTED, REVOKED, EXPIRED, EXECUTING, EXECUTED, FAILED
    is_automated_blocked = Column(Boolean, default=True, nullable=False)

    proposed_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approver_1_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approver_1_at = Column(DateTime(timezone=True), nullable=True)
    approver_2_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approver_2_at = Column(DateTime(timezone=True), nullable=True)

    approval_expires_at = Column(DateTime(timezone=True), nullable=True)
    execution_lease_until = Column(DateTime(timezone=True), nullable=True)
    execution_output = Column(Text, nullable=True)
    rollback_status = Column(String(30), default="NOT_APPLICABLE", nullable=False)  # NOT_APPLICABLE, READY, ROLLED_BACK, ROLLBACK_FAILED
    executed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    organization = relationship("Organization")
    security_case = relationship("SecurityCase", back_populates="containment_actions")
    proposed_by = relationship("User", foreign_keys=[proposed_by_user_id])
    approver_1 = relationship("User", foreign_keys=[approver_1_user_id])
    approver_2 = relationship("User", foreign_keys=[approver_2_user_id])


class SecurityForensicAuditChain(Base):
    """
    Append-only, blockchain-style cryptographic audit ledger for security incident forensics.
    Chained SHA-256 hashes ensure non-repudiation and tamper evidence.
    Protected against updates and deletes.
    """
    __tablename__ = "security_forensic_audit_chain"
    __table_args__ = (
        UniqueConstraint("security_case_id", "sequence_number", name="uq_sec_audit_case_seq"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    security_case_id = Column(UUID(as_uuid=True), ForeignKey("security_cases.id", ondelete="CASCADE"), nullable=False, index=True)

    sequence_number = Column(Integer, nullable=False)
    event_type = Column(String(50), nullable=False)  # EVIDENCE_FROZEN, CONTAINMENT_PROPOSED, SIGN_OFF_1_GRANTED, SIGN_OFF_2_GRANTED, CONTAINMENT_EXECUTED, APPROVAL_EXPIRED, CASE_RESOLVED
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name = Column(String(255), nullable=True)
    payload_json = Column(JSON, nullable=True)
    previous_hash = Column(String(64), nullable=False)
    current_hash = Column(String(64), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    organization = relationship("Organization")
    security_case = relationship("SecurityCase", back_populates="audit_chain_entries")
    actor = relationship("User")


# Immutability guards for Forensic Snapshots and Audit Chain Entries
@event.listens_for(SecurityEvidenceSnapshot, "before_update")
def guard_security_evidence_update(mapper, connection, target):
    raise ValueError("SecurityEvidenceSnapshot is cryptographically immutable and cannot be updated.")


@event.listens_for(SecurityEvidenceSnapshot, "before_delete")
def guard_security_evidence_delete(mapper, connection, target):
    raise ValueError("SecurityEvidenceSnapshot is cryptographically immutable and cannot be deleted.")


@event.listens_for(SecurityForensicAuditChain, "before_update")
def guard_security_audit_update(mapper, connection, target):
    raise ValueError("SecurityForensicAuditChain records are append-only and cannot be updated.")


@event.listens_for(SecurityForensicAuditChain, "before_delete")
def guard_security_audit_delete(mapper, connection, target):
    raise ValueError("SecurityForensicAuditChain records are append-only and cannot be deleted.")