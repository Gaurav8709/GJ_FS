"""
GJ-Fashion — Face Alert & Employee Management Router
Pre-registers employee database (Face, ID, metadata) and handles real-time detection alert triggers.
"""

import json
import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.new_features import EmployeeFace, EmployeeDetectionLog, ForensicClip
from app.services.s3_service import save_file
from app.routers.streaming import alert_manager

router = APIRouter(prefix="/api/face-alerts", tags=["Face Alerts & Employees"])


@router.post("/employees")
async def register_employee(
    emp_id: str = Form(...),
    emp_name: str = Form(...),
    department: str = Form("Sales"),
    role: str = Form("Staff"),
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db)
):
    """Register or update an employee with face photo and metadata in DB."""
    face_url = None
    if file:
        file_bytes = await file.read()
        face_url = await save_file(file_bytes, f"{emp_id}_{file.filename}", folder="employees")

    # Check if employee already exists
    res = await db.execute(select(EmployeeFace).where(EmployeeFace.emp_id == emp_id))
    existing = res.scalar_one_or_none()

    if existing:
        existing.emp_name = emp_name
        existing.department = department
        existing.role = role
        if face_url:
            existing.face_url = face_url
        await db.commit()
        await db.refresh(existing)
        return existing.to_dict()

    employee = EmployeeFace(
        emp_id=emp_id,
        emp_name=emp_name,
        department=department,
        role=role,
        face_url=face_url or ""
    )

    db.add(employee)
    await db.commit()
    await db.refresh(employee)
    return employee.to_dict()


@router.get("/employees")
async def list_employees(db: AsyncSession = Depends(get_db)):
    """List registered employees."""
    result = await db.execute(select(EmployeeFace).order_by(EmployeeFace.emp_name.asc()))
    employees = result.scalars().all()
    return [e.to_dict() for e in employees]


@router.post("/detect")
async def trigger_face_detection_alert(
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    API endpoint provided for CV team / face recognition model to trigger detection alerts.
    Payload: { emp_id, emp_name, cam_id, location, confidence, snapshot_url, timestamp }
    Saves detection log to RDS database and broadcasts real-time WebSocket alert.
    """
    emp_id = payload.get("emp_id")
    emp_name = payload.get("emp_name", "Unknown Employee")
    cam_id = payload.get("cam_id", "cam1")
    confidence = float(payload.get("confidence", 0.95))
    snapshot_url = payload.get("snapshot_url", "")

    # Auto-resolve location from Camera & Section DB tables if location not provided
    location = payload.get("location")
    if not location and cam_id:
        from app.models.camera import Camera
        from app.models.floor import Section

        cam_res = await db.execute(select(Camera).where(Camera.cam_id == cam_id))
        cam_obj = cam_res.scalar_one_or_none()
        if cam_obj:
            if cam_obj.section_id:
                sec_res = await db.execute(select(Section).where(Section.id == cam_obj.section_id))
                sec_obj = sec_res.scalar_one_or_none()
                if sec_obj:
                    location = f"{sec_obj.name} ({cam_obj.name or cam_id.upper()})"
                else:
                    location = cam_obj.location or cam_obj.name or f"Camera {cam_id.upper()}"
            else:
                location = cam_obj.location or cam_obj.name or f"Camera {cam_id.upper()}"

    if not location:
        location = f"Camera {cam_id.upper()}"

    # Parse custom timestamp if sent by CV team, else default to current server time
    raw_ts = payload.get("timestamp")
    event_timestamp = datetime.datetime.utcnow()
    if raw_ts:
        try:
            clean_ts = str(raw_ts).replace("Z", "").replace("T", " ")
            if "." in clean_ts:
                clean_ts = clean_ts.split(".")[0]
            event_timestamp = datetime.datetime.strptime(clean_ts.strip(), "%Y-%m-%d %H:%M:%S")
        except Exception:
            event_timestamp = datetime.datetime.utcnow()

    # Look up employee info if emp_id passed
    if emp_id:
        res = await db.execute(select(EmployeeFace).where(EmployeeFace.emp_id == emp_id))
        emp = res.scalar_one_or_none()
        if emp:
            emp_name = emp.emp_name


    # 1. Save Detection Log to RDS database
    detection_log = EmployeeDetectionLog(
        emp_id=emp_id or "EMP-UNKNOWN",
        emp_name=emp_name,
        cam_id=cam_id,
        location=location,
        confidence=confidence,
        snapshot_url=snapshot_url,
        timestamp=event_timestamp
    )
    db.add(detection_log)
    await db.commit()
    await db.refresh(detection_log)

    # 2. Broadcast real-time WebSocket alert
    alert_message = f"Employee {emp_name} ({emp_id or 'N/A'}) detected at {location}"
    alert_event = {
        "id": detection_log.id,
        "type": "face_alert",
        "cam_id": cam_id,
        "location": location,
        "emp_id": emp_id,
        "emp_name": emp_name,
        "message": alert_message,
        "confidence": confidence,
        "snapshot_url": snapshot_url,
        "timestamp": event_timestamp.isoformat(),
        "acknowledged": False
    }

    await alert_manager.broadcast(alert_event)

    return {"status": "detection_logged_and_broadcasted", "detection": detection_log.to_dict()}


@router.get("/detections")
async def get_employee_detections(
    emp_id: Optional[str] = None,
    cam_id: Optional[str] = None,
    date: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """
    Returns list of employee detections filtered by employee ID, camera, or date.
    """
    query = select(EmployeeDetectionLog).order_by(EmployeeDetectionLog.timestamp.desc())

    if emp_id:
        query = query.where(EmployeeDetectionLog.emp_id == emp_id)
    if cam_id:
        query = query.where(EmployeeDetectionLog.cam_id == cam_id)

    result = await db.execute(query.limit(limit))
    detections = result.scalars().all()
    return [d.to_dict() for d in detections]


@router.get("/monitoring-summary")
async def get_monitoring_summary(
    db: AsyncSession = Depends(get_db)
):
    """
    Returns summary of all assigned employees with detection counts, unique cameras detected,
    last seen camera location, and timestamp history.
    """
    # Fetch assigned employees from forensic_clips & employee_faces
    fc_res = await db.execute(select(ForensicClip).where(ForensicClip.category == "assign_employee"))
    clips = fc_res.scalars().all()

    # Also fetch registered employee faces
    ef_res = await db.execute(select(EmployeeFace))
    faces = ef_res.scalars().all()

    # Map employee master dictionary
    emp_dict = {}

    for f in faces:
        emp_dict[f.emp_id] = {
            "emp_id": f.emp_id,
            "emp_name": f.emp_name,
            "role": f.role or "Staff",
            "department": f.department or "Sales",
            "shift": "Morning",
            "face_url": f.face_url or ""
        }

    for c in clips:
        e_id = c.emp_id or f"EMP-{c.id}"
        if e_id not in emp_dict:
            emp_dict[e_id] = {
                "emp_id": e_id,
                "emp_name": c.emp_name or c.title,
                "role": c.role or "Sales Executive",
                "department": "Sales",
                "shift": c.shift or "Morning",
                "face_url": c.file_url or ""
            }

    # Fetch all detection logs
    det_res = await db.execute(select(EmployeeDetectionLog).order_by(EmployeeDetectionLog.timestamp.desc()))
    all_detections = det_res.scalars().all()

    # Group detections by emp_id
    det_map = {}
    for d in all_detections:
        if d.emp_id not in det_map:
            det_map[d.emp_id] = []
        det_map[d.emp_id].append(d.to_dict())

    # Build monitoring response for each employee
    summary_list = []
    for emp_id, emp_info in emp_dict.items():
        user_dets = det_map.get(emp_id, [])
        unique_cams = list(set(d["cam_id"] for d in user_dets))
        last_det = user_dets[0] if user_dets else None

        summary_list.append({
            "emp_id": emp_id,
            "emp_name": emp_info["emp_name"],
            "role": emp_info["role"],
            "department": emp_info["department"],
            "shift": emp_info["shift"],
            "face_url": emp_info["face_url"],
            "total_detections": len(user_dets),
            "unique_cameras_count": len(unique_cams),
            "detected_cameras": unique_cams,
            "last_seen_camera": last_det["cam_id"] if last_det else None,
            "last_seen_location": last_det["location"] if last_det else None,
            "last_seen_timestamp": last_det["timestamp"] if last_det else None,
            "recent_snapshots": [d["snapshot_url"] for d in user_dets if d.get("snapshot_url")][:5],
            "detections": user_dets[:50]
        })

    return summary_list

