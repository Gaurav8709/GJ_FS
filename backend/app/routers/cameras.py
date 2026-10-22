"""
GJ-Fashion — Cameras Router
Full CRUD & Onboarding for cameras + live status from CameraManager.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy import select, delete, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any

from app.database import get_db
from app.models.camera import Camera
from app.schemas.camera import CameraCreate, CameraUpdate, CameraResponse
from app.services.camera_manager import CameraManager
import json
from pathlib import Path

HEATMAP_SETTINGS_FILE = Path(__file__).resolve().parents[1] / "heatmap_settings.json"
HEATMAP_INTERVALS = {15, 30, 45, 60, 90, 120}
def _read_heatmap_settings():
    try:
        return json.loads(HEATMAP_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
def _write_heatmap_settings(data):
    HEATMAP_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = HEATMAP_SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(HEATMAP_SETTINGS_FILE)

router = APIRouter(prefix="/api/cameras", tags=["cameras"])

_columns_verified = False

async def _ensure_columns(db: AsyncSession):
    global _columns_verified
    if _columns_verified:
        return
    try:
        await db.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS web_rtsp_url VARCHAR(500);"))
        await db.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS codec VARCHAR(50) DEFAULT 'H.264';"))
        await db.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS footfall_enabled BOOLEAN DEFAULT TRUE;"))
        await db.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS heatmap_enabled BOOLEAN DEFAULT TRUE;"))
        await db.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS analytics_config VARCHAR(250) DEFAULT '';"))
        await db.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS inside_point VARCHAR(250) DEFAULT NULL;"))
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


@router.get("/footfall-config/export")
@router.get("/footfall-config")
async def get_footfall_cameras_config(db: AsyncSession = Depends(get_db)):
    """
    Returns dynamic footfall_cameras.json configuration for CV DeepStream / Python pipeline.
    Matches exact structure expected by CV team.
    """
    await _ensure_columns(db)
    result = await db.execute(select(Camera).order_by(Camera.id))
    cameras = result.scalars().all()

    cameras_map = {}
    heatmap_settings = _read_heatmap_settings()
    for cam in cameras:
        cameras_map[cam.cam_id] = {
            "enabled": bool(cam.footfall_enabled if cam.footfall_enabled is not None else cam.active),
            "uri": cam.rtsp_url or f"rtsp://65.1.214.31:8554/gj/{cam.cam_id}",
            "analytics": cam.analytics_config or f"config_nvdsanalytics_{cam.cam_id}.txt",
            "inside_point": cam.inside_point,
            "heatmap_interval_minutes": int(heatmap_settings.get(cam.cam_id, 60))
        }

    return {
        "backend_url": "http://65.2.158.148",
        "coord_width": 1920,
        "coord_height": 1080,
        "cameras": cameras_map
    }


@router.get("/{cam_id}/heatmap-config")
async def get_heatmap_config(cam_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Camera).where(func.lower(Camera.cam_id) == cam_id.strip().lower()))
    cam = result.scalar_one_or_none()
    if cam is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    return {"cam_id": cam.cam_id, "heatmap_interval_minutes": int(_read_heatmap_settings().get(cam.cam_id, 60))}


@router.put("/{cam_id}/heatmap-config")
async def update_heatmap_config(cam_id: str, payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Camera).where(func.lower(Camera.cam_id) == cam_id.strip().lower()))
    cam = result.scalar_one_or_none()
    if cam is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    try:
        interval = int(payload.get("heatmap_interval_minutes", 60))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Invalid interval")
    if interval not in HEATMAP_INTERVALS:
        raise HTTPException(status_code=422, detail="Interval must be 15, 30, 45, 60, 90, or 120")
    settings = _read_heatmap_settings()
    settings[cam.cam_id] = interval
    _write_heatmap_settings(settings)
    return {"cam_id": cam.cam_id, "heatmap_interval_minutes": interval}


@router.post("/footfall-config/import")
async def import_footfall_cameras_config(
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Imports footfall_cameras.json structure to bulk update/onboard camera analytics settings.
    """
    await _ensure_columns(db)
    cams_data = payload.get("cameras", {})
    updated_cams = []

    for cam_id, config in cams_data.items():
        cam_id_clean = str(cam_id).strip()
        result = await db.execute(
            select(Camera).where(func.lower(Camera.cam_id) == cam_id_clean.lower())
        )
        cam = result.scalar_one_or_none()

        enabled = bool(config.get("enabled", True))
        uri = str(config.get("uri", f"rtsp://65.1.214.31:8554/gj/{cam_id_clean}"))
        analytics = str(config.get("analytics", f"config_nvdsanalytics_{cam_id_clean}.txt"))
        inside_pt = config.get("inside_point")

        if cam:
            cam.footfall_enabled = enabled
            cam.rtsp_url = uri if uri else cam.rtsp_url
            cam.analytics_config = analytics
            cam.inside_point = str(inside_pt) if inside_pt else None
            updated_cams.append(cam_id_clean)
        else:
            new_cam = Camera(
                cam_id=cam_id_clean,
                name=f"Camera {cam_id_clean.upper()}",
                rtsp_url=uri,
                footfall_enabled=enabled,
                heatmap_enabled=True,
                analytics_config=analytics,
                inside_point=str(inside_pt) if inside_pt else None,
                active=True
            )
            db.add(new_cam)
            updated_cams.append(cam_id_clean)

    await db.commit()
    return {"status": "success", "imported_count": len(updated_cams), "cameras": updated_cams}


@router.put("/{cam_id}/analytics-toggle")
async def toggle_camera_analytics(
    cam_id: str,
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """Toggle Footfall or Heatmap Analytics per camera."""
    await _ensure_columns(db)
    result = await db.execute(
        select(Camera).where(func.lower(Camera.cam_id) == cam_id.strip().lower())
    )
    cam = result.scalar_one_or_none()
    if cam is None:
        raise HTTPException(status_code=404, detail=f"Camera '{cam_id}' not found")

    if "footfall_enabled" in payload:
        cam.footfall_enabled = bool(payload["footfall_enabled"])
    if "heatmap_enabled" in payload:
        cam.heatmap_enabled = bool(payload["heatmap_enabled"])
    if "analytics_config" in payload:
        cam.analytics_config = str(payload["analytics_config"])
    if "inside_point" in payload:
        cam.inside_point = str(payload["inside_point"]) if payload["inside_point"] else None

    await db.commit()
    await db.refresh(cam)
    return cam.to_dict()

