"""
GJ-Fashion — Zones Router
CRUD for camera polygon zones.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.database import get_db
from app.models.camera import Camera, CameraZone
from app.schemas.zone import ZoneCreate, ZoneUpdate, ZoneResponse
from app.services.camera_manager import CameraManager
from app.utils.auth import get_current_user_id

router = APIRouter(prefix="/api/zones", tags=["zones"])


@router.get("")
async def list_all_zones(db: AsyncSession = Depends(get_db)):
    """List all zones across all cameras."""
    result = await db.execute(
        select(CameraZone).where(CameraZone.active == True).order_by(CameraZone.camera_id)
    )
    zones = result.scalars().all()
    return [z.to_dict() for z in zones]


@router.get("/camera/{cam_id}")
async def list_zones_for_camera(cam_id: str, db: AsyncSession = Depends(get_db)):
    """List all zones for a specific camera (by cam_id string)."""
    # Resolve cam_id to camera.id
    cam_result = await db.execute(select(Camera).where(Camera.cam_id == cam_id))
    cam = cam_result.scalar_one_or_none()
    if cam is None:
        raise HTTPException(status_code=404, detail="Camera not found")

    result = await db.execute(
        select(CameraZone)
        .where(CameraZone.camera_id == cam.id, CameraZone.active == True)
    )
    zones = result.scalars().all()
    return [z.to_dict() for z in zones]


@router.post("", status_code=201)
async def create_zone(
    body: ZoneCreate,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new polygon zone for a camera."""
    # Validate camera exists
    cam_result = await db.execute(select(Camera).where(Camera.id == body.camera_id))
    cam = cam_result.scalar_one_or_none()
    if cam is None:
        raise HTTPException(status_code=404, detail="Camera not found")

    # Validate polygon has at least 3 points
    if len(body.polygon_points) < 3:
        raise HTTPException(status_code=400, detail="Polygon must have at least 3 points")

    # Validate coordinates are normalised 0.0–1.0
    for pt in body.polygon_points:
        if len(pt) != 2 or not (0.0 <= pt[0] <= 1.0) or not (0.0 <= pt[1] <= 1.0):
            raise HTTPException(
                status_code=400,
                detail="All polygon points must be [x, y] with values between 0.0 and 1.0",
            )

    zone = CameraZone(**body.model_dump())
    db.add(zone)
    await db.commit()
    await db.refresh(zone)

    # Hot-reload zones in the camera processor
    manager = CameraManager.get_instance()
    await manager.update_camera_zones(cam.cam_id, db)

    return zone.to_dict()


@router.get("/{zone_id}")
async def get_zone(zone_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single zone by ID."""
    result = await db.execute(select(CameraZone).where(CameraZone.id == zone_id))
    zone = result.scalar_one_or_none()
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")
    return zone.to_dict()


@router.put("/{zone_id}")
async def update_zone(
    zone_id: int,
    body: ZoneUpdate,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Update a zone polygon or settings."""
    result = await db.execute(select(CameraZone).where(CameraZone.id == zone_id))
    zone = result.scalar_one_or_none()
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")

    update_data = body.model_dump(exclude_unset=True)

    # Validate polygon if being updated
    if "polygon_points" in update_data:
        pts = update_data["polygon_points"]
        if len(pts) < 3:
            raise HTTPException(status_code=400, detail="Polygon must have at least 3 points")
        for pt in pts:
            if len(pt) != 2 or not (0.0 <= pt[0] <= 1.0) or not (0.0 <= pt[1] <= 1.0):
                raise HTTPException(status_code=400, detail="Invalid polygon coordinates")

    for key, value in update_data.items():
        setattr(zone, key, value)

    await db.commit()
    await db.refresh(zone)

    # Hot-reload zones in the camera processor
    cam_result = await db.execute(select(Camera).where(Camera.id == zone.camera_id))
    cam = cam_result.scalar_one_or_none()
    if cam:
        manager = CameraManager.get_instance()
        await manager.update_camera_zones(cam.cam_id, db)

    return zone.to_dict()


@router.delete("/{zone_id}")
async def delete_zone(
    zone_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a zone."""
    result = await db.execute(select(CameraZone).where(CameraZone.id == zone_id))
    zone = result.scalar_one_or_none()
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")

    zone.active = False
    await db.commit()

    # Hot-reload zones
    cam_result = await db.execute(select(Camera).where(Camera.id == zone.camera_id))
    cam = cam_result.scalar_one_or_none()
    if cam:
        manager = CameraManager.get_instance()
        await manager.update_camera_zones(cam.cam_id, db)

    return {"success": True}
