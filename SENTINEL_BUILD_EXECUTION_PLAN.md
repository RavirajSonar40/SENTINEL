# Sentinel Build Execution Plan

## Purpose of this document

This is the implementation document for Sentinel.

It is written for a coding agent that may have limited reasoning ability, limited context, or limited model quality. The agent must follow the instructions literally, inspect the current repository, implement one phase at a time, run the required tests, and report the result before continuing.

This document is not a product essay. It is an execution contract.

The project directory is:

```text
D:\AI INCIDENT RESPONSE
```

The application has:

```text
backend/       FastAPI/Python API and services
sentinel-ui/   Next.js/React frontend
docs/          architecture and operational documents
```

The current infrastructure is:

```text
PostgreSQL     durable application data
Redis          background jobs and event processing
Pinecone       vector/code/document retrieval
GitHub         repositories, commits, branches, Draft PRs
Nemotron API   low-cost/free LLM provider
```

---

## 1. Product definition

Sentinel is a multi-repository AI engineering and production incident-response system.

It must perform two separate jobs.

### Job A: developer assistant

A human may request:

```text
Add README.md
Fix login when the password is empty
Add dark mode to settings
Upgrade a dependency
Add tests for this bug
```

Sentinel must understand the request, inspect the correct repositories, make a scoped change, validate it, and prepare a GitHub Draft PR.

### Job B: autonomous production agent

A human does not need to submit a request when production becomes unhealthy.

Sentinel must continuously receive or collect:

- Metrics
- Logs
- Traces
- Health-check results
- Alerts
- Deployment events
- Configuration changes
- Feature-flag changes
- Dependency changes
- Infrastructure changes

When a production problem is detected, Sentinel must automatically:

```text
Detect signal
→ create or update incident
→ identify service/environment/region
→ identify repositories
→ calculate blast radius
→ investigate evidence
→ compare competing hypotheses
→ identify root cause or abstain
→ create regression test where possible
→ generate fix
→ validate fix
→ apply safety policy
→ create one Draft PR per affected repository
```

The human is involved for review and approval. Sentinel must never merge or deploy autonomously.

---

## 2. Non-negotiable rules

Every implementation agent must follow these rules.

### Safety rules

1. Never merge a pull request.
2. Never deploy to production.
3. Never write to production infrastructure in the initial product.
4. Never overwrite a complete file because a patch snippet was not found.
5. Never modify a repository outside the approved scope.
6. Never create a fix when evidence is insufficient.
7. Never present an LLM guess as observed evidence.
8. Never expose API keys, tokens, passwords, or secrets.
9. Never bypass organization or user authorization.
10. Never silently fall back from Nemotron to fake production intelligence.

### Engineering rules

1. Inspect before editing.
2. Preserve unrelated user changes.
3. Use Alembic migrations for database changes.
4. Add tests with each behavior change.
5. Keep changes small and reversible.
6. Run the relevant test suite after each phase.
7. Do not mark a phase complete if its acceptance criteria fail.
8. Persist long-running work; do not rely only on in-memory state.
9. Use exact repository and commit context for patches.
10. If uncertain, block safely and report the missing information.

---

## 3. Required handoff procedure

If one coding agent stops, the next agent must begin with this procedure.

### Step 1: inspect checkpoint

Read:

```text
SENTINEL_BUILD_EXECUTION_PLAN.md
SENTINEL_IMPLEMENTATION_PLAN.md
docs/operations.md
```

Then inspect:

```text
git status --short
git log -5 --oneline
```

### Step 2: determine current phase

Find the most recent checkpoint file:

```text
docs/implementation-progress.md
```

If it does not exist, create it after inspecting the current repository. Do not assume that the last completed phase is known from conversation history.

### Step 3: verify the previous phase

Run the previous phase’s acceptance tests. If they fail, fix that phase before starting new work.

### Step 4: continue only one phase

Implement the next incomplete phase. Do not implement multiple phases in one uncontrolled change.

### Step 5: update checkpoint

The checkpoint must contain:

```markdown
# Sentinel implementation progress

Current phase: PHASE-N
Status: in_progress | blocked | complete

Completed:
- ...

Files changed:
- ...

Tests run:
- command: ...
  result: passed/failed

Known limitations:
- ...

Next action:
- ...
```

---

## 4. Current architecture to preserve

Before editing, inspect these files.

```text
backend/app/main.py
backend/app/models/incident.py
backend/app/core/config.py
backend/app/core/auth.py
backend/app/core/database.py
backend/app/services/llm.py
backend/app/services/task_queue.py
backend/app/services/investigation_engine.py
backend/app/services/hypothesis_engine.py
backend/app/services/retrieval.py
backend/app/services/vector_store.py
backend/app/services/diff_generator.py
backend/app/services/validation.py
backend/app/services/github.py
backend/app/services/repository_resolver.py
backend/app/routes/incidents.py
backend/app/routes/auto_detect.py
backend/app/routes/webhooks.py
backend/app/routes/investigation_engine.py
backend/app/routes/remediation.py
backend/app/routes/approvals.py
backend/app/routes/health.py
backend/app/routes/metrics.py
sentinel-ui/src/lib/api.ts
sentinel-ui/src/app/incidents/
sentinel-ui/src/app/investigations/
sentinel-ui/src/app/repositories/
sentinel-ui/src/app/health/
sentinel-ui/src/app/pull-requests/
```

Do not delete these components merely because they are incomplete. Improve them or add new services around them.

---

## 5. Final system architecture

```text
                 SENTINEL CONTROL PLANE
       users / organizations / policies / permissions
                              │
       ┌──────────────────────┼──────────────────────┐
       │                      │                      │
       ▼                      ▼                      ▼
  Company Graph          Observability          Developer Work
  repos/services/        metrics/logs/          direct tasks/bugs/
  deployments/owners     traces/alerts          features
       │                      │                      │
       └──────────────────────┼──────────────────────┘
                              ▼
                    Work-Item Router
                              ▼
                   Type-Specific Workflow
                              ▼
       Evidence → Hypotheses → RCA or Abstention
                              ▼
                   Patch and Test Generation
                              ▼
                Validation and Safety Gateway
                              ▼
                     Draft PR per repository
                              ▼
                  Human review and external merge
                              ▼
                     Outcome monitoring/memory
```

The central application concepts are:

```text
Organization
  → User and memberships
  → Teams and ownership
  → Services
  → Environments and regions
  → Repositories
  → Deployments
  → Dependencies
  → Signals
  → Work items/incidents
  → Investigations
  → Evidence
  → Hypotheses
  → Root causes
  → Fixes
  → Validation runs
  → Approvals
  → Draft PRs
  → Outcomes and memory
```

---

## 6. Phase 0 — baseline and safety audit

### Goal

Understand the current code and remove dangerous behavior before adding intelligence.

### Instructions

1. Run the backend tests.
2. Run frontend lint.
3. Run frontend build.
4. Run the backend application locally if dependencies are available.
5. Inspect database migrations.
6. Search for unsafe file replacement.
7. Search for automatic approval.
8. Search for tokens written to logs or responses.
9. Search for broad exception swallowing.
10. Record all failures in the checkpoint.

### Required safety fixes

The agent must verify and fix:

- Invalid `old_code` cannot overwrite a whole file.
- Duplicate `old_code` cannot be replaced ambiguously.
- Empty patches cannot be published.
- Files outside approved scope cannot be changed.
- Fixes cannot become approved automatically without an authorized approval record.
- Draft PR creation checks organization, investigation, fix, repository, validation, and authorization.
- GitHub tokens are not returned by APIs.
- GitHub tokens are encrypted at rest.
- Webhook signatures are verified.
- OAuth state is validated.

### Tests required

```text
test_invalid_patch_is_rejected
test_duplicate_patch_target_is_rejected
test_empty_patch_is_rejected
test_unapproved_fix_is_rejected
test_cross_organization_access_is_rejected
test_webhook_signature_is_required
test_tokens_are_not_serialized
```

### Completion condition

Do not begin Phase 1 until all safety tests pass or a specific external dependency is documented as blocked.

---

## 7. Phase 1 — Nemotron-compatible AI provider

### Goal

Make the intelligence layer work with the user’s free/low-cost Nemotron API.

### Files

```text
backend/app/core/config.py
backend/app/services/llm.py
backend/tests/test_llm_provider.py
.env.example
```

### Required environment configuration

```text
LLM_PROVIDER=nemotron
LLM_BASE_URL=<Nemotron-compatible endpoint>
LLM_API_KEY=<secret>
LLM_MODEL=<configured model name>
LLM_TIMEOUT_SECONDS=60
LLM_MAX_OUTPUT_TOKENS=4000
LLM_MAX_RETRIES=2
```

The endpoint and model must be configurable. Do not hardcode assumptions about the exact Nemotron hosting provider.

### Provider behavior

Implement:

```python
async def generate_text(messages, options=None) -> LLMResponse
async def generate_json(messages, schema, options=None) -> LLMResponse
```

The response must record:

```text
provider
model
request ID
input token estimate
output token estimate
latency
error state
```

### Structured response behavior

For JSON requests:

1. Request JSON explicitly.
2. Parse defensively.
3. Validate with Pydantic.
4. Retry one time on malformed output.
5. Mark the task failed if the retry is invalid.

### Cost controls

Before calling Nemotron, use deterministic code for:

- Obvious intent classification
- File-name extraction
- Repository matching
- Permission checks
- Scope checks
- Patch validation

Add a response cache for safe repeated analysis. Cache keys must include provider, model, prompt version, context hash, and schema version.

### Mock provider rule

The mock provider may be used only when explicitly configured for tests or local development. Production must not silently use mock responses.

### Completion tests

```text
test_nemotron_request_uses_configured_endpoint
test_api_key_is_not_logged
test_invalid_json_is_retried
test_invalid_json_after_retry_fails
test_mock_provider_requires_explicit_configuration
test_provider_timeout_is_reported_as_blocked
```

---

## 8. Phase 2 — work items and intent routing

### Goal

Ensure that Sentinel understands what is being asked before choosing a workflow.

### Required work types

```text
DIRECT_TASK
BUG
FEATURE
PRODUCTION_INCIDENT
SECURITY_INCIDENT
```

### Files

```text
backend/app/models/work_item.py
backend/app/schemas/work_item.py
backend/app/routes/work_items.py
backend/app/services/intent_router.py
backend/app/services/workflow_router.py
backend/tests/test_intent_router.py
backend/tests/test_workflow_router.py
```

### Router output

```json
{
  "work_type": "DIRECT_TASK",
  "confidence": 0.95,
  "repository_scope": [],
  "service_scope": [],
  "environment_scope": [],
  "region_scope": [],
  "target_files": ["README.md"],
  "requires_runtime_evidence": false,
  "requires_code_change": true,
  "workflow": "repository_task"
}
```

### Required classifications

```text
“Add README.md”                 → DIRECT_TASK
“Create CONTRIBUTING.md”        → DIRECT_TASK
“Fix login returns 500”         → BUG
“Add dark mode”                 → FEATURE
“Production checkout is down”   → PRODUCTION_INCIDENT
“CPU is high in production”     → PRODUCTION_INCIDENT
“Suspicious login activity”     → SECURITY_INCIDENT
```

### Required behavior

For a direct task:

- Do not create incident hypotheses.
- Do not query production telemetry.
- Do not search unrelated code.
- Do not select arbitrary files.

For an automatically received production alert:

- Create a production incident without a human request.
- Start the production incident workflow.

### Completion tests

```text
test_readme_is_direct_task
test_login_error_is_bug
test_dark_mode_is_feature
test_cpu_alert_is_production_incident
test_security_signal_uses_security_workflow
test_direct_task_skips_incident_hypotheses
```

---

## 9. Phase 3 — organization, repositories, services, and environments

### Goal

Represent a real company with many repositories and services.

### Required entities

```text
Organization
Membership
Team
Service
Environment
Region
Repository
ServiceRepository
Deployment
Dependency
Ownership
```

### Repository relationships

Never use only one repository string for a service.

```text
checkout-api
├── company/checkout-api       application
├── company/platform-config    configuration
├── company/infrastructure     infrastructure
└── company/shared-auth        dependency
```

Each relationship must store:

```text
organization_id
service_id
repository_id
role
is_primary
confidence
source
```

### Environment and region

Represent:

```text
production / us-east
production / ap-south
staging / us-east
preview / pull-request-123
```

### Required migrations

Use Alembic. Do not rely only on `create_all()` or startup `ALTER TABLE` statements.

### Required APIs

```text
GET/POST /organizations
GET/POST /services
GET/POST /environments
GET/POST /repositories
GET/POST /service-repositories
GET/POST /dependencies
GET/POST /ownership
```

### Completion tests

Create one organization containing:

- Three services
- Five repositories
- Three environments
- Two regions
- One shared dependency repository

Verify:

- A service maps to multiple repositories.
- A repository can support multiple services.
- Organization A cannot read Organization B.
- All repository selections include reasons.
- No code assumes the first connected repository is correct.

---

## 10. Phase 4 — deployment inventory

### Goal

Allow Sentinel to answer what is deployed, where it is deployed, and which commit is running.

### Deployment record

```text
organization_id
service_id
environment_id
region_id
repository_id
commit_sha
version
provider
external_deployment_id
status
url
deployed_at
metadata
```

### Initial ingestion

Implement:

1. Manual deployment registration.
2. GitHub deployment webhook.
3. Generic signed deployment webhook.
4. Provider-independent deployment API.

### Required queries

```text
current deployment for service/environment/region
deployments during incident window
previous stable deployment
commits included between deployments
deployment status history
```

### Completion test

Register:

```text
payment-service
production-us
company/payment-service
commit abc123
version v2.8.1
```

Verify that a future incident for `payment-service` automatically retrieves this deployment and commit.

---

## 11. Phase 5 — autonomous monitoring and detection

### Goal

Automatically detect production incidents without a human submitting a request.

### Important clarification

Sentinel does not magically observe CPU or service health. It must integrate with telemetry providers or execute configured health checks.

### Initial providers

Implement in this order:

1. Prometheus/Alertmanager.
2. Generic signed webhook.
3. GitHub deployment events.
4. Health-check poller.
5. Sentry or another exception provider.

### Signal pipeline

```text
Provider
→ authenticated receiver/poller
→ normalized signal
→ raw payload reference
→ fingerprint
→ deduplication
→ incident correlation
→ rule evaluation
→ incident create/update
→ investigation job
```

### Signal schema

```json
{
  "organization_id": "...",
  "provider": "prometheus",
  "external_id": "alert-123",
  "signal_type": "metric_threshold",
  "service": "checkout-api",
  "environment": "production",
  "region": "us-east",
  "metric": "http_error_rate",
  "value": 0.20,
  "threshold": 0.05,
  "observed_at": "2026-08-28T10:00:00Z",
  "raw_payload_reference": "..."
}
```

### Initial rules

- CPU threshold
- Memory threshold
- Error-rate threshold
- Latency threshold
- Health-check failure
- Crash-loop detection
- Restart spike
- Disk threshold
- Queue backlog
- Database connection saturation
- Deployment regression
- Repeated exception signature

### Correlation key

Use:

```text
organization
service
environment
region
signal class
error signature
time window
deployment
```

### Completion test

Send synthetic alerts for:

```text
CPU 98%
error rate 20%
health check failing
deployment 10 minutes earlier
```

Verify:

- No human creates an incident.
- One incident is created.
- Duplicate signals attach to the same incident.
- The incident records affected environment and region.
- An investigation job is queued.
- The dashboard updates automatically.

---

## 12. Phase 6 — service graph and blast radius

### Goal

Understand the company as a connected system.

### Graph nodes

```text
service
repository
endpoint
environment
region
database
queue
external provider
team
deployment
```

### Graph edges

```text
calls
depends_on
implemented_by
deployed_as
owned_by
stores_in
publishes_to
consumes_from
```

### Graph sources

- Service registration
- Repository configuration
- Kubernetes and Helm files
- Terraform
- API specifications
- OpenTelemetry traces
- Import analysis
- Deployment metadata
- CODEOWNERS
- Human corrections

Every edge must have a source and confidence.

### Blast-radius calculation

```text
Incident
→ directly affected service
→ endpoint
→ dependency traversal
→ observed downstream signals
→ traffic and user estimates
→ blast-radius report
```

### Output

```json
{
  "direct_services": [],
  "indirect_services": [],
  "affected_endpoints": [],
  "affected_repositories": [],
  "affected_environments": [],
  "affected_regions": [],
  "observed_traffic_percent": null,
  "estimated_user_percent": null,
  "unknowns": []
}
```

### Rules

- Mark observed impact separately from inferred impact.
- Do not label every graph neighbor as affected.
- Use telemetry to confirm downstream impact.
- Do not create a patch for an evidence-only repository.

### Completion test

For:

```text
Frontend → Checkout → Payment → PaymentDB
```

When Payment fails, Sentinel must identify:

- Payment as directly affected.
- Checkout as a likely downstream service.
- Frontend as possible customer-facing impact.
- PaymentDB as a dependency.
- Inventory as unaffected unless signals show otherwise.

---

## 13. Phase 7 — change intelligence

### Goal

Track all meaningful changes, not just deployments.

### Change types

```text
code commit
pull request
configuration
environment variable
dependency upgrade
database migration
infrastructure
feature flag
API contract
deployment
scaling change
```

### Change record

```text
organization_id
service_id
environment_id
repository_id
change_type
external_id
commit_sha
author
effective_at
observed_at
affected_components
source_url
metadata
```

### Incident behavior

When an incident begins, retrieve changes from a configurable window such as 30 minutes, 2 hours, and 24 hours.

Rank:

1. Changes deployed immediately before failure.
2. Feature flags enabled immediately before failure.
3. Configuration changes.
4. Dependency upgrades.
5. Database migrations.
6. Infrastructure changes.
7. Related repository changes.

### Completion test

Given:

```text
10:00 feature flag OFF
10:05 feature flag ON
10:07 error rate increases
```

Sentinel must show the timing relationship and mark it as correlation, not proof.

---

## 14. Phase 8 — investigation workflows

### Goal

Implement separate workflows for separate work types.

### Workflow registry

```python
WORKFLOWS = {
    "repository_task": run_repository_task,
    "bug": run_bug_investigation,
    "feature": run_feature_implementation,
    "production_incident": run_production_investigation,
    "security_incident": run_security_investigation,
}
```

### Direct task workflow

```text
Resolve repository
→ inspect repository tree
→ read manifests and configuration
→ inspect relevant files
→ create task plan
→ generate patch
→ validate
→ create Draft PR
```

### Bug workflow

```text
Identify affected code
→ inspect tests
→ inspect symbols and call paths
→ inspect relevant history
→ generate hypotheses
→ generate regression test
→ generate patch
→ validate
→ create Draft PR
```

### Feature workflow

```text
Understand architecture
→ identify affected modules
→ inspect conventions
→ plan multi-file change
→ implement
→ validate
→ create Draft PR
```

### Production workflow

```text
Read signals
→ identify service/environment/region
→ calculate blast radius
→ retrieve current deployment
→ retrieve recent changes
→ query metrics/logs/traces
→ inspect affected code
→ search incident memory
→ generate hypotheses
→ seek contradicting evidence
→ select root cause or abstain
→ generate test and patch
→ validate/replay
→ apply policy
→ create Draft PRs
```

### Security workflow

```text
Preserve evidence
→ identify affected systems/accounts
→ assess scope
→ notify security owners
→ require security approval
→ do not mutate production automatically
```

---

## 15. Phase 9 — evidence and root-cause analysis

### Goal

Ensure Sentinel’s conclusions are evidence-backed.

### Evidence requirements

Each evidence item must contain:

```text
organization_id
work_item_id or incident_id
source_type
source_id
service
environment
region
repository
commit_sha
observed_at
file path and lines when applicable
source URL
retrieval method
retrieval score
content or secure content reference
```

### Evidence categories

- Metrics
- Logs
- Traces
- Alerts
- Deployments
- Commits
- Diffs
- Files
- Functions
- Dependencies
- Runbooks
- Previous incidents
- Pull requests

### Required distinction

```text
Evidence:
Database utilization reached 96%.

Inference:
The increase began after deployment v2.8.1.

Conclusion:
The deployment’s connection-pool change is the strongest current explanation.
```

### Hypothesis competition

For each hypothesis, store:

```text
description
supporting evidence IDs
contradicting evidence IDs
missing evidence
temporal fit
code-path fit
operational fit
status
confidence
```

The planner must attempt to disprove the leading hypothesis.

### Abstention

If minimum evidence is not met:

```text
status = INSUFFICIENT_EVIDENCE
root_cause = null
fix_generation = blocked
```

Do not fabricate a root cause to complete the workflow.

---

## 16. Phase 10 — incident memory and explainability

### Goal

Make investigations improve over time without blindly training on bad answers.

### Incident memory

Store only confirmed patterns:

```text
error signature
service
deployment pattern
confirmed root cause
successful fix
validation method
post-deployment outcome
```

Historical memory may inform current hypotheses but cannot override current evidence.

### Explainable timeline

Each incident must show:

```text
09:41 deployment completed
09:43 connection usage increased
09:45 latency increased
09:47 timeout rate increased
09:48 HTTP 503 spike
```

Every event must link to evidence or be marked as a derived inference.

### Agent activity log

Show observable actions, not hidden chain-of-thought:

```text
✓ Received Prometheus alert
✓ Correlated Sentry exception
✓ Found recent deployment
✓ Retrieved commit
✓ Inspected affected file
✓ Generated hypotheses
✓ Retrieved contradicting evidence
✓ Generated regression test
✓ Validation passed
✓ Draft PR created
```

---

## 17. Phase 11 — patch generation and test generation

### Goal

Generate precise, repository-specific, safe changes.

### Patch input

Provide the model with:

- Exact repository
- Exact base SHA
- Approved file scope
- Relevant file contents
- Relevant symbols
- User requirements
- Acceptance criteria
- Existing test conventions
- Root-cause evidence if applicable

### Patch schema

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
  "tests_to_add": [],
  "tests_to_run": [],
  "risk": "low",
  "rollback_plan": "..."
}
```

### Direct task rule

For “Add README.md”:

- Create README.md if absent.
- Modify README.md if it exists and modification is requested.
- Do not modify unrelated files.
- Read actual project structure.
- Do not use a generic hardcoded README.

### Bug rule

For reproducible bugs, generate a regression test whenever possible.

The test should fail before the fix and pass after the fix when practical.

### Patch rejection

Reject if:

- File is outside scope.
- File does not exist for modification.
- `old_code` is empty when exact replacement is required.
- `old_code` appears zero times.
- `old_code` appears more than once.
- Patch is unexpectedly large.
- Patch contains secrets.
- Patch has no actual change.

---

## 18. Phase 12 — isolated validation and replay

### Goal

Test whether the proposed fix addresses the actual failure.

### Validation pipeline

```text
Checkout exact base SHA
→ apply patch
→ run pre-patch reproduction if available
→ run generated regression test
→ run targeted tests
→ run full repository tests
→ run lint/type/build/security checks
→ replay sanitized scenario if available
→ compare results
→ persist validation report
```

### Validation record

```text
fix_id
repository
base_sha
workspace_id
check_type
command
status
exit_code
output_reference
duration
started_at
completed_at
```

### Incident-specific result

The report must distinguish:

```text
Compilation: passed
Tests: passed
Original failure reproduced: yes
Failure absent after patch: yes
Production outcome: unknown until deployed
```

### Safety

- Never replay unsanitized customer data.
- Never test against production by default.
- Apply timeouts and resource limits.
- Do not execute arbitrary model-generated commands without policy validation.

---

## 19. Phase 13 — policy gateway and approvals

### Goal

Enforce safety through code, not prompts.

### Policy decision

```text
Proposed action
→ organization check
→ permission check
→ repository check
→ file scope check
→ evidence threshold check
→ risk check
→ validation check
→ approval check
→ ALLOW/BLOCK/REQUIRE_HUMAN
```

### Default policy

```text
Read production telemetry       ALLOW
Write production                BLOCK
Read repository                 ALLOW
Create branch                   ALLOW after validation
Create Draft PR                 ALLOW after policy checks
Merge PR                        BLOCK
Deploy                          BLOCK
Modify secrets                  BLOCK
Modify infrastructure           MULTI_APPROVAL
Database migration              MULTI_APPROVAL
Security change                 SECURITY_APPROVAL
```

### Approval states

```text
PROPOSED
VALIDATED
DRAFT_PR_CREATED
HUMAN_APPROVED
CHANGES_REQUESTED
HUMAN_REJECTED
MERGED_EXTERNALLY
```

The implementation must remove any code path that automatically marks an AI-generated fix as human-approved.

---

## 20. Phase 14 — multi-repository remediation

### Goal

Handle incidents that affect multiple repositories correctly.

### Required structure

```text
Parent incident
├── child investigation: company/checkout-api
│   └── fix → validation → Draft PR
├── child investigation: company/payment-service
│   └── fix → validation → Draft PR
└── evidence-only: company/platform-config
    └── no patch
```

### Rules

- One repository investigation per affected repository.
- One base SHA per repository.
- One patch per repository.
- One validation report per repository.
- One Draft PR per repository requiring a change.
- Do not combine unrelated repositories into one patch.
- Preserve dependency ordering between PRs.
- Do not create PRs for evidence-only repositories.

### Completion test

Create a synthetic incident affecting Payment and Checkout. Verify:

- Two child investigations.
- Two repository-specific diffs.
- Two independent validation results.
- Two Draft PR records.
- One parent incident showing the combined blast radius.

---

## 21. Phase 15 — operations command center

### Goal

Give engineers a company-wide view of runtime and engineering state.

### Required views

```text
Organization overview
Service inventory
Deployment inventory
Dependency graph
Active incidents
Incident workspace
Investigation activity
Draft PR queue
Reliability dashboard
Integrations
Policies
```

### Overview metrics

```text
active incidents
healthy services
degraded services
down services
recent deployments
predicted risks
Draft PRs
error-budget consumption
```

### Service view

Show:

- Service name
- Owner team
- On-call contact
- Environment and region
- Health
- Version
- Commit SHA
- Repository links
- CPU
- Memory
- Error rate
- Latency
- Latest deployment
- Dependencies
- Open incidents

### Incident view

Show:

- Detection source
- Impact
- Blast radius
- Regions
- Environments
- Timeline
- Current deployment
- Change ledger
- Evidence
- Hypotheses
- Root cause
- Proposed fixes by repository
- Validation
- Policy decision
- Draft PRs
- Agent activity
- Human feedback

---

## 22. Phase 16 — advanced reliability capabilities

Implement these only after automatic detection, investigations, patches, validation, and PRs are reliable.

### 22.1 SLO and error budgets

Track:

- Availability
- Error rate
- Latency
- SLO compliance
- Error-budget consumption
- MTTD
- MTTA
- MTTR
- Change failure rate
- Incident frequency

### 22.2 Predictive detection

Start with transparent rules:

- Moving averages
- Rate-of-change
- Burn-rate thresholds
- Linear trend
- Forecast horizon

Output:

```text
Payment service may become degraded within approximately 20 minutes.
Reason: database connections increased from 70% to 91%.
Confidence: medium.
```

Predictions are advisory initially.

### 22.3 Business impact

Estimate:

- Affected traffic
- Affected users
- Blocked workflows
- Orders or transactions affected
- Revenue range where data supports it

Always show assumptions and uncertainty.

### 22.4 Rollback analysis

Assess:

- Previous stable version
- Database migrations
- API compatibility
- Configuration compatibility
- Data compatibility
- Rollback risk

Never perform a production rollback automatically in the first product.

### 22.5 Post-deployment outcome

After a human merges and deploys a fix:

```text
Identify deployment
→ monitor service
→ compare metrics before/after
→ check error signature
→ detect recurrence
→ update fix effectiveness
→ update incident memory
```

### 22.6 Confidence calibration

Compare predicted confidence with actual outcomes. Do not interpret an LLM-generated `0.95` as a scientifically calibrated probability until measured.

---

## 23. Phase 17 — security incident mode

Security signals must use a stricter workflow.

Examples:

- Suspicious authentication activity
- Credential leakage
- Permission escalation
- Unusual data access
- Vulnerable dependency in production

Required behavior:

```text
Preserve evidence
→ scope affected systems
→ identify security owners
→ recommend containment
→ require security approval
→ prohibit autonomous security mutation
```

Do not treat a security incident as a normal application bug.

---

## 24. Testing requirements

### Unit tests

- Intent router
- Signal normalizers
- Detection rules
- Fingerprinting
- Deduplication
- Repository resolver
- Graph traversal
- Blast radius
- Change ranking
- Evidence filtering
- Temporal filtering
- Hypothesis scoring
- Patch application
- Policy evaluation
- Approval transitions
- Validation profiles

### Service tests

- Nemotron provider
- Investigation planner
- Repository task workflow
- Bug workflow
- Production workflow
- Security workflow
- Incident memory
- Deployment correlation
- Multi-repository orchestration
- GitHub client

### API tests

- Organization isolation
- Authentication
- Service and repository APIs
- Deployment ingestion
- Monitoring ingestion
- Automatic incident creation
- Incident correlation
- Investigation queueing
- Approvals
- Draft PR restrictions

### Integration tests

Use PostgreSQL, Redis, and Pinecone where available. Mock GitHub, Prometheus, Sentry, and Nemotron responses in deterministic tests.

### Required end-to-end scenarios

#### E2E-1 direct README task

```text
Input: Add README.md
Expected: direct task, repository context, one-file patch, validation, Draft PR
```

#### E2E-2 bug fix

```text
Input: Login fails for empty password
Expected: auth investigation, regression test, scoped patch, validation, Draft PR
```

#### E2E-3 feature

```text
Input: Add dark mode
Expected: feature workflow, relevant multi-file patch, frontend validation
```

#### E2E-4 automatic incident

```text
Input: Prometheus reports CPU and error-rate anomaly
Expected: no human request, incident, investigation, evidence, remediation
```

#### E2E-5 multi-repository outage

```text
Input: Payment failure affects Checkout
Expected: graph traversal, blast radius, two investigations, two PRs
```

#### E2E-6 insufficient evidence

```text
Input: generic outage with no useful telemetry
Expected: abstention and no patch
```

---

## 25. Required progress-report format

At the end of every phase, the coding agent must report:

```markdown
## Phase report

Phase: PHASE-N — name
Status: complete | blocked | incomplete

Implemented:
- ...

Files changed:
- ...

Database changes:
- ...

API changes:
- ...

Tests added:
- ...

Commands run:
- ...

Results:
- passed: ...
- failed: ...

Known limitations:
- ...

Next phase:
- ...
```

The agent must not say “done” if tests are failing.

---

## 26. Final acceptance checklist

Sentinel is ready for a serious pilot only when:

- Multiple organizations are isolated.
- Multiple repositories are supported.
- Multiple services are supported.
- Multiple environments and regions are supported.
- Deployments map to repositories and commit SHAs.
- Production signals arrive without human incident creation.
- Metrics, logs, traces, health checks, and deployment events are visible.
- Duplicate alerts are correlated.
- Service dependency graph is available.
- Incident blast radius is calculated.
- Direct, bug, feature, production, and security workflows are separated.
- Root causes use evidence and can abstain.
- Hypotheses include contradicting evidence.
- Change intelligence includes configuration, dependencies, feature flags, migrations, and infrastructure.
- Patches are exact and scoped.
- Regression tests are generated where possible.
- Validation runs in an isolated environment.
- Incident replay is supported where safe.
- Policy gateway blocks forbidden actions.
- One Draft PR is created per repository requiring a change.
- Humans review and approve changes.
- Sentinel cannot merge or deploy.
- Post-deployment outcomes are monitored.
- Incident memory stores confirmed knowledge.
- Reliability and SLO metrics are available.
- Production behavior does not silently use mock intelligence.
- Backend, frontend, integration, and end-to-end tests pass.

---

## 27. Final instruction to the implementing agent

Build Sentinel as a dependable system, not as a collection of impressive AI responses.

The correct order is:

```text
Reliable data
→ correct company/service/repository context
→ automatic signal detection
→ correct workflow selection
→ evidence-backed reasoning
→ safe patching
→ isolated validation
→ policy enforcement
→ human-controlled Draft PR review
→ post-deployment feedback
```

Nemotron is responsible for language understanding and reasoning. Application code is responsible for identity, permissions, scope, evidence provenance, patch safety, validation, and external actions.

When the agent is unsure, it must stop safely, explain what is missing, and leave the repository in a recoverable state.
