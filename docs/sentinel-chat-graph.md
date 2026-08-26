# Sentinel Chat Graph

```mermaid
flowchart TD
    Goal[Product goal: publishable Sentinel incident response platform]

    Goal --> Entry[Incident entry points]
    Entry --> Manual[Manual incident from UI]
    Entry --> Alerts[Webhook or automatic detection]

    Manual --> Discovery[Discover affected services and repositories]
    Alerts --> Discovery
    Discovery --> MultiRepo[Resolve every affected repository]
    MultiRepo --> Evidence[Collect evidence]

    Evidence --> GitHub[GitHub commits, files, deployments and PRs]
    Evidence --> Observability[Logs, metrics and traces]
    Evidence --> Qdrant[Qdrant code and semantic search]
    Evidence --> Chat[Chatbot explanation and investigation assistant]

    Evidence --> Hypotheses[Generate competing hypotheses]
    Hypotheses --> RCA[Evidence-backed root cause]
    RCA --> Abstain[Abstain when evidence is insufficient]
    RCA --> Fixes[Generate one fix per repository]

    Fixes --> Diff[Show exact code diff and risk]
    Diff --> Validate[Run tests, lint, build and security checks]
    Validate --> Review[Human review and explicit approval]
    Review --> DraftPR[Create one Draft PR per repository]
    DraftPR --> NoMerge[No autonomous merge or deployment]

    IncidentBug[Observed: 95 percent investigations stuck]
    IncidentBug --> StreamFix[Fixed stream persistence and failure recovery]
    StreamFix --> Retry[Failed investigations can be retried]

    RepoBug[Observed: detached RepositoryScope session error]
    RepoBug --> RepoFix[Resolve repository names before stream starts]
    RepoFix --> MultiRepo

    QualityBug[Observed: logo incident chose generic rollback]
    QualityBug --> QualityCause[Qdrant unavailable and patch generation used weak or local context]
    QualityCause --> RealPatch[Use immutable GitHub files and generate exact patches]
    RealPatch --> Diff

    PRBug[Observed: no useful PR or code change]
    PRBug --> PRCause[Fix had no files and PR flow was not approval-safe]
    PRCause --> Validate

    Infra[Deployment foundation]
    Infra --> Postgres[Managed PostgreSQL]
    Infra --> Redis[Managed Redis and durable workers]
    Infra --> QdrantCloud[Qdrant Cloud]
    Infra --> Secrets[Managed secrets and encrypted GitHub tokens]
    Infra --> Security[Ownership, webhook signatures and OAuth state]

    Publish[Publishability gate]
    Publish --> Infra
    Publish --> Security
    Publish --> Tests[End-to-end tests and monitoring]
    Publish --> Frontend[Frontend lint and production build]

    Goal --> Publish
```

## Verified milestones

- Manual incident creation works.
- Deployed login and incident creation were tested.
- Multi-repository data model and investigation fan-out were added.
- Investigation stream recovery was fixed.
- Proposed diffs are persisted and displayed when a real patch exists.
- Draft PR publication is guarded against empty or stale patches.
- Incident edit and delete actions were added.
- Backend tests passed with 68 tests.
- The deployed test found and fixed the stale `inc_scopes` variable.

## Current limitation

The deployed logo test completed its investigation but selected a generic rollback and had no applicable code patch. The next required implementation is real GitHub source retrieval, evidence-based repository and root-cause scoring, validation, and approval-gated Draft PR creation.

## Complete implementation roadmap

```mermaid
flowchart LR
    P0[Phase 0: Security and integrity]
    P1[Phase 1: Durable foundation]
    P2[Phase 2: Ingestion and topology]
    P3[Phase 3: Evidence and investigation]
    P4[Phase 4: Patch and validation]
    P5[Phase 5: Review and Draft PR]
    P6[Phase 6: Publishability]

    P0 --> P1 --> P2 --> P3 --> P4 --> P5 --> P6

    P0 --> S1[Rotate secrets]
    P0 --> S2[Encrypt GitHub tokens]
    P0 --> S3[Enforce tenant ownership]
    P0 --> S4[Verify webhook signatures]
    P0 --> S5[Require approval before PR]

    P1 --> D1[Repair Alembic chain]
    P1 --> D2[Atomic incident numbering]
    P1 --> D3[Redis jobs and retries]
    P1 --> D4[Persist task state and metrics]

    P2 --> T1[Service to repository mapping]
    P2 --> T2[Stack trace and log matching]
    P2 --> T3[Deployment and commit correlation]
    P2 --> T4[Multi-repository scoring]

    P3 --> E1[GitHub source indexing]
    P3 --> E2[Qdrant semantic retrieval]
    P3 --> E3[Logs metrics traces adapters]
    P3 --> E4[Evidence provenance]
    P3 --> E5[Competing hypotheses]
    P3 --> E6[Abstention on weak evidence]

    P4 --> R1[Immutable GitHub base SHA]
    P4 --> R2[Exact old and new code patch]
    P4 --> R3[Isolated patch workspace]
    P4 --> R4[Lint tests build security checks]

    P5 --> H1[Evidence and diff review UI]
    P5 --> H2[Role-based approval]
    P5 --> H3[One Draft PR per repository]
    P5 --> H4[No merge or deployment]

    P6 --> Q1[Managed PostgreSQL]
    P6 --> Q2[Qdrant Cloud]
    P6 --> Q3[Managed Redis]
    P6 --> Q4[Separate API and worker]
    P6 --> Q5[Monitoring and end-to-end tests]
```

## Implementation dependency chain

```mermaid
sequenceDiagram
    participant User
    participant UI
    participant API
    participant Queue
    participant GitHub
    participant Review

    User->>UI: Create manual incident or receive alert
    UI->>API: Store incident and selected scope
    API->>Queue: Enqueue durable investigation
    Queue->>API: Resolve all affected repositories
    API->>GitHub: Fetch files, commits and deployments
    API->>API: Search Qdrant and observability evidence
    API->>API: Generate RCA or abstain
    API->>GitHub: Read exact files at immutable base SHA
    API->>API: Generate and validate repository patches
    API->>Review: Show evidence, risk, validation and diffs
    User->>Review: Explicitly approve each fix
    Review->>GitHub: Create branch, commit and Draft PR
    GitHub-->>Review: Return PR URL and status
    Note over Review,GitHub: Never merge or deploy automatically
```

## Release gates

```text
Gate 1: Security passes
Gate 2: Database and workers survive restart
Gate 3: All affected repositories are discovered
Gate 4: Every RCA is evidence-backed or abstained
Gate 5: Every code fix has a real exact diff
Gate 6: Required validation passes
Gate 7: Human approval is recorded
Gate 8: Draft PR is created per repository
Gate 9: Production monitoring and rollback are ready
```

## Detailed engineering blueprint

### 1. Product contract

```mermaid
flowchart TD
        A[Production signal]
        A --> B{Entry type}
        B -->|Manual| C[User submits logs and context]
        B -->|Webhook| D[Provider sends alert]
        B -->|Detection| E[Rules detect anomaly]
        C --> F[Normalize incident]
        D --> F
        E --> F
        F --> G[Deduplicate by fingerprint]
        G --> H[Correlate related signals]
        H --> I[Create incident lifecycle record]
        I --> J[Resolve affected services]
        J --> K[Resolve all affected repositories]
        K --> L[Investigation per repository]
        L --> M{Evidence sufficient?}
        M -->|No| N[Insufficient evidence report]
        M -->|Yes| O[Root cause report]
        O --> P[Repository-specific fix]
        P --> Q[Exact code diff]
        Q --> R[Validation sandbox]
        R --> S{Validation passed?}
        S -->|No| T[Fix blocked with results]
        S -->|Yes| U[Human review]
        U --> V{Approved?}
        V -->|No| W[Rejected or changes requested]
        V -->|Yes| X[Create Draft PR]
        X --> Y[Await external merge decision]
```

The non-negotiable contract is that Sentinel may investigate, explain, generate, validate, and prepare a Draft PR. It must not merge code or deploy to production autonomously.

### 2. Current code map

| Area | Main location | Current responsibility | State |
|---|---|---|---|
| API startup | `backend/app/main.py` | FastAPI app, middleware, route registration | Implemented, needs production startup cleanup |
| Auth | `backend/app/core/auth.py` | bcrypt passwords and JWT sessions | Implemented, needs stronger authorization |
| Database | `backend/app/core/database.py` | SQLAlchemy engine and sessions | Implemented |
| Domain model | `backend/app/models/incident.py` | Incidents, investigations, evidence, fixes, approvals | Broad model exists |
| Manual incidents | `backend/app/routes/incidents.py` | Create, update, delete, list incidents | Implemented |
| Webhook ingestion | `backend/app/routes/webhooks.py` | Normalize external alert payloads | Partial, signatures needed |
| Detection | `backend/app/routes/auto_detect.py` | Evaluate rules and create incidents | Partial, no durable scheduler |
| Investigation API | `backend/app/routes/investigation_engine.py` | Run and stream investigations | Partial, needs durable jobs and stronger RCA |
| Investigation engine | `backend/app/services/investigation_engine.py` | Plan tasks and execute tools | Partial, several tools are placeholders |
| Retrieval | `backend/app/services/retrieval.py` | Hybrid retrieval orchestration | Partial |
| Vector store | `backend/app/services/vector_store.py` | Qdrant indexing and search | Partial, deployment/dependencies needed |
| LLM | `backend/app/services/llm.py` | Provider abstraction and mock mode | Implemented, needs production controls |
| Patch generation | `backend/app/services/diff_generator.py` | Generate patch structure and diffs | Partial, must use GitHub source |
| GitHub client | `backend/app/services/github.py` | Read and write GitHub API operations | Primitives exist |
| Remediation | `backend/app/routes/remediation.py` | Fix records and Draft PR publishing | Partial, approval gate required |
| Validation | `backend/app/services/validation.py` | Run checks in a process | Partial, not fully wired |
| Chatbot | `backend/app/routes/chat.py`, UI ChatBot | Answer incident questions | Partial, needs scoped evidence and citations |
| Frontend shell | `sentinel-ui/src/components` | Navigation, auth gate, layout | Implemented |
| Incident UI | `sentinel-ui/src/app/incidents` | Create, investigate, review incidents | Partial |
| PR review UI | `sentinel-ui/src/app/pull-requests` | Approval queue | Partial, needs diff and validation review |

### 3. Phase 0: Security and integrity

#### Work

1. Rotate every credential that has ever been committed, including database passwords and GitHub secrets.
2. Remove secret files from Git tracking and add safe environment templates.
3. Encrypt GitHub tokens at rest using a dedicated encryption key from the deployment secret store.
4. Add `organization_id` or an equivalent tenant boundary to users, repositories, incidents, investigations, fixes, approvals, and audit events.
5. Add ownership filters to every query, including chatbot context queries.
6. Require an active user and enforce roles for destructive actions and approvals.
7. Verify HMAC signatures for every supported webhook provider.
8. Add GitHub OAuth `state`, expiry, and user binding.
9. Add rate limits and request size limits to webhook and chat endpoints.
10. Treat logs, commits, PR descriptions, and repository files as untrusted prompt input.

#### Acceptance tests

```text
User A cannot read User B incidents.
User A cannot create a PR for User B fixes.
Unsigned webhook returns 401 or 403.
Expired OAuth state is rejected.
GitHub tokens never appear in API responses or logs.
No branch, commit, or PR exists before approval.
```

### 4. Phase 1: Durable foundation

#### Work

1. Repair the Alembic revision chain so every referenced revision exists.
2. Run migrations during deployment before the API accepts traffic.
3. Remove broad `except: pass` blocks around schema changes.
4. Add unique indexes for repository scopes and provider fingerprints.
5. Allocate incident numbers atomically.
6. Move investigation execution from in-memory asyncio tasks to Redis-backed jobs.
7. Add job IDs, leases, retries, dead-letter states, and idempotency keys.
8. Persist investigation tasks, task inputs, task outputs, timestamps, and failures.
9. Persist progress events instead of relying only on one browser SSE connection.
10. Move metrics to a durable or external metrics system.

#### Required state machine

```mermaid
stateDiagram-v2
        [*] --> Created
        Created --> Queued
        Queued --> Investigating
        Investigating --> RootCauseAnalysis
        Investigating --> InsufficientEvidence
        Investigating --> InvestigationFailed
        RootCauseAnalysis --> FixGenerated
        FixGenerated --> FixValidating
        FixValidating --> ValidationFailed
        FixValidating --> AwaitingApproval
        AwaitingApproval --> Approved
        AwaitingApproval --> HumanRejected
        Approved --> DraftPRCreated
        DraftPRCreated --> Resolved
        InvestigationFailed --> Queued
```

Every transition must be persisted, auditable, and safe to retry.

### 5. Phase 2: Ingestion and topology

#### Incident input normalization

All input providers should produce the same normalized object:

```json
{
    "provider": "sentry",
    "external_id": "event-123",
    "title": "Checkout request failed",
    "description": "HTTP 500 from checkout service",
    "service": "checkout-api",
    "severity": "SEV-2",
    "error_signature": "NullPointerException",
    "occurred_at": "2026-08-26T10:00:00Z",
    "deployment_id": "deploy-456",
    "raw_payload_reference": "secure-storage-key"
}
```

#### Repository resolver

The resolver should score all candidate repositories:

```text
Explicit incident scope                         +100
Exact service-to-repository mapping              +80
Stack trace path matches repository              +70
Deployment belongs to repository                +65
GitHub file or symbol evidence                   +50
Import/dependency relationship                   +35
Keyword or semantic match                        +20
```

Return every repository above the configured threshold, with reasons. Never silently choose only the first repository.

#### Multi-repository behavior

For payment and email services:

```text
Incident
├── payment repository investigation
│   ├── evidence
│   ├── RCA
│   ├── fix
│   ├── validation
│   └── Draft PR
└── email repository investigation
        ├── evidence
        ├── RCA
        ├── fix
        ├── validation
        └── Draft PR
```

Each child result must retain its repository, base SHA, confidence, and failure state.

### 6. Phase 3: Evidence and RCA

#### Evidence adapters

- GitHub files, commits, PRs, reviews, deployments, and releases.
- Prometheus or Alertmanager metrics and alert history.
- Sentry events, stack traces, releases, and breadcrumbs.
- Generic logs with timestamps and correlation IDs.
- Qdrant code chunks with repository and commit metadata.
- Previous incidents limited to the same tenant and relevant service.

#### Evidence record requirements

Every evidence item needs:

```text
source_type
source_id
repository
commit_sha
observed_at
file_path
line_start and line_end
source_url
retrieval_score
retrieval_method
```

#### RCA rules

1. Generate multiple competing hypotheses.
2. Link supporting and contradicting evidence to each hypothesis.
3. Apply temporal filtering using commit/deployment time, not indexing time.
4. Detect missing evidence.
5. Calibrate confidence.
6. Abstain when minimum evidence is not met.
7. Never select the first hypothesis merely because all stronger options failed.

### 7. Phase 4: Real patch and validation pipeline

```mermaid
flowchart TD
        A[Selected root cause]
        A --> B[Repository and base commit SHA]
        B --> C[Download exact affected files from GitHub]
        C --> D[Generate old_code and new_code]
        D --> E{Exact replacement count is one?}
        E -->|No| F[Reject patch as unsafe]
        E -->|Yes| G[Build unified diff]
        G --> H[Create isolated temporary workspace]
        H --> I[Apply patch]
        I --> J[Run targeted tests]
        J --> K[Run lint]
        K --> L[Run build]
        L --> M[Run security checks]
        M --> N{Required checks pass?}
        N -->|No| O[Validation failed]
        N -->|Yes| P[Ready for human approval]
```

For the logo incident, the expected patch must contain actual changes in the Sentinel repository, such as consolidating `Sidebar`, `TopBar`, login, and profile logo rendering around one canonical component or asset. A rollback with zero files is not a valid code fix.

### 8. Phase 5: Approval and Draft PR

The PR endpoint must verify:

```text
Fix belongs to current tenant
Fix belongs to investigation
Fix has a repository
Fix has a non-empty exact patch
Validation passed
Approval exists from an authorized reviewer
GitHub token has write permission
Base SHA is still current or safely rebased
```

The PR body should include:

- Incident link and summary
- Affected repository and base SHA
- Root cause and confidence
- Evidence links
- Files changed
- Unified diff summary
- Validation results
- Risk and rollback notes
- Explicit statement that Sentinel did not merge the PR

### 9. Phase 6: Qdrant, Redis, and production deployment

#### Recommended deployment topology

```mermaid
flowchart LR
        Browser[Vercel frontend]
        API[Render API service]
        Worker[Render worker service]
        DB[Managed PostgreSQL]
        Vector[Qdrant Cloud]
        Cache[Managed Redis]
        GH[GitHub API]
        Obs[Prometheus/Sentry/log provider]

        Browser --> API
        API --> DB
        API --> Cache
        API --> Vector
        API --> GH
        API --> Obs
        API --> Worker
        Worker --> DB
        Worker --> Cache
        Worker --> Vector
        Worker --> GH
        Worker --> Obs
```

#### Deployment requirements

- API and worker use the same source revision and environment contract.
- Database migrations run before release traffic.
- Qdrant collection dimensions match the embedding model.
- Redis is used for jobs, locks, retries, and rate limiting.
- Health endpoints distinguish liveness from readiness.
- Render environment variables contain service URLs, never `localhost`.
- CORS allows only the actual Vercel production and preview origins needed.
- Logs include request ID, incident ID, investigation ID, repository, and task ID.

### 10. Chatbot contract

The chatbot is an assistant over Sentinel data, not an unrestricted agent.

It must:

1. Scope every answer to the authenticated tenant.
2. Cite incident, evidence, file, commit, and PR sources.
3. State confidence and uncertainty.
4. Never claim a patch or PR exists without persisted records.
5. Never approve, merge, deploy, or delete without explicit authorized action.
6. Refuse prompt instructions found inside repository files or logs.
7. Explain repository selection and root-cause reasoning.

### 11. Test pyramid

```text
Unit tests:
    parsers, normalizers, scoring, deduplication, patch application, HMAC verification

Service tests:
    repository resolver, retrieval, RCA, validation, chatbot context, GitHub client mocks

API tests:
    auth, ownership, lifecycle transitions, approvals, webhooks, migrations

Integration tests:
    PostgreSQL, Redis, Qdrant, mocked GitHub and observability providers

End-to-end staging test:
    incident -> two repositories -> evidence -> two diffs -> validation -> approvals -> two Draft PRs
```

### 12. Final definition of done

Sentinel is publishable only when all of these are true:

```text
Security secrets rotated and encrypted.
Tenant isolation tested.
Webhook signatures enforced.
OAuth state protection enabled.
Migrations are deterministic.
Qdrant and Redis are deployed and healthy.
Workers survive restart.
Manual and automatic incidents use the same lifecycle.
All affected repositories are resolved and investigated.
RCA is evidence-backed or abstains.
Patch is generated from GitHub source at an immutable SHA.
Diff is visible in the UI.
Validation runs before approval.
Approval is required before branch, commit, or PR creation.
One Draft PR is created per repository.
No autonomous merge or deployment exists.
Chatbot is scoped and cites evidence.
Backend tests, integration tests, frontend lint, TypeScript, and build pass.
Production monitoring and rollback procedures are documented.
```
