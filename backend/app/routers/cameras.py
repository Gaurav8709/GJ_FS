"""
GJ-Fashion — Cameras Router
Full CRUD & Onboarding for cameras + live status from CameraManager.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.database import get_db
from app.models.camera import Camera
from app.schemas.camera import CameraCreate, CameraUpdate, CameraResponse
from app.services.camera_manager import CameraManager

router = APIRouter(prefix="/api/cameras", tags=["cameras"])

_columns_verified = False

async def _ensure_columns(db: AsyncSession):
    global _columns_verified
    if _columns_verified:
        return
    try:
        await db.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS web_rtsp_url VARCHAR(500);"))
        await db.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS codec VARCHAR(50) DEFAULT 'H.264';"))
        await db.commit()
        _columns_verified = True
    except Exception:
        await db.rollback()


@router.get("", response_model=List[CameraResponse])
async def list_cameras(db: AsyncSession = Depends(get_db)):
    """List all cameras."""
    await _ensure_columns(db)
    result = await db.execute(select(Camera).order_by(Camera.id))
    cameras = result.scalars().all()
    return [cam.to_dict() for cam in cameras]


@router.delete("/clear-all")
async def clear_all_cameras(db: AsyncSession = Depends(get_db)):
    """Delete all cameras from RDS database."""
    await _ensure_columns(db)
    await db.execute(delete(Camera))
    await db.commit()
    return {"success": True, "message": "All existing cameras deleted successfully"}


@router.post("", response_model=CameraResponse, status_code=201)
async def create_camera(
    body: CameraCreate,
    db: AsyncSession = Depends(get_db),
):
    """Onboard/Create a new camera with unique cam_id validation."""
    await _ensure_columns(db)
    cam_id_clean = body.cam_id.strip()

    # Check for duplicate cam_id (case-insensitive)
    existing = await db.execute(
        select(Camera).where(func.lower(Camera.cam_id) == cam_id_clean.lower())
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"Camera ID '{cam_id_clean}' already exists! Existing camera numbers cannot be reused."
        )

    cam_data = body.model_dump()
    cam_data["cam_id"] = cam_id_clean
    cam = Camera(**cam_data)
    db.add(cam)
    await db.commit()
    await db.refresh(cam)
    return cam.to_dict()


@router.get("/{cam_id}")
async def get_camera(cam_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single camera by cam_id."""
    await _ensure_columns(db)
    result = await db.execute(
        select(Camera).where(func.lower(Camera.cam_id) == cam_id.strip().lower())
    )
    cam = result.scalar_one_or_none()
    if cam is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    return cam.to_dict()


@router.put("/{cam_id}")
async def update_camera(
    cam_id: str,
    body: CameraUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a camera's details."""
    await _ensure_columns(db)
    result = await db.execute(
        select(Camera).where(func.lower(Camera.cam_id) == cam_id.strip().lower())
    )
    cam = result.scalar_one_or_none()
    if cam is None:
        raise HTTPException(status_code=404, detail="Camera not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(cam, key, value)

    await db.commit()
    await db.refresh(cam)
    return cam.to_dict()


@router.delete("/{cam_id}")
async def delete_camera(
    cam_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Hard delete a camera by cam_id."""
    await _ensure_columns(db)
    result = await db.execute(
        select(Camera).where(func.lower(Camera.cam_id) == cam_id.strip().lower())
    )
    cam = result.scalar_one_or_none()
    if cam is None:
        raise HTTPException(status_code=404, detail="Camera not found")

    await db.delete(cam)
    await db.commit()
    return {"success": True, "message": f"Camera '{cam_id}' deleted successfully"}


@router.get("/status/all")
async def all_camera_status():
    """Get live status of all camera processors."""
    manager = CameraManager.get_instance()
    return manager.get_all_status()


@router.get("/status/{cam_id}")
async def camera_status(cam_id: str):
    """Get live status for a specific camera."""
    manager = CameraManager.get_instance()
    processor = manager.get_processor(cam_id)
    if processor is None:
        raise HTTPException(status_code=404, detail="Camera processor not found")
    return processor.get_status()


@router.post("/{cam_id}/restart")
async def restart_camera(
    cam_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Restart a camera processor (reload from DB)."""
    manager = CameraManager.get_instance()
    ok = await manager.restart_camera(cam_id, db)
    if not ok:
        raise HTTPException(status_code=404, detail="Camera not found or inactive")
    return {"success": True, "cam_id": cam_id}
