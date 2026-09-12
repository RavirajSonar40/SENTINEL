# Functional Bug Fixes

## Changes

- Corrected patch generation fallback to use the incident model's `service_name` field.
- Aligned the frontend patch editor with the backend's `patch` response field.
- Added frontend listeners for named investigation SSE events and removed them during cleanup.
- Made incident deletion skip PostgreSQL-only trigger cleanup when running against SQLite test databases.
- Rejected inactive users during login and authenticated request resolution.
- Scoped audit-log queries to the authenticated user's organization and restricted migrations to admins.
- Added HMAC verification for legacy alert webhooks outside test environments.
- Encrypted newly stored GitHub PAT and OAuth tokens while retaining legacy-row compatibility.
- Replaced shell-based Git operations and validation command execution with direct subprocess arguments.
- Upgraded Next.js to 16.3.5 and removed reported production dependency vulnerabilities.
- Scoped legacy settings and alert-rule state by organization.
- Added production/staging startup validation for development JWT and database defaults.
- Corrected incident-detail evidence, hypotheses, root-cause, and timeline requests to use incident IDs instead of investigation IDs.
- Corrected the shared frontend API helper URLs for those same incident-scoped endpoints.
- Unwrapped evidence and timeline response envelopes before rendering them as arrays.
- Made missing blast-radius reports render as an empty state instead of logging a page error.

## Validation

- `sentinel-ui`: `npm run build` passed.
- `backend`: `python -m compileall -q app` passed.
- `backend`: `python -m pytest -q` passed with 313 tests passed and 5 skipped.
- `sentinel-ui`: `npm run build` passed with Next.js 16.3.5.
- `sentinel-ui`: `npm audit --omit=dev` passed with 0 vulnerabilities.
- `backend`: focused authorization, webhook, remediation, and validation tests passed.
- `backend`: final compile and full test suite passed after configuration/state fixes.
- `sentinel-ui`: `npx next build --webpack` passed after local Turbopack subprocess crashes.
- Live Render health recovered after a transient 503; its OpenAPI now exposes all corrected incident routes.
- `sentinel-ui`: `npx tsc --noEmit` passed and webpack build passed with `NODE_OPTIONS=--max-old-space-size=4096`.

## Scope

Frontend lint still reports React effect, `any` type, and declaration-order violations; automatic fixes did not resolve these semantic issues, and no lint rules were suppressed.
