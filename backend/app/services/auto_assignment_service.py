"""
GJ-Fashion — Auto Assignment Service
Background async task that polls camera statuses and auto-assigns workers when alerts trigger.
"""

import asyncio
import logging
import time

from app.database import async_session
from app.services.camera_manager import CameraManager
from app.services.assignment_service import auto_assign_idle_worker

logger = logging.getLogger("gjfashion.auto_assignment")

class AutoAssignmentService:
    _instance = None

    def __init__(self):
        self._running = False
        self._task = None
        # Track last assignment time per zone to avoid spamming
        self._last_assignment_times = {}

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Started Auto Assignment Service")

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("Stopped Auto Assignment Service")

    async def _loop(self):
        manager = CameraManager.get_instance()
        while self._running:
            try:
                statuses = manager.get_all_status()
                for status in statuses:
                    if not status.get("has_alert"):
                        continue
                    
                    cam_id = status["cam_id"]
                    zones = status.get("zones", {})
                    
                    for zone_name, zone_data in zones.items():
                        # We use zone_name as a proxy for section lookup in this prototype.
                        # In a real app, we'd need the exact section_id linked to the zone.
                        # For now, if there is a shortage counter > alert delay, we trigger.
                        shortage = zone_data.get("shortage_counter", 0)
                        if shortage > 0: # An alert is active
                            # Ensure we don't spam assignments (cooldown 5 minutes)
                            key = f"{cam_id}_{zone_name}"
                            last_time = self._last_assignment_times.get(key, 0)
                            if time.time() - last_time > 300:
                                await self._trigger_assignment(zone_name)
                                self._last_assignment_times[key] = time.time()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Auto assignment loop error: {e}")
            
            await asyncio.sleep(5)  # Poll every 5 seconds

    async def _trigger_assignment(self, zone_name: str):
        # We need to find the section_id. For prototype, we'll try to find a section by name
        from sqlalchemy import select
        from app.models.floor import Section
        
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(Section).where(Section.name.ilike(f"%{zone_name}%"))
                )
                section = result.scalars().first()
                if section:
                    await auto_assign_idle_worker(session, section.id)
                else:
                    logger.warning(f"Could not find section matching zone name: {zone_name}")
        except Exception as e:
            logger.error(f"Failed to trigger auto assignment: {e}")
