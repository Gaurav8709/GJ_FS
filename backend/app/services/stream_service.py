"""
GJ-Fashion — Stream Service
MJPEG and WebSocket frame generators for video streaming.
"""

import asyncio
import logging
from typing import AsyncGenerator, Optional

from fastapi import WebSocket, WebSocketDisconnect
from app.services.camera_manager import CameraManager

logger = logging.getLogger("gjfashion.stream")


async def mjpeg_generator(
    cam_id: str,
    quality: int = 75,
    fps: float = 30.0,
    show_zones: bool = True,
) -> AsyncGenerator[bytes, None]:
    """
    Async generator yielding MJPEG frames for StreamingResponse.

    Uses asyncio.to_thread to avoid blocking the event loop during
    JPEG encoding in CameraProcessor.get_frame().

    Args:
        cam_id: Camera identifier (cam1, cam2, ...).
        quality: JPEG quality (0-100). Lower = faster for grid views.
        fps: Target streaming FPS.
        show_zones: Whether to draw zone overlays on the frame.

    Yields:
        MJPEG frame bytes with multipart boundaries.
    """
    manager = CameraManager.get_instance()
    interval = 1.0 / fps

    while True:
        processor = manager.get_processor(cam_id)

        if processor is not None:
            # Run get_frame in a thread to avoid blocking the event loop
            frame_bytes = await asyncio.to_thread(processor.get_frame, quality, show_zones)
        else:
            frame_bytes = None

        if frame_bytes is None:
            # Generate blank frame
            import cv2
            import numpy as np
            blank = np.full((480, 640, 3), 80, dtype=np.uint8)
            cv2.putText(
                blank, f"{cam_id} NOT FOUND",
                (100, 250), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2,
            )
            _, buf = cv2.imencode(".jpg", blank)
            frame_bytes = buf.tobytes()

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + frame_bytes
            + b"\r\n"
        )

        await asyncio.sleep(interval)


async def snapshot_bytes(cam_id: str, quality: int = 85) -> Optional[bytes]:
    """
    Get a single JPEG snapshot from a camera.

    Args:
        cam_id: Camera identifier.
        quality: JPEG quality.

    Returns:
        JPEG bytes or None.
    """
    manager = CameraManager.get_instance()
    processor = manager.get_processor(cam_id)

    if processor is not None:
        return await asyncio.to_thread(processor.get_frame, quality)
    return None

async def ws_sender(websocket: WebSocket, cam_id: str, quality: int = 75, fps: float = 30.0, show_zones: bool = True):
    """
    Send JPEG frames over WebSocket.
    """
    manager = CameraManager.get_instance()
    interval = 1.0 / fps

    try:
        while True:
            processor = manager.get_processor(cam_id)

            if processor is not None:
                frame_bytes = await asyncio.to_thread(processor.get_frame, quality, show_zones)
            else:
                frame_bytes = None

            if frame_bytes is None:
                import cv2
                import numpy as np
                blank = np.full((480, 640, 3), 80, dtype=np.uint8)
                cv2.putText(
                    blank, f"{cam_id} NOT FOUND",
                    (100, 250), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2,
                )
                _, buf = cv2.imencode(".jpg", blank)
                frame_bytes = buf.tobytes()

            await websocket.send_bytes(frame_bytes)
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        logger.info(f"[{cam_id}] WebSocket client disconnected")
    except Exception as e:
        logger.error(f"[{cam_id}] WebSocket streaming error: {e}")
