"""
GJ-Fashion — Camera-Specific Heatmap Management Router
Receives heatmap images from CV team and serves camera-specific density views.
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.new_features import CameraHeatmap
from app.services.s3_service import save_file

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
async def get_camera_heatmap(cam_id: str, db: AsyncSession = Depends(get_db)):
    """Fetch latest heatmap for a specific camera."""
    result = await db.execute(
        select(CameraHeatmap)
        .where(CameraHeatmap.cam_id == cam_id)
        .order_by(CameraHeatmap.created_at.desc())
    )
    heatmaps = result.scalars().all()
    if not heatmaps:
        return {"cam_id": cam_id, "image_url": None, "message": "No heatmap uploaded for this camera yet"}

    return heatmaps[0].to_dict()


@router.get("/latest")
async def list_latest_heatmaps(db: AsyncSession = Depends(get_db)):
    """List all latest camera heatmaps across showroom."""
    result = await db.execute(select(CameraHeatmap).order_by(CameraHeatmap.created_at.desc()))
    heatmaps = result.scalars().all()

    # Get latest per camera
    latest_map = {}
    for h in heatmaps:
        if h.cam_id not in latest_map:
            latest_map[h.cam_id] = h.to_dict()

    return list(latest_map.values())
