"""
=============================================================================
GJ-Fashion AI Smart Showroom — Computer Vision (CV) Team Facial Embedding Listener
=============================================================================
This script connects to the GJ-Fashion AI Backend to receive newly assigned 
employee media clips (Video/Photos) uploaded from the web application.

It downloads the S3 assets, extracts facial features, and updates 
the 512-D facial embedding database for real-time camera face recognition.

Usage:
    python cv_listener_pipeline.py --once
    python cv_listener_pipeline.py --poll --interval 10
=============================================================================
"""

import os
import sys
import time
import json
import logging
import argparse
import urllib.request
import numpy as np
from datetime import datetime

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [CV-Pipeline]: %(message)s"
)
logger = logging.getLogger("cv_facial_listener")

# Configurations
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
EMBEDDINGS_DIR = os.path.join(os.path.dirname(__file__), "cv_embeddings")
PROCESSED_LOG = os.path.join(os.path.dirname(__file__), "processed_clips.json")

os.makedirs(EMBEDDINGS_DIR, exist_ok=True)


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


def fetch_assigned_employees():
    """Fetch assigned employee records from backend REST API."""
    url = f"{API_BASE_URL}/api/forensics/list?category=assign_employee"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CV-Pipeline-Worker/1.0"})
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                return data
    except Exception as e:
        logger.error(f"Failed to fetch assigned employee clips from API ({url}): {e}")
    return []


def download_media_file(file_url, save_filename):
    """Download video or picture file from AWS S3 or Local Static Server."""
    # Convert relative static URL to absolute URL if needed
    if file_url.startswith("/"):
        full_url = f"{API_BASE_URL}{file_url}"
    else:
        full_url = file_url

    dest_path = os.path.join(EMBEDDINGS_DIR, save_filename)
    logger.info(f"Downloading training media from: {full_url}")

    try:
        req = urllib.request.Request(full_url, headers={"User-Agent": "CV-Pipeline-Worker/1.0"})
        with urllib.request.urlopen(req) as response, open(dest_path, "wb") as out_file:
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
    
    # --------------------------------------------------------------------------
    # CV TEAM PLUG-IN HERE:
    # Example using InsightFace / FaceNet / OpenCV:
    # 
    # import cv2
    # import insightface
    # app = insightface.app.FaceAnalysis()
    # app.prepare(ctx_id=0, det_size=(640, 640))
    # img = cv2.imread(media_path)
    # faces = app.get(img)
    # embedding = faces[0].embedding # (512,)
    # --------------------------------------------------------------------------

    # Simulated 512-D normalized feature vector for demonstration:
    np.random.seed(hash(emp_id) % (2**32))
    dummy_vector = np.random.randn(512).astype(np.float32)
    dummy_vector /= np.linalg.norm(dummy_vector) # Normalize vector

    return dummy_vector.tolist()


def process_employee_clip(clip):
    """Process a single assigned employee record."""
    clip_id = clip.get("id")
    emp_id = clip.get("emp_id") or "UNKNOWN_ID"
    emp_name = clip.get("emp_name") or clip.get("title") or "Unnamed Employee"
    role = clip.get("role", "Staff")
    shift = clip.get("shift", "Morning")
    file_url = clip.get("file_url")
    listener_json = clip.get("listener_json", {})

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

    # Determine file extension
    ext = os.path.splitext(file_url)[1]
    if not ext:
        ext = ".mp4" if "video" in str(clip.get("metadata_json")) else ".png"

    filename = f"{emp_id}_{clip_id}{ext}"
    media_local_path = download_media_file(file_url, filename)

    if not media_local_path:
        logger.error(f"Could not download file for {emp_name}. Will retry next cycle.")
        return

    # Compute Embeddings
    embeddings = generate_facial_embeddings(media_local_path, emp_id, emp_name)

    # Save Output JSON & NPY files for Face Alerts / Camera Listener Pipeline
    output_payload = {
        "clip_id": clip_id,
        "emp_id": emp_id,
        "emp_name": emp_name,
        "role": role,
        "shift": shift,
        "media_s3_url": file_url,
        "local_media_path": media_local_path,
        "embedding_vector_dim": len(embeddings),
        "facial_embeddings": embeddings, # 512-D float list
        "status": "EMBEDDINGS_INDEXED_SUCCESSFULLY",
        "timestamp": datetime.now().isoformat()
    }

    # Save facial embedding vector file (.json)
    embedding_json_path = os.path.join(EMBEDDINGS_DIR, f"{emp_id}_embeddings.json")
    with open(embedding_json_path, "w") as f:
        json.dump(output_payload, f, indent=2)

    # Save raw numpy array (.npy)
    numpy_path = os.path.join(EMBEDDINGS_DIR, f"{emp_id}_vector.npy")
    np.save(numpy_path, np.array(embeddings, dtype=np.float32))

    logger.info(f"SUCCESS: Facial embeddings saved to {embedding_json_path}")
    logger.info(f"SUCCESS: Numpy vector array saved to {numpy_path}")
    
    # Mark as processed
    save_processed_id(clip_id)


def run_pipeline(poll=False, interval=10):
    """Main listener loop."""
    logger.info("Starting Computer Vision Listener & Embedding Pipeline...")
    logger.info(f"Connecting to API Base: {API_BASE_URL}")

    while True:
        processed_ids = load_processed_ids()
        clips = fetch_assigned_employees()

        unprocessed = [c for c in clips if c.get("id") not in processed_ids]

        if unprocessed:
            logger.info(f"Found {len(unprocessed)} new employee clip(s) to process.")
            for clip in unprocessed:
                process_employee_clip(clip)
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

    args = parser.parse_args()
    
    run_pipeline(poll=args.poll, interval=args.interval)
