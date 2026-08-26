# Approval Gate Change

- Timestamp: 2026-08-26
- Change: Enforced explicit human approval before draft PR creation.
- Reason: Investigation completion must not create branches, commits, or pull requests automatically.
- Files changed: `backend/app/routes/investigation_engine.py`, `backend/app/routes/remediation.py`, `backend/tests/test_approval_gate.py`.
- Validation: Focused approval-gate test and full backend test suite.
- Commit: `ac99258752f687c4a02eebfc64a605e4090810e2`.