from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.database import get_db
from app.models.detection import DetectionLog, Alert
from app.models.worker import Worker, WorkerAssignment
from app.utils.auth import get_current_user_id

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

@router.get("/dashboard")
async def get_dashboard_stats(db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """Get high-level stats for the dashboard."""
    # Count active workers
    workers_res = await db.execute(select(func.count(Worker.id)).where(Worker.active == True))
    active_workers = workers_res.scalar()

    # Count unacknowledged alerts
    alerts_res = await db.execute(select(func.count(Alert.id)).where(Alert.acknowledged == False))
    unack_alerts = alerts_res.scalar()
    
    # Active assignments today
    # Just a simple count of active assignments for now
    assign_res = await db.execute(select(func.count(WorkerAssignment.id)).where(WorkerAssignment.active == True))
    active_assignments = assign_res.scalar()

    return {
        "active_workers": active_workers,
        "active_assignments": active_assignments,
        "unacknowledged_alerts": unack_alerts,
        "system_status": "Operational" if unack_alerts < 5 else "Warning"
    }

@router.get("/compliance")
async def get_compliance_stats(db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """Get zone compliance statistics based on latest logs."""
    # Very simplified compliance metric for demonstration
    # In a real app this would query logs grouped by zone and calculate time-in-compliance
    return {
        "overall_compliance": 85.5,
        "zones": [
            {"name": "Menswear Premium", "compliance": 90.0},
            {"name": "Womens Ethnic", "compliance": 75.2},
            {"name": "Kids Section", "compliance": 95.1}
        ]
    }
