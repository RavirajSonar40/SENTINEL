"""Worker entrypoint — runs task queue consumers without the API server."""
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [worker] %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("sentinel.worker")


async def main():
    from app.core.database import engine, Base
    from app.services.task_queue import _task_queue, _registered_handlers, _tasks

    logger.info("Worker starting — connecting to database")

    # Ensure tables exist
    Base.metadata.create_all(bind=engine)

    # Initialize task queue (Redis-backed if REDIS_URL set)
    from app.services.task_queue import get_queue
    queue = await get_queue()

    logger.info(f"Worker ready — listening on queue: {type(queue).__name__}")
    logger.info(f"Registered handlers: {list(_registered_handlers.keys())}")

    # Process tasks
    while True:
        try:
            task_type, payload = await queue.get()
            handler = _registered_handlers.get(task_type)
            if not handler:
                logger.warning(f"No handler for task type: {task_type}")
                continue

            task_id = payload.get("task_id", "unknown")
            logger.info(f"Processing task {task_id} ({task_type})")
            _tasks[task_id] = {"status": "running"}

            try:
                result = await handler(**payload)
                _tasks[task_id] = {"status": "completed", "result": result}
                logger.info(f"Task {task_id} completed")
            except Exception as e:
                _tasks[task_id] = {"status": "failed", "error": str(e)}
                logger.error(f"Task {task_id} failed: {e}")

        except asyncio.CancelledError:
            logger.info("Worker shutting down")
            break
        except Exception as e:
            logger.error(f"Worker error: {e}")
            await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker stopped")
        sys.exit(0)
