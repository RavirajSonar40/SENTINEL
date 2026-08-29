# Sentinel: Complete Product and Implementation Plan

## Document status

This document defines the target product, architecture, implementation sequence, operating model, safety boundaries, and verification strategy for Sentinel.

Sentinel is intended to become an AI engineering and incident-response platform for companies that operate multiple services across multiple repositories and deployment environments.

The document is deliberately organized around product behavior and system guarantees. Individual technologies may change, but the guarantees described here must remain true.

---

## 1. Executive summary

Sentinel should behave like a junior software engineer and an AI site-reliability engineer working continuously across a company’s engineering estate.

It must support two fundamentally different entry points:

1. **Developer-request mode**: a person gives Sentinel a task such as creating a README, fixing a bug, or implementing a feature.
2. **Autonomous production mode**: Sentinel receives or collects production signals without a person submitting a request. It detects abnormal behavior, creates an incident, investigates it, proposes a remediation, validates the change, and prepares a GitHub Draft PR.

The human should not need to tell Sentinel that CPU is high, a service is down, or error rates have increased. Sentinel must obtain that information from monitoring systems, deployment systems, health checks, logs, traces, and metrics.

The human safety boundary is review and approval of the proposed code change. Sentinel must never merge or deploy code autonomously.

The central design principle is:

> Sentinel must understand what kind of work is being requested or detected before choosing a workflow.

A README task must not be processed as a production incident. A production outage must not be treated as a generic coding task.

---

## 2. Product vision

Sentinel should give an engineering organization one place to understand:

- What repositories exist
- What services those repositories provide
- Where those services are deployed
- Which commit is running in each environment
- Which services are healthy, degraded, or down
- Which production signals indicate an incident
- What changed before the incident
- What evidence supports a root-cause conclusion
- Which repositories are affected
- What code change is proposed
- Whether the change passed validation
- Which Draft PRs are ready for human review

The long-term experience should be:

```text
Company engineering estate
        ↓
Sentinel observes services, deployments, repositories, and signals
        ↓
Sentinel detects abnormal behavior automatically
        ↓
Sentinel correlates the abnormal behavior into an incident
        ↓
Sentinel identifies affected services and repositories
        ↓
Sentinel investigates using operational and code evidence
        ↓
Sentinel identifies a root cause or explicitly abstains
        ↓
Sentinel prepares and validates a repository-specific patch
        ↓
Sentinel creates one Draft PR per affected repository
        ↓
Human reviews and approves through normal engineering controls
```

---

## 3. Scope and non-goals

### 3.1 In scope

Sentinel will provide:

- Multi-organization and multi-user access
- Multiple repositories per company
- Multiple services per company
- Multiple environments per service
- Deployment inventory and commit tracking
- Automatic production signal ingestion
- Automatic anomaly and threshold detection
- Incident deduplication and correlation
- Service-to-repository resolution
- Code and documentation indexing
- Evidence-backed investigation
- Competing hypothesis generation
- Root-cause analysis with abstention
- Patch generation
- Isolated validation
- Human review and approval
- GitHub branch, commit, and Draft PR creation
- Incident timeline and audit history
- Developer-request workflows for direct tasks, bugs, and features

### 3.2 Explicit non-goals for the first production version

The first reliable version should not attempt to:

- Automatically merge code
- Automatically deploy code
- Automatically change production infrastructure
- Guarantee that every incident has an identifiable root cause
- Replace a full observability platform
- Replace human incident command
- Run arbitrary commands against production
- Modify unrelated repositories merely because they are connected
- Treat an LLM response as proof

Sentinel should integrate with observability systems rather than trying to recreate every metric, log, trace, and alert product from scratch.

---

## 4. Current repository assessment

The existing repository already contains useful foundations:

### Backend foundations

- FastAPI API service
- SQLAlchemy models and Alembic migrations
- Authentication and user routes
- Incident and investigation models
- Incident lifecycle states
- Automatic detection rules
- Webhook normalizers
- GitHub API integration
- Pinecone/vector-store integration
- Investigation engine
- Hypothesis engine
- Diff generation
- Validation service
- Redis/in-memory task queue
- Approval routes
- Health and metrics routes

### Frontend foundations

- Next.js application
- Authentication screens
- Incident screens
- Investigation screens
- Repository screens
- Integration screens
- Health screens
- Pull-request screens
- Settings and audit screens
- Chatbot component

### Existing infrastructure

- PostgreSQL in Docker Compose
- Redis in Docker Compose
- Pinecone as the managed vector database
- Backend and frontend local services
- Render deployment configuration

### Current architectural gaps

The current implementation is not yet the complete target product because:

1. The data model is primarily incident-focused rather than work-item-focused.
2. Production monitoring is not yet a complete always-on ingestion system.
3. Automatic detection currently depends heavily on supplied contexts and rules rather than a durable signal pipeline.
4. Some investigation tools are placeholders, especially logs and dependency analysis.
5. The LLM configuration defaults to mock behavior.
6. Evidence filtering and causal reasoning need stronger guarantees.
7. Multi-repository investigation needs explicit child records and independent results.
8. Validation is not yet a fully enforced end-to-end gate in every path.
9. GitHub approval and publishing need strict state transitions.
10. Tenant isolation and token security need to be consistently enforced.

The implementation should preserve useful existing services while changing the orchestration model around them.

---

## 5. Core product model

### 5.1 Work items

Introduce a general work-item concept above incidents.

```text
WorkItem
├── Direct task
├── Bug report
├── Feature request
└── Production incident
```

Suggested fields:

```text
id
organization_id
type
title
description
status
priority
requester_id
service_id
environment_id
detected_at
created_at
updated_at
```

Incidents remain a specialized work-item type with signals, affected services, evidence, hypotheses, root causes, and remediation.

### 5.2 Organization

Every business object must belong to an organization or tenant.

Required ownership coverage includes:

- Users and memberships
- Services
- Environments
- Repositories
- Deployments
- Signals
- Incidents
- Investigations
- Evidence
- Hypotheses
- Root causes
- Fixes
- Validations
- Approvals
- Audit events

Every query must apply organization scope before returning data.

### 5.3 Service

A service is the operational unit that can be deployed and monitored.

```text
Service
- name
- description
- owner team
- organization
- criticality
- dependencies
- health endpoints
- default alert policy
```

A service can be backed by one or more repositories.

### 5.4 Environment

An environment represents where a service is running.

Examples:

- Production
- Staging
- Development
- Preview
- Region-specific production environments

```text
Environment
- name
- type
- region
- provider
- cluster or project
- organization
```

### 5.5 Repository relationship

Do not assume one service equals one repository.

```text
checkout-api
├── company/checkout-api       application
├── company/platform-config    configuration
├── company/infra               infrastructure
└── company/shared-auth         shared dependency
```

Each relationship should identify:

```text
repository
service
role
priority
ownership confidence
is_primary
```

### 5.6 Deployment

Deployment records connect runtime state to source code.

```text
Deployment
- service
- environment
- repository
- commit_sha
- version
- provider
- deployment_id
- deployed_at
- status
- URL
- metadata
```

This is how Sentinel determines which code was running when an incident began.

---

## 6. Operating modes

### 6.1 Direct developer task

Example:

> Add a comprehensive README.md file for the Sentinel repository.

Workflow:

```text
Classify as direct task
        ↓
Resolve repository
        ↓
Inspect actual repository structure
        ↓
Read package and deployment configuration
        ↓
Generate contextual README
        ↓
Validate content
        ↓
Create exact patch
        ↓
Create Draft PR
```

No incident hypotheses or production log searches are required.

### 6.2 Bug report

Example:

> Login returns HTTP 500 when the password is empty.

Workflow:

```text
Classify as bug
        ↓
Resolve relevant repositories
        ↓
Find authentication symbols and routes
        ↓
Read implementation and tests
        ↓
Inspect relevant history
        ↓
Generate hypotheses
        ↓
Generate and validate patch
        ↓
Create Draft PR
```

### 6.3 Feature request

Example:

> Add a dark-mode toggle to the settings page.

Workflow:

```text
Classify as feature
        ↓
Understand existing UI and design system
        ↓
Find settings, theme, and styling files
        ↓
Plan multi-file change
        ↓
Implement feature
        ↓
Run frontend checks
        ↓
Create Draft PR
```

### 6.4 Autonomous production incident

No human request is required.

```text
Metrics/logs/traces/health/deployment signals
        ↓
Signal normalization
        ↓
Deduplication and correlation
        ↓
Incident creation
        ↓
Automatic investigation
        ↓
Root cause or abstention
        ↓
Validated remediation
        ↓
Draft PR per affected repository
```

---

## 7. Always-on production monitoring

### 7.1 Required principle

Sentinel cannot detect CPU, memory, latency, or service outages without receiving runtime observations. Therefore, the monitoring system must connect to existing telemetry providers.

Sentinel should integrate with:

- Prometheus and Alertmanager
- Sentry
- OpenTelemetry-compatible traces
- Generic log providers
- Kubernetes or cloud health APIs
- GitHub deployment events
- Render, Vercel, AWS, or other deployment systems
- Generic webhook sources

### 7.2 Metrics

Initial metrics should include:

- CPU usage
- Memory usage
- Request count
- Error rate
- P50/P95/P99 latency
- Restart count
- Availability
- Queue depth
- Database connection usage
- Disk usage
- Dependency failure rate

Each metric observation must include:

```text
organization
service
environment
metric name
value
unit
timestamp
provider
labels
```

### 7.3 Logs

Log ingestion should support structured and unstructured logs.

Important fields:

```text
timestamp
service
environment
severity
message
exception type
stack trace
request ID
trace ID
deployment version
provider
```

The first version can ingest alert summaries and selected error records rather than every log line.

### 7.4 Traces

Trace data is especially valuable for multi-service incidents.

Sentinel should be able to identify:

```text
request
  → service
  → endpoint
  → downstream service
  → database or external provider
```

Trace evidence should link the affected operation to a service and, where possible, a code symbol or file.

### 7.5 Health checks

Every registered service should support configurable checks such as:

```text
GET /health
GET /ready
GET /version
```

Sentinel should periodically execute checks and record:

- Response status
- Latency
- Error message
- Availability state
- Consecutive failure count

### 7.6 Deployment events

Deployment ingestion must capture:

- Service
- Environment
- Repository
- Commit SHA
- Version
- Deployment start and completion time
- Deployment status
- Provider and external link

This enables temporal reasoning such as:

```text
Deployment at 09:48
Error rate increased at 10:02
```

Temporal correlation is evidence, but not proof by itself.

---

## 8. Detection and incident correlation

### 8.1 Signal lifecycle

```text
Receive signal
      ↓
Authenticate provider
      ↓
Normalize payload
      ↓
Persist raw and normalized forms
      ↓
Calculate fingerprint
      ↓
Find matching incident
      ↓
Append signal or create incident
      ↓
Evaluate severity and rules
      ↓
Queue investigation
```

### 8.2 Detection rules

Initial detection rules should include:

- Error rate threshold
- Latency threshold
- CPU threshold
- Memory threshold
- Health-check failure
- Crash loop
- Restart spike
- Disk exhaustion
- Queue backlog
- Database saturation
- Repeated exception signature
- Multiple dependency failures
- Deployment regression

### 8.3 Correlation

Signals must be grouped using a correlation key derived from:

```text
organization
service
environment
signal class
error signature
deployment
time window
```

The same outage should not create separate incidents for every alert source.

Example:

```text
Prometheus alert
Sentry exception spike
Health-check failures
GitHub deployment event
        ↓
One correlated incident
```

### 8.4 Severity

Severity should consider:

- User impact
- Service criticality
- Availability loss
- Error rate
- Duration
- Number of affected environments
- Dependency blast radius

The LLM may explain severity, but deterministic rules should provide the initial severity classification.

---

## 9. Multi-repository architecture

### 9.1 Core requirement

One incident may involve multiple services and repositories.

```text
Incident INC-142
├── checkout-api
│   └── company/checkout-api
├── payment-service
│   └── company/payment-service
└── platform-config
    └── company/platform-config
```

Not every related repository must be modified. Some may only provide evidence.

### 9.2 Repository resolution

Sentinel should score candidate repositories using:

```text
Explicit scope                         highest priority
Service mapping                        high priority
Deployment ownership                   high priority
Stack-trace path                       high priority
Current running commit                 high priority
Changed files                          medium priority
Code ownership                         medium priority
Dependency graph                       medium priority
Keyword or semantic match              low priority
```

The resolver must return all candidates above a configured threshold and explain the reason for each selection.

It must never silently select the first connected repository.

### 9.3 Child investigations

Create a child investigation per repository:

```text
Incident
├── Repository investigation: checkout-api
├── Repository investigation: payment-service
└── Repository investigation: platform-config
```

Each child investigation stores:

- Repository
- Base commit SHA
- Deployment relationship
- Evidence
- Hypotheses
- Root cause
- Proposed fix
- Validation
- Failure state
- Draft PR

### 9.4 Cross-repository correlation

The parent incident should combine child results into an overall explanation.

Example:

```text
payment-service is the primary cause.
checkout-api is affected downstream.
platform-config contains deployment configuration evidence but requires no change.
```

---

## 10. Intent and workflow router

### 10.1 Required output

The router should produce a structured envelope:

```json
{
  "work_type": "direct_task",
  "confidence": 0.96,
  "repository_scope": ["company/sentinel"],
  "service_scope": [],
  "environment_scope": [],
  "target_files": ["README.md"],
  "requires_runtime_evidence": false,
  "requires_code_change": true,
  "workflow": "repository_task"
}
```

### 10.2 Router behavior

The router should use:

1. Deterministic patterns for obvious tasks.
2. Repository-aware context for ambiguity.
3. LLM classification only when necessary.
4. Schema validation for every result.
5. A safe clarification or blocked state when confidence is low.

### 10.3 LLM role

The LLM may interpret ambiguous natural language, but it must not directly bypass:

- Permission checks
- Repository scope
- Patch restrictions
- Approval requirements
- Validation requirements

---

## 11. Investigation design

### 11.1 Planner

The planner should produce a task graph based on work type.

It should not use one hardcoded task list for every request.

Each task must define:

```text
task type
purpose
inputs
tool
expected output
required evidence
retry policy
```

### 11.2 Direct task evidence

For simple tasks, the required context may be:

- Repository tree
- Project manifest
- Configuration
- Existing documentation
- Relevant source files
- Tests

Production metrics are unnecessary unless the task explicitly involves runtime behavior.

### 11.3 Incident evidence

For production incidents, collect:

- Alert payloads
- Metrics around the incident window
- Logs and exception signatures
- Traces
- Current deployment
- Recent deployments
- Commits before the incident
- Diffs in the deployment
- Relevant source files
- Dependencies
- Runbooks
- Previous incidents

### 11.4 Evidence filtering

Every evidence item must be filtered by:

- Organization
- Service
- Environment
- Repository
- Time window
- Commit/deployment relationship

Semantic similarity is only a retrieval mechanism. It is not proof of relevance.

### 11.5 Tool execution

Tools should be typed and permissioned.

Examples:

- `list_repository_tree`
- `read_repository_file`
- `search_symbol`
- `search_code`
- `get_commit_history`
- `get_deployment`
- `query_metrics`
- `query_logs`
- `query_traces`
- `search_runbooks`
- `search_previous_incidents`

Every tool result should record its source and retrieval time.

---

## 12. Evidence-backed root-cause analysis

### 12.1 Hypotheses

Sentinel should generate multiple plausible hypotheses when the incident warrants it.

```text
H1: Recent deployment changed connection-pool configuration
H2: Database is saturated independently of the deployment
H3: External payment provider latency caused request buildup
H4: Memory pressure caused worker instability
```

### 12.2 Hypothesis structure

```json
{
  "description": "...",
  "status": "supported",
  "confidence": "high",
  "supporting_evidence_ids": [],
  "contradicting_evidence_ids": [],
  "missing_evidence": [],
  "temporal_fit": true,
  "code_path_fit": true
}
```

### 12.3 Acceptance rules

A root cause should require:

- A relevant affected service
- A plausible causal mechanism
- Temporal compatibility
- Code-path or operational compatibility
- Supporting evidence from more than one useful source where possible
- No unresolved contradiction that invalidates the explanation

### 12.4 Abstention

Abstention is a successful outcome when evidence is inadequate.

```text
Root cause: Undetermined
Confidence: Insufficient evidence
Reason: Metrics show an outage, but no service-level or code-level evidence
connects the outage to a specific change.
Required evidence: traces and deployment metadata.
```

---

## 13. Patch generation and safety

### 13.1 Patch inputs

The patch generator must receive:

- Repository
- Base commit SHA
- Approved file scope
- Relevant code sections
- Work-item requirements
- Acceptance criteria
- Existing tests
- Project conventions
- Root-cause evidence, if the work is an incident

### 13.2 Patch schema

```json
{
  "summary": "...",
  "changes": [
    {
      "file": "README.md",
      "action": "create",
      "old_code": "",
      "new_code": "..."
    }
  ],
  "tests_to_run": [],
  "risk": "low",
  "rollback_plan": "..."
}
```

### 13.3 Mandatory rejection rules

Reject a patch when:

- It targets a repository outside the approved scope.
- It modifies a file outside the approved scope.
- A modification target does not exist.
- `old_code` is empty for a modification when exact replacement is required.
- `old_code` occurs zero times.
- `old_code` occurs more than once.
- The patch is unexpectedly large.
- The base SHA is stale or unknown.
- The output is malformed.
- The patch produces no actual change.

Sentinel must never replace an entire remote file merely because a target snippet was not found.

### 13.4 Direct-file tasks

For a file-creation task, Sentinel should:

1. Confirm the intended repository.
2. Check whether the target file already exists.
3. Read the repository context needed for accurate content.
4. Generate the complete file.
5. Validate the file.
6. Create exactly the requested file unless additional files are justified and approved.

There should be no hardcoded behavior limited to README.md, hello.txt, or a particular file name.

---

## 14. Validation system

Validation must happen against the exact repository revision used to generate the patch.

```text
Checkout exact base SHA
        ↓
Apply patch in isolated workspace
        ↓
Run targeted checks
        ↓
Run repository checks
        ↓
Persist results
        ↓
Allow or reject Draft PR creation
```

Possible checks:

- Unit tests
- Integration tests
- Lint
- Formatting
- Type checking
- Build
- Security scanning
- Dependency checks
- Markdown validation
- Link validation
- Infrastructure validation

Each check should store:

```text
check type
command
status
exit code
stdout/stderr reference
duration
started_at
completed_at
```

Validation must be repository-aware. A Python service, Next.js frontend, and Terraform repository should not receive identical commands.

---

## 15. GitHub and approval lifecycle

### 15.1 Recommended lifecycle

```text
Proposed
    ↓
Validated
    ↓
Draft PR created
    ↓
Human review
    ├── Approved
    ├── Changes requested
    └── Rejected
    ↓
Merged externally under repository controls
```

Sentinel may create a branch and Draft PR after validation, but it must not merge or deploy.

### 15.2 Draft PR content

Every Draft PR should include:

- Incident or work-item link
- Summary
- Affected service and environment
- Repository and base SHA
- Root cause, when applicable
- Confidence and uncertainty
- Supporting evidence links
- Files changed
- Validation results
- Risk assessment
- Rollback plan
- Explicit statement that Sentinel did not merge or deploy the change

### 15.3 Multi-repository PRs

For a multi-repository incident:

```text
One parent incident
        ↓
One validated fix per repository
        ↓
One Draft PR per repository
```

If a repository is evidence-only, no PR should be created for it.

---

## 16. Data model expansion

The database should evolve toward the following relationships:

```text
Organization
├── Users and memberships
├── Services
│   ├── Environments
│   ├── Repository relationships
│   ├── Deployments
│   └── Signals
├── Work items
│   ├── Incidents
│   ├── Direct tasks
│   ├── Bugs
│   └── Features
├── Investigations
├── Evidence
├── Hypotheses
├── Root causes
├── Proposed fixes
├── Validation runs
├── Approvals
└── Audit events
```

Important database requirements:

- Foreign keys for ownership
- Unique constraints for provider event IDs
- Unique constraints for deployment identities
- Indexes on organization, service, environment, status, and timestamps
- Immutable evidence references
- Immutable base commit SHA for fixes
- Durable task and progress records
- Explicit state-transition history

---

## 17. Backend implementation plan

### Phase 0: Safety baseline

Objectives:

- Prevent destructive patch behavior.
- Enforce approval correctly.
- Establish tenant isolation.
- Improve auditability.

Work:

- Add patch application tests.
- Reject unmatched replacement snippets.
- Remove automatic approval shortcuts.
- Add organization filters to every route.
- Encrypt GitHub tokens.
- Add webhook signature verification.
- Add OAuth state validation.
- Add request size limits and rate limits.
- Record every GitHub write in audit events.

Exit criteria:

- An invalid patch cannot overwrite an unrelated file.
- An unauthorized user cannot access another organization’s data.
- An unapproved fix cannot be published under the selected approval policy.

### Phase 1: Work items and intent routing

Work:

- Add work-item model.
- Add work-item API.
- Add intent classifier.
- Add workflow router.
- Add direct repository task workflow.
- Add structured request envelope.

First acceptance case:

```text
Add a comprehensive README.md file.
```

Expected result:

- Classified as a direct task.
- No incident investigation.
- Correct repository selected.
- Contextual README generated.
- Only intended files changed.

### Phase 2: Repository intelligence

Work:

- Repository tree inspection.
- Framework and language detection.
- Manifest discovery.
- Symbol indexing.
- Dependency graph.
- Code ownership mapping.
- Multi-repository resolver.
- Repository-scoped retrieval.

### Phase 3: Service and deployment catalog

Work:

- Service CRUD.
- Environment CRUD.
- Service/repository relationships.
- Deployment ingestion.
- Current deployment tracking.
- Health endpoint configuration.
- Ownership and criticality.

### Phase 4: Autonomous observability

Start with a focused MVP:

- Prometheus/Alertmanager integration.
- Generic signed webhook integration.
- GitHub deployment webhook.
- Service health checks.
- Sentry integration or equivalent exception source.

Work:

- Normalize signals.
- Persist raw payloads safely.
- Deduplicate.
- Correlate.
- Create incidents.
- Queue investigations.
- Add durable scheduler workers.

### Phase 5: Investigation and RCA

Work:

- Replace fixed planning with type-specific plans.
- Implement real log retrieval.
- Implement deployment retrieval.
- Implement dependency analysis.
- Implement trace retrieval.
- Add evidence provenance.
- Add temporal filtering.
- Add hypothesis/evidence linking.
- Add abstention thresholds.

### Phase 6: Patch and validation

Work:

- Exact SHA checkout.
- Isolated execution workspace.
- Repository-specific validation profiles.
- Safe patch application.
- Persisted validation results.
- Diff viewer and validation UI.

### Phase 7: GitHub workflow

Work:

- Branch creation.
- Commit creation.
- Draft PR creation.
- PR status synchronization.
- Review status synchronization.
- Changes-requested workflow.
- Multi-repository PR grouping.

### Phase 8: Production hardening

Work:

- Redis worker leases.
- Retry policies.
- Dead-letter queue.
- Persistent progress events.
- Readiness checks.
- External metrics.
- Alerting for Sentinel itself.
- Backups and recovery.
- Evaluation datasets.

---

## 18. Frontend implementation plan

### 18.1 Operations overview

Show:

- Active incidents
- Service health
- Production environments
- Recent deployments
- Services with high CPU
- Services with high error rates
- Services with failing health checks
- Current alerts
- Recent Draft PRs

### 18.2 Service inventory

Each service page should display:

```text
Service name
Owner
Environment
Health
Current version
Current commit
Repository links
CPU
Memory
Error rate
Latency
Latest deployment
Dependencies
Open incidents
```

### 18.3 Incident workspace

The incident workspace should contain:

- Summary
- Severity
- Detection source
- Service and environment
- Current deployment
- Timeline
- Metrics
- Logs
- Traces
- Evidence
- Repository investigations
- Hypotheses
- Root cause
- Proposed fixes
- Validation
- Draft PRs
- Audit history

### 18.4 Multi-repository view

```text
Incident INC-142

Repositories:
├── company/checkout-api
│   ├── Investigation complete
│   ├── Validation passed
│   └── Draft PR ready
├── company/payment-service
│   ├── Root cause identified
│   ├── Validation failed
│   └── Draft PR blocked
└── company/platform-config
    ├── Evidence only
    └── No code change
```

### 18.5 Developer task view

This view should show:

- Interpreted request type
- Selected repository
- Files selected
- Context used
- Proposed plan
- Generated diff
- Validation
- Draft PR

---

## 19. Worker and orchestration design

The API should accept events quickly and delegate long-running work to durable workers.

```text
API request or provider event
        ↓
Persist work item/signal
        ↓
Submit idempotent job
        ↓
Redis queue
        ↓
Worker lease
        ↓
Execute task graph
        ↓
Persist progress and output
        ↓
Release or retry
```

Workers need:

- Job IDs
- Idempotency keys
- Leases
- Heartbeats
- Retry count
- Maximum attempts
- Dead-letter state
- Cancellation
- Durable progress
- Safe restart recovery

The system must not depend on one browser connection or one process’s in-memory state.

---

## 20. Security and safety model

### 20.1 Permissions

Use role-based permissions for:

- Connecting repositories
- Reading production data
- Starting manual tasks
- Approving fixes
- Creating branches
- Creating PRs
- Changing detection rules
- Managing integrations

### 20.2 Prompt injection defense

Repository files, logs, PR descriptions, and issue text are untrusted data.

They must never be allowed to override system instructions, permissions, or safety rules.

### 20.3 Production boundary

Sentinel may read production telemetry. It must not receive unrestricted production write access in the initial product.

### 20.4 GitHub boundary

The GitHub integration should use least-privilege permissions and separate read and write capabilities where possible.

### 20.5 Auditability

Record:

- Who initiated or authorized an action
- Which model and prompt version were used
- Which evidence was retrieved
- Which files were read
- Which patch was generated
- Which validation commands ran
- Which GitHub operations occurred
- Which approval was given

---

## 21. Testing strategy

### Unit tests

- Intent classification
- Repository resolution
- Service mapping
- Signal normalization
- Fingerprinting
- Deduplication
- Detection rules
- Temporal filtering
- Evidence scoring
- Patch application
- Approval transitions
- Webhook signatures

### Service tests

- Multi-repository resolution
- Investigation planning
- Evidence collection
- Hypothesis evaluation
- Root-cause abstention
- Validation profile selection
- GitHub client behavior

### API tests

- Authentication
- Organization isolation
- Incident lifecycle
- Webhook ingestion
- Automatic incident creation
- Investigation queueing
- Approval gates
- Draft PR restrictions

### Integration tests

- PostgreSQL
- Redis
- Pinecone
- Mocked GitHub
- Mocked Prometheus
- Mocked Sentry
- Mocked log provider

### End-to-end scenarios

#### Scenario A: README task

```text
User task
→ direct-task classification
→ repository inspection
→ README generation
→ validation
→ one-file Draft PR
```

#### Scenario B: Production deployment regression

```text
Deployment event
→ error-rate alert
→ incident correlation
→ service/repository resolution
→ deployment and code evidence
→ root cause
→ patch
→ validation
→ Draft PR
```

#### Scenario C: Multi-repository incident

```text
One production incident
→ two affected services
→ two repository investigations
→ one evidence-only repository
→ two independent validations
→ two Draft PRs
```

#### Scenario D: Insufficient evidence

```text
Production anomaly
→ incident created
→ evidence insufficient
→ no fabricated root cause
→ no unsafe patch
→ request for additional evidence
```

---

## 22. Operational deployment

Target topology:

```text
Browser
  ↓
Next.js frontend
  ↓
FastAPI API
  ├── PostgreSQL
  ├── Redis
  ├── Pinecone
  ├── GitHub
  ├── Observability providers
  └── Worker queue
        ↓
      Workers
```

Production requirements:

- API and workers run the same source revision.
- Migrations run before traffic is accepted.
- Redis is durable enough for the required job guarantees.
- Pinecone index dimensions match the embedding model.
- Production URLs are used instead of localhost configuration.
- CORS is restricted to known frontend origins.
- Secrets are stored in the deployment secret manager.
- Liveness and readiness are separate.
- Sentinel monitors its own API, worker, database, queue, and integrations.

---

## 23. Definition of done

Sentinel is ready for a first serious production pilot when all of the following are true:

- A company can connect multiple repositories.
- A company can register multiple services and environments.
- Every service maps to its deployed repository and commit.
- Production signals arrive without a human creating an incident.
- CPU, memory, latency, errors, health checks, and deployment events are visible.
- Similar signals are correlated into one incident.
- The incident automatically enters investigation.
- Multiple affected repositories are discovered and investigated separately.
- Evidence is stored with provenance.
- Root causes are evidence-backed or explicitly undetermined.
- The system does not invent evidence.
- Patches are generated from exact repository revisions.
- Invalid patches are rejected.
- Validation runs in an isolated environment.
- Validation results are visible.
- One Draft PR is created per repository requiring a code change.
- Evidence-only repositories do not receive unnecessary PRs.
- Human review is required before merge.
- Sentinel cannot merge or deploy autonomously.
- Tenant isolation tests pass.
- Webhook authentication tests pass.
- Worker restart and retry tests pass.
- Backend and frontend checks pass.
- Sentinel’s own health is monitored.

---

## 24. Final product statement

The final Sentinel product is not merely a chatbot and not merely an alert dashboard.

It is a multi-repository, always-on AI engineering system that:

```text
Understands developer work
        +
Understands company service topology
        +
Watches production automatically
        +
Investigates incidents using evidence
        +
Generates repository-specific fixes
        +
Validates changes safely
        +
Creates reviewable Draft PRs
        +
Keeps humans in control of approval and deployment
```

The first priority is not making the LLM sound intelligent. The first priority is making the system choose the correct workflow, observe the correct systems, maintain the correct repository and deployment context, and refuse unsafe or unsupported actions.

---

## 25. Expanded company-wide intelligence capabilities

The initial plan establishes incident detection, investigation, remediation, and developer-task workflows. The following capabilities extend Sentinel from an incident tool into a continuously updated model of the company’s engineering system.

These capabilities should be implemented in layers. The basic versions belong in the reliability foundation; advanced prediction, replay, causal analysis, and learning should follow after the underlying data is trustworthy.

The common principle is:

> Sentinel should understand the company as a connected system, not as a collection of isolated incidents and repositories.

---

## 26. Service dependency graph

### 26.1 Purpose

Sentinel must understand how services, repositories, databases, queues, external providers, environments, and teams relate to one another.

Example:

```text
Frontend
    ↓
API Gateway
    ↓
Checkout
  ├── Payment
  │     ↓
  │   Postgres
  └── Inventory
```

The graph should answer:

- What does this service depend on?
- Which services depend on this service?
- Which repository implements the service?
- Which team owns the service?
- Which deployments affect the service?
- Which environments and regions run it?
- What is the likely downstream impact if it fails?

### 26.2 Graph sources

The graph should be constructed and continuously updated from:

- Explicit service registration
- Repository configuration
- Docker Compose files
- Kubernetes manifests
- Helm charts
- Terraform and infrastructure code
- API specifications
- OpenTelemetry service relationships
- Distributed traces
- Database and queue configuration
- Import and dependency analysis
- GitHub ownership files
- Deployment metadata
- Human corrections

No single source will always be complete. Each relationship should record its source and confidence.

### 26.3 Graph entities

```text
Node:
- service
- repository
- environment
- deployment
- database
- queue
- external provider
- team
- endpoint

Edge:
- calls
- depends_on
- deployed_as
- owned_by
- implemented_by
- publishes_to
- consumes_from
- stores_in
```

### 26.4 Graph behavior during an incident

If Payment fails, Sentinel should calculate:

```text
Directly affected:
- Payment service
- Payment endpoints
- Payment repository

Likely downstream impact:
- Checkout service
- Order service
- Customer checkout flow

Likely unaffected:
- Inventory service
- Authentication service
```

The graph must distinguish observed impact from predicted impact.

---

## 27. Incident blast-radius analysis

### 27.1 Purpose

Every incident should include an automatically generated blast-radius assessment.

Sentinel should answer:

- Which services are directly affected?
- Which services are indirectly affected?
- Which APIs and endpoints are affected?
- Which repositories are potentially involved?
- Which regions and environments are affected?
- What percentage of traffic is affected?
- What percentage of users may be affected?
- What business workflows are blocked?

### 27.2 Blast-radius calculation

```text
Incident signal
      ↓
Affected service and endpoint
      ↓
Dependency graph traversal
      ↓
Observed downstream signals
      ↓
Traffic and user-impact estimation
      ↓
Blast-radius report
```

The calculation should combine:

- Trace relationships
- Service dependency edges
- Request volume
- Error rate by endpoint
- Region and environment labels
- Customer or tenant segmentation where available
- Business-service mapping

### 27.3 Observed versus inferred impact

The UI should clearly distinguish:

```text
Observed:
Checkout API returned errors for 31% of requests.

Inferred:
Order creation is likely affected because Checkout calls Order Service.

Unknown:
The percentage of completed purchases cannot be calculated without business events.
```

### 27.4 Multi-repository result

The blast-radius output should identify repository roles:

```text
company/payment-service     primary affected repository
company/checkout-api        downstream affected repository
company/platform-config     related configuration repository
company/shared-auth         unaffected dependency
```

Only repositories requiring an actual change should receive proposed patches.

---

## 28. Change intelligence

Sentinel should track more than deployments. It should maintain a change ledger for the company.

### 28.1 Change types

- Code commits
- Pull requests
- Configuration changes
- Environment variable changes
- Dependency upgrades
- Database migrations
- Infrastructure changes
- Feature-flag changes
- API contract changes
- Deployment changes
- Scaling changes
- Runtime configuration changes

### 28.2 Change ledger

```text
Change
- organization
- service
- environment
- repository
- commit or external ID
- change type
- author
- observed_at
- effective_at
- affected components
- source URL
- compatibility notes
```

### 28.3 Incident use

When an incident begins, Sentinel should ask:

```text
What changed in the relevant time window?
```

It should rank:

1. Changes deployed immediately before the incident.
2. Feature flags enabled before the incident.
3. Configuration changes affecting the service.
4. Dependency upgrades.
5. Database migrations.
6. Infrastructure or scaling changes.
7. Related repository changes.

Example:

```text
10:00 Feature flag new_checkout_flow disabled
10:05 Feature flag new_checkout_flow enabled
10:07 Error rate increased
```

Sentinel should report the timing and, where telemetry allows it, compare affected and unaffected cohorts.

---

## 29. Explainable RCA timeline

The incident explanation should be a timeline rather than only a final sentence.

Example:

```text
09:41  Deployment v2.8.1 completed
09:43  Database connection utilization increased 18%
09:45  P95 latency increased
09:47  Timeout rate increased
09:48  HTTP 503 responses spiked
09:49  Health checks began failing
```

The timeline must classify statements as:

```text
Evidence:
Database connections increased by 18%.

Inference:
The increase is temporally correlated with deployment v2.8.1.

Conclusion:
The connection-pool configuration in v2.8.1 is the strongest current explanation.
```

This distinction is essential. Sentinel must not present an inference as a directly observed fact.

Every timeline event should link to an evidence record or explicitly identify itself as a derived inference.

---

## 30. Hypothesis competition and disproof

Hypotheses should compete rather than merely accumulate.

| Hypothesis | Supporting evidence | Contradicting evidence | Status |
|---|---:|---:|---|
| Deployment regression | 4 | 0 | Strong |
| Database saturation | 2 | 3 | Weak |
| External provider failure | 1 | 4 | Rejected |

For each hypothesis, Sentinel should determine:

- What evidence would support it?
- What evidence would contradict it?
- What evidence is missing?
- Which diagnostic query would best distinguish it from alternatives?
- Whether its timing is compatible with the incident
- Whether the affected request path actually uses the suspected component

The investigation planner should actively request disconfirming evidence for the leading hypothesis.

This reduces confirmation bias and prevents the first plausible explanation from becoming the root cause.

---

## 31. Automatic regression test generation

When Sentinel identifies a reproducible bug, it should normally generate a regression test alongside the fix.

```text
Observed bug
      ↓
Root cause
      ↓
Regression test reproducing old failure
      ↓
Code patch
      ↓
Test passes with patch
      ↓
Draft PR
```

The generated test must:

- Reproduce the original failure or a faithful minimal version.
- Fail against the unpatched code when practical.
- Pass against the patched code.
- Follow the repository’s existing testing conventions.
- Be included in the proposed diff and validation report.

Sentinel must not generate meaningless tests that only assert the new implementation’s output without exercising the original failure.

---

## 32. Incident-specific fix verification

Compilation and unit tests are necessary but not always sufficient.

The stronger workflow is:

```text
Capture relevant request, trace, or test scenario
        ↓
Reproduce failure against pre-patch version
        ↓
Apply candidate patch
        ↓
Replay the same scenario
        ↓
Compare behavior
        ↓
Run normal validation
        ↓
Report whether the incident mechanism was addressed
```

Verification may use:

- A captured sanitized request
- A generated regression test
- A trace-derived test case
- A staging replay
- A synthetic load scenario
- A dependency mock
- A recorded error signature

Production data must be sanitized and must not be replayed into production by default.

The result should distinguish:

```text
Code validation: passed
Incident reproduction: reproduced before patch
Post-patch replay: failure no longer reproduced
Production outcome: not yet known
```

---

## 33. Change impact analysis

Before publishing a Draft PR, Sentinel should estimate the impact of the proposed change.

```text
Changed:
payment/config.py

Potentially affected:
├── PaymentService
├── CheckoutService
├── OrderService
└── 17 API endpoints
```

The analysis should include:

- Changed services
- Changed endpoints
- Dependent repositories
- Affected tests
- Database or schema impact
- Configuration impact
- Deployment impact
- Rollback complexity
- Security sensitivity
- Estimated blast radius

The PR should display a human-readable summary:

```text
Estimated change risk: Medium
Affected services: 3
Affected repositories: 2
Database migration detected: No
Rollback complexity: Low
```

This is an estimate and must not be presented as certainty.

---

## 34. Business impact and multi-region awareness

### 34.1 Business impact

Technical metrics should be translated into business impact when the organization has suitable mappings.

```text
Technical impact:
Payment API unavailable

Estimated business impact:
31% of checkout requests affected
Approximately 4,200 orders potentially blocked
Estimated revenue at risk: ₹X–₹Y
```

Every business estimate must show:

- Input metrics
- Calculation method
- Assumptions
- Time window
- Uncertainty range

### 34.2 Regions

Sentinel should represent health by region:

```text
India       healthy
US          unhealthy
Europe      healthy
```

It should classify incidents as:

- Regional
- Global
- Deployment-specific
- Infrastructure-specific
- Dependency-specific
- Unknown

Region-aware investigation prevents a US-only outage from being described as a global outage.

---

## 35. Sentinel agent activity and investigation trace

Sentinel should expose an auditable action log, not hidden chain-of-thought.

Example:

```text
Sentinel investigation

✓ Received Prometheus alert
✓ Correlated with Sentry exception spike
✓ Found deployment 7 minutes earlier
✓ Identified checkout-api
✓ Found downstream payment dependency
✓ Retrieved commit abc123
✓ Inspected connection-pool configuration
✓ Generated competing hypotheses
✓ Retrieved contradicting database evidence
✓ Generated regression test
✓ Generated patch
✓ Validation passed
✓ Draft PR created
```

Each activity event should record:

- Activity type
- Status
- Timestamp
- Investigation/task ID
- Input references
- Output references
- Model/tool version where relevant
- Error details where relevant

Do not expose private model reasoning. Expose observable actions, evidence, decisions, and explanations.

---

## 36. Safety gateway and formal policy engine

The safety gateway should be an explicit subsystem between AI proposals and external actions.

```text
AI proposal
     ↓
Policy engine
     ├── Permission check
     ├── Evidence check
     ├── Scope check
     ├── Risk check
     ├── Validation check
     └── Approval check
     ↓
ALLOW / BLOCK / REQUIRE HUMAN DECISION
```

Example policy:

```text
Production:
  read telemetry       allowed
  write runtime        forbidden

Repositories:
  read source          allowed
  create branch        allowed after validation
  create Draft PR      allowed after policy checks
  merge                forbidden

Files:
  application source   allowed with review
  infrastructure       multiple approvals required
  database migrations  multiple approvals required
  secrets              forbidden
```

Policies must be organization-configurable, versioned, audited, and evaluated independently of the LLM.

---

## 37. AI incident commander mode

During a major incident, Sentinel should maintain a current incident command view.

```text
Incident commander view
├── Current status
├── Customer impact
├── Affected regions
├── Timeline
├── Leading hypotheses
├── Contradicting evidence
├── Actions completed
├── Recommended next action
├── Owners and on-call contacts
├── Decisions
└── Open questions
```

Example response:

```text
Payment API is degraded in US production.
Checkout failures are approximately 31%.
The strongest hypothesis is connection-pool exhaustion.
The last deployment occurred 14 minutes before degradation.
The next highest-value diagnostic is database connection utilization by instance.
```

The commander mode may recommend read-only diagnostic actions. It must not execute production mutations without a separate explicit authorization and policy path.

---

## 38. Ownership and on-call intelligence

Sentinel should know:

```text
Payment Service
    ↓
Payments Team
    ↓
Primary: Alice
Backup: Bob
Rotation: Payments on-call
Repository: company/payment-service
```

This information should come from:

- Service catalog
- CODEOWNERS
- Team directory
- PagerDuty or equivalent on-call integration
- Repository ownership
- Human-maintained overrides

It enables questions such as:

- Who owns this service?
- Which team should review the PR?
- Who is currently on call?
- Which repositories should be notified?

---

## 39. Runbook-aware diagnostics

Runbooks should become executable knowledge for safe read-only diagnostics.

Example:

```text
Runbook: Redis connection exhaustion

Step 1: Check connection count       completed
Step 2: Check worker utilization     completed
Step 3: Compare recent deployment    completed
Step 4: Human action required        pending
```

Runbook steps must be classified as:

- Read-only and safe to automate
- Requires human confirmation
- Forbidden for autonomous execution

Runbook execution should produce evidence and activity events.

---

## 40. Incident memory and organizational knowledge

Historical incidents should become an explicit knowledge subsystem rather than merely another vector-search collection.

### 40.1 Memory record

```text
Incident pattern
- error signatures
- affected services
- deployment patterns
- relevant metrics
- useful diagnostic queries
- confirmed root causes
- successful fixes
- validation strategy
- prevention actions
- confidence and outcome quality
```

### 40.2 Historical investigation

For a current payment 503 incident, Sentinel might find:

```text
INC-104
Same service
Same error signature
Similar deployment timing
Confirmed root cause: connection-pool exhaustion
Successful fix: configuration correction
```

Historical incidents should inform investigation but never override current evidence.

### 40.3 Knowledge quality

Memory entries should be updated only after:

- Human-confirmed root cause
- Validated fix
- Observed post-deployment outcome

Do not blindly train on every generated hypothesis.

---

## 41. Rollback analysis

Rollback should be treated as a specific remediation option with risk analysis.

```text
Current deployment:  v2.8.1
Previous stable:     v2.8.0
```

Sentinel should evaluate:

- Whether the previous deployment is available
- Whether schema migrations occurred
- Whether API contracts changed
- Whether data migrations are backward-compatible
- Whether configuration changed
- Whether rollback restores the suspected behavior
- Whether rollback could create a second failure

Possible output:

```text
Rollback possible: Yes
Rollback risk: High
Reason: Incompatible database migration detected
Recommendation: Do not roll back automatically
```

or:

```text
Rollback possible: Yes
Rollback risk: Low
Reason: No incompatible schema or API changes detected
```

Sentinel must never execute a production rollback autonomously in the initial product.

---

## 42. Security incident workflow

Security signals require a separate workflow from normal reliability incidents.

```text
Suspicious authentication failures
        ↓
Security incident
        ↓
Evidence preservation
        ↓
Affected systems and accounts
        ↓
Security-team review
```

Security incidents should emphasize:

- Evidence preservation
- Chain of custody
- Access review
- Credential and token exposure assessment
- Scope containment recommendations
- Mandatory security approval

Sentinel should not automatically modify authentication, permissions, firewall, secrets, or production security settings.

---

## 43. Dependency intelligence

Sentinel should continuously track repository dependencies:

```text
payment-service
├── postgres driver
├── Redis client
├── Stripe SDK
└── Web framework
```

It should identify:

- Vulnerable dependencies
- Deprecated packages
- Major upgrades
- Breaking API changes
- Unusual behavior after an upgrade
- Dependency changes correlated with incidents

Dependency intelligence must feed both proactive reliability analysis and incident investigation.

Infrastructure and security dependency changes should require stronger policy gates than ordinary application changes.

---

## 44. Reliability intelligence and SLOs

Sentinel should eventually maintain reliability profiles for every critical service.

Example:

```text
Payment Service

Reliability score: 82/100
Availability: 99.91%
P95 latency: 340ms
Error rate: 0.7%
Incidents: 4
MTTR: 23m
MTTD: 4m
Change failure rate: 8%
SLO: 99.95%
Error budget consumed: 82%
```

Metrics should include:

- MTTD
- MTTA
- MTTR
- Incident frequency
- Availability
- Error rate
- P95/P99 latency
- Change failure rate
- SLO compliance
- Error-budget consumption

Severity prioritization should eventually combine:

```text
Customer impact
+ SLO impact
+ Error-budget consumption
+ Service criticality
```

This creates continuous reliability intelligence rather than only incident-by-incident reporting.

---

## 45. Confidence calibration and outcome learning

Confidence should not remain an unverified number.

Sentinel should track:

```text
Predicted confidence
        ↓
Human judgment and actual outcome
        ↓
Calibration statistics
```

After a fix is merged and deployed, Sentinel should observe:

- Whether the incident disappeared
- Whether metrics returned to baseline
- Whether the same error recurred
- Whether a regression appeared
- Whether the root-cause hypothesis was confirmed

If high-confidence conclusions are frequently wrong, the system should reduce trust in that reasoning pattern and surface the calibration problem.

---

## 46. Post-incident learning and feedback loop

The complete lifecycle is:

```text
Incident detected
        ↓
Investigation
        ↓
RCA
        ↓
Fix
        ↓
Human review
        ↓
Merge and deployment
        ↓
Outcome monitoring
        ↓
RCA and fix effectiveness
        ↓
Incident memory update
```

Sentinel should generate a post-incident report containing:

- Summary
- Detection
- Customer and business impact
- Affected services and regions
- Timeline
- Evidence
- Competing hypotheses
- Root cause
- Contributing factors
- Fixes and Draft PRs
- Validation
- Outcome after deployment
- Preventive actions
- Follow-up owners

The system should learn structured patterns from confirmed outcomes, not blindly reuse all generated text.

---

## 47. Predictive incident detection

Predictive detection is an advanced capability and should come after reliable historical telemetry exists.

### 47.1 Signals

- Steadily increasing latency
- Memory growth
- Disk exhaustion trajectory
- Queue buildup
- Error-rate acceleration
- Connection-pool saturation
- Increasing restart frequency
- Error-budget burn rate

### 47.2 Predictive output

```text
Payment service risk: high

Observed trend:
Database connections: 70% → 78% → 85% → 91%

Prediction:
At the current trend, the service may enter a degraded state in approximately
20 minutes.

Confidence:
Medium

Recommended action:
Inspect connection growth and recent configuration changes.
```

Predictions must include:

- Time horizon
- Trend used
- Model or rule used
- Confidence
- Uncertainty
- Recommended next diagnostic

Predictive alerts should initially be advisory. They should not automatically create code changes.

---

## 48. Counterfactual and causal investigation

Sentinel should distinguish correlation from causation.

Useful questions include:

- If deployment X had not happened, would the incident likely have occurred?
- If database saturation were the cause, what additional signals should exist?
- Did unaffected regions run the same version?
- Did unaffected cohorts use the new feature flag?
- Did the error disappear after rollback or configuration correction?

The system should not claim formal causal inference without adequate experimental evidence. It can, however, perform structured counterfactual checks and report the result as supporting or weakening evidence.

---

## 49. Revised capability roadmap

### Foundation: required first

- Multi-organization data isolation
- Multi-repository and multi-service inventory
- Environments and deployments
- Service dependency graph foundation
- Metrics, logs, traces, health, and deployment ingestion
- Automatic incident detection
- Incident correlation
- Intent routing for developer tasks
- Evidence provenance
- Safe patch application
- Validation
- Approval and Draft PR controls

### Reliability intelligence: next

- Blast-radius analysis
- Explainable RCA timeline
- Change intelligence
- SLO and error-budget tracking
- Ownership and on-call context
- Runbook-aware read-only diagnostics
- Incident memory
- Service reliability profiles
- Agent activity timeline

### Advanced investigation: after the foundation

- Hypothesis disproof planning
- Regression test generation
- Incident-specific replay
- Change impact analysis
- Rollback risk analysis
- Post-deployment fix effectiveness
- Multi-region analysis
- Business-impact estimation

### Advanced intelligence: later

- Predictive incident detection
- Counterfactual analysis
- Confidence calibration
- Technical debt detection
- Dependency risk intelligence
- Structured organizational learning

### Specialized workflows

- Security incident mode
- AI incident commander mode
- Major-incident coordination
- Organization-specific policy profiles

---

## 50. Expanded definition of done

In addition to the original definition of done, the mature Sentinel platform should satisfy these guarantees:

- The company’s services, repositories, environments, deployments, dependencies, teams, and owners are represented in one connected model.
- An incident automatically produces a blast-radius assessment.
- Directly affected and indirectly affected services are distinguished.
- Observed impact and inferred impact are distinguished.
- Code, configuration, dependency, infrastructure, feature-flag, migration, and deployment changes are tracked.
- RCA is presented as an evidence-linked timeline.
- Hypotheses are actively tested and challenged.
- Reproducible bugs receive meaningful regression tests where possible.
- Candidate fixes are evaluated against the incident mechanism, not only compilation.
- Change impact and rollback risk are visible before PR creation.
- Region-specific and global failures are distinguished.
- Engineers can inspect Sentinel’s auditable actions and provide investigation feedback.
- Policy decisions are enforced by code, not prompts.
- Ownership and on-call information are available for affected services.
- Read-only runbook diagnostics can be executed safely.
- Historical incidents improve investigation without overriding current evidence.
- Security incidents use a separate, stricter workflow.
- SLO, error-budget, and reliability metrics are tracked.
- Post-deployment outcomes update fix effectiveness and incident memory.
- Predictive warnings include time horizon, evidence, model/rule, and uncertainty.

The mature product is therefore a continuously updated engineering intelligence system:

```text
Repositories + Services + Deployments + Runtime + Ownership
                         ↓
                  Sentinel system model
                         ↓
           Detection + impact + investigation
                         ↓
             Evidence + hypotheses + RCA
                         ↓
                Fix + validation + policy
                         ↓
                     Draft PR
                         ↓
               Human review and merge
                         ↓
                 Outcome and learning
```

---

## 51. Agent-executable implementation playbook

This section is written so that another coding agent can implement Sentinel step by step without needing to infer the architecture from the entire document.

The implementing agent must follow these rules:

1. Inspect existing code before changing it.
2. Make one phase work completely before beginning the next phase.
3. Do not replace working architecture with a new framework without a demonstrated need.
4. Do not make production writes while investigating.
5. Do not trust an LLM response without schema validation and deterministic checks.
6. Do not claim a feature is complete unless its acceptance tests pass.
7. Keep mock providers for tests, but never silently use mock intelligence in production.
8. Preserve multi-tenant and multi-repository boundaries in every new feature.
9. If evidence is missing, return a blocked or insufficient-evidence result instead of inventing an answer.
10. Do not solve a simple developer task using the production-incident workflow.

### 51.1 Required implementation order

Implement in this exact order:

```text
0. Baseline and safety audit
1. Provider-safe AI abstraction
2. Work-item model and intent router
3. Multi-repository company model
4. Service, environment, and deployment inventory
5. Signal ingestion and automatic detection
6. Dependency graph and blast radius
7. Type-specific investigation workflows
8. Evidence, memory, and explainability
9. Patch generation and regression tests
10. Isolated validation and incident replay
11. Policy gateway and approval workflow
12. Multi-repository Draft PR workflow
13. Operations UI and incident command center
14. Outcome monitoring, SLOs, prediction, and learning
15. Evaluation and production hardening
```

Do not begin predictive detection, technical-debt detection, or autonomous remediation before phases 0–12 are stable.

---

## 52. Development rules for the AI provider constraint

### 52.1 Primary requirement

The project must work with a free or low-cost Nemotron API rather than assuming access to paid models.

The AI layer must therefore be provider-agnostic and cost-aware.

### 52.2 Provider interface

Keep one stable internal interface in `backend/app/services/llm.py`:

```python
class LLMProvider:
    async def generate_text(self, messages, **options): ...
    async def generate_json(self, messages, schema, **options): ...
```

The provider implementation must support:

- Nemotron-compatible API endpoint
- Mock provider for tests
- Optional local provider later
- Configurable model name
- Configurable base URL
- Timeout
- Retry count
- Maximum input size
- Maximum output tokens
- Request cost metadata
- Request ID and model metadata

Configuration should come from environment variables, for example:

```text
LLM_PROVIDER=nemotron
LLM_BASE_URL=<provider endpoint>
LLM_API_KEY=<secret>
LLM_MODEL=<nemotron model name>
LLM_TIMEOUT_SECONDS=60
LLM_MAX_OUTPUT_TOKENS=4000
```

Never hardcode the API key, endpoint, or model name.

### 52.3 Low-cost execution strategy

Use deterministic code before calling Nemotron:

- Detect obvious intent with rules.
- Extract file names with rules.
- Extract service names with known inventory data.
- Validate repository scope in code.
- Use the LLM only for ambiguity, synthesis, code understanding, and patch generation.

Cache safe repeated requests using a hash of:

```text
provider
model
prompt version
input context hash
schema version
```

Never cache responses containing secrets or unbounded production data.

### 52.4 Structured output requirement

Every LLM call that controls a workflow must return a validated schema.

If the provider cannot reliably return JSON:

1. Ask for JSON only.
2. Extract the first JSON object defensively.
3. Validate it with Pydantic.
4. Reject invalid output.
5. Retry once with a correction prompt.
6. Mark the task failed if the second attempt is invalid.

Do not parse arbitrary prose as an instruction to modify code.

### 52.5 Model fallback behavior

Production behavior must be explicit:

```text
Nemotron available       → use Nemotron
Nemotron temporarily down → retry, then mark task blocked
Mock enabled explicitly   → allow only in development/test
No provider configured    → fail clearly
```

The system must never silently produce a fake root cause or fake patch because a real model is unavailable.

---

## 53. Phase 0: baseline, backup, and safety audit

### Objective

Understand the current implementation and eliminate unsafe behavior before adding capabilities.

### Agent instructions

1. Read `# Sentinel.txt`, `docs/operations.md`, and this document.
2. Read all backend routes, models, investigation services, GitHub services, and validation services.
3. Run the existing backend test suite.
4. Run frontend lint and build.
5. Record every failure before changing behavior.
6. Inspect `git status` and preserve unrelated user changes.
7. Search for unsafe file replacement, automatic approval, token logging, broad exception swallowing, and cross-tenant queries.

### Required safety fixes

- Reject an unmatched patch replacement.
- Reject an ambiguous replacement occurring more than once.
- Reject empty or malformed patches.
- Remove any path that marks a fix approved without a real authorized approval.
- Ensure Draft PR creation checks organization, investigation, fix, validation, repository, and authorization.
- Ensure GitHub tokens never appear in responses or logs.
- Add audit events for every branch, commit, and PR operation.

### Acceptance tests

```text
Invalid old_code → patch rejected
Duplicate old_code → patch rejected
Empty changes → PR rejected
Unapproved fix → PR rejected
User from another organization → access denied
GitHub token in output/log → test fails
```

Do not continue until these tests pass.

---

## 54. Phase 1: work items and intent routing

### Objective

Stop treating every user request as an incident.

### Files to add or modify

```text
backend/app/models/incident.py
backend/app/routes/work_items.py
backend/app/services/intent_router.py
backend/app/services/workflow_router.py
backend/app/schemas/work_items.py
backend/tests/test_intent_router.py
backend/tests/test_work_items.py
```

### Required work types

```text
DIRECT_TASK
BUG
FEATURE
PRODUCTION_INCIDENT
SECURITY_INCIDENT
```

### Router output

```json
{
  "work_type": "DIRECT_TASK",
  "confidence": 0.95,
  "repository_scope": [],
  "service_scope": [],
  "environment_scope": [],
  "target_files": [],
  "requires_runtime_evidence": false,
  "requires_code_change": true,
  "workflow": "repository_task"
}
```

### Required deterministic examples

```text
“Add README.md”                  → DIRECT_TASK
“Create CONTRIBUTING.md”         → DIRECT_TASK
“Fix login returns 500”          → BUG
“Add dark mode”                  → FEATURE
“Production checkout is down”    → PRODUCTION_INCIDENT
“CPU is high in prod”            → PRODUCTION_INCIDENT
“Suspicious login activity”      → SECURITY_INCIDENT
```

### Acceptance test

For “Add a comprehensive README.md file”:

- No root-cause hypotheses are generated.
- No production metrics are queried.
- No unrelated files are selected.
- The target file is identified as `README.md`.
- The repository task workflow is selected.

---

## 55. Phase 2: company and multi-repository model

### Objective

Allow one organization to manage many repositories, services, teams, and environments.

### Required entities

```text
Organization
UserMembership
Team
Service
Environment
Repository
ServiceRepository
Deployment
Dependency
Ownership
```

### Required relationship examples

```text
Organization: Acme
├── Team: Payments
├── Service: payment-service
│   ├── production / us-east
│   ├── production / ap-south
│   └── company/payment-service
├── Service: checkout-api
│   └── company/checkout-api
└── Repository: company/platform-config
```

### Agent instructions

1. Add migrations rather than altering only runtime tables.
2. Add organization ownership to every new row.
3. Add unique constraints for provider IDs and repository scope.
4. Create service-to-repository relationship records instead of a single repository string.
5. Add API endpoints for services, environments, dependencies, and deployments.
6. Add tests for multiple repositories and multiple organizations.

### Acceptance test

Create an organization with three services and five repositories. Verify that:

- Each service maps to one or more repositories.
- One repository can support multiple services.
- Repository results are organization-scoped.
- The resolver returns all relevant repositories with reasons.
- It never chooses the first repository by default.

---

## 56. Phase 3: service and deployment inventory

### Objective

Make Sentinel able to answer what is deployed and where.

### Deployment fields

```text
organization_id
service_id
environment_id
repository_id
commit_sha
version
provider
external_deployment_id
deployed_at
status
url
metadata
```

### Required ingestion sources

Start with:

1. Manual service registration.
2. GitHub deployment webhook.
3. Generic deployment webhook.
4. Health-check configuration.

Add provider-specific deployment integrations later.

### Acceptance test

Given:

```text
service = payment-service
environment = production-us
repository = company/payment-service
commit = abc123
```

Sentinel must show the current deployment and link future incidents to `abc123`.

---

## 57. Phase 4: autonomous production monitoring

### Objective

Detect production incidents without a human creating a request.

### Required architecture

```text
Provider signal
      ↓
Authenticated ingestion endpoint or poller
      ↓
Signal normalizer
      ↓
Persist raw and normalized signal
      ↓
Fingerprint and deduplicate
      ↓
Correlate with active incidents
      ↓
Detection rule evaluation
      ↓
Create/update incident
      ↓
Submit investigation job
```

### MVP providers

Implement these first:

- Prometheus/Alertmanager
- Generic signed webhook
- GitHub deployment events
- Service health checks
- One exception provider such as Sentry

### Required signal fields

```text
organization
provider
external_id
signal_type
service
environment
region
metric or error signature
value
threshold
observed_at
raw payload reference
```

### Worker requirement

Do not use only `asyncio.create_task()` for autonomous incident handling. Use the Redis-backed durable queue with:

- Idempotency keys
- Retry count
- Lease timeout
- Failure state
- Persistent progress
- Recovery after worker restart

### Acceptance test

Send a synthetic Prometheus alert stating that error rate is 20% above a 5% threshold. Verify:

1. No user creates an incident manually.
2. The signal is persisted.
3. An incident is created.
4. Duplicate alerts update the same incident.
5. An investigation job is queued.
6. The incident appears in the operations dashboard.

---

## 58. Phase 5: dependency graph and blast radius

### Objective

Understand impact across services and repositories.

### Agent instructions

1. Create graph node and edge records.
2. Import explicit service dependencies.
3. Derive relationships from traces where available.
4. Derive repository relationships from service inventory.
5. Traverse downstream dependencies when an incident is created.
6. Compare predicted impact with observed downstream signals.
7. Label every relationship with source and confidence.

### Blast-radius output

```json
{
  "direct_services": [],
  "indirect_services": [],
  "affected_endpoints": [],
  "affected_repositories": [],
  "affected_regions": [],
  "affected_environments": [],
  "observed_traffic_percent": null,
  "estimated_user_percent": null,
  "unknowns": []
}
```

### Acceptance test

Given:

```text
Frontend → Checkout → Payment → PaymentDB
```

When Payment fails, Sentinel must identify:

- Payment as directly affected.
- Checkout as a likely downstream impact.
- Frontend as a possible customer-facing impact.
- PaymentDB as a dependency.
- Unrelated Inventory as unaffected unless telemetry says otherwise.

---

## 59. Phase 6: type-specific investigation workflows

### Objective

Use the correct investigation for each work type.

### Workflow registry

Create a workflow registry with explicit handlers:

```python
WORKFLOWS = {
    "repository_task": run_repository_task,
    "bug_investigation": run_bug_investigation,
    "feature_implementation": run_feature_workflow,
    "production_incident": run_incident_workflow,
    "security_incident": run_security_workflow,
}
```

### Direct task workflow

Required steps:

```text
Resolve repository
→ Inspect tree
→ Detect project
→ Read relevant context
→ Generate task plan
→ Generate patch
→ Validate
→ Create Draft PR
```

### Production workflow

Required steps:

```text
Read incident signals
→ Identify service/environment/region
→ Calculate blast radius
→ Find current deployment
→ Retrieve recent changes
→ Collect metrics/logs/traces
→ Inspect relevant code
→ Search historical memory
→ Generate hypotheses
→ Seek contradicting evidence
→ Select root cause or abstain
→ Generate fix/test
→ Validate/replay
→ Apply policy
→ Create Draft PRs
```

### Acceptance test

The README request and synthetic production alert must produce different task graphs and different evidence requirements.

---

## 60. Phase 7: evidence, memory, and explanations

### Objective

Make every important decision explainable and reusable.

### Evidence record

Every evidence record must contain:

```text
organization_id
incident_id or work_item_id
source_type
source_id
service
environment
region
repository
commit_sha
observed_at
content reference
source URL
retrieval method
```

### Explanation structure

```text
Observed evidence
Derived inference
Conclusion
Uncertainty
```

### Incident memory

Only store confirmed knowledge after outcome review:

```text
error signature
service
deployment pattern
confirmed cause
successful fix
validation method
post-deployment outcome
```

Historical memory can guide investigation but cannot override current evidence.

### Acceptance test

The incident screen must show why a repository, hypothesis, or root cause was selected, including supporting and contradicting evidence.

---

## 61. Phase 8: patch generation and regression tests

### Objective

Generate precise, repository-specific changes.

### Agent instructions

1. Pin the repository to a base commit SHA.
2. Provide only relevant files and context to Nemotron.
3. Require structured patch output.
4. Validate file scope before applying the patch.
5. Generate a regression test for reproducible bugs where possible.
6. Show the exact unified diff.
7. Reject unexpected files and oversized changes.

### Direct task acceptance test

For “Add README.md”:

- Create exactly `README.md` if it does not exist.
- Do not modify `repositories.py`, `main.py`, or unrelated files.
- Base content on the actual repository.
- Validate Markdown and commands.

### Bug acceptance test

For an empty-password login bug:

- Find the actual authentication code.
- Generate a test that captures the failure.
- Apply the fix.
- Verify the test passes after the patch.
- Include the test in the Draft PR where appropriate.

---

## 62. Phase 9: isolated validation and incident replay

### Objective

Determine whether the patch fixes the actual problem, not only whether it compiles.

### Validation stages

```text
Checkout exact SHA
→ Apply patch
→ Reproduce original failure if possible
→ Run regression test
→ Run repository tests
→ Run lint/type/build/security checks
→ Replay sanitized scenario
→ Compare before and after
→ Persist report
```

### Safety rules

- Never replay real customer data without sanitization.
- Never replay against production by default.
- Never allow arbitrary model-generated shell commands without validation and policy approval.
- Apply resource limits and timeouts.
- Store command output securely.

### Acceptance test

The validation report must distinguish:

```text
Compilation: passed
Tests: passed
Original failure reproduced: yes/no/unknown
Failure absent after patch: yes/no/unknown
Production outcome: not yet known
```

---

## 63. Phase 10: policy gateway and approvals

### Objective

Move safety decisions out of prompts and into deterministic policy code.

### Policy checks

Before any external write, check:

```text
Organization ownership
User or worker authorization
Repository scope
File scope
Risk category
Evidence threshold
Validation result
Approval requirement
Base SHA freshness
```

### Default policy

```text
Read production telemetry       allowed
Write production                forbidden
Read repositories               allowed
Create branch                   allowed after validation
Create Draft PR                 allowed after policy checks
Merge PR                        forbidden
Modify secrets                  forbidden
Modify infrastructure           multiple approvals
Modify database migrations      multiple approvals
```

### Acceptance test

Attempt each forbidden action through the API and verify that the policy gateway blocks it regardless of what the LLM requests.

---

## 64. Phase 11: multi-repository remediation

### Objective

Create independent, traceable fixes for each repository that actually needs modification.

### Required parent-child structure

```text
Parent incident
├── Repository investigation A
│   └── Fix → validation → Draft PR A
├── Repository investigation B
│   └── Fix → validation → Draft PR B
└── Evidence-only repository C
    └── No fix
```

### Rules

- Never combine unrelated repositories into one patch.
- Pin each repository to its own base SHA.
- Validate each repository independently.
- Create no PR for an evidence-only repository.
- Show cross-repository ordering requirements.
- Detect whether one fix must merge before another.

### Acceptance test

Create a synthetic incident affecting two repositories. Verify two independent diffs, two validation results, and two Draft PR records.

---

## 65. Phase 12: operations command center

### Objective

Provide a clear company-wide view of deployed systems and incidents.

### Required pages

- Organization overview
- Service inventory
- Dependency graph
- Deployment inventory
- Active incidents
- Incident workspace
- Investigation activity
- Draft PR review queue
- Reliability/SLO dashboard
- Integrations and policies

### Organization overview metrics

```text
Active incidents
Healthy services
Degraded services
Down services
Recent deployments
Predicted risks
Draft PRs
Error-budget burn
```

### Incident screen

The incident screen must include:

- Detection source
- Impact and blast radius
- Regions and environments
- Current deployment
- Change ledger
- Explainable timeline
- Evidence
- Hypothesis competition
- Root cause or abstention
- Proposed fixes by repository
- Validation
- Policy decision
- Draft PRs
- Activity log
- Human feedback

---

## 66. Phase 13: reliability, prediction, and learning

Implement only after the monitoring and historical data foundation is reliable.

### Reliability metrics

- MTTD
- MTTA
- MTTR
- Availability
- Error rate
- SLO compliance
- Error-budget consumption
- Change failure rate
- Incident frequency

### Predictive detection

Start with transparent statistical rules:

- Moving averages
- Rate-of-change
- Linear trend
- Burn-rate thresholds
- Forecast horizon

Only introduce more complex models after measuring false positives and false negatives.

### Outcome learning

After a PR is merged and deployed:

1. Identify the deployment.
2. Monitor the affected service.
3. Compare metrics before and after.
4. Check whether the error signature disappeared.
5. Detect regressions.
6. Update incident memory only after outcome confirmation.

---

## 67. Test scenarios every implementation agent must run

### Scenario 1: README creation

```text
Input: Add a comprehensive README.md
Expected: direct task, one-file patch, no incident RCA
```

### Scenario 2: Bug fix

```text
Input: Login returns 500 for empty password
Expected: auth investigation, regression test, scoped patch
```

### Scenario 3: Feature request

```text
Input: Add dark mode toggle
Expected: frontend workflow, relevant multi-file patch, frontend validation
```

### Scenario 4: Automatic CPU incident

```text
Input: synthetic CPU alert from production
Expected: automatic signal ingestion, incident, investigation job
```

### Scenario 5: Deployment regression

```text
Input: deployment followed by latency and error spike
Expected: deployment correlation, changed-code investigation, RCA evidence
```

### Scenario 6: Multi-repository incident

```text
Input: Payment failure affecting Checkout
Expected: dependency traversal, two repository investigations, independent PRs
```

### Scenario 7: Insufficient evidence

```text
Input: generic outage without deployment, logs, or trace evidence
Expected: abstention, no fabricated root cause, no unsafe patch
```

### Scenario 8: Security incident

```text
Input: suspicious authentication activity
Expected: security workflow, evidence preservation, no automatic production mutation
```

---

## 68. Definition of success for the first working product

The first meaningful milestone is not every advanced capability. It is this complete vertical slice:

```text
Two repositories
Two services
One production environment
Prometheus or synthetic monitoring signal
Automatic incident creation
Deployment correlation
Evidence-backed investigation
One or more hypotheses
Safe patch generation
Validation
One Draft PR per affected repository
Human approval required for merge
```

In parallel, prove the developer workflow:

```text
“Add README.md”
→ direct task routing
→ repository-aware content
→ exact one-file patch
→ validation
→ Draft PR
```

These two vertical slices prove the central product promise: Sentinel can understand both ordinary engineering work and autonomous production incidents.

---

## 69. Instructions for handing this document to another coding agent

Give the coding agent the following instruction:

```text
You are implementing Sentinel according to SENTINEL_IMPLEMENTATION_PLAN.md.

Read the entire plan and inspect the current repository before editing.
Implement only one numbered phase at a time.
For the selected phase:
1. List the files you will inspect.
2. List the database/API/code changes required.
3. Implement the smallest complete slice.
4. Add or update tests.
5. Run the relevant tests and checks.
6. Report failures honestly.
7. Do not continue to the next phase until the current phase acceptance criteria pass.

Never:
- invent evidence
- silently use mock intelligence in production
- modify an unapproved repository
- overwrite a file after an unmatched replacement
- merge or deploy code
- bypass the policy gateway
- expose secrets
- treat a production incident and a direct developer task as the same workflow

If a requirement is ambiguous, preserve safety, keep the change reversible,
and report the ambiguity instead of guessing.
```

The implementing agent should maintain a progress file or issue checklist showing:

```text
Phase
Status
Files changed
Tests added
Tests passed
Known limitations
Next safe step
```

---

## 70. Final implementation principle

Do not try to make Sentinel “smart” by giving a weak model a larger prompt.

Make the system smart through structure:

```text
Correct data model
+ correct service graph
+ correct runtime signals
+ correct repository context
+ correct workflow selection
+ evidence provenance
+ deterministic safety checks
+ isolated validation
+ human-controlled policy gates
```

Nemotron can then perform the language and reasoning work it is good at while the application code guarantees that it acts on the correct service, repository, environment, evidence, and scope.
