"""
GJ-Fashion — Assignment Service
Worker-to-Section assignment business logic.
"""

import logging
from typing import List, Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.worker import Worker, WorkerAssignment
from app.models.floor import Section

logger = logging.getLogger("gjfashion.assignment")


async def get_assignments_for_section(
    db: AsyncSession, section_id: int
) -> List[WorkerAssignment]:
    """Get all active assignments for a section."""
    result = await db.execute(
        select(WorkerAssignment)
        .options(selectinload(WorkerAssignment.worker), selectinload(WorkerAssignment.section))
        .where(WorkerAssignment.section_id == section_id, WorkerAssignment.active == True)
    )
    return result.scalars().all()


async def get_assignments_for_worker(
    db: AsyncSession, worker_id: int
) -> List[WorkerAssignment]:
    """Get all active assignments for a worker."""
    result = await db.execute(
        select(WorkerAssignment)
        .options(selectinload(WorkerAssignment.worker), selectinload(WorkerAssignment.section))
        .where(WorkerAssignment.worker_id == worker_id, WorkerAssignment.active == True)
    )
    return result.scalars().all()


async def assign_worker_to_section(
    db: AsyncSession,
    worker_id: int,
    section_id: int,
    shift: str = "day",
) -> WorkerAssignment:
    """Create a new worker assignment."""
    assignment = WorkerAssignment(
        worker_id=worker_id,
        section_id=section_id,
        shift=shift,
        active=True,
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return assignment


async def remove_assignment(db: AsyncSession, assignment_id: int) -> bool:
    """Deactivate an assignment."""
    result = await db.execute(
        select(WorkerAssignment).where(WorkerAssignment.id == assignment_id)
    )
    assignment = result.scalar_one_or_none()
    if assignment is None:
        return False
    assignment.active = False
    await db.commit()
    return True


async def auto_assign_idle_worker(db: AsyncSession, section_id: int) -> Optional[WorkerAssignment]:
    """Find an idle worker and assign them to the section automatically."""
    # Find active workers with no active assignments
    subq = select(WorkerAssignment.worker_id).where(WorkerAssignment.active == True)
    result = await db.execute(
        select(Worker).where(Worker.active == True, Worker.id.not_in(subq))
    )
    idle_workers = result.scalars().all()

    if not idle_workers:
        logger.warning(f"No idle workers available to auto-assign to section {section_id}")
        return None

    # Pick the first available worker
    selected_worker = idle_workers[0]
    logger.info(f"Auto-assigning worker {selected_worker.name} (ID: {selected_worker.id}) to section {section_id}")

    return await assign_worker_to_section(
        db=db,
        worker_id=selected_worker.id,
        section_id=section_id,
        shift="auto"
    )
