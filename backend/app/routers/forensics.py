"""
GJ-Fashion — FRS & Forensics Video Upload & Listener API Router
Handles clip uploads, metadata updates, and CV team listener JSON file exports.
"""

import json
from typing import Optional, List
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.new_features import ForensicClip
from app.services.s3_service import save_file

router = APIRouter(prefix="/api/forensics", tags=["Forensics & FRS"])


@router.post("/upload")
async def upload_forensic_clip(
    title: str = Form(...),
    category: str = Form("frs"),  # frs, forensic, assign_employee
    cam_id: Optional[str] = Form(None),
    emp_id: Optional[str] = Form(None),
    emp_name: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    shift: Optional[str] = Form("Morning"), # Morning, Afternoon, Day, Night
    media_type: Optional[str] = Form(None),  # video, picture
    metadata: Optional[str] = Form("{}"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Upload Assigned Employee Video or Picture clip (S3 & RDS sync).
    Saves file to AWS S3 / RDS database and exports structured listener JSON for CV facial embedding script.
    """
    # Auto-detect media_type if not provided
    if not media_type:
        fn_lower = (file.filename or "").lower()
        if any(fn_lower.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']) or (file.content_type and 'image' in file.content_type):
            media_type = "picture"
        else:
            media_type = "video"

    file_bytes = await file.read()
    # Save to AWS S3 / local fallback
    file_url = await save_file(file_bytes, file.filename, folder=f"forensics/{category}")

    try:
        parsed_meta = json.loads(metadata) if metadata else {}
    except Exception:
        parsed_meta = {"raw": metadata}

    parsed_meta["media_type"] = media_type
    parsed_meta["original_filename"] = file.filename

    # Structured listener JSON format for CV team embedding script
    listener_json = {
        "clip_id": None,
        "title": title,
        "category": category,
        "cam_id": cam_id,
        "emp_id": emp_id,
        "emp_name": emp_name,
        "role": role,
        "shift": shift,
        "media_type": media_type,
        "file_url": file_url,
        "s3_url": file_url,
        "metadata": parsed_meta,
        "status": "ready_for_cv_facial_embedding"
    }

    clip = ForensicClip(
        title=title,
        category=category,
        cam_id=cam_id,
        emp_id=emp_id,
        emp_name=emp_name,
        role=role,
        shift=shift,
        file_url=file_url,
        metadata_json=parsed_meta,
        listener_json=listener_json,
        status="processed"
    )

    db.add(clip)
    await db.commit()
    await db.refresh(clip)

    clip.listener_json["clip_id"] = clip.id
    db.add(clip)
    await db.commit()

    return clip.to_dict()


@router.get("/list")
async def list_forensic_clips(
    category: Optional[str] = None,
    cam_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """List uploaded FRS clips and Forensic videos."""
    query = select(ForensicClip).order_by(ForensicClip.created_at.desc())
    if category:
        query = query.where(ForensicClip.category == category)
    if cam_id:
        query = query.where(ForensicClip.cam_id == cam_id)

    result = await db.execute(query)
    clips = result.scalars().all()
    return [c.to_dict() for c in clips]


@router.get("/{clip_id}")
async def get_clip_details(clip_id: int, db: AsyncSession = Depends(get_db)):
    """Fetch details and listener JSON for a specific clip."""
    result = await db.execute(select(ForensicClip).where(ForensicClip.id == clip_id))
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    return clip.to_dict()


@router.delete("/{clip_id}")
async def delete_forensic_clip(clip_id: int, db: AsyncSession = Depends(get_db)):
    """Delete an assigned employee / forensic clip record."""
    result = await db.execute(select(ForensicClip).where(ForensicClip.id == clip_id))
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    await db.delete(clip)
    await db.commit()
    return {"status": "deleted", "id": clip_id}

