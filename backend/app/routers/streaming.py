from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket
from fastapi.responses import StreamingResponse, Response
from typing import Optional

from app.services.stream_service import mjpeg_generator, snapshot_bytes, ws_sender
from app.utils.auth import get_current_user_id

from typing import Optional, List, Dict, Any
import json

class AlertManager:
    """Manages active WebSocket clients and broadcasts real-time alerts."""
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        msg_str = json.dumps(message)
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(msg_str)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)

alert_manager = AlertManager()

router = APIRouter(prefix="/api/streams", tags=["Streaming"])


@router.get("/{camera_id}/mjpeg")
async def stream_mjpeg(
    camera_id: str,
    q: int = Query(75, description="JPEG quality 1-100"),
    fps: float = Query(30.0, description="Target FPS"),
    show_zones: bool = Query(True, description="Whether to show zones")
    # Authentication removed for simpler video tag embedding, 
    # but in production use token via query param
):
    """
    MJPEG video stream endpoint for a given camera.
    Returns multipart/x-mixed-replace.
    """
    return StreamingResponse(
        mjpeg_generator(camera_id, quality=q, fps=fps, show_zones=show_zones),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@router.get("/{camera_id}/snapshot")
async def get_snapshot(
    camera_id: str,
    q: int = Query(85, description="JPEG quality"),
    user_id: int = Depends(get_current_user_id)
):
    """
    Get a single JPEG snapshot of the latest frame from a camera.
    """
    frame_bytes = await snapshot_bytes(camera_id, quality=q)
    if not frame_bytes:
        raise HTTPException(status_code=404, detail="Camera frame not available")
        
    return Response(content=frame_bytes, media_type="image/jpeg")
