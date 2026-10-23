"""
GJ-Fashion — Footfall Listener & Analytics Router
Handles real-time footfall updates (+1/-1, gender & age breakdowns) and timestamped chart data.
"""

import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, extract

from app.database import get_db
from app.models.new_features import FootfallRecord, FootfallEvent, FootfallGate
from app.models.camera import Camera
from app.services.camera_manager import CameraManager

router = APIRouter(prefix="/api/footfall", tags=["Footfall Analytics"])


@router.post("/listener-update")
async def receive_footfall_update(
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Listener endpoint for CV team listener script.
    Receives JSON updates containing (+1/-1 footfall, gender, age breakdown).
    """
    cam_id = payload.get("cam_id", "cam1")
    entries = int(payload.get("entries", 0))
    exits = int(payload.get("exits", 0))
    net_count = int(payload.get("net_count", max(0, entries - exits)))
    male_count = int(payload.get("male_count", 0))
    female_count = int(payload.get("female_count", 0))

    age_data = payload.get("age_breakdown", {})
    age_0_9 = int(age_data.get("0_9", 0))
    age_10_17 = int(age_data.get("10_17", 0))
    age_18_25 = int(age_data.get("18_25", 0))
    age_26_35 = int(age_data.get("26_35", 0))
    age_36_50 = int(age_data.get("36_50", 0))
    age_50_plus = int(age_data.get("50_plus", 0))

    # Parse custom timestamp if sent by CV team, else default to current time
    raw_ts = payload.get("timestamp")
    record_timestamp = datetime.datetime.utcnow()
    if raw_ts:
        try:
            clean_ts = str(raw_ts).replace("Z", "").replace("T", " ")
            if "." in clean_ts:
                clean_ts = clean_ts.split(".")[0]
            record_timestamp = datetime.datetime.strptime(clean_ts.strip(), "%Y-%m-%d %H:%M:%S")
        except Exception:
            record_timestamp = datetime.datetime.utcnow()

    record = FootfallRecord(
        cam_id=cam_id,
        entries=entries,
        exits=exits,
        net_count=net_count,
        male_count=male_count,
        female_count=female_count,
        age_0_9=age_0_9,
        age_10_17=age_10_17,
        age_18_25=age_18_25,
        age_26_35=age_26_35,
        age_36_50=age_36_50,
        age_50_plus=age_50_plus,
        timestamp=record_timestamp
    )

    db.add(record)
    await db.commit()
    await db.refresh(record)

    return {"status": "success", "record": record.to_dict()}


@router.get("/stats")
async def get_footfall_stats(
    cam_id: Optional[str] = Query(None, description="Camera ID filter"),
    start_date: Optional[str] = Query(None, description="Start Date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End Date (YYYY-MM-DD)"),
    start_time: Optional[str] = Query(None, description="Start Time (HH:MM)"),
    end_time: Optional[str] = Query(None, description="End Time (HH:MM)"),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns aggregated footfall statistics, timestamped history, gender & age distributions
    filtered by date range, time duration, or specific camera stream.
    """
    default_start = datetime.datetime(2026, 9, 28, 0, 0, 0)
    start_dt = default_start
    end_dt = None

    if start_date:
        try:
            s_date = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
            s_time = datetime.time(0, 0, 0)
            if start_time:
                p = start_time.split(":")
                s_time = datetime.time(int(p[0]), int(p[1]))
            start_dt = datetime.datetime.combine(s_date, s_time)
        except Exception:
            pass

    if end_date:
        try:
            e_date = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
            e_time = datetime.time(23, 59, 59)
            if end_time:
                p = end_time.split(":")
                e_time = datetime.time(int(p[0]), int(p[1]))
            end_dt = datetime.datetime.combine(e_date, e_time)
        except Exception:
            pass

    query = select(FootfallRecord).where(FootfallRecord.timestamp >= start_dt)
    if end_dt:
        query = query.where(FootfallRecord.timestamp <= end_dt)

    if cam_id:
        query = query.where(FootfallRecord.cam_id == cam_id)

    result = await db.execute(query.order_by(FootfallRecord.timestamp.asc()))
    records = result.scalars().all()

    total_entries = sum(r.entries for r in records)
    total_exits = sum(r.exits for r in records)
    net_current = max(0, total_entries - total_exits)
    total_male = sum(r.male_count or 0 for r in records)
    total_female = sum(r.female_count or 0 for r in records)

    age_totals = {
        "0_9": sum((r.age_0_9 or 0) for r in records),
        "10_17": sum((r.age_10_17 or 0) for r in records),
        "18_25": sum((r.age_18_25 or 0) for r in records),
        "26_35": sum((r.age_26_35 or 0) for r in records),
        "36_50": sum((r.age_36_50 or 0) for r in records),
        "50_plus": sum((r.age_50_plus or 0) for r in records),
    }

    # Format timestamp series for bar graphs (latest N time points)
    recent_records = records[-limit:] if len(records) > limit else records
    timestamps = []
    for r in recent_records:
        ts_label = r.timestamp.strftime("%Y-%m-%d %H:%M:%S") if r.timestamp else "N/A"
        timestamps.append({
            "timestamp": ts_label,
            "entries": r.entries,
            "exits": r.exits,
            "net": r.net_count,
            "cam_id": r.cam_id
        })

    return {
        "total_entries": total_entries,
        "total_exits": total_exits,
        "net_current": net_current,
        "gender_breakdown": {
            "male": total_male,
            "female": total_female
        },
        "age_breakdown": age_totals,
        "time_series": timestamps,
        "raw_records": [r.to_dict() for r in recent_records[-10:]]
    }




@router.get("/gates/{cam_id}")
async def get_footfall_gate(
    cam_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the configured entry/exit line for a camera."""
    camera_result = await db.execute(
        select(Camera).where(Camera.cam_id == cam_id)
    )
    camera = camera_result.scalar_one_or_none()

    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")

    gate_result = await db.execute(
        select(FootfallGate).where(FootfallGate.cam_id == cam_id)
    )
    gate = gate_result.scalar_one_or_none()

    if gate is None:
        return {
            "cam_id": cam_id,
            "line_start": [0.25, 0.5],
            "line_end": [0.75, 0.5],
            "entry_side": 1,
            "enabled": False,
        }

    return gate.to_dict()


@router.put("/gates/{cam_id}")
async def save_footfall_gate(
    cam_id: str,
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Create or update a camera's entry/exit line."""
    camera_result = await db.execute(
        select(Camera).where(Camera.cam_id == cam_id)
    )
    camera = camera_result.scalar_one_or_none()

    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")

    line_start = payload.get("line_start")
    line_end = payload.get("line_end")
    entry_side = payload.get("entry_side", 1)
    enabled = payload.get("enabled", False)

    for name, point in (
        ("line_start", line_start),
        ("line_end", line_end),
    ):
        if (
            not isinstance(point, list)
            or len(point) != 2
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not 0 <= value <= 1
                for value in point
            )
        ):
            raise HTTPException(
                status_code=422,
                detail=f"{name} must contain two normalized coordinates between 0 and 1",
            )

    if line_start == line_end:
        raise HTTPException(
            status_code=422,
            detail="The gate line endpoints must be different",
        )

    if (
        not isinstance(entry_side, int)
        or isinstance(entry_side, bool)
        or entry_side not in (-1, 1)
    ):
        raise HTTPException(
            status_code=422,
            detail="entry_side must be 1 or -1",
        )

    if not isinstance(enabled, bool):
        raise HTTPException(
            status_code=422,
            detail="enabled must be a boolean",
        )

    gate_result = await db.execute(
        select(FootfallGate).where(FootfallGate.cam_id == cam_id)
    )
    gate = gate_result.scalar_one_or_none()

    if gate is None:
        gate = FootfallGate(
            cam_id=cam_id,
            line_start=line_start,
            line_end=line_end,
            entry_side=entry_side,
            enabled=enabled,
        )
        db.add(gate)
    else:
        gate.line_start = line_start
        gate.line_end = line_end
        gate.entry_side = entry_side
        gate.enabled = enabled


    await db.commit()
    await db.refresh(gate)

    # Apply the new configuration without restarting the camera.
    manager = CameraManager.get_instance()
    processor = manager.get_processor(cam_id)

    if processor is not None:
        processor.update_footfall_gate(gate.to_dict())

    return gate.to_dict()


@router.get("/events")
async def get_footfall_events(
    cam_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Return separate entry/exit crossing records with pagination and filters."""
    conditions = []

    if cam_id:
        conditions.append(FootfallEvent.cam_id == cam_id)

    if event_type:
        normalized_type = event_type.upper()
        if normalized_type not in ("ENTRY", "EXIT"):
            raise HTTPException(
                status_code=422,
                detail="event_type must be ENTRY or EXIT",
            )
        conditions.append(FootfallEvent.event_type == normalized_type)

    try:
        if start_date:
            parsed_date = datetime.datetime.strptime(
                start_date, "%Y-%m-%d"
            ).date()

            start_dt = datetime.datetime.combine(
                parsed_date,
                datetime.time.min,
            )

            if start_time:
                parsed_time = datetime.time.fromisoformat(start_time)
                start_dt = datetime.datetime.combine(
                    parsed_date, parsed_time
                )

            conditions.append(FootfallEvent.timestamp >= start_dt)

        if end_date:
            parsed_date = datetime.datetime.strptime(
                end_date, "%Y-%m-%d"
            ).date()

            end_dt = datetime.datetime.combine(
                parsed_date,
                datetime.time.max,
            )

            if end_time:
                parsed_time = datetime.time.fromisoformat(end_time)
                end_dt = datetime.datetime.combine(
                    parsed_date, parsed_time
                )

            conditions.append(FootfallEvent.timestamp <= end_dt)

        # Time-only filters also work when a date is not specified.
        timestamp_minutes = (
            extract("hour", FootfallEvent.timestamp) * 60
            + extract("minute", FootfallEvent.timestamp)
        )

        if start_time and not start_date:
            parsed_time = datetime.time.fromisoformat(start_time)
            conditions.append(
                timestamp_minutes
                >= parsed_time.hour * 60 + parsed_time.minute
            )

        if end_time and not end_date:
            parsed_time = datetime.time.fromisoformat(end_time)
            conditions.append(
                timestamp_minutes
                <= parsed_time.hour * 60 + parsed_time.minute
            )

    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Dates must use YYYY-MM-DD and times must use HH:MM",
        )

    count_result = await db.execute(
        select(func.count(FootfallEvent.id)).where(*conditions)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(FootfallEvent)
        .where(*conditions)
        .order_by(
            FootfallEvent.timestamp.desc(),
            FootfallEvent.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )

    events = result.scalars().all()

    return {
        "items": [event.to_dict() for event in events],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
