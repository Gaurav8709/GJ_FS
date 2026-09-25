"""
GJ-Fashion — Camera Manager
Singleton lifecycle manager for all CameraProcessor instances.
"""

import logging
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.camera_processor import CameraProcessor
from app.services.zone_engine import ZoneConfig
from app.models.camera import Camera, CameraZone

logger = logging.getLogger("gjfashion.camera_manager")


class CameraManager:
    """
    Manages all CameraProcessor instances.
    Provides lifecycle operations: start/stop/restart cameras.
    """
    _instance: Optional["CameraManager"] = None

    def __init__(self):
        self._processors: Dict[str, CameraProcessor] = {}

    @classmethod
    def get_instance(cls) -> "CameraManager":
        """Get or create the singleton camera manager."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Lifecycle ────────────────────────────────────────────

    async def load_cameras_from_db(self, db: AsyncSession):
        """
        Load all active cameras and their zones from the database,
        create CameraProcessor instances, and start them.
        """
        result = await db.execute(
            select(Camera).where(Camera.active == True)
        )
        cameras = result.scalars().all()

        logger.info(f"Loading {len(cameras)} cameras from database")

        for cam in cameras:
            zones = self._build_zone_configs(cam.zones)
            processor = CameraProcessor(
                cam_id=cam.cam_id,
                rtsp_url=cam.rtsp_url,
                zones=zones,
            )
            self._processors[cam.cam_id] = processor

        logger.info(f"Loaded {len(self._processors)} camera processors")

    def start_all(self):
        """Start all loaded camera processors."""
        for cam_id, processor in self._processors.items():
            processor.start()
        logger.info(f"Started {len(self._processors)} camera processors")

    def stop_all(self):
        """Stop all camera processors."""
        for cam_id, processor in self._processors.items():
            processor.stop()
        logger.info("Stopped all camera processors")

    def start_camera(self, cam_id: str) -> bool:
        """Start a specific camera processor."""
        processor = self._processors.get(cam_id)
        if processor is None:
            logger.warning(f"Camera {cam_id} not found")
            return False
        processor.start()
        return True

    def stop_camera(self, cam_id: str) -> bool:
        """Stop a specific camera processor."""
        processor = self._processors.get(cam_id)
        if processor is None:
            return False
        processor.stop()
        return True

    async def restart_camera(self, cam_id: str, db: AsyncSession) -> bool:
        """Stop, reload from DB, and restart a camera."""
        self.stop_camera(cam_id)

        result = await db.execute(
            select(Camera).where(Camera.cam_id == cam_id, Camera.active == True)
        )
        cam = result.scalar_one_or_none()
        if cam is None:
            self._processors.pop(cam_id, None)
            return False

        zones = self._build_zone_configs(cam.zones)
        processor = CameraProcessor(
            cam_id=cam.cam_id,
            rtsp_url=cam.rtsp_url,
            zones=zones,
        )
        self._processors[cam_id] = processor
        processor.start()
        return True

    async def add_camera(self, cam_id: str, rtsp_url: str, zones: List[ZoneConfig] = None):
        """Add and start a new camera processor dynamically."""
        if cam_id in self._processors:
            self._processors[cam_id].stop()

        processor = CameraProcessor(cam_id=cam_id, rtsp_url=rtsp_url, zones=zones or [])
        self._processors[cam_id] = processor
        processor.start()

    async def update_camera_zones(self, cam_id: str, db: AsyncSession) -> bool:
        """Reload zones for a camera from the database."""
        processor = self._processors.get(cam_id)
        if processor is None:
            return False

        result = await db.execute(
            select(Camera).where(Camera.cam_id == cam_id)
        )
        cam = result.scalar_one_or_none()
        if cam is None:
            return False

        zones = self._build_zone_configs(cam.zones)
        processor.update_zones(zones)
        return True

    # ── Accessors ────────────────────────────────────────────

    def get_processor(self, cam_id: str) -> Optional[CameraProcessor]:
        """Get a specific camera processor."""
        return self._processors.get(cam_id)

    def get_all_processors(self) -> Dict[str, CameraProcessor]:
        """Get all camera processors."""
        return dict(self._processors)

    def get_all_status(self) -> List[dict]:
        """Get status of all cameras."""
        return [p.get_status() for p in self._processors.values()]

    def get_camera_ids(self) -> List[str]:
        """Get list of all managed camera IDs."""
        return list(self._processors.keys())

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _build_zone_configs(orm_zones) -> List[ZoneConfig]:
        """Convert ORM CameraZone objects to lightweight ZoneConfig DTOs."""
        configs = []
        if orm_zones is None:
            return configs

        for z in orm_zones:
            if not z.active:
                continue
            configs.append(ZoneConfig(
                id=z.id,
                zone_name=z.zone_name,
                zone_type=z.zone_type or "monitoring",
                polygon_points=z.polygon_points or [],
                color=z.color or "#00FF00",
                opacity=z.opacity or 0.15,
                required_count=z.required_count or 1,
                max_count=z.max_count or 0,
                alert_enabled=z.alert_enabled if z.alert_enabled is not None else True,
            ))
        return configs
