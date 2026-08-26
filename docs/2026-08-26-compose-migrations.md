# Compose Migration Startup

- Timestamp: 2026-08-26
- Change: Updated the Compose backend command to apply Alembic migrations before Uvicorn starts.
- Reason: Compose overrides the backend Dockerfile command and would otherwise skip migrations locally.
- Files changed: `docker-compose.yml`.
- Validation: Compose configuration inspection.
- Commit: To be added after validation.