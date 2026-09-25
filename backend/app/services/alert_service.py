"""
GJ-Fashion — Alert Service
Per-zone shortage tracking, alert generation, and WebSocket broadcast.
"""

import asyncio
import logging
import time
import os
from typing import Dict, List, Optional, Set

from fastapi import WebSocket

from app.config import settings

logger = logging.getLogger("gjfashion.alert")


class AlertService:
    """
    Manages alert WebSocket clients and provides alert broadcast.
    Also tracks per-zone shortage counters for alerting logic.
    """
    _instance: Optional["AlertService"] = None

    def __init__(self):
        self._alert_clients: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "AlertService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── WebSocket Client Management ─────────────────────────

    async def register_client(self, ws: WebSocket):
        """Register a WebSocket client for alert broadcasts."""
        async with self._lock:
            self._alert_clients.add(ws)
        logger.info(f"Alert client connected. Total: {len(self._alert_clients)}")

    async def unregister_client(self, ws: WebSocket):
        """Remove a WebSocket client."""
        async with self._lock:
            self._alert_clients.discard(ws)
        logger.info(f"Alert client disconnected. Total: {len(self._alert_clients)}")

    async def broadcast_alert(self, alert_data: dict):
        """Broadcast alert data to all connected WebSocket clients."""
        async with self._lock:
            dead_clients = set()
            for ws in self._alert_clients:
                try:
                    await ws.send_json(alert_data)
                except Exception:
                    dead_clients.add(ws)
            self._alert_clients -= dead_clients

    # ── Alert Generation ────────────────────────────────────

    async def broadcast_camera_status(self, status_data: dict):
        """Broadcast live status updates to connected clients."""
        await self.broadcast_alert({
            "type": "status_update",
            "data": status_data,
        })

    async def broadcast_shortage_alert(
        self,
        cam_id: str,
        zone_name: str,
        detected: int,
        required: int,
        screenshot_path: Optional[str] = None,
    ):
        """Broadcast a worker shortage alert."""
        await self.broadcast_alert({
            "type": "worker_shortage",
            "cam_id": cam_id,
            "zone_name": zone_name,
            "detected": detected,
            "required": required,
            "screenshot_path": screenshot_path,
            "timestamp": time.time(),
        })
