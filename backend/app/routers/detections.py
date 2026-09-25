from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from datetime import datetime

from app.database import get_db
from app.models.detection import DetectionLog, Alert
from app.schemas.detection import DetectionLogResponse, AlertResponse, AlertAcknowledge
from app.utils.auth import get_current_user_id

router = APIRouter(prefix="/api", tags=["Detections & Alerts"])


@router.get("/detections", response_model=List[DetectionLogResponse])
async def get_detections(
    camera_id: str = None, 
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db), 
    user_id: int = Depends(get_current_user_id)
):
    """Get recent detection logs."""
    query = select(DetectionLog).order_by(DetectionLog.created_at.desc()).limit(limit)
    if camera_id:
        query = query.where(DetectionLog.camera_id == camera_id)
        
    result = await db.execute(query)
    logs = result.scalars().all()
    return [log.to_dict() for log in logs]


@router.get("/alerts", response_model=List[AlertResponse])
async def get_alerts(
    unacknowledged_only: bool = False,
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """Get recent alerts."""
    query = select(Alert).order_by(Alert.created_at.desc()).limit(limit)
    if unacknowledged_only:
        query = query.where(Alert.acknowledged == False)
        
    result = await db.execute(query)
    alerts = result.scalars().all()
    return [a.to_dict() for a in alerts]


@router.put("/alerts/{alert_id}/acknowledge", response_model=AlertResponse)
async def acknowledge_alert(
    alert_id: int, 
    data: AlertAcknowledge,
    db: AsyncSession = Depends(get_db), 
    user_id: int = Depends(get_current_user_id)
):
    """Acknowledge an alert."""
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
        
    alert.acknowledged = True
    alert.acknowledged_by = data.acknowledged_by
    alert.acknowledged_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(alert)
    return alert.to_dict()
