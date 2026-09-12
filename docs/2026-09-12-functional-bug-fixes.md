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

## Validation

- `sentinel-ui`: `npm run build` passed.
- `backend`: `python -m compileall -q app` passed.
- `backend`: `python -m pytest -q` passed with 313 tests passed and 5 skipped.
- `sentinel-ui`: `npm run build` passed with Next.js 16.3.5.
- `sentinel-ui`: `npm audit --omit=dev` passed with 0 vulnerabilities.
- `backend`: focused authorization, webhook, remediation, and validation tests passed.
- `backend`: final compile and full test suite passed after configuration/state fixes.

## Scope

Frontend lint still reports React effect, `any` type, and declaration-order violations; automatic fixes did not resolve these semantic issues, and no lint rules were suppressed.
