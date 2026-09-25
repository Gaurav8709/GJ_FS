from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List

from app.database import get_db
from app.models.worker import Worker
from app.schemas.worker import WorkerCreate, WorkerUpdate, WorkerResponse
from app.utils.auth import get_current_user_id

router = APIRouter(prefix="/api/workers", tags=["Workers"])


@router.get("", response_model=List[WorkerResponse])
async def get_workers(db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """Get all workers."""
    result = await db.execute(select(Worker).order_by(Worker.name))
    workers = result.scalars().all()
    return [w.to_dict() for w in workers]


@router.get("/{worker_id}", response_model=WorkerResponse)
async def get_worker(worker_id: int, db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """Get worker by ID."""
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    return worker.to_dict()


@router.post("", response_model=WorkerResponse, status_code=status.HTTP_201_CREATED)
async def create_worker(data: WorkerCreate, db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """Create a new worker."""
    # Check duplicate worker_id
    result = await db.execute(select(Worker).where(Worker.worker_id == data.worker_id))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Worker ID already exists")

    new_worker = Worker(
        worker_id=data.worker_id,
        name=data.name,
        role=data.role,
        phone=data.phone,
        shift=data.shift
    )
    db.add(new_worker)
    await db.commit()
    await db.refresh(new_worker)
    return new_worker.to_dict()


@router.put("/{worker_id}", response_model=WorkerResponse)
async def update_worker(worker_id: int, data: WorkerUpdate, db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """Update a worker."""
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(worker, key, value)

    await db.commit()
    await db.refresh(worker)
    return worker.to_dict()


@router.delete("/{worker_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_worker(worker_id: int, db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """Delete a worker."""
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    
    await db.delete(worker)
    await db.commit()
