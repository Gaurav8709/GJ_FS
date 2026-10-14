#!/usr/bin/env python3
"""
=============================================================================
GJ-Fashion AI Smart Showroom — CV Employee Sync, Snapshot Upload & Attendance
=============================================================================
This script does FOUR things for the CV Team:

1. EMPLOYEE MEDIA SYNC (Automated):
   Polls Backend API for new assigned employees → downloads their
   training video/photo → saves as {emp_id}.ext  (e.g. GG0005.mp4)

2. EMPLOYEE DELETION SYNC (Automated):
   When employee is deleted from Dashboard → deletes local file.

3. SNAPSHOT UPLOAD  ← NEW (Option B Step 1):
   upload_snapshot(image_path, emp_id, cam_id)
   Uploads face crop image to AWS S3 (employee_detections/ folder)
   Returns snapshot_url to use in Step 2.

4. ATTENDANCE REPORTING  ← NEW (Option B Step 2):
   send_attendance(emp_id, cam_id, status, snapshot_url, date)
   Sends attendance record (present/absent) to RDS via API.
   Also supports batch: send_attendance_batch(records_list)

5. REAL-TIME DETECTION ALERT (existing):
   send_face_detection_alert(emp_id, emp_name, cam_id, confidence, snapshot_url)
   Triggers real-time WebSocket alert on Dashboard.

=============================================================================
API Endpoints:
   Production:  http://65.2.158.148
   Local Dev:   http://localhost:8000

Usage:
   # Run continuous employee sync
   python3 cv_employee_sync_listener.py --poll --interval 5 --api-url http://65.2.158.148

   # Run once
   python3 cv_employee_sync_listener.py --once

   # Test snapshot upload + attendance
   python3 cv_employee_sync_listener.py --test-attendance --api-url http://65.2.158.148
=============================================================================
"""

import os
import sys
import glob
import time
import json
import logging
import argparse
import mimetypes
import urllib.request
import urllib.error
from datetime import datetime

# ── Setup Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [CV-Sync]: %(message)s"
)
logger = logging.getLogger("cv_employee_sync")

DEFAULT_API_BASE = os.getenv("API_BASE_URL", "http://65.2.158.148").rstrip("/")
MEDIA_DIR  = os.path.join(os.path.dirname(__file__), "cv_embeddings")
INDEX_FILE = os.path.join(MEDIA_DIR, ".active_sync_index.json")

os.makedirs(MEDIA_DIR, exist_ok=True)


# ==============================================================================
# UTILITY — API URL resolution with fallbacks
# ==============================================================================

def get_api_candidates(base_url: str = None) -> list:
    """Returns fallback candidate API URLs (port 80 vs 8000 handling)."""
    if not base_url:
        base_url = DEFAULT_API_BASE
    base_url = base_url.rstrip("/")
    candidates = [base_url]
    if ":8000" in base_url:
        candidates.append(base_url.replace(":8000", ""))
    elif "localhost" not in base_url and "127.0.0.1" not in base_url:
        candidates.append(f"{base_url}:8000")
    for fallback in ["http://65.2.158.148", "http://localhost:8000"]:
        if fallback not in candidates:
            candidates.append(fallback)
    return candidates


def load_sync_index():
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read sync index: {e}")
    return {}


def save_sync_index(index_data):
    with open(INDEX_FILE, "w") as f:
        json.dump(index_data, f, indent=2)


# ==============================================================================
# FUNCTION 1 — SNAPSHOT UPLOAD  (Option B — Step 1)
# ==============================================================================

def upload_snapshot(image_path: str, emp_id: str, cam_id: str = "unknown", api_base_url: str = None) -> str:
    """
    CV Team — Upload a face detection snapshot image to AWS S3.

    Saves to: s3://gj-snapshots/employee_detections/{emp_id}_{cam_id}_{timestamp}.jpg
    Returns:  snapshot_url  (pass this to send_attendance() or send_face_detection_alert())

    Args:
        image_path   : Path to the face crop image file (jpg/png)
        emp_id       : Employee ID  (e.g. "GG0005" or "EMP-105")
        cam_id       : Camera ID    (e.g. "cam5")
        api_base_url : Backend API URL (default: http://65.2.158.148)

    Returns:
        str: snapshot_url like "/static/employee_detections/GG0005_cam5_20261013_083000.jpg"
             Returns "" on failure.

    Example:
        url = upload_snapshot("face_crops/GG0005_frame42.jpg", "GG0005", "cam5")
        send_attendance("GG0005", "cam5", "present", snapshot_url=url)
    """
    if not os.path.exists(image_path):
        logger.error(f"❌ Image file not found: {image_path}")
        return ""

    candidates = get_api_candidates(api_base_url)
    filename   = os.path.basename(image_path)
    mime_type, _ = mimetypes.guess_type(image_path)
    if not mime_type:
        mime_type = "image/jpeg"

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    # Build multipart/form-data body
    boundary = "----GJFashionCVBoundary7MA4YWxkTrZu0gW"
    body_parts = []

    for field_name, field_value in [("emp_id", emp_id), ("cam_id", cam_id)]:
        body_parts.append(
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"{field_name}\"\r\n\r\n"
            f"{field_value}\r\n"
        )
    body_parts.append(
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        f"Content-Type: {mime_type}\r\n\r\n"
    )
    body_start = "".join(body_parts).encode("utf-8")
    body_end   = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body_bytes = body_start + image_bytes + body_end

    for base in candidates:
        url = f"{base}/api/face-alerts/upload-snapshot"
        try:
            req = urllib.request.Request(
                url, data=body_bytes,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Content-Length": str(len(body_bytes)),
                    "User-Agent": "CV-Snapshot-Uploader/2.0"
                }
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                if response.status == 200:
                    res = json.loads(response.read().decode())
                    snapshot_url = res.get("snapshot_url", "")
                    logger.info(f"📸 Snapshot uploaded: {snapshot_url}")
                    return snapshot_url
        except Exception as e:
            logger.debug(f"Upload attempt failed at {url}: {e}")

    logger.error(f"❌ Failed to upload snapshot: {image_path}")
    return ""


# ==============================================================================
# FUNCTION 2 — SEND ATTENDANCE RECORD  (Option B — Step 2)
# ==============================================================================

def send_attendance(
    emp_id: str,
    cam_id: str,
    status: str = "present",
    snapshot_url: str = "",
    attendance_date: str = None,
    confidence: float = 1.0,
    emp_name: str = "",
    location: str = "",
    timestamp: str = None,
    api_base_url: str = None
) -> dict:
    """
    CV Team — Send a single employee attendance record to RDS (employee_detections table).

    Args:
        emp_id          : Employee ID  (e.g. "GG0005")
        cam_id          : Camera ID    (e.g. "cam5")
        status          : "present" or "absent"
        snapshot_url    : URL from upload_snapshot() — shown on frontend
        attendance_date : Date string "DD-MM-YYYY" (defaults to today)
        confidence      : Face recognition confidence (0.0–1.0)
        emp_name        : Employee name (optional — auto-looked up from DB)
        location        : Location string (optional — auto-resolved from camera DB)
        timestamp       : "YYYY-MM-DD HH:MM:SS" (optional — defaults to now)
        api_base_url    : Backend API URL

    Returns:
        dict: API response or {} on failure

    Example:
        # After uploading snapshot:
        url = upload_snapshot("face.jpg", "GG0005", "cam5")
        send_attendance("GG0005", "cam5", "present", snapshot_url=url, confidence=0.97)
    """
    if attendance_date is None:
        attendance_date = datetime.now().strftime("%d-%m-%Y")
    if timestamp is None:
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    if status not in ("present", "absent", "detected"):
        status = "present"

    candidates = get_api_candidates(api_base_url)
    payload = {
        "emp_id": emp_id,
        "cam_id": cam_id,
        "status": status,
        "attendance_date": attendance_date,
        "snapshot_url": snapshot_url,
        "confidence": float(confidence),
        "timestamp": timestamp,
    }
    if emp_name:
        payload["emp_name"] = emp_name
    if location:
        payload["location"] = location

    data_bytes = json.dumps(payload).encode("utf-8")

    for base in candidates:
        url = f"{base}/api/face-alerts/attendance"
        try:
            req = urllib.request.Request(
                url, data=data_bytes,
                headers={"Content-Type": "application/json", "User-Agent": "CV-Attendance-Pusher/2.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    res = json.loads(response.read().decode())
                    logger.info(f"✅ Attendance sent: {emp_id} | {status} | {cam_id} | {attendance_date}")
                    return res
        except Exception as e:
            logger.debug(f"Attendance push failed at {url}: {e}")

    logger.error(f"❌ Failed to send attendance for {emp_id}")
    return {}


def send_attendance_batch(records: list, api_base_url: str = None) -> dict:
    """
    CV Team — Send multiple attendance records in one API call (batch mode).

    Matches the attendance_records/ folder structure from the CV pipeline:
        attendance_records/DD-MM-YYYY/cam_id/present|absent/{emp_id}.txt

    Args:
        records : List of dicts, each with keys:
                  emp_id, cam_id, status, attendance_date, snapshot_url (optional), confidence (optional)
        api_base_url : Backend API URL

    Returns:
        dict: { saved_count, error_count, saved, errors }

    Example:
        records = [
            { "emp_id": "GG0001", "cam_id": "cam14", "status": "absent",  "attendance_date": "13-10-2026" },
            { "emp_id": "GG0005", "cam_id": "cam5",  "status": "present", "attendance_date": "13-10-2026",
              "snapshot_url": "/static/employee_detections/GG0005_cam5_xxx.jpg" },
        ]
        result = send_attendance_batch(records)
        print(f"Saved: {result['saved_count']}, Errors: {result['error_count']}")
    """
    if not records:
        logger.warning("send_attendance_batch: No records provided.")
        return {}

    candidates = get_api_candidates(api_base_url)
    payload = {"records": records}
    data_bytes = json.dumps(payload).encode("utf-8")

    for base in candidates:
        url = f"{base}/api/face-alerts/attendance"
        try:
            req = urllib.request.Request(
                url, data=data_bytes,
                headers={"Content-Type": "application/json", "User-Agent": "CV-Attendance-Pusher/2.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                if response.status == 200:
                    res = json.loads(response.read().decode())
                    logger.info(
                        f"✅ Batch attendance saved: {res.get('saved_count', '?')} records, "
                        f"{res.get('error_count', 0)} errors"
                    )
                    return res
        except Exception as e:
            logger.debug(f"Batch attendance failed at {url}: {e}")

    logger.error("❌ Failed to send batch attendance to backend.")
    return {}


# ==============================================================================
# FUNCTION 3 — REAL-TIME FACE DETECTION ALERT  (existing — updated)
# ==============================================================================

def send_face_detection_alert(
    emp_id: str,
    emp_name: str,
    cam_id: str = "cam5",
    confidence: float = 0.95,
    snapshot_url: str = "",
    api_base_url: str = None
) -> dict:
    """
    CV Team — Trigger a real-time face detection alert on the Dashboard (WebSocket broadcast).

    Option B Recommended Workflow:
        Step 1: url = upload_snapshot("face.jpg", emp_id, cam_id)    ← upload image → S3
        Step 2: send_face_detection_alert(emp_id, emp_name, cam_id,   ← alert + save to RDS
                                          confidence, snapshot_url=url)

    Args:
        emp_id       : Employee ID
        emp_name     : Employee name
        cam_id       : Camera ID
        confidence   : Face recognition confidence
        snapshot_url : URL from upload_snapshot() — shown on frontend
        api_base_url : Backend API URL

    Returns:
        dict: API response or {} on failure
    """
    candidates = get_api_candidates(api_base_url)
    payload = {
        "emp_id": emp_id,
        "emp_name": emp_name,
        "cam_id": cam_id,
        "confidence": float(confidence),
        "snapshot_url": snapshot_url,
        "status": "detected",
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    }
    data_bytes = json.dumps(payload).encode("utf-8")

    for base in candidates:
        url = f"{base}/api/face-alerts/detect"
        try:
            req = urllib.request.Request(
                url, data=data_bytes,
                headers={"Content-Type": "application/json", "User-Agent": "CV-Alert-Pusher/2.0"}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    res = json.loads(response.read().decode())
                    logger.info(f"🚨 Detection alert sent: {emp_name} ({emp_id}) on {cam_id}")
                    return res
        except Exception as e:
            logger.debug(f"Alert push failed at {url}: {e}")

    logger.error(f"❌ Failed to send detection alert for {emp_id}")
    return {}


# ==============================================================================
# FUNCTION 4 — EMPLOYEE MEDIA SYNC  (existing — unchanged)
# ==============================================================================

def fetch_assigned_employees_from_api(api_base_url: str = None):
    """Fetch all active assigned employees from REST API."""
    candidates = get_api_candidates(api_base_url)
    for base in candidates:
        url = f"{base}/api/forensics/list?category=assign_employee"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CV-Sync-Worker/2.0"})
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    return json.loads(response.read().decode()), base
        except Exception as e:
            logger.debug(f"Candidate {url} failed: {e}")
    logger.error("Failed to connect to any Backend API candidate URL.")
    return [], candidates[0]


def download_employee_media(file_url, dest_filename, active_api_base):
    """Download employee video/photo from S3 or server."""
    if file_url.startswith("/"):
        full_url = f"{active_api_base}{file_url}"
    else:
        full_url = file_url

    dest_path = os.path.join(MEDIA_DIR, dest_filename)
    logger.info(f"📥 Downloading Media: {full_url}")
    try:
        req = urllib.request.Request(full_url, headers={"User-Agent": "CV-Sync-Worker/2.0"})
        with urllib.request.urlopen(req, timeout=15) as response, open(dest_path, "wb") as f:
            f.write(response.read())
        logger.info(f"✅ Saved: {dest_path}")
        return dest_path
    except Exception as e:
        logger.error(f"❌ Download failed: {e}")
        return None


def sync_employees_with_cv_pipeline(api_base_url=None):
    """Sync employee media files: download new, delete removed."""
    sync_index = load_sync_index()
    api_records, active_api_base = fetch_assigned_employees_from_api(api_base_url)

    api_active_map = {}
    for r in api_records:
        e_id = r.get("emp_id") or f"EMP-{r.get('id')}"
        api_active_map[e_id] = r

    # ADDITIONS
    added_count = 0
    for emp_id, record in api_active_map.items():
        if emp_id not in sync_index:
            emp_name = record.get("emp_name") or record.get("title") or "Unnamed"
            file_url = record.get("file_url") or ""
            logger.info(f"✨ New employee: {emp_id} ({emp_name})")
            if file_url:
                ext = os.path.splitext(file_url)[1] or ".mp4"
                media_filename = f"{emp_id}{ext}"
                local_path = download_employee_media(file_url, media_filename, active_api_base)
                if local_path:
                    sync_index[emp_id] = {
                        "emp_id": emp_id, "emp_name": emp_name,
                        "local_file": local_path, "filename": media_filename,
                        "synced_at": datetime.now().isoformat()
                    }
                    added_count += 1

    # DELETIONS
    deleted_count = 0
    for emp_id in list(sync_index.keys()):
        if emp_id not in api_active_map:
            logger.info(f"🗑️ Removing employee: {emp_id}")
            saved_file = sync_index[emp_id].get("local_file")
            if saved_file and os.path.exists(saved_file):
                os.remove(saved_file)
            for f in glob.glob(os.path.join(MEDIA_DIR, f"{emp_id}.*")):
                if os.path.exists(f):
                    os.remove(f)
            del sync_index[emp_id]
            deleted_count += 1

    if added_count > 0 or deleted_count > 0:
        save_sync_index(sync_index)
        logger.info(f"🔄 Sync complete: {added_count} added, {deleted_count} deleted")

    return sync_index


# ==============================================================================
# MAIN — CLI entry point
# ==============================================================================

def run_cv_listener_loop(poll=True, interval=5, api_base_url=None):
    """Continuous sync loop."""
    logger.info("=" * 60)
    logger.info("GJ-Fashion CV Employee Sync Listener started")
    logger.info(f"Backend API : {api_base_url or DEFAULT_API_BASE}")
    logger.info(f"Media Dir  : {MEDIA_DIR}")
    logger.info(f"Poll every : {interval}s")
    logger.info("=" * 60)

    while True:
        try:
            sync_employees_with_cv_pipeline(api_base_url)
        except Exception as e:
            logger.error(f"Sync error: {e}")
        if not poll:
            break
        time.sleep(interval)


def run_test_attendance(api_base_url=None):
    """Quick test — upload a dummy snapshot + send attendance record."""
    import tempfile
    from PIL import Image
    import io

    logger.info("=" * 60)
    logger.info("TEST: Snapshot Upload + Attendance Submission")
    logger.info("=" * 60)

    # Create a small test image
    img = Image.new("RGB", (112, 112), color=(100, 149, 237))
    tmp_path = os.path.join(tempfile.gettempdir(), "test_face_GG0005.jpg")
    img.save(tmp_path, "JPEG")
    logger.info(f"Created test image: {tmp_path}")

    # Step 1: Upload snapshot
    url = upload_snapshot(tmp_path, "GG0005", "cam5", api_base_url=api_base_url)
    logger.info(f"Step 1 result — snapshot_url: {url}")

    # Step 2: Send attendance
    result = send_attendance(
        emp_id="GG0005", cam_id="cam5", status="present",
        snapshot_url=url, confidence=0.97, api_base_url=api_base_url
    )
    logger.info(f"Step 2 result — attendance: {result}")
    os.remove(tmp_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GJ-Fashion CV Employee Sync Listener")
    parser.add_argument("--poll",             action="store_true", default=True)
    parser.add_argument("--once",             action="store_true", help="Run sync once and exit")
    parser.add_argument("--interval",         type=int, default=5, help="Polling interval (seconds)")
    parser.add_argument("--api-url",          type=str, default=None, help="Backend API Base URL")
    parser.add_argument("--test-attendance",  action="store_true", help="Test snapshot upload + attendance")

    args = parser.parse_args()

    if args.test_attendance:
        run_test_attendance(api_base_url=args.api_url)
    else:
        should_poll = not args.once
        run_cv_listener_loop(poll=should_poll, interval=args.interval, api_base_url=args.api_url)
