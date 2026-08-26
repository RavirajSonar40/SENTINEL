# Compose Migration Startup

- Timestamp: 2026-08-26
- Change: Updated the Compose backend command to apply Alembic migrations before Uvicorn starts.
- Reason: Compose overrides the backend Dockerfile command and would otherwise skip migrations locally.
- Files changed: `docker-compose.yml`.
- Validation: Compose configuration inspection.
- Commit: `53e43908a38cb64cac9efb531d102b88e3f52118`.