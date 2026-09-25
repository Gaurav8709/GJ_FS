"""
GJ-Fashion — Footfall Listener & Analytics Router
Handles real-time footfall updates (+1/-1, gender & age breakdowns) and timestamped chart data.
"""

import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models.new_features import FootfallRecord

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
    cam_id: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """
    Returns aggregated footfall statistics, timestamped history, gender & age distributions for bar graphs.
    """
    query = select(FootfallRecord).order_by(FootfallRecord.timestamp.asc())
    if cam_id:
        query = query.where(FootfallRecord.cam_id == cam_id)

    result = await db.execute(query.limit(limit))
    records = result.scalars().all()

    total_entries = sum(r.entries for r in records)
    total_exits = sum(r.exits for r in records)
    net_current = max(0, total_entries - total_exits)
    total_male = sum(r.male_count for r in records)
    total_female = sum(r.female_count for r in records)

    age_totals = {
        "0_9": sum((r.age_0_9 or 0) for r in records),
        "10_17": sum((r.age_10_17 or 0) for r in records),
        "18_25": sum((r.age_18_25 or 0) for r in records),
        "26_35": sum((r.age_26_35 or 0) for r in records),
        "36_50": sum((r.age_36_50 or 0) for r in records),
        "50_plus": sum((r.age_50_plus or 0) for r in records),
    }


    # Format timestamp series for bar graphs
    timestamps = []
    for r in records:
        ts_label = r.timestamp.strftime("%H:%M:%S") if r.timestamp else "N/A"
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
        "raw_records": [r.to_dict() for r in records[-10:]]
    }
