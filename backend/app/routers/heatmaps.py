"""
GJ-Fashion — Camera-Specific Heatmap Management Router
Receives heatmap images from CV team and serves camera-specific density views.
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, Date

from app.database import get_db
from app.models.new_features import CameraHeatmap
from app.services.s3_service import save_file

from datetime import datetime, time
import logging

logger = logging.getLogger("gjfashion.heatmaps")
router = APIRouter(prefix="/api/heatmaps", tags=["Heatmaps"])


@router.post("/upload")
async def upload_camera_heatmap(
    cam_id: str = Form(...),
    peak_density: float = Form(0.0),
    meta_info: Optional[str] = Form("{}"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Endpoint for CV team to send camera-specific heatmap images and metadata.
    Uploads image to AWS S3 & RDS database, linked to camera_id.
    """
    file_bytes = await file.read()
    image_url = await save_file(file_bytes, f"heatmap_{cam_id}_{file.filename}", folder="heatmaps")

    import json
    try:
        parsed_meta = json.loads(meta_info) if meta_info else {}
    except Exception:
        parsed_meta = {"raw": meta_info}

    heatmap = CameraHeatmap(
        cam_id=cam_id,
        image_url=image_url,
        peak_density=peak_density,
        meta_info=parsed_meta
    )

    db.add(heatmap)
    await db.commit()
    await db.refresh(heatmap)

    return heatmap.to_dict()


@router.get("/camera/{cam_id}")
async def get_camera_heatmap(
    cam_id: str,
    limit: int = 50,
    date: Optional[str] = Query(None, description="Filter by YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db)
):
    """Fetch heatmaps for a specific camera with limit and date filtering."""
    query = select(CameraHeatmap).where(CameraHeatmap.cam_id == cam_id)

    if date and isinstance(date, str):
        try:
            parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
            start_dt = datetime.combine(parsed_date, time.min)
            end_dt = datetime.combine(parsed_date, time.max)
            query = query.where(CameraHeatmap.created_at >= start_dt, CameraHeatmap.created_at <= end_dt)
        except Exception as e:
            logger.error(f"Error parsing date filter ({date}): {e}")

    query = query.order_by(CameraHeatmap.created_at.desc()).limit(limit)
    result = await db.execute(query)
    heatmaps = result.scalars().all()

    if not heatmaps:
        return {
            "cam_id": cam_id,
            "image_url": None,
            "peak_density": 0.0,
            "meta_info": {},
            "history": [],
            "message": "No heatmap uploaded for this camera yet"
        }

    latest_dict = heatmaps[0].to_dict()
    history_list = [h.to_dict() for h in heatmaps]
    latest_dict["history"] = history_list
    return latest_dict


@router.get("/latest")
async def list_latest_heatmaps(
    date: Optional[str] = Query(None, description="Filter by YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db)
):
    """List all latest camera heatmaps across showroom with date filter."""
    query = select(CameraHeatmap)
    if date and isinstance(date, str):
        try:
            parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
            start_dt = datetime.combine(parsed_date, time.min)
            end_dt = datetime.combine(parsed_date, time.max)
            query = query.where(CameraHeatmap.created_at >= start_dt, CameraHeatmap.created_at <= end_dt)
        except Exception as e:
            logger.error(f"Error parsing date filter ({date}): {e}")

    query = query.order_by(CameraHeatmap.created_at.desc())
    result = await db.execute(query)
    heatmaps = result.scalars().all()

    # Get latest per camera
    latest_map = {}
    for h in heatmaps:
        if h.cam_id not in latest_map:
            latest_map[h.cam_id] = h.to_dict()

    return list(latest_map.values())


