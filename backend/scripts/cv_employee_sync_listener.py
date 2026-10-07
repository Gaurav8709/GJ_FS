#!/usr/bin/env python3
"""
=============================================================================
GJ-Fashion AI Smart Showroom — Computer Vision (CV) Employee Sync & Alert Listener
=============================================================================
This standalone Python script provides complete 2-way integration for the CV Team:

1. AUTOMATED EMPLOYEE ADDITION:
   Polls Backend API for new assigned employees, downloads training media from 
   AWS S3, and extracts/indexes 512-D facial embeddings.

2. AUTOMATED EMPLOYEE DELETION:
   Monitors deletion events from the Web Dashboard. If an employee (emp_id) is 
   deleted by the admin, this script automatically evicts their facial embeddings 
   from the CV vector store.

3. LIVE FACE DETECTION ALERTS:
   Includes helper function `send_detection_alert()` to trigger real-time WebSocket 
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
import time
import json
import logging
import argparse
import urllib.request
import urllib.error
import numpy as np
from datetime import datetime

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [CV-Sync-Engine]: %(message)s"
)
logger = logging.getLogger("cv_employee_sync")

DEFAULT_API_BASE = os.getenv("API_BASE_URL", "http://65.2.158.148").rstrip("/")
EMBEDDINGS_DIR = os.path.join(os.path.dirname(__file__), "cv_embeddings")
CACHE_INDEX_FILE = os.path.join(EMBEDDINGS_DIR, "active_employees_index.json")

os.makedirs(EMBEDDINGS_DIR, exist_ok=True)


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


def load_local_cache_index():
    """Load local CV employee cache index: { emp_id: { clip_id, emp_name, role, shift, s3_url, updated_at } }"""
    if os.path.exists(CACHE_INDEX_FILE):
        try:
            with open(CACHE_INDEX_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read local cache index: {e}")
    return {}


def save_local_cache_index(index_data):
    """Save active CV employee cache index to disk."""
    with open(CACHE_INDEX_FILE, "w") as f:
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


def download_media_asset(file_url, dest_filename, active_api_base):
    """Download facial training video/image from AWS S3 or server static path."""
    if file_url.startswith("/"):
        full_url = f"{active_api_base}{file_url}"
    else:
        full_url = file_url

    dest_path = os.path.join(EMBEDDINGS_DIR, dest_filename)
    logger.info(f"📥 Downloading S3 Media Asset: {full_url}")

    try:
        req = urllib.request.Request(full_url, headers={"User-Agent": "CV-Sync-Worker/1.0"})
        with urllib.request.urlopen(req, timeout=15) as response, open(dest_path, "wb") as out_file:
            out_file.write(response.read())
        logger.info(f"✅ Downloaded & Saved: {dest_path}")
        return dest_path
    except Exception as e:
        logger.error(f"❌ Failed to download asset: {e}")
        return None


def generate_512d_facial_embedding(media_path, emp_id, emp_name):
    """
    Facial Feature Extractor.
    CV Team: Replace this function body with your InsightFace / FaceNet / DeepStream model call.
    Returns: 512-dimensional float32 vector.
    """
    logger.info(f"🧠 Computing 512-D Facial Vector for {emp_name} ({emp_id}) using InsightFace/FaceNet...")
    
    # Deterministic dummy vector generator based on emp_id for demonstration
    np.random.seed(abs(hash(emp_id)) % (2**32))
    vec = np.random.randn(512).astype(np.float32)
    vec /= np.linalg.norm(vec)
    return vec.tolist()


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
    1. Detects new employees -> Downloads media -> Generates & indexes 512-D facial vectors.
    2. Detects deleted employees -> Evicts vectors & deletes local embeddings.
    """
    local_cache = load_local_cache_index()
    api_records, active_api_base = fetch_assigned_employees_from_api(api_base_url)

    # Build active map from API response
    api_active_map = {}
    for r in api_records:
        e_id = r.get("emp_id") or f"EMP-{r.get('id')}"
        api_active_map[e_id] = r

    # -------------------------------------------------------------------------
    # PART 1: PROCESS NEW / ADDED EMPLOYEES
    # -------------------------------------------------------------------------
    added_count = 0
    for emp_id, record in api_active_map.items():
        if emp_id not in local_cache:
            emp_name = record.get("emp_name") or record.get("title") or "Unnamed Employee"
            role = record.get("role", "Sales Executive")
            shift = record.get("shift", "Morning")
            file_url = record.get("file_url") or ""
            clip_id = record.get("id")

            logger.info("=" * 70)
            logger.info(f"✨ NEW EMPLOYEE ADDITION DETECTED FROM DASHBOARD:")
            logger.info(f" - Employee ID : {emp_id}")
            logger.info(f" - Name        : {emp_name}")
            logger.info(f" - Role        : {role}")
            logger.info(f" - Shift       : {shift}")
            logger.info(f" - S3 Media URL: {file_url}")
            logger.info("=" * 70)

            if file_url:
                ext = os.path.splitext(file_url)[1] or ".png"
                local_media_name = f"{emp_id}_{clip_id}{ext}"
                local_media_path = download_media_asset(file_url, local_media_name, active_api_base)

                if local_media_path:
                    # Generate 512-d facial embedding vector
                    vector = generate_512d_facial_embedding(local_media_path, emp_id, emp_name)

                    # Save embedding vector (.npy) and JSON metadata
                    vector_path = os.path.join(EMBEDDINGS_DIR, f"{emp_id}_vector.npy")
                    np.save(vector_path, np.array(vector, dtype=np.float32))

                    meta_payload = {
                        "emp_id": emp_id,
                        "emp_name": emp_name,
                        "role": role,
                        "shift": shift,
                        "s3_url": file_url,
                        "local_media": local_media_path,
                        "vector_file": vector_path,
                        "dimension": len(vector),
                        "indexed_at": datetime.now().isoformat()
                    }
                    meta_path = os.path.join(EMBEDDINGS_DIR, f"{emp_id}_meta.json")
                    with open(meta_path, "w") as f:
                        json.dump(meta_payload, f, indent=2)

                    # Update local cache index
                    local_cache[emp_id] = meta_payload
                    added_count += 1
                    logger.info(f"✅ Successfully indexed facial embeddings for {emp_name} ({emp_id})")

    # -------------------------------------------------------------------------
    # PART 2: PROCESS DELETED / REMOVED EMPLOYEES
    # -------------------------------------------------------------------------
    deleted_count = 0
    cached_emp_ids = list(local_cache.keys())
    
    for emp_id in cached_emp_ids:
        if emp_id not in api_active_map:
            logger.info("=" * 70)
            logger.info(f"🗑️ EMPLOYEE DELETION EVENT DETECTED FROM DASHBOARD:")
            logger.info(f" - Employee ID : {emp_id}")
            logger.info(f" - Action      : EVICTING FACIAL EMBEDDINGS FROM CV PIPELINE")
            logger.info("=" * 70)

            # Clean up local embedding files
            vec_file = os.path.join(EMBEDDINGS_DIR, f"{emp_id}_vector.npy")
            meta_file = os.path.join(EMBEDDINGS_DIR, f"{emp_id}_meta.json")

            if os.path.exists(vec_file):
                try: os.remove(vec_file)
                except Exception: pass

            if os.path.exists(meta_file):
                try: os.remove(meta_file)
                except Exception: pass

            # Delete from cache
            del local_cache[emp_id]
            deleted_count += 1
            logger.info(f"❌ Evicted facial embeddings for deleted employee: {emp_id}")

    # Save updated cache index if changes occurred
    if added_count > 0 or deleted_count > 0:
        save_local_cache_index(local_cache)
        logger.info(f"🔄 CV Employee Index Updated: {added_count} added, {deleted_count} deleted. Total Active: {len(local_cache)}")
    else:
        logger.debug(f"CV Employee Index in sync. Total Active Employees: {len(local_cache)}")

    return local_cache


def run_cv_listener_loop(poll=True, interval=5, api_base_url=None):
    """Continuous listening loop for CV team."""
    logger.info("Starting Computer Vision Employee Sync Listener Loop...")
    logger.info(f"Target Backend API: {api_base_url or DEFAULT_API_BASE}")
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
    parser = argparse.ArgumentParser(description="GJ-Fashion Computer Vision Employee Sync & Alert Listener")
    parser.add_argument("--poll", action="store_true", default=True, help="Run continuous sync listener loop")
    parser.add_argument("--once", action="store_true", help="Run sync once and exit")
    parser.add_argument("--interval", type=int, default=5, help="Polling interval in seconds")
    parser.add_argument("--api-url", type=str, default=None, help="Backend API Base URL")

    args = parser.parse_args()
    should_poll = not args.once

    run_cv_listener_loop(poll=should_poll, interval=args.interval, api_base_url=args.api_url)
