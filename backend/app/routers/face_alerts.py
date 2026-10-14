"""
GJ-Fashion — Face Alert & Employee Management Router
Handles employee registration, real-time detection alerts, snapshot upload,
and attendance record ingestion from the CV team.
"""

import datetime
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.new_features import EmployeeFace, EmployeeDetectionLog, ForensicClip
from app.services.s3_service import save_file
from app.routers.streaming import alert_manager

router = APIRouter(prefix="/api/face-alerts", tags=["Face Alerts & Employees"])


# =============================================================================
# Employee Registration
# =============================================================================

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
        emp_id=emp_id, emp_name=emp_name,
        department=department, role=role,
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
    return [e.to_dict() for e in result.scalars().all()]


# =============================================================================
# NEW — Step 1: Upload Detection Snapshot → S3 employee_detections/ folder
# =============================================================================

@router.post("/upload-snapshot")
async def upload_detection_snapshot(
    file: UploadFile = File(...),
    emp_id: str = Form(...),
    cam_id: str = Form("unknown"),
):
    """
    CV Team — Step 1: Upload a face crop/detection snapshot image to AWS S3.

    Saves to:  s3://gj-snapshots/employee_detections/{emp_id}_{cam_id}_{timestamp}.jpg
    Also saves local copy: /static/employee_detections/{emp_id}_{cam_id}_{timestamp}.jpg

    Returns snapshot_url → use it in Step 2 (/detect or /attendance).

    curl example:
        curl -X POST http://65.2.158.148/api/face-alerts/upload-snapshot \\
          -F "file=@face_crop.jpg" \\
          -F "emp_id=GG0005" \\
          -F "cam_id=cam5"
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are accepted (jpg, png, webp, etc.)")

    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{emp_id}_{cam_id}_{ts}.{ext}"

    # save_file() saves locally AND uploads to S3 bucket gj-snapshots under folder employee_detections/
    snapshot_url = await save_file(file_bytes, filename, folder="employee_detections")

    return {
        "status": "uploaded",
        "snapshot_url": snapshot_url,
        "emp_id": emp_id,
        "cam_id": cam_id,
        "filename": filename,
        "s3_path": f"s3://gj-snapshots/employee_detections/{filename}",
        "message": "Pass snapshot_url to /api/face-alerts/detect or /api/face-alerts/attendance"
    }


# =============================================================================
# NEW — Step 2a: Submit Attendance Records → RDS employee_detections table
# =============================================================================

@router.post("/attendance")
async def submit_attendance(
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    CV Team — Step 2a: Submit employee attendance data to RDS (employee_detections table).
    Accepts single record OR batch array.

    ─── Single record ────────────────────────────────────────────────
    POST /api/face-alerts/attendance
    {
        "emp_id":          "GG0005",
        "cam_id":          "cam5",
        "status":          "present",               ← present | absent
        "attendance_date": "13-10-2026",            ← DD-MM-YYYY
        "snapshot_url":    "/static/employee_detections/GG0005_cam5_xxx.jpg",
        "confidence":      0.97,
        "emp_name":        "Rajesh Suthar",         ← optional (auto-looked up)
        "location":        "Ground Floor Section",  ← optional (auto-resolved)
        "timestamp":       "2026-10-13 08:30:00"    ← optional
    }

    ─── Batch (matches CV team attendance_records/ folder structure) ──
    {
        "records": [
            { "emp_id": "GG0001", "cam_id": "cam14", "status": "absent",  "attendance_date": "13-10-2026" },
            { "emp_id": "GG0005", "cam_id": "cam5",  "status": "present", "attendance_date": "13-10-2026",
              "snapshot_url": "/static/employee_detections/GG0005_cam5_20261013_083000.jpg" }
        ]
    }
    """
    records_to_process = payload.get("records") or [payload]
    if not records_to_process:
        raise HTTPException(status_code=400, detail="No records provided.")

    saved, errors = [], []

    for rec in records_to_process:
        try:
            emp_id       = str(rec.get("emp_id", "")).strip()
            cam_id       = str(rec.get("cam_id", "unknown")).strip()
            status       = str(rec.get("status", "present")).strip().lower()
            att_date     = str(rec.get("attendance_date", "")).strip()
            snapshot_url = str(rec.get("snapshot_url", "")).strip()
            confidence   = float(rec.get("confidence", 1.0))
            emp_name     = str(rec.get("emp_name", "")).strip()

            if not emp_id:
                errors.append({"record": rec, "error": "emp_id is required"})
                continue

            if status not in ("present", "absent", "detected"):
                status = "present"

            # Auto-lookup employee name
            if not emp_name:
                ef_res = await db.execute(select(EmployeeFace).where(EmployeeFace.emp_id == emp_id))
                ef_obj = ef_res.scalar_one_or_none()
                if ef_obj:
                    emp_name = ef_obj.emp_name
                else:
                    fc_res = await db.execute(
                        select(ForensicClip).where(
                            ForensicClip.emp_id == emp_id,
                            ForensicClip.category == "assign_employee"
                        )
                    )
                    fc_obj = fc_res.scalar_one_or_none()
                    emp_name = (fc_obj.emp_name if fc_obj else None) or emp_id

            # Auto-resolve location from Camera DB
            location = str(rec.get("location", "")).strip()
            if not location and cam_id and cam_id != "unknown":
                try:
                    from app.models.camera import Camera
                    from app.models.floor import Section
                    cam_res = await db.execute(select(Camera).where(Camera.cam_id == cam_id))
                    cam_obj = cam_res.scalar_one_or_none()
                    if cam_obj:
                        if cam_obj.section_id:
                            sec_res = await db.execute(select(Section).where(Section.id == cam_obj.section_id))
                            sec_obj = sec_res.scalar_one_or_none()
                            location = f"{sec_obj.name} ({cam_obj.name or cam_id})" if sec_obj else (cam_obj.name or f"Camera {cam_id}")
                        else:
                            location = cam_obj.location or cam_obj.name or f"Camera {cam_id}"
                except Exception:
                    pass
            if not location:
                location = f"Camera {cam_id.upper()}"

            # Parse timestamp
            raw_ts = rec.get("timestamp")
            event_ts = datetime.datetime.utcnow()
            if raw_ts:
                try:
                    clean = str(raw_ts).replace("Z", "").replace("T", " ").split(".")[0].strip()
                    event_ts = datetime.datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass

            log = EmployeeDetectionLog(
                emp_id=emp_id, emp_name=emp_name,
                cam_id=cam_id, location=location,
                confidence=confidence, snapshot_url=snapshot_url,
                status=status, attendance_date=att_date,
                meta_info=rec.get("meta_info") or {},
                timestamp=event_ts
            )
            db.add(log)
            await db.flush()

            saved.append({
                "id": log.id, "emp_id": emp_id, "emp_name": emp_name,
                "cam_id": cam_id, "status": status, "attendance_date": att_date,
                "snapshot_url": snapshot_url, "location": location,
                "timestamp": event_ts.isoformat()
            })

        except Exception as e:
            errors.append({"record": rec, "error": str(e)})

    await db.commit()
    return {
        "status": "attendance_saved",
        "saved_count": len(saved),
        "error_count": len(errors),
        "saved": saved,
        "errors": errors
    }


@router.get("/attendance")
async def get_attendance(
    emp_id: Optional[str] = None,
    cam_id: Optional[str] = None,
    attendance_date: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 200,
    db: AsyncSession = Depends(get_db)
):
    """
    Query attendance records from RDS.
    Filters: emp_id, cam_id, attendance_date (DD-MM-YYYY), status (present/absent).
    """
    query = select(EmployeeDetectionLog).order_by(EmployeeDetectionLog.timestamp.desc())
    if emp_id:
        query = query.where(EmployeeDetectionLog.emp_id == emp_id)
    if cam_id:
        query = query.where(EmployeeDetectionLog.cam_id == cam_id)
    if attendance_date:
        query = query.where(EmployeeDetectionLog.attendance_date == attendance_date)
    if status:
        query = query.where(EmployeeDetectionLog.status == status)
    result = await db.execute(query.limit(limit))
    return [r.to_dict() for r in result.scalars().all()]


# =============================================================================
# EXISTING — Step 2b: Real-time Face Detection Alert (updated with snapshot_url)
# =============================================================================

@router.post("/detect")
async def trigger_face_detection_alert(
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    CV Team — Step 2b: Trigger real-time detection alert + log to RDS.
    Payload: { emp_id, emp_name, cam_id, location, confidence, snapshot_url, timestamp, status }

    Option B workflow:
      Step 1 → POST /upload-snapshot  (get snapshot_url)
      Step 2 → POST /detect           (pass snapshot_url here)
    """
    emp_id       = payload.get("emp_id")
    emp_name     = payload.get("emp_name", "Unknown Employee")
    cam_id       = payload.get("cam_id", "cam1")
    confidence   = float(payload.get("confidence", 0.95))
    snapshot_url = payload.get("snapshot_url", "")
    status       = payload.get("status", "detected")

    # Auto-resolve location
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
                location = f"{sec_obj.name} ({cam_obj.name or cam_id.upper()})" if sec_obj else (cam_obj.location or cam_obj.name or f"Camera {cam_id.upper()}")
            else:
                location = cam_obj.location or cam_obj.name or f"Camera {cam_id.upper()}"
    if not location:
        location = f"Camera {cam_id.upper()}"

    # Parse timestamp
    raw_ts = payload.get("timestamp")
    event_timestamp = datetime.datetime.utcnow()
    if raw_ts:
        try:
            clean_ts = str(raw_ts).replace("Z", "").replace("T", " ")
            if "." in clean_ts:
                clean_ts = clean_ts.split(".")[0]
            event_timestamp = datetime.datetime.strptime(clean_ts.strip(), "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    # Auto-lookup employee name
    if emp_id:
        res = await db.execute(select(EmployeeFace).where(EmployeeFace.emp_id == emp_id))
        emp = res.scalar_one_or_none()
        if emp:
            emp_name = emp.emp_name

    detection_log = EmployeeDetectionLog(
        emp_id=emp_id or "EMP-UNKNOWN",
        emp_name=emp_name, cam_id=cam_id, location=location,
        confidence=confidence, snapshot_url=snapshot_url,
        status=status, timestamp=event_timestamp
    )
    db.add(detection_log)
    await db.commit()
    await db.refresh(detection_log)

    await alert_manager.broadcast({
        "id": detection_log.id, "type": "face_alert",
        "cam_id": cam_id, "location": location,
        "emp_id": emp_id, "emp_name": emp_name,
        "message": f"Employee {emp_name} ({emp_id or 'N/A'}) detected at {location}",
        "confidence": confidence, "snapshot_url": snapshot_url,
        "status": status, "timestamp": event_timestamp.isoformat(),
        "acknowledged": False
    })

    return {"status": "detection_logged_and_broadcasted", "detection": detection_log.to_dict()}


@router.get("/detections")
async def get_employee_detections(
    emp_id: Optional[str] = None,
    cam_id: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """Returns employee detection logs filtered by emp_id or cam_id."""
    query = select(EmployeeDetectionLog).order_by(EmployeeDetectionLog.timestamp.desc())
    if emp_id:
        query = query.where(EmployeeDetectionLog.emp_id == emp_id)
    if cam_id:
        query = query.where(EmployeeDetectionLog.cam_id == cam_id)
    result = await db.execute(query.limit(limit))
    return [d.to_dict() for d in result.scalars().all()]


@router.get("/monitoring-summary")
async def get_monitoring_summary(db: AsyncSession = Depends(get_db)):
    """
    Returns summary of all assigned employees with detections, attendance status,
    recent snapshots, and last seen info.
    """
    fc_res = await db.execute(select(ForensicClip).where(ForensicClip.category == "assign_employee"))
    clips = fc_res.scalars().all()

    ef_res = await db.execute(select(EmployeeFace))
    faces = ef_res.scalars().all()

    emp_dict = {}
    for f in faces:
        emp_dict[f.emp_id] = {
            "emp_id": f.emp_id, "emp_name": f.emp_name,
            "role": f.role or "Staff", "department": f.department or "Sales",
            "shift": "Morning", "face_url": f.face_url or ""
        }
    for c in clips:
        e_id = c.emp_id or f"EMP-{c.id}"
        if e_id not in emp_dict:
            emp_dict[e_id] = {
                "emp_id": e_id, "emp_name": c.emp_name or c.title,
                "role": c.role or "Sales Executive", "department": "Sales",
                "shift": c.shift or "Morning", "face_url": c.file_url or ""
            }

    det_res = await db.execute(select(EmployeeDetectionLog).order_by(EmployeeDetectionLog.timestamp.desc()))
    all_detections = det_res.scalars().all()

    det_map = {}
    for d in all_detections:
        det_map.setdefault(d.emp_id, []).append(d.to_dict())

    today_str = datetime.datetime.utcnow().strftime("%d-%m-%Y")
    summary_list = []

    for emp_id, emp_info in emp_dict.items():
        user_dets = det_map.get(emp_id, [])
        unique_cams = list(set(d["cam_id"] for d in user_dets))
        last_det = user_dets[0] if user_dets else None

        # Attendance status from today's records
        today_att = [d for d in user_dets if d.get("attendance_date") == today_str]
        att_status = today_att[0]["status"] if today_att else ("detected" if user_dets else "absent")

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
            "attendance_status": att_status,
            "recent_snapshots": [d["snapshot_url"] for d in user_dets if d.get("snapshot_url")][:5],
            "detections": user_dets[:50]
        })

    return summary_list
