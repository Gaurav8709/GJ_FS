from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from typing import List

from app.database import get_db
from app.models.worker import WorkerAssignment, Worker
from app.models.floor import Section
from app.schemas.worker import AssignmentCreate, AssignmentUpdate, AssignmentResponse
from app.utils.auth import get_current_user_id

router = APIRouter(prefix="/api/assignments", tags=["Assignments"])


@router.get("", response_model=List[AssignmentResponse])
async def get_assignments(db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """Get all worker assignments."""
    result = await db.execute(select(WorkerAssignment).options(selectinload(WorkerAssignment.worker), selectinload(WorkerAssignment.section)).order_by(WorkerAssignment.id.desc()))
    assignments = result.scalars().all()
    return [a.to_dict() for a in assignments]


@router.post("", response_model=AssignmentResponse, status_code=status.HTTP_201_CREATED)
async def create_assignment(data: AssignmentCreate, db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """Create a new worker assignment."""
    # Check if worker exists
    worker_res = await db.execute(select(Worker).where(Worker.id == data.worker_id))
    if not worker_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Worker not found")
        
    # Check if section exists
    section_res = await db.execute(select(Section).where(Section.id == data.section_id))
    if not section_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Section not found")

    new_assignment = WorkerAssignment(
        worker_id=data.worker_id,
        section_id=data.section_id,
        shift=data.shift,
        date=data.date
    )
    db.add(new_assignment)
    await db.commit()
    await db.refresh(new_assignment)
    
    # Reload with relations
    result = await db.execute(select(WorkerAssignment).options(selectinload(WorkerAssignment.worker), selectinload(WorkerAssignment.section)).where(WorkerAssignment.id == new_assignment.id))
    assigned = result.scalar_one()
    return assigned.to_dict()


@router.put("/{assignment_id}", response_model=AssignmentResponse)
async def update_assignment(assignment_id: int, data: AssignmentUpdate, db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """Update an assignment."""
    result = await db.execute(select(WorkerAssignment).options(selectinload(WorkerAssignment.worker), selectinload(WorkerAssignment.section)).where(WorkerAssignment.id == assignment_id))
    assignment = result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(assignment, key, value)

    await db.commit()
    return assignment.to_dict()


@router.delete("/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assignment(assignment_id: int, db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """Delete an assignment."""
    result = await db.execute(select(WorkerAssignment).where(WorkerAssignment.id == assignment_id))
    assignment = result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    
    await db.delete(assignment)
    await db.commit()
