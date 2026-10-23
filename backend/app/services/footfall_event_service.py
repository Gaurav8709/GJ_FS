"""Async persistence for footfall crossing snapshots, scheduled onto the API event loop."""

import asyncio
import logging
import threading
import uuid
from typing import Optional

from app.database import async_session
from app.models.new_features import FootfallEvent
from app.services.s3_service import save_file

logger = logging.getLogger("gjfashion.footfall_events")
_EVENT_LOOP: Optional[asyncio.AbstractEventLoop] = None
_PENDING_COUNT = 0
_PENDING_LOCK = threading.Lock()
_MAX_PENDING = 1000


def configure_footfall_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Bind writes to FastAPI's loop to avoid using the DB pool across event loops."""
    global _EVENT_LOOP
    _EVENT_LOOP = loop


def _save_snapshot_in_thread(snapshot_bytes: bytes, filename: str) -> str:
    # Keep synchronous file/S3 work off the API event loop.
    return asyncio.run(save_file(snapshot_bytes, filename, folder="footfall_events"))


async def _persist_event(item: dict) -> None:
    filename = f"{item['event_id']}.jpg"
    snapshot_url = await asyncio.to_thread(
        _save_snapshot_in_thread, item["snapshot_bytes"], filename
    )

    async with async_session() as db:
        db.add(
            FootfallEvent(
                event_id=item["event_id"],
                cam_id=item["cam_id"],
                camera_name=item.get("camera_name"),
                tracking_id=str(item["tracking_id"]),
                event_type=item["event_type"],
                timestamp=item["timestamp"],
                snapshot_url=snapshot_url,
            )
        )
        await db.commit()


def enqueue_footfall_event(
    *,
    cam_id: str,
    tracking_id: str,
    event_type: str,
    timestamp,
    snapshot_bytes: bytes,
    camera_name: str = None,
) -> bool:
    """Schedule an event write from the camera inference thread."""
    global _PENDING_COUNT

    loop = _EVENT_LOOP
    if loop is None or loop.is_closed():
        logger.error(
            "Footfall event loop is not configured; event not queued for %s",
            cam_id,
        )
        return False

    with _PENDING_LOCK:
        if _PENDING_COUNT >= _MAX_PENDING:
            logger.error(
                "Footfall event backlog is full; event dropped for camera %s",
                cam_id,
            )
            return False
        _PENDING_COUNT += 1

    item = {
        "event_id": str(uuid.uuid4()),
        "cam_id": cam_id,
        "camera_name": camera_name,
        "tracking_id": str(tracking_id),
        "event_type": event_type,
        "timestamp": timestamp,
        "snapshot_bytes": snapshot_bytes,
    }

    try:
        future = asyncio.run_coroutine_threadsafe(_persist_event(item), loop)
    except Exception:
        with _PENDING_LOCK:
            _PENDING_COUNT -= 1
        logger.exception("Could not schedule footfall event for camera %s", cam_id)
        return False

    def _done(completed_future):
        global _PENDING_COUNT
        try:
            completed_future.result()
        except Exception:
            logger.exception(
                "Failed to persist footfall event %s", item["event_id"]
            )
        finally:
            with _PENDING_LOCK:
                _PENDING_COUNT = max(0, _PENDING_COUNT - 1)

    future.add_done_callback(_done)
    return True