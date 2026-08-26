# Migration Foundation

- Timestamp: 2026-08-26
- Change: Repaired the Alembic revision chain and added deploy-time migration execution.
- Reason: The previous chain referenced a missing revision and the container served traffic without applying schema changes.
- Files changed: `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/015_baseline.py`, `backend/alembic/versions/016_add_fix_fields.py`, `backend/alembic/versions/017_add_fix_repository_patch.py`, `backend/Dockerfile`.
- Validation: Alembic configuration and backend compilation; full migration execution requires the deployment database.
- Commit: `2edc4688627fcc672d63b8f224c973edf831fa36`.