#!/usr/bin/env python3
"""
=============================================================================
GJ-Fashion AI Smart Showroom — Computer Vision (CV) Employee Sync & Alert Listener
=============================================================================
This standalone Python script syncs employee media clips (Videos/Photos) 
directly with the CV Team's pipeline:

1. AUTOMATED EMPLOYEE ADDITION:
   Polls Backend API for new assigned employees, downloads training video/photo 
   directly from AWS S3, and saves it named EXACTLY as `{emp_id}.ext` (e.g. EMP-105.mp4).
   Does NOT create extra .npy or .json files as requested by CV team.

2. AUTOMATED EMPLOYEE DELETION:
   Monitors deletion events from the Web Dashboard. When an employee is deleted 
   by admin, this script automatically deletes their local video/photo file ({emp_id}.ext) 
   from disk.

3. LIVE FACE DETECTION ALERTS:
   Includes helper function `send_face_detection_alert()` to trigger real-time WebSocket 
   alerts on the Web Dashboard whenever a camera detects a registered employee.

Endpoints:
   Production Server: http://65.2.158.148
   Local Dev Server:  http://localhost:8000

Usage:
   python3 cv_employee_sync_listener.py --poll --interval 5 --api-url http://65.2.158.148
   python3 cv_employee_sync_listener.py --once
=============================================================================
"""

import os
import sys
import glob
import time
import json
import logging
import argparse
import urllib.request
import urllib.error
from datetime import datetime

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [CV-Sync-Engine]: %(message)s"
)
logger = logging.getLogger("cv_employee_sync")

DEFAULT_API_BASE = os.getenv("API_BASE_URL", "http://65.2.158.148").rstrip("/")
MEDIA_DIR = os.path.join(os.path.dirname(__file__), "cv_embeddings")
INDEX_FILE = os.path.join(MEDIA_DIR, ".active_sync_index.json")

os.makedirs(MEDIA_DIR, exist_ok=True)


def get_api_candidates(base_url: str = None) -> list:
    """Returns fallback candidate API URLs for port 80 vs 8000 handling."""
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
    """Load local employee sync index tracking downloaded media files."""
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read sync index: {e}")
    return {}


def save_sync_index(index_data):
    """Save active employee sync index to disk."""
    with open(INDEX_FILE, "w") as f:
        json.dump(index_data, f, indent=2)


def fetch_assigned_employees_from_api(api_base_url: str = None):
    """Fetch all active assigned employees from REST API."""
    candidates = get_api_candidates(api_base_url)
    
    for base in candidates:
        url = f"{base}/api/forensics/list?category=assign_employee"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CV-Sync-Worker/1.0"})
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    return data, base
        except Exception as e:
            logger.debug(f"Candidate {url} failed: {e}")
            
    logger.error("Failed to connect to any Backend API candidate URL.")
    return [], candidates[0]


def download_employee_media(file_url, dest_filename, active_api_base):
    """Download video/photo asset from AWS S3 or server static path."""
    if file_url.startswith("/"):
        full_url = f"{active_api_base}{file_url}"
    else:
        full_url = file_url

    dest_path = os.path.join(MEDIA_DIR, dest_filename)
    logger.info(f"📥 Downloading S3 Media Asset: {full_url}")

    try:
        req = urllib.request.Request(full_url, headers={"User-Agent": "CV-Sync-Worker/1.0"})
        with urllib.request.urlopen(req, timeout=15) as response, open(dest_path, "wb") as out_file:
            out_file.write(response.read())
        logger.info(f"✅ Video/Photo Saved: {dest_path}")
        return dest_path
    except Exception as e:
        logger.error(f"❌ Failed to download asset: {e}")
        return None


def send_face_detection_alert(emp_id, emp_name, cam_id="cam5", confidence=0.95, snapshot_url="", api_base_url=None):
    """
    Helper function for CV Team to trigger real-time alerts on Web Dashboard.
    Call this function inside your live DeepStream / RTSP camera pipeline.
    """
    candidates = get_api_candidates(api_base_url)
    payload = {
        "emp_id": emp_id,
        "emp_name": emp_name,
        "cam_id": cam_id,
        "confidence": float(confidence),
        "snapshot_url": snapshot_url,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    }

    data_bytes = json.dumps(payload).encode("utf-8")

    for base in candidates:
        url = f"{base}/api/face-alerts/detect"
        try:
            req = urllib.request.Request(
                url, 
                data=data_bytes, 
                headers={"Content-Type": "application/json", "User-Agent": "CV-Alert-Pusher/1.0"}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    res_data = json.loads(response.read().decode())
                    logger.info(f"🚨 Broadcasted Face Detection Alert: {emp_name} ({emp_id}) on {cam_id} -> Status 200")
                    return res_data
        except Exception as e:
            logger.warning(f"Failed to push detection alert to {url}: {e}")

    logger.error("Could not send face detection alert to backend API.")
    return None


def sync_employees_with_cv_pipeline(api_base_url=None):
    """
    Core Synchronization Function:
    1. ADDITIONS: Downloads video/photo and names it EXACTLY {emp_id}.ext (e.g. EMP-105.mp4).
    2. DELETIONS: Deletes local video/photo file ({emp_id}.ext) when deleted from Web Dashboard.
    """
    sync_index = load_sync_index()
    api_records, active_api_base = fetch_assigned_employees_from_api(api_base_url)

    # Build active map from API response
    api_active_map = {}
    for r in api_records:
        e_id = r.get("emp_id") or f"EMP-{r.get('id')}"
        api_active_map[e_id] = r

    # -------------------------------------------------------------------------
    # PART 1: PROCESS NEW / ADDED EMPLOYEES (Save Media as {emp_id}.ext)
    # -------------------------------------------------------------------------
    added_count = 0
    for emp_id, record in api_active_map.items():
        if emp_id not in sync_index:
            emp_name = record.get("emp_name") or record.get("title") or "Unnamed Employee"
            role = record.get("role", "Sales Executive")
            shift = record.get("shift", "Morning")
            file_url = record.get("file_url") or ""

            logger.info("=" * 70)
            logger.info(f"✨ NEW EMPLOYEE ADDITION DETECTED FROM DASHBOARD:")
            logger.info(f" - Employee ID : {emp_id}")
            logger.info(f" - Name        : {emp_name}")
            logger.info(f" - Role        : {role}")
            logger.info(f" - Shift       : {shift}")
            logger.info(f" - S3 Media URL: {file_url}")
            logger.info("=" * 70)

            if file_url:
                # Extract original extension (.mp4, .mov, .jpg, .png, etc.)
                ext = os.path.splitext(file_url)[1]
                if not ext or len(ext) > 5:
                    ext = ".mp4" if "video" in str(record.get("metadata_json")) else ".jpg"

                # Named EXACTLY as {emp_id}.ext (e.g. EMP-105.mp4 or EMP-105.jpg)
                media_filename = f"{emp_id}{ext}"
                local_media_path = download_employee_media(file_url, media_filename, active_api_base)

                if local_media_path:
                    sync_index[emp_id] = {
                        "emp_id": emp_id,
                        "emp_name": emp_name,
                        "role": role,
                        "shift": shift,
                        "s3_url": file_url,
                        "local_file": local_media_path,
                        "filename": media_filename,
                        "synced_at": datetime.now().isoformat()
                    }
                    added_count += 1
                    logger.info(f"✅ Saved Employee Media File: {media_filename}")

    # -------------------------------------------------------------------------
    # PART 2: PROCESS DELETED EMPLOYEES (Delete local video/photo file)
    # -------------------------------------------------------------------------
    deleted_count = 0
    synced_emp_ids = list(sync_index.keys())

    for emp_id in synced_emp_ids:
        if emp_id not in api_active_map:
            logger.info("=" * 70)
            logger.info(f"🗑️ EMPLOYEE DELETION EVENT DETECTED FROM DASHBOARD:")
            logger.info(f" - Employee ID : {emp_id}")
            logger.info(f" - Action      : DELETING LOCAL VIDEO/PHOTO MEDIA FILE")
            logger.info("=" * 70)

            # 1. Delete file recorded in index
            emp_info = sync_index.get(emp_id, {})
            saved_file = emp_info.get("local_file")
            if saved_file and os.path.exists(saved_file):
                try:
                    os.remove(saved_file)
                    logger.info(f"🗑️ Removed Media File: {saved_file}")
                except Exception as e:
                    logger.error(f"Error removing file {saved_file}: {e}")

            # 2. Pattern cleanup for any files matching emp_id.* (e.g. EMP-105.mp4, EMP-105.jpg)
            matching_files = glob.glob(os.path.join(MEDIA_DIR, f"{emp_id}.*"))
            for match in matching_files:
                if os.path.exists(match):
                    try:
                        os.remove(match)
                        logger.info(f"🗑️ Pattern Removed File: {match}")
                    except Exception:
                        pass

            # 3. Evict from local index
            del sync_index[emp_id]
            deleted_count += 1
            logger.info(f"❌ Deleted local video/photo asset for Employee ID: {emp_id}")

    # Save updated sync index if changes occurred
    if added_count > 0 or deleted_count > 0:
        save_sync_index(sync_index)
        logger.info(f"🔄 CV Employee Media Directory Synced: {added_count} downloaded, {deleted_count} deleted. Total Active: {len(sync_index)}")

    return sync_index


def run_cv_listener_loop(poll=True, interval=5, api_base_url=None):
    """Continuous listening loop for CV team."""
    logger.info("Starting Computer Vision Employee Media Sync Listener Loop...")
    logger.info(f"Target Backend API: {api_base_url or DEFAULT_API_BASE}")
    logger.info(f"Media Storage Directory: {MEDIA_DIR}")
    logger.info(f"Polling Interval: {interval} seconds")

    while True:
        try:
            sync_employees_with_cv_pipeline(api_base_url)
        except Exception as e:
            logger.error(f"Error during CV employee sync: {e}")

        if not poll:
            break

        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GJ-Fashion Computer Vision Employee Media Sync & Alert Listener")
    parser.add_argument("--poll", action="store_true", default=True, help="Run continuous sync listener loop")
    parser.add_argument("--once", action="store_true", help="Run sync once and exit")
    parser.add_argument("--interval", type=int, default=5, help="Polling interval in seconds")
    parser.add_argument("--api-url", type=str, default=None, help="Backend API Base URL")

    args = parser.parse_args()
    should_poll = not args.once

    run_cv_listener_loop(poll=should_poll, interval=args.interval, api_base_url=args.api_url)
