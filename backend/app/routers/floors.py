"""
GJ-Fashion — Floors Router
Floor and Section CRUD.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing import List

from app.database import get_db
from app.models.floor import Floor, Section
from app.schemas.user import FloorCreate, FloorUpdate, SectionCreate, SectionUpdate
from app.utils.auth import get_current_user_id

router = APIRouter(prefix="/api/floors", tags=["floors"])


# ── Floors ───────────────────────────────────────────────────

@router.get("")
async def list_floors(db: AsyncSession = Depends(get_db)):
    """List all floors with their sections."""
    result = await db.execute(
        select(Floor).options(selectinload(Floor.sections)).order_by(Floor.sort_order)
    )
    floors = result.scalars().all()
    data = []
    for f in floors:
        fd = f.to_dict()
        fd["sections"] = [s.to_dict() for s in (f.sections or []) if s.active]
        data.append(fd)
    return data


@router.post("", status_code=201)
async def create_floor(
    body: FloorCreate,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new floor."""
    existing = await db.execute(select(Floor).where(Floor.code == body.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Floor code '{body.code}' already exists")

    floor = Floor(**body.model_dump())
    db.add(floor)
    await db.commit()
    await db.refresh(floor)
    return floor.to_dict()


@router.get("/{floor_id}")
async def get_floor(floor_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single floor with its sections."""
    result = await db.execute(
        select(Floor).options(selectinload(Floor.sections)).where(Floor.id == floor_id)
    )
    floor = result.scalar_one_or_none()
    if floor is None:
        raise HTTPException(status_code=404, detail="Floor not found")
    fd = floor.to_dict()
    fd["sections"] = [s.to_dict() for s in (floor.sections or []) if s.active]
    return fd


@router.put("/{floor_id}")
async def update_floor(
    floor_id: int,
    body: FloorUpdate,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Update a floor."""
    result = await db.execute(select(Floor).where(Floor.id == floor_id))
    floor = result.scalar_one_or_none()
    if floor is None:
        raise HTTPException(status_code=404, detail="Floor not found")

    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(floor, key, value)

    await db.commit()
    await db.refresh(floor)
    return floor.to_dict()


@router.delete("/{floor_id}")
async def delete_floor(
    floor_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a floor."""
    result = await db.execute(select(Floor).where(Floor.id == floor_id))
    floor = result.scalar_one_or_none()
    if floor is None:
        raise HTTPException(status_code=404, detail="Floor not found")

    floor.active = False
    await db.commit()
    return {"success": True}


# ── Sections ─────────────────────────────────────────────────

@router.get("/{floor_id}/sections")
async def list_sections(floor_id: int, db: AsyncSession = Depends(get_db)):
    """List all sections for a floor."""
    result = await db.execute(
        select(Section).where(Section.floor_id == floor_id, Section.active == True)
        .order_by(Section.sort_order)
    )
    sections = result.scalars().all()
    return [s.to_dict() for s in sections]


@router.post("/sections", status_code=201)
async def create_section(
    body: SectionCreate,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new section."""
    existing = await db.execute(select(Section).where(Section.code == body.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Section code '{body.code}' already exists")

    section = Section(**body.model_dump())
    db.add(section)
    await db.commit()
    await db.refresh(section)
    return section.to_dict()


@router.put("/sections/{section_id}")
async def update_section(
    section_id: int,
    body: SectionUpdate,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Update a section."""
    result = await db.execute(select(Section).where(Section.id == section_id))
    section = result.scalar_one_or_none()
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")

    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(section, key, value)

    await db.commit()
    await db.refresh(section)
    return section.to_dict()


@router.delete("/sections/{section_id}")
async def delete_section(
    section_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a section."""
    result = await db.execute(select(Section).where(Section.id == section_id))
    section = result.scalar_one_or_none()
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")

    section.active = False
    await db.commit()
    return {"success": True}
