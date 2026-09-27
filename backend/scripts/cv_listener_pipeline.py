"""
=============================================================================
GJ-Fashion AI Smart Showroom — Computer Vision (CV) Team Facial Embedding Listener
=============================================================================
This script connects to the GJ-Fashion AI Backend to receive newly assigned 
employee media clips (Video/Photos) uploaded from the web application.

It downloads the S3 assets, extracts facial features, and updates 
the 512-D facial embedding database for real-time camera face recognition.

API Endpoints:
    Production: http://65.2.158.148 (Port 80)
    Local:      http://localhost:8000

Note:
    Do NOT use port 8000 for remote IP 65.2.158.148 as the server reverse-proxies
    API requests on standard HTTP port 80. This script automatically handles 
    retries and candidate URL fallbacks if port 8000 times out.

Usage:
    python cv_listener_pipeline.py --once
    python cv_listener_pipeline.py --poll --interval 10 --api-url http://65.2.158.148
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
    format="%(asctime)s [%(levelname)s] [CV-Pipeline]: %(message)s"
)
logger = logging.getLogger("cv_facial_listener")

DEFAULT_API_BASE = os.getenv("API_BASE_URL", "http://65.2.158.148")
EMBEDDINGS_DIR = os.path.join(os.path.dirname(__file__), "cv_embeddings")
PROCESSED_LOG = os.path.join(os.path.dirname(__file__), "processed_clips.json")

os.makedirs(EMBEDDINGS_DIR, exist_ok=True)


def get_api_candidates(base_url: str = None) -> list:
    """Generates candidate API base URLs to handle port 80 vs port 8000 fallback gracefully."""
    if not base_url:
        base_url = DEFAULT_API_BASE
    
    base_url = base_url.rstrip("/")
    candidates = [base_url]

    if ":8000" in base_url:
        no_port = base_url.replace(":8000", "")
        if no_port not in candidates:
            candidates.append(no_port)
    elif "localhost" not in base_url and "127.0.0.1" not in base_url:
        with_port = f"{base_url}:8000"
        if with_port not in candidates:
            candidates.append(with_port)

    for fallback in ["http://65.2.158.148", "http://localhost:8000"]:
        if fallback not in candidates:
            candidates.append(fallback)

    return candidates


def load_processed_ids():
    """Load IDs of clips that have already been processed into embeddings."""
    if os.path.exists(PROCESSED_LOG):
        try:
            with open(PROCESSED_LOG, "r") as f:
                return set(json.load(f))
        except Exception as e:
            logger.warning(f"Could not read processed log: {e}")
    return set()


def save_processed_id(clip_id):
    """Mark clip ID as processed to prevent duplicate processing."""
    processed = load_processed_ids()
    processed.add(clip_id)
    with open(PROCESSED_LOG, "w") as f:
        json.dump(list(processed), f, indent=2)


def fetch_assigned_employees(api_base_url: str = None):
    """Fetch assigned employee records from backend REST API with automatic URL fallback."""
    candidates = get_api_candidates(api_base_url)

    for base in candidates:
        url = f"{base}/api/forensics/list?category=assign_employee"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CV-Pipeline-Worker/1.0"})
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    logger.info(f"Successfully connected to API: {base}")
                    return data, base
        except (urllib.error.URLError, TimeoutError, Exception) as e:
            logger.warning(f"Failed connection attempt to {url}: {e}. Retrying next candidate...")

    logger.error("All candidate API endpoints failed for fetching assigned employees.")
    return [], candidates[0]


def download_media_file(file_url, save_filename, active_api_base):
    """Download video or picture file from AWS S3 or Local Static Server."""
    if file_url.startswith("/"):
        full_url = f"{active_api_base}{file_url}"
    else:
        full_url = file_url

    dest_path = os.path.join(EMBEDDINGS_DIR, save_filename)
    logger.info(f"Downloading training media from: {full_url}")

    try:
        req = urllib.request.Request(full_url, headers={"User-Agent": "CV-Pipeline-Worker/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response, open(dest_path, "wb") as out_file:
            out_file.write(response.read())
        logger.info(f"Media successfully saved locally: {dest_path}")
        return dest_path
    except Exception as e:
        logger.error(f"Failed to download media file: {e}")
        return None


def generate_facial_embeddings(media_path, emp_id, emp_name):
    """
    Dummy Facial Embedding Engine.
    Replace/Plug-in your OpenCV / InsightFace / FaceNet / PyTorch model here.
    
    Output: 512-dimensional float32 embedding vector.
    """
    logger.info(f"Extracting facial frames and computing 512-D embeddings for {emp_name} ({emp_id})...")

    np.random.seed(hash(emp_id) % (2**32))
    dummy_vector = np.random.randn(512).astype(np.float32)
    dummy_vector /= np.linalg.norm(dummy_vector)

    return dummy_vector.tolist()


def process_employee_clip(clip, active_api_base):
    """Process a single assigned employee record."""
    clip_id = clip.get("id")
    emp_id = clip.get("emp_id") or "UNKNOWN_ID"
    emp_name = clip.get("emp_name") or clip.get("title") or "Unnamed Employee"
    role = clip.get("role", "Staff")
    shift = clip.get("shift", "Morning")
    file_url = clip.get("file_url")

    logger.info("=" * 60)
    logger.info(f"RECEIVED NEW EMPLOYEE PIPELINE PAYLOAD:")
    logger.info(f" - Employee ID : {emp_id}")
    logger.info(f" - Name        : {emp_name}")
    logger.info(f" - Role        : {role}")
    logger.info(f" - Shift       : {shift}")
    logger.info(f" - Media S3 URL: {file_url}")
    logger.info("=" * 60)

    if not file_url:
        logger.warning(f"No file_url provided for clip ID {clip_id}. Skipping.")
        return

    ext = os.path.splitext(file_url)[1]
    if not ext:
        ext = ".mp4" if "video" in str(clip.get("metadata_json")) else ".png"

    filename = f"{emp_id}_{clip_id}{ext}"
    media_local_path = download_media_file(file_url, filename, active_api_base)

    if not media_local_path:
        logger.error(f"Could not download file for {emp_name}. Will retry next cycle.")
        return

    embeddings = generate_facial_embeddings(media_local_path, emp_id, emp_name)

    output_payload = {
        "clip_id": clip_id,
        "emp_id": emp_id,
        "emp_name": emp_name,
        "role": role,
        "shift": shift,
        "media_s3_url": file_url,
        "local_media_path": media_local_path,
        "embedding_vector_dim": len(embeddings),
        "facial_embeddings": embeddings,
        "status": "EMBEDDINGS_INDEXED_SUCCESSFULLY",
        "timestamp": datetime.now().isoformat()
    }

    embedding_json_path = os.path.join(EMBEDDINGS_DIR, f"{emp_id}_embeddings.json")
    with open(embedding_json_path, "w") as f:
        json.dump(output_payload, f, indent=2)

    numpy_path = os.path.join(EMBEDDINGS_DIR, f"{emp_id}_vector.npy")
    np.save(numpy_path, np.array(embeddings, dtype=np.float32))

    logger.info(f"SUCCESS: Facial embeddings saved to {embedding_json_path}")
    logger.info(f"SUCCESS: Numpy vector array saved to {numpy_path}")
    
    save_processed_id(clip_id)


def run_pipeline(poll=False, interval=10, api_base_url=None):
    """Main listener loop."""
    logger.info("Starting Computer Vision Listener & Embedding Pipeline...")
    logger.info(f"Target API Base URL: {api_base_url or DEFAULT_API_BASE}")

    while True:
        processed_ids = load_processed_ids()
        clips, active_api_base = fetch_assigned_employees(api_base_url)

        unprocessed = [c for c in clips if c.get("id") not in processed_ids]

        if unprocessed:
            logger.info(f"Found {len(unprocessed)} new employee clip(s) to process.")
            for clip in unprocessed:
                process_employee_clip(clip, active_api_base)
        else:
            logger.info("No new employee media clips found. Pipeline up-to-date.")

        if not poll:
            break

        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GJ-Fashion CV Facial Embedding Listener")
    parser.add_argument("--poll", action="store_true", help="Run in continuous listening mode")
    parser.add_argument("--interval", type=int, default=10, help="Polling interval in seconds")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--api-url", type=str, default=None, help="API Base URL (default: http://65.2.158.148)")

    args = parser.parse_args()
    
    run_pipeline(poll=args.poll, interval=args.interval, api_base_url=args.api_url)

