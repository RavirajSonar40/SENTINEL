"""Tests for task queue persistence helpers and local fallback."""
import asyncio

from app.services import task_queue


def test_task_serialization_round_trip():
    original = task_queue.BackgroundTask(
        id="task-test",
        task_type="investigation",
        payload={"incident_id": "incident-test"},
        progress=25,
        progress_message="Searching",
    )

    restored = task_queue._deserialize_task(task_queue._serialize_task(original))

    assert restored.id == original.id
    assert restored.task_type == original.task_type
    assert restored.payload == original.payload
    assert restored.status == task_queue.TaskStatus.PENDING
    assert restored.progress == 25


def test_redis_disabled_without_url():
    original_url = task_queue._redis_url
    task_queue._redis_url = lambda: ""
    try:
        assert asyncio.run(task_queue._get_redis()) is None
    finally:
        task_queue._redis_url = original_url