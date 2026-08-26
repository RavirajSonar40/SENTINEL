# Redis Worker Foundation

- Timestamp: 2026-08-26
- Change: Added optional Redis-backed task persistence and queue processing with an in-memory fallback.
- Reason: In-memory investigation jobs disappear when the API restarts; Redis is required for restart-safe work.
- Files changed: `backend/requirements.txt`, `backend/app/core/config.py`, `backend/app/services/task_queue.py`, `backend/tests/test_task_queue.py`.
- Validation: Queue serialization tests, Redis-disabled fallback test, full backend suite, and Python compilation.
- Commit: `fef2d320d6cb02bc63ae1e993795a910570b3659`.