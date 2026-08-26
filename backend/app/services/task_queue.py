"""Background task queue — async investigation execution using Redis or in-memory."""
import asyncio
import json
import uuid
from typing import Dict, Any, Optional, Callable, Awaitable
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from enum import Enum

try:
    import redis.asyncio as redis
except ImportError:
    redis = None

from app.core.config import settings


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BackgroundTask:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    task_type: str = ""
    status: TaskStatus = TaskStatus.PENDING
    payload: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress: int = 0
    progress_message: str = ""


# --- In-Memory Queue (for development) ---

_task_queue: asyncio.Queue = asyncio.Queue()
_tasks: Dict[str, BackgroundTask] = {}
_running = False
_workers: list = []
_redis_client = None
_redis_queue_key = "sentinel:tasks:queue"
_redis_processing_key = "sentinel:tasks:processing"
_redis_task_prefix = "sentinel:task:"
_redis_recovered = False


def _redis_url() -> str:
    return settings.REDIS_URL


async def _get_redis():
    global _redis_client
    url = _redis_url()
    if redis is None or not url:
        return None
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(url, decode_responses=True, ssl_cert_reqs=None)
        except Exception:
            _redis_client = redis.from_url(url, decode_responses=True)
    try:
        await _redis_client.ping()
        return _redis_client
    except Exception:
        _redis_client = None
        return None


def _serialize_task(task: BackgroundTask) -> str:
    data = asdict(task)
    data["status"] = task.status.value
    return json.dumps(data)


def _deserialize_task(raw: str) -> BackgroundTask:
    data = json.loads(raw)
    data["status"] = TaskStatus(data.get("status", TaskStatus.PENDING.value))
    return BackgroundTask(**data)


async def _persist_task(task: BackgroundTask):
    client = await _get_redis()
    if client:
        await client.set(f"{_redis_task_prefix}{task.id}", _serialize_task(task))


async def _recover_redis_tasks(client):
    global _redis_recovered
    if _redis_recovered:
        return
    pending = await client.lrange(_redis_processing_key, 0, -1)
    if pending:
        await client.lpush(_redis_queue_key, *pending)
        await client.delete(_redis_processing_key)
    _redis_recovered = True


async def _worker():
    """Background worker that processes tasks."""
    global _running
    while _running:
        client = await _get_redis()
        if client:
            await _recover_redis_tasks(client)
            raw = await client.brpoplpush(_redis_queue_key, _redis_processing_key, timeout=1)
            if not raw:
                continue
            task = _deserialize_task(raw)
            _tasks[task.id] = task
        else:
            try:
                task = await asyncio.wait_for(_task_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(timezone.utc).isoformat()
        await _persist_task(task)

        try:
            handler = TASK_HANDLERS.get(task.task_type)
            if not handler:
                raise ValueError(f"Unknown task type: {task.task_type}")

            result = await handler(task)
            task.result = result
            task.status = TaskStatus.COMPLETED
            task.progress = 100
        except Exception as e:
            task.error = str(e)
            task.status = TaskStatus.FAILED
        finally:
            task.completed_at = datetime.now(timezone.utc).isoformat()
            await _persist_task(task)
            if client:
                await client.lrem(_redis_processing_key, 1, raw)
            else:
                _task_queue.task_done()


def start_workers(count: int = 2):
    """Start background workers."""
    global _running
    if _running:
        return
    _running = True
    for _ in range(count):
        _workers.append(asyncio.create_task(_worker()))


def stop_workers():
    """Stop background workers."""
    global _running
    _running = False


# --- Task Submission ---

async def submit_task(
    task_type: str,
    payload: Dict[str, Any],
    idempotency_key: Optional[str] = None,
) -> BackgroundTask:
    """Submit a task to the background queue. Duplicate idempotency_key returns existing task."""
    if idempotency_key:
        for existing in _tasks.values():
            if (
                existing.idempotency_key == idempotency_key
                and existing.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
            ):
                return existing

    task = BackgroundTask(task_type=task_type, payload=payload, idempotency_key=idempotency_key)
    _tasks[task.id] = task
    client = await _get_redis()
    if client:
        await _persist_task(task)
        await client.lpush(_redis_queue_key, _serialize_task(task))
    else:
        await _task_queue.put(task)
    return task


def get_task(task_id: str) -> Optional[BackgroundTask]:
    """Get task status."""
    return _tasks.get(task_id)


def list_tasks(status: Optional[TaskStatus] = None, limit: int = 50) -> list:
    """List tasks with optional status filter."""
    tasks = list(_tasks.values())
    if status:
        tasks = [t for t in tasks if t.status == status]
    tasks.sort(key=lambda t: t.created_at, reverse=True)
    return tasks[:limit]


async def get_queue():
    """Get the active queue (Redis or in-memory)."""
    client = await _get_redis()
    if client:
        return _RedisQueue(client)
    return _task_queue


class _RedisQueue:
    """Adapter to make Redis queue compatible with asyncio.Queue.get()."""

    def __init__(self, client):
        self._client = client

    async def get(self):
        raw = await self._client.brpoplpush(_redis_queue_key, _redis_processing_key, timeout=5)
        if raw:
            return _deserialize_task(raw)
        raise asyncio.TimeoutError()


def update_task_progress(task_id: str, progress: int, message: str = ""):
    """Update task progress."""
    task = _tasks.get(task_id)
    if task:
        task.progress = progress
        task.progress_message = message


# --- Task Handlers ---

TASK_HANDLERS: Dict[str, Callable[..., Awaitable[Dict]]] = {}


def register_handler(task_type: str):
    """Decorator to register a task handler."""
    def decorator(fn):
        TASK_HANDLERS[task_type] = fn
        return fn
    return decorator


@register_handler("investigation")
async def handle_investigation(task: BackgroundTask) -> Dict:
    """Handle investigation task."""
    from app.services.investigation_engine import InvestigationState, run_investigation

    payload = task.payload
    state = InvestigationState(
        incident_id=payload.get("incident_id", ""),
        incident_title=payload.get("incident_title", ""),
        incident_description=payload.get("incident_description", ""),
        error_signals=payload.get("error_signals", []),
        repository=payload.get("repository"),
        service=payload.get("service"),
    )

    task.progress = 10
    task.progress_message = "Planning investigation..."

    result = await run_investigation(state)

    return {
        "incident_id": result.incident_id,
        "status": result.status,
        "tasks_completed": result.tasks_completed,
        "tasks_failed": result.tasks_failed,
        "evidence_count": len(result.evidence_collected),
        "confidence": result.confidence,
    }


@register_handler("index_repository")
async def handle_index_repository(task: BackgroundTask) -> Dict:
    """Handle repository indexing task."""
    from app.routes.indexing import _scan_directory, _index_files

    payload = task.payload
    local_path = payload.get("local_path", "")

    task.progress = 10
    task.progress_message = "Scanning files..."

    files = _scan_directory(local_path)

    task.progress = 50
    task.progress_message = f"Indexing {len(files)} files..."

    chunks_count = await _index_files(
        files,
        repository=payload.get("repository", ""),
        indexed_at=datetime.now(timezone.utc).isoformat(),
    )

    return {
        "files_indexed": len(files),
        "chunks_indexed": chunks_count,
    }


@register_handler("detect_anomaly")
async def handle_detect_anomaly(task: BackgroundTask) -> Dict:
    """Handle anomaly detection task."""
    from app.routes.auto_detect import evaluate_rules

    payload = task.payload
    context = payload.get("context", {})
    service_name = payload.get("service_name", "")

    triggered = evaluate_rules(context)

    return {
        "service": service_name,
        "rules_triggered": len(triggered),
        "triggered_rules": triggered,
    }


# Exported for worker.py
_registered_handlers = TASK_HANDLERS
