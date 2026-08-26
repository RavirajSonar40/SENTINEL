"""Cron-triggered task processor — processes pending tasks from Redis queue."""
from fastapi import APIRouter, Header
from typing import Optional
import logging
import asyncio

from app.core.config import settings

logger = logging.getLogger("sentinel.tasks")

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])

CRON_SECRET = settings.CRON_SECRET


@router.post("/process")
async def process_pending_tasks(x_cron_secret: Optional[str] = Header(None)):
    """Process pending tasks from Redis queue. Called by GitHub Actions cron."""
    if x_cron_secret != CRON_SECRET:
        return {"error": "unauthorized"}, 401

    from app.services.task_queue import (
        _get_redis,
        _redis_queue_key,
        _redis_processing_key,
        _deserialize_task,
        _serialize_task,
        TASK_HANDLERS,
        TaskStatus,
    )
    from datetime import datetime, timezone

    client = await _get_redis()
    if not client:
        return {"processed": 0, "reason": "no_redis"}

    # Recover any stuck processing tasks
    processing = await client.lrange(_redis_processing_key, 0, -1)
    if processing:
        await client.lpush(_redis_queue_key, *processing)
        await client.delete(_redis_processing_key)

    processed = 0
    failed = 0

    # Process up to 10 tasks per cron run
    for _ in range(10):
        raw = await client.lpop(_redis_queue_key)
        if not raw:
            break

        task = _deserialize_task(raw)
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(timezone.utc).isoformat()

        # Move to processing list
        await client.lpush(_redis_processing_key, _serialize_task(task))

        handler = TASK_HANDLERS.get(task.task_type)
        if not handler:
            task.status = TaskStatus.FAILED
            task.error = f"Unknown task type: {task.task_type}"
            task.completed_at = datetime.now(timezone.utc).isoformat()
            await client.lrem(_redis_processing_key, 1, _serialize_task(task))
            failed += 1
            continue

        try:
            result = await handler(task)
            task.result = result
            task.status = TaskStatus.COMPLETED
            task.progress = 100
            processed += 1
        except Exception as e:
            task.error = str(e)
            task.status = TaskStatus.FAILED
            failed += 1
        finally:
            task.completed_at = datetime.now(timezone.utc).isoformat()
            await client.lrem(_redis_processing_key, 1, _serialize_task(task))

    return {"processed": processed, "failed": failed}
