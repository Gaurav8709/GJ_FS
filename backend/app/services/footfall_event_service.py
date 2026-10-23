
"""Background persistence for footfall entry/exit events."""

import asyncio
import logging
import queue
import threading
import uuid

from app.database import async_session
from app.models.new_features import FootfallEvent
from app.services.s3_service import save_file

logger = logging.getLogger("gjfashion.footfall_events")

_EVENT_QUEUE = queue.Queue(maxsize=1000)
_START_LOCK = threading.Lock()
_WORKER_STARTED = False


async def _persist_event(item: dict) -> None:
    """Save a snapshot, then persist its event record."""
    filename = f"{item['event_id']}.jpg"

    snapshot_url = await save_file(
        item["snapshot_bytes"],
        filename,
        folder="footfall_events",
    )

    async with async_session() as db:
        event = FootfallEvent(
            event_id=item["event_id"],
            cam_id=item["cam_id"],
            camera_name=item.get("camera_name"),
            tracking_id=str(item["tracking_id"]),
            event_type=item["event_type"],
            timestamp=item["timestamp"],
            snapshot_url=snapshot_url,
        )
        db.add(event)
        await db.commit()


async def _worker_loop() -> None:
    """Process queued events without blocking camera inference."""
    while True:
        item = await asyncio.to_thread(_EVENT_QUEUE.get)
        try:
            await _persist_event(item)
        except Exception:
            logger.exception(
                "Failed to persist footfall event %s",
                item.get("event_id"),
            )
        finally:
            _EVENT_QUEUE.task_done()


def _start_worker() -> None:
    global _WORKER_STARTED

    with _START_LOCK:
        if _WORKER_STARTED:
            return

        thread = threading.Thread(
            target=lambda: asyncio.run(_worker_loop()),
            name="footfall-event-writer",
            daemon=True,
        )
        thread.start()
        _WORKER_STARTED = True


def enqueue_footfall_event(
    *,
    cam_id: str,
    tracking_id: str,
    event_type: str,
    timestamp,
    snapshot_bytes: bytes,
    camera_name: str = None,
) -> bool:
    """Queue an event for asynchronous snapshot storage and persistence."""
    item = {
        "event_id": str(uuid.uuid4()),
        "cam_id": cam_id,
        "camera_name": camera_name,
        "tracking_id": str(tracking_id),
        "event_type": event_type,
        "timestamp": timestamp,
        "snapshot_bytes": snapshot_bytes,
    }

    _start_worker()

    try:
        _EVENT_QUEUE.put_nowait(item)
        return True
    except queue.Full:
        logger.error(
            "Footfall event queue is full; event dropped for camera %s",
            cam_id,
        )
        return False
