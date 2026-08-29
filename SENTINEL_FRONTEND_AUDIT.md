# Sentinel Frontend Audit

## Purpose

This document records the current frontend flaws, misleading UI behavior, missing product capabilities, and implementation work required to turn the existing dashboard into the real Sentinel application.

This is a read-only audit. No frontend behavior was changed while producing it.

Scope inspected:

```text
sentinel-ui/src/app/**
sentinel-ui/src/components/**
sentinel-ui/src/lib/**
sentinel-ui/package.json
sentinel-ui/next.config.ts
sentinel-ui/tsconfig.json
```

---

## 1. Executive summary

The frontend has a strong visual shell and many screens, but it is currently a partially connected prototype rather than a reliable operations console.

The largest issues are:

1. Several screens display derived, placeholder, or misleading information instead of real Sentinel data.
2. Errors are frequently swallowed and converted into empty states, making outages look like “no data.”
3. The notification center is actually a temporary audit-log viewer, not a notification system.
4. The frontend does not yet represent the company-wide multi-service, multi-repository operating model.
5. The automatic-response page does not prove that Sentinel is continuously monitoring production.
6. The dashboard contains fallback values that look like real metrics.
7. Important actions lack confirmation, authorization-aware UI, or clear state transitions.
8. The frontend uses inconsistent API access patterns and weak response typing.
9. Authentication state is stored in localStorage and the UI does not robustly handle expired sessions.
10. There is no complete UI for service topology, deployment inventory, blast radius, incident memory, SLOs, predictive risk, or post-incident outcomes.

The frontend should eventually be a SRE command center and developer workbench, not just a set of pages that display API responses.

---

## 2. Important distinction: current display versus required display

The audit uses this format:

```text
Current behavior: what the code currently renders or does.
Required behavior: what the real Sentinel product should render or do.
Risk: why the current behavior is misleading or unsafe.
Fix: implementation direction.
```

An empty state caused by a failed API request must not be presented as a valid empty state.

---

## 3. Shared shell audit

### 3.1 `src/components/TopBar.tsx`

#### Finding: notification button is not a real notification center

Current behavior:

- The notification bell calls `listAuditLogs(token, 20)`.
- It filters those audit logs to the last 24 hours.
- It displays audit action, entity type, truncated entity ID, and timestamp.
- “Clear all” only calls `setNotifications([])` in browser memory.
- There is no read/unread state.
- There is no persistence.
- There is no realtime update.
- There is no navigation to the related incident, investigation, validation, or PR.

Required behavior:

Notifications should be a dedicated product object with:

- Notification ID
- Organization ID
- Recipient/user/team
- Type
- Severity
- Title
- Body
- Related entity
- Related URL
- Created time
- Read time
- Dismissed time
- Delivery status

Useful notification types include:

```text
New production incident detected
Service became unhealthy
Deployment regression suspected
Investigation completed
Root cause identified
Insufficient evidence
Validation failed
Draft PR created
PR review requested
Human changes requested
Fix merged externally
Incident returned after fix
Predictive risk warning
SLO/error-budget warning
Integration disconnected
Sentinel worker unhealthy
```

Risk:

The current button suggests operational awareness but only shows recent audit entries. Users cannot reliably know whether an item requires action.

Fix:

- Add notification API endpoints.
- Store notification state server-side.
- Link every notification to its related entity.
- Add read/unread and mark-all-read actions.
- Add polling or WebSocket/SSE updates.
- Show severity and actionable status.
- Keep audit logs as a separate page and concept.

#### Finding: notification count is not unread count

Current behavior:

The badge displays `notifications.length`, which is the number of filtered audit logs.

Required behavior:

The badge must display unread notifications only, preferably grouped or capped, for example `9+`.

#### Finding: notification failures are invisible

Current behavior:

The request uses `.catch(() => {})`.

Required behavior:

Show a degraded notification state such as “Notifications unavailable” and provide retry behavior. Do not silently show “No notifications” when the API failed.

#### Finding: search is incomplete

Current behavior:

Search queries incidents and service health only.

Required behavior:

Search should cover:

- Incidents
- Services
- Repositories
- Deployments
- Investigations
- Draft PRs
- Teams and owners
- Evidence

Search results should show loading, error, empty, and partial-result states independently.

#### Finding: search result request handling is fragile

Current behavior:

- The code uses raw `fetch` separately from the shared API client.
- Responses are not consistently checked with `response.ok`.
- A failed request may be interpreted as an empty array.
- The cancellation flag prevents some state updates but does not abort the network requests.

Fix:

- Centralize requests in `src/lib/api.ts`.
- Use `AbortController`.
- Validate response shapes.
- Display partial failures.

#### Finding: external help link is hardcoded

Current behavior:

The Help button opens a fixed GitHub repository URL.

Required behavior:

Use configurable documentation URL and provide in-product help for:

- Incident statuses
- Detection rules
- Evidence
- Approvals
- Integrations
- Safe remediation

#### Finding: accessibility is incomplete

Potential issues across the TopBar include:

- Icon-only buttons rely on visual meaning and often lack accessible labels.
- Dropdown/modal focus management is not implemented.
- Escape handling is global rather than scoped.
- Notification and search menus do not expose appropriate ARIA roles.
- Keyboard navigation is incomplete.

Fix:

- Add `aria-label` to icon-only controls.
- Use dialog/menu semantics.
- Trap focus inside modals.
- Return focus to the triggering button.
- Support keyboard navigation.

### 3.2 `src/components/Sidebar.tsx`

#### Finding: navigation is static and not permission-aware

Current behavior:

All users see admin routes such as Users, Settings, and Audit Logs.

Required behavior:

Navigation should depend on server-provided permissions and organization role.

#### Finding: “Report Production Error” conflicts with autonomous detection

Current behavior:

The main CTA is manual incident creation.

Required behavior:

Keep manual reporting for developer input, but make the primary operations experience show:

- Active incidents
- Service health
- Detection status
- Recent deployments
- Predicted risks

Rename or clarify the CTA, for example “Create work item” or “Report issue,” while clearly showing that production incidents are detected automatically.

#### Finding: no global service/repository context

Required behavior:

Add organization, environment, and region selectors. A user should be able to scope the console to:

```text
Organization → environment → region → service → repository
```

### 3.3 `src/components/Footer.tsx`

#### Finding: footer health model is stale/inconsistent

Current behavior:

The frontend status interface still contains `qdrant`, while the planned architecture uses Pinecone.

Required behavior:

Display actual dependency health from the backend, including:

- PostgreSQL
- Redis
- Pinecone
- Nemotron provider
- GitHub
- Monitoring integrations
- Worker queue

Do not label a dependency healthy merely because the endpoint responded with an incomplete object.

#### Finding: errors are swallowed

Current behavior:

Health fetch failure is silently ignored.

Required behavior:

Show “Status unavailable” with a timestamp and retry option. Distinguish:

```text
healthy
degraded
unhealthy
unknown
```

---

## 4. Dashboard audit: `src/app/page.tsx`

### Finding: dashboard uses fake fallback progress

Current behavior:

The investigation pipeline uses a fallback progress value of `35` when no progress is available.

Risk:

The UI can show a partially progressing investigation even when the backend has no investigation data.

Required behavior:

- Show “No active investigation” if none exists.
- Show actual persisted progress.
- Show the current task and last update time.
- Show stale-worker warnings.
- Never invent progress.

### Finding: dashboard is incident-centric, not company-centric

Current behavior:

The dashboard focuses on a short list of incidents, approvals, system health, and a pipeline.

Required behavior:

Add organization-level operational information:

- Healthy services
- Degraded services
- Down services
- Active incidents
- Recent deployments
- Deployment regressions
- Affected regions
- High-risk services
- Draft PRs
- SLO/error-budget state
- Queue/worker state

### Finding: only a small incident subset is shown

Current behavior:

The page slices incidents to five entries.

Required behavior:

Show a meaningful “recent incidents” component with:

- Clear time window
- Pagination or link to complete list
- Severity
- Service
- Environment
- Region
- Detection source
- Status
- Impact

### Finding: system health is not service health

Current behavior:

The system health section mainly represents Sentinel’s own dependencies.

Required behavior:

Separate:

1. Sentinel platform health.
2. Customer service health.

The user needs to see both without confusing them.

### Finding: dashboard API failures look like zero data

Current behavior:

Several requests use `.catch(() => [])` or `.catch(() => null)`.

Required behavior:

Each widget needs independent states:

```text
loading
loaded
empty
error
stale
```

---

## 5. Incidents list: `src/app/incidents/page.tsx`

### Finding: filter options are hardcoded

Current behavior:

Severity, status, source, and some service options are static or assembled from a health response.

Required behavior:

- Status values should come from a shared typed enum.
- Sources should include all provider types.
- Services should come from the service catalog, not only health results.
- Add environment, region, team, repository, and incident type filters.

### Finding: source labels are incomplete

Current behavior:

The source list includes manual, alert, Prometheus, Sentry, webhook, and deployment regression.

Required behavior:

Support and display source/provider separately:

```text
source: automatic
provider: prometheus
signal_type: cpu_threshold
```

### Finding: no automatic refresh

Current behavior:

The incident list loads on mount.

Required behavior:

Because incidents are generated automatically, the list needs:

- Polling or realtime updates
- New-incident indicator
- Last refreshed time
- Pause/resume live updates
- Safe refresh during filtering

### Finding: filtering and pagination are likely client-side only

Current behavior:

The page maintains filter and page state locally.

Required behavior:

Use server-side filtering and pagination for large organizations. Preserve filters in the URL so views can be shared and revisited.

### Finding: failure can appear as an empty incident list

Current behavior:

Some fetch failures are logged or ignored.

Required behavior:

Show a clear API failure state distinct from “No incidents.”

### Finding: incident rows lack operational context

Required behavior:

Each row should show:

- Service
- Environment
- Region
- Detection source
- Current deployment
- Impact
- Blast radius indicator
- Incident age
- Current owner
- Investigation status

---

## 6. New incident page: `src/app/incidents/new/page.tsx`

### Finding: manual incident creation is too prominent for the autonomous model

Manual creation is valid, but the screen should clearly explain:

- Production alerts create incidents automatically.
- This form is for manual reports, bugs, and developer tasks.
- A user does not need to report CPU or service-down signals manually.

### Finding: form is still incident-specific

Required behavior:

Add an initial work-type selector:

```text
Developer task
Bug
Feature request
Production incident
Security incident
```

The form fields must change based on the selected type.

Examples:

- README task: repository, requested file, requirements.
- Bug: symptoms, reproduction, expected behavior.
- Production incident: service, environment, incident context.
- Security incident: security classification and evidence-preservation warning.

### Finding: repository selection is still treated as a manual prerequisite

Required behavior:

Allow automatic repository resolution and show its result after submission:

```text
Sentinel selected:
company/payment-service — reason: owns deployed service
company/checkout-api — reason: downstream affected service
```

### Finding: advanced fields expose unsafe or confusing controls

The advanced branch/file fields should be policy-aware. Users should not be able to imply arbitrary write scope without server validation.

### Finding: no duplicate/submission idempotency feedback

If a user double-clicks or refreshes during submission, the UI should show the existing work item rather than create duplicates.

### Finding: no draft plan preview before execution

Required behavior:

Show the interpreted request and planned workflow before starting expensive investigation or patch generation.

---

## 7. Incident detail: `src/app/incidents/[id]/page.tsx`

### Finding: too many independent requests with swallowed errors

The page fetches incident, investigation, evidence, hypotheses, root cause, fixes, timeline, repositories, and GitHub data separately.

Current risks:

- Partial failures are invisible.
- The page may combine stale data from different requests.
- There is no request cancellation on navigation.
- There is no consistent refresh strategy.
- The UI cannot tell whether a section is empty or unavailable.

Required fix:

Use a typed incident workspace endpoint or a query layer that returns section status and timestamps.

### Finding: manual “Run Investigation” is not aligned with automatic incidents

Current behavior:

The detail page provides a button to manually start investigation.

Required behavior:

For automatic incidents:

- Investigation should start automatically.
- The button should become “Retry investigation” only after failure.
- The UI should show queue, running, stale, blocked, and completed states.

Manual rerun must be idempotent and permission-controlled.

### Finding: streamed investigation state is not durable enough in the UI

Current behavior:

The page collects stream steps during the current browser session, then reloads related records.

Required behavior:

The activity timeline must be persisted server-side. If the browser refreshes, the user must see the full historical investigation activity.

### Finding: repository selector can imply a single-repository model

Required behavior:

Display all repository investigations:

```text
Primary repository
Downstream repository
Configuration repository
Evidence-only repository
```

The user must be able to switch between child investigations without losing the parent incident context.

### Finding: GitHub data controls are not an investigation evidence view

Current behavior:

Buttons fetch commits, PRs, and branches.

Required behavior:

Show:

- Deployment commit
- Changes since previous stable deployment
- Relevant files
- Relevant symbols
- PRs associated with the deployment
- Evidence links
- Why each item is relevant

### Finding: Draft PR action needs clearer gate state

Current behavior:

A fix can expose a “Create Draft PR” action.

Required behavior:

The button must be disabled or replaced with a reason when:

- Root cause is insufficient.
- Patch is empty.
- Validation has not passed.
- Approval is required but absent.
- Repository is unresolved.
- Base SHA is stale.
- Policy blocks the action.

Show these requirements visibly before the user clicks.

### Finding: no blast-radius section

Required behavior:

Incident detail must show:

- Directly affected services
- Indirectly affected services
- Affected endpoints
- Affected repositories
- Affected environments
- Affected regions
- Observed traffic impact
- Estimated user impact
- Unknowns

### Finding: no explainable RCA separation

Required behavior:

Use separate panels for:

```text
Observed evidence
Inference
Conclusion
Contradicting evidence
Missing evidence
```

### Finding: no engineer feedback controls

Required behavior:

Allow authorized engineers to:

- Reject a hypothesis
- Add evidence request
- Ask Sentinel to check a specific metric
- Mark evidence irrelevant
- Add a note
- Re-run a selected diagnostic

---

## 8. Investigations page: `src/app/investigations/page.tsx`

### Finding: investigation list does not expose enough state

Required fields:

- Parent incident/work item
- Repository
- Service
- Environment
- Current task
- Progress
- Last event
- Worker health
- Retry count
- Blocked reason
- Evidence count
- Hypothesis count
- Root-cause state

### Finding: filter model is too small

Add filters for:

- Work type
- Service
- Repository
- Environment
- Region
- Status
- Confidence
- Blocked reason
- Age/staleness

### Finding: no live activity or stale detection

An investigation that has not changed for a long time should be visibly stale, not just “analyzing.”

---

## 9. Automatic response page: `src/app/automatic-response/page.tsx`

### Finding: “Active” does not prove continuous monitoring

Current behavior:

The page labels the detection engine active based mainly on loaded rule data.

Required behavior:

Show:

- Monitor scheduler status
- Last successful signal received
- Last rule evaluation
- Worker status
- Provider connection status
- Number of monitored services
- Number of monitored environments
- Detection lag
- Failed ingestion count

### Finding: auto-detected filter only checks `source === "webhook"`

Current behavior:

The page defines auto-detected incidents as webhook incidents.

Risk:

Prometheus, Sentry, deployment-regression, health-check, and future provider incidents can be incorrectly omitted.

Required behavior:

Use a server-provided `is_automatic` or normalized detection metadata field.

### Finding: no recent alerts/signals view

Required behavior:

Show recent normalized signals:

```text
provider
service
environment
region
signal type
value
threshold
status
correlated incident
time
```

### Finding: no monitoring coverage view

Required behavior:

Show which services are and are not monitored:

```text
42 services registered
38 services with health checks
35 services with metrics
27 services with logs
19 services with traces
```

### Finding: active rules are not enough

The page needs rule execution history, false-positive controls, silence windows, maintenance windows, and per-service scope.

---

## 10. Alerts page: `src/app/alerts/page.tsx`

### Finding: page manages rules but does not show alerts

The subtitle says “Manage alert rules and view recent alerts,” but the page only renders rules.

Required behavior:

Split into tabs:

```text
Rules
Recent signals
Triggered alerts
Silences
Maintenance windows
```

### Finding: rule control has no accessible label or confirmation

The toggle button has no clear accessible name, and changing a production detection rule can have serious consequences.

Fix:

- Add accessible label.
- Show current scope.
- Show last evaluation.
- Require confirmation for disabling critical rules.
- Record audit event.
- Show rollback/restore action.

### Finding: toggle failure feedback is invisible

Current behavior:

The UI optimistically changes and silently reverts on failure.

Required behavior:

Show a toast or inline error explaining that the rule was not changed.

### Finding: no create/edit rule UI

The backend exposes rule management, but the page appears focused on toggling existing rules.

Required behavior:

Support creating and editing rules with:

- Metric or signal
- Threshold
- Window
- Evaluation frequency
- Service scope
- Environment scope
- Region scope
- Severity
- Deduplication key
- Silence window

---

## 11. Services page: `src/app/services/page.tsx`

### Finding: services page appears to be a health summary, not a service catalog

Required service view:

- Service identity
- Owner team
- On-call
- Repositories
- Environments
- Regions
- Current deployments
- Dependencies
- Health checks
- Metrics
- Logs/traces coverage
- Open incidents
- SLOs
- Error budget
- Recent changes

### Finding: no service detail route

Users need to click a service and inspect its operational history. A single aggregate page is insufficient for a multi-service company.

### Finding: health score needs explanation

If an overall health score is displayed, show its formula and contributing signals. Never display a score without explaining whether it is based on availability, latency, error rate, incidents, or missing data.

---

## 12. Health page: `src/app/health/page.tsx`

### Finding: Sentinel health and customer service health are conflated

Separate these pages or sections:

```text
Sentinel platform health
Customer service health
Monitoring coverage
```

### Finding: no historical trend

Health requires trend data, not only current status. Add:

- Time range
- Availability history
- Latency history
- Error-rate history
- Incident markers
- Deployment markers
- Region comparison

### Finding: failed API requests become no data

Use explicit dependency-level error cards and retry buttons.

---

## 13. Repositories page: `src/app/repositories/page.tsx`

### Finding: repository list is not enough for multi-repository operations

Required repository fields:

- Organization
- Full name
- Service relationships
- Repository role
- Default branch
- Current deployment(s)
- Last indexed commit
- Index status
- Sync status
- Last sync error
- Ownership
- Connected GitHub installation
- Open Sentinel fixes

### Finding: sync action is ambiguous

The page uses GitHub synchronization actions, but the user needs to know whether this means:

- Fetch repository metadata
- Fetch commits
- Index code
- Sync deployments
- Refresh branches

Separate these operations or label them clearly.

### Finding: bulk sync lacks progress and per-repository results

For many repositories, show:

- Queue position
- Current repository
- Completed count
- Failed count
- Retry action
- Last indexed commit

### Finding: external links use `#` when no URL exists

Do not render a clickable link to `#`. Show “URL unavailable” instead.

---

## 14. Integrations page: `src/app/integrations/page.tsx`

### Finding: integration cards are static configuration data

The `integrations` array is hardcoded. Static descriptive cards are acceptable for documentation, but they must not imply that every listed integration is implemented or connected.

Required per-integration state:

```text
available
configured
connected
healthy
last event
last successful sync
permissions
failure reason
```

### Finding: only GitHub has a real connection flow

The UI mentions PagerDuty, Datadog, Sentry, Slack, and custom sources, but each must have a clear state:

```text
Not implemented
Available to configure
Configured but unhealthy
Connected and receiving events
```

Do not show an integration as active based only on its presence in a static array.

### Finding: PAT entry is risky UX

The page accepts a GitHub personal access token directly.

Required behavior:

- Prefer GitHub OAuth or App installation.
- Explain required permissions.
- Never echo the token.
- Clear input after submission.
- Show last four characters only if necessary.
- Provide disconnect/revoke flow.
- Show token expiry/health.

### Finding: webhook configuration is not a complete monitoring setup

For each provider, show:

- Endpoint
- Signing secret status
- Accepted event types
- Last received event
- Last signature failure
- Delivery health
- Test event action

---

## 15. Pull Requests page: `src/app/pull-requests/page.tsx`

### Finding: page is primarily an approval queue, not a PR inventory

Required behavior:

Show Draft PRs and fixes with:

- Repository
- Service
- Incident/work item
- Fix type
- Root cause
- Validation status
- Policy status
- Approval status
- GitHub PR status
- Branch
- Base SHA
- Changed files
- Risk
- Created time

### Finding: approval and GitHub PR states are not separated

These are different:

```text
Sentinel fix approval
GitHub Draft PR status
Human GitHub review
Merge status
Deployment status
```

The UI should show them separately.

### Finding: approve/reject actions lack review context

Before approval, show:

- Exact diff
- Evidence
- Root cause
- Validation output
- Risk
- Blast radius
- Rollback analysis
- Required number of reviewers

### Finding: reject action lacks reason

Require a rejection or changes-requested reason and display it in the investigation activity log.

---

## 16. ChatBot: `src/components/ChatBot.tsx`

### Finding: initial greeting is client-side static content

The initial assistant message is hardcoded. This is acceptable as a welcome message, but it must not be confused with current system knowledge.

### Finding: quick actions are static and may be misleading

Quick actions should be contextual to the current page, selected incident, organization, and permissions.

### Finding: chat response is not visibly grounded

Required behavior:

Every operational answer should display:

- Scope used
- Evidence references
- Confidence
- Timestamp of data
- Unknowns
- Links to incidents, services, repositories, commits, and PRs

### Finding: chat can appear to execute actions without a structured action flow

For commands such as “Create a fix,” use:

```text
Interpretation
→ proposed action
→ policy check
→ confirmation if required
→ execution
→ result
```

Do not treat a text response as evidence that an action occurred.

### Finding: request errors become generic chat messages

Display whether the issue is:

- Authentication failure
- Backend unavailable
- Nemotron unavailable
- Rate limited
- Invalid request
- No evidence found

### Finding: drag/resize implementation needs mobile and keyboard handling

The custom mouse-based resize behavior should have:

- Touch support
- Keyboard alternative
- Min/max dimensions
- Viewport clamping
- Cleanup on unmount
- Accessible controls

---

## 17. Settings page: `src/app/settings/page.tsx`

### Finding: settings include dangerous `auto_merge`

Current behavior:

The UI exposes an auto-merge setting.

Required behavior:

Because Sentinel must not autonomously merge, this setting should be removed or permanently disabled in the initial product. If organization policy later supports automated merging for low-risk changes, it requires an explicit policy engine and stronger controls.

### Finding: settings default to mock LLM

Current behavior:

The initial settings state uses `llm_provider: "mock"`.

Required behavior:

- Nemotron should be the configured production provider.
- Mock should be labeled development/test only.
- Show provider health and last successful call.
- Never present mock output as real reasoning.

### Finding: model placeholder mentions paid providers without product configuration

The UI placeholder references models such as GPT or Claude even though the project uses Nemotron. Use provider-specific configuration and clear documentation.

### Finding: save feedback is incomplete

The page displays a temporary “saved” state but needs:

- Validation errors
- Unsaved-change warning
- Server-confirmed values
- Permission-aware disabled fields
- Last updated timestamp

### Finding: notification settings are too narrow

An email field alone is insufficient. Add per-event delivery preferences for:

- New incidents
- Critical incidents
- Validation failures
- Draft PR creation
- Approval requests
- Predictive risk
- Integration failures

---

## 18. Users and profile pages

### `src/app/users/page.tsx`

Required improvements:

- Organization membership
- Team membership
- Role and permissions
- Active/inactive state
- Last login
- Approval authority
- Repository/service scope
- Invite and revoke flows

### `src/app/profile/page.tsx`

Current profile statistics are minimal and may only count incidents.

Required profile information:

- Organization
- Teams
- Current permissions
- Assigned services
- Pending reviews
- Approved/rejected fixes
- Recent activity
- Notification preferences

### Finding: logout/session expiry behavior is incomplete

If `/auth/me` fails, the app clears state and redirects eventually, but the user should see a clear session-expired message and avoid losing unsaved work.

---

## 19. Audit logs page: `src/app/audit-logs/page.tsx`

### Finding: audit logs are being reused as notifications

Separate concerns:

```text
Audit log: all security and operational actions
Notification: actionable message for a recipient
Activity trace: investigation execution events
```

### Required audit features

- Actor
- Organization
- Action
- Target entity
- Repository/service/environment
- Timestamp
- Request ID
- Result
- Before/after summary where safe
- Link to related incident or PR
- Export/filter capability

Do not expose secrets or sensitive payloads in audit details.

---

## 20. Authentication and API layer: `src/lib/AuthContext.tsx`, `src/lib/api.ts`

### Finding: token in localStorage

Current behavior:

The access token is stored in localStorage.

Risk:

XSS can expose the token.

Required improvement:

Prefer secure, HTTP-only cookies if the deployment architecture allows it. If localStorage remains temporarily:

- Enforce strong CSP.
- Avoid injecting unsafe HTML.
- Implement short-lived tokens.
- Handle expiry centrally.
- Clear all auth state on logout.

### Finding: API access is inconsistent

Current behavior:

Some screens use helper functions, while others call `fetch` directly.

Required improvement:

Create one API client that handles:

- Base URL
- Authorization
- JSON parsing
- `response.ok`
- Error normalization
- Request IDs
- Abort signals
- Retry policy
- 401 handling
- Typed response validation

### Finding: response types are too permissive

Use shared schemas or runtime validation for:

- Incident
- Service
- Repository
- Deployment
- Evidence
- Hypothesis
- Root cause
- Proposed fix
- Validation
- Approval
- Notification
- Health

Do not cast arbitrary API data with TypeScript assertions and assume it is valid.

### Finding: no global query/cache strategy

The same data is fetched independently by multiple pages. Add a consistent cache/query strategy or a typed data layer to avoid stale, duplicated requests.

---

## 21. Missing frontend features required by the full Sentinel product

The following screens or components are not adequately represented yet.

### 21.1 Organization switcher

Required for users who belong to multiple organizations.

### 21.2 Environment and region switcher

Required to distinguish production US from production India or staging.

### 21.3 Service dependency graph

Interactive graph showing:

- Services
- Repositories
- Databases
- Queues
- External providers
- Ownership
- Health state
- Incident state

### 21.4 Deployment inventory

Show all deployed versions and commit SHAs.

### 21.5 Blast-radius panel

Show direct, indirect, observed, inferred, and unknown impact.

### 21.6 Change ledger

Show code, config, dependency, infrastructure, feature-flag, migration, and deployment changes.

### 21.7 Incident memory

Show similar historical incidents, confirmed causes, fixes, and outcome quality.

### 21.8 SLO and error-budget dashboard

Show reliability trends and budget consumption.

### 21.9 Predictive-risk dashboard

Show warnings with:

- Service
- Metric trend
- Forecast window
- Confidence
- Reason
- Recommended diagnostic

### 21.10 Post-incident report

Show generated timeline, impact, root cause, fix, outcome, and follow-up work.

---

## 22. What the notification tab should show

The notification tab should not be a list of arbitrary audit records.

It should look like this:

```text
Notifications

UNREAD
────────────────────────────────────────
SEV-1  Payment service is unhealthy
       US production health checks failing
       2 minutes ago
       [Open incident]

ACTION REQUIRED
────────────────────────────────────────
Draft PR ready for review
       company/payment-service
       Validation passed · Medium risk
       14 minutes ago
       [Review PR]

INFO
────────────────────────────────────────
Investigation completed
       Root cause identified for INC-142
       25 minutes ago
       [View investigation]

SYSTEM
────────────────────────────────────────
Prometheus integration stopped sending signals
       Last successful event: 31 minutes ago
       [Fix integration]
```

Actions required:

- Open related entity
- Mark read
- Mark all read
- Snooze if supported
- Filter by severity/type
- Navigate to notification settings

---

## 23. Frontend implementation order

Implement frontend improvements in this order:

### Frontend Phase 0: data truth and failure states

- Remove fake fallback metrics.
- Separate empty from error.
- Add typed API error handling.
- Add loading, stale, retry, and unavailable states.
- Remove misleading mock labels from production UI.

### Frontend Phase 1: API/data foundation

- Centralize API requests.
- Add response validation.
- Add auth-expiry handling.
- Add query caching and refetch behavior.
- Add shared domain types.

### Frontend Phase 2: company context

- Organization selector.
- Environment selector.
- Region selector.
- Service catalog.
- Multi-repository views.
- Deployment inventory.

### Frontend Phase 3: autonomous operations

- Real notification center.
- Live incident list.
- Monitoring coverage.
- Recent signals.
- Provider health.
- Detection engine status.

### Frontend Phase 4: investigation workspace

- Durable activity trace.
- Evidence panel.
- Hypothesis competition.
- RCA timeline.
- Blast radius.
- Change ledger.
- Engineer feedback.

### Frontend Phase 5: remediation review

- Diff viewer improvements.
- Regression test display.
- Validation details.
- Policy decision.
- Approval requirements.
- Multi-repository Draft PR grouping.

### Frontend Phase 6: reliability intelligence

- Dependency graph.
- SLO/error budgets.
- Predictive risk.
- Post-incident reports.
- Incident memory.
- Fix effectiveness.

---

## 24. Frontend acceptance tests

### Test A: API failure is not empty data

Disconnect the backend. Verify that every page shows an error state and retry action rather than “No data.”

### Test B: notification behavior

Create two unread notifications and one read notification. Verify:

- Badge shows two.
- Panel shows all according to filter.
- Clicking opens related entity.
- Mark read persists after refresh.
- Mark all read persists after refresh.

### Test C: automatic production incident

Send a synthetic monitoring signal. Verify:

- No manual form submission is needed.
- Incident appears in the live dashboard.
- Notification is created.
- Service, environment, region, and detection source are shown.
- Investigation status updates without page reload.

### Test D: multi-repository incident

Create an incident affecting two repositories. Verify:

- Parent incident is shown.
- Two child investigations are shown.
- Each repository has its own status, diff, validation, and Draft PR.
- Evidence-only repositories are not shown as modified.

### Test E: insufficient evidence

Create an incident with weak evidence. Verify:

- UI shows insufficient evidence.
- No false root cause appears.
- No “Create Draft PR” action is available.
- Missing evidence is listed.

### Test F: unsafe fix

Return an invalid patch. Verify:

- Patch is blocked.
- UI explains why.
- No PR action is available.

### Test G: stale monitoring

Stop a provider from sending signals. Verify:

- Monitoring coverage indicates stale data.
- UI shows last successful event.
- The system does not claim monitoring is healthy.

---

## 25. Final frontend standard

The frontend is complete only when it tells the truth about the backend state.

It must never:

- Show invented progress.
- Show mock AI output as real analysis.
- Show failed API calls as empty data.
- Represent audit logs as notifications.
- Call the detection engine active without monitoring evidence.
- Hide which repositories and environments are affected.
- Hide validation or policy failures.
- Allow users to believe Sentinel merged or deployed a fix.

The frontend should make this entire lifecycle visible:

```text
Service monitored
→ signal received
→ incident detected automatically
→ blast radius calculated
→ investigation running
→ evidence collected
→ hypotheses evaluated
→ root cause or abstention
→ fix and regression test generated
→ validation completed
→ safety policy evaluated
→ Draft PR created per repository
→ human review
→ merge/deployment outcome monitored
```

The current frontend is a useful shell for this product, but it needs a substantial data-truth, operations, multi-repository, and investigation-workspace upgrade before it represents the complete Sentinel vision.
