"""
=============================================================================
GJ-Fashion AI Smart Showroom — Computer Vision (CV) Employee Detector Pusher
=============================================================================
This script provides a Python helper for the Computer Vision (CV) team to push 
real-time Employee Detection events (when a face/employee is recognized on any 
camera) to the GJ-Fashion AI backend.

API Endpoints:
    Production: POST http://65.2.158.148/api/face-alerts/detect (Port 80)
    Local:      POST http://localhost:8000/api/face-alerts/detect

Note:
    Do NOT use port 8000 for remote IP 65.2.158.148 as the server reverse-proxies
    API requests on standard HTTP port 80. This script automatically handles 
    retries and candidate URL fallbacks if port 8000 times out.

Usage in CV Pipeline:
    from cv_employee_detector_pusher import push_employee_detection

    push_employee_detection(
        emp_id="EMP-105",
        emp_name="Gaurav",
        cam_id="cam06",  # Backend automatically maps cam06 -> GF - Menswear Section
        confidence=0.97,
        snapshot_url="https://gj-snapshots.s3.ap-south-1.amazonaws.com/detections/emp_105_cam06.jpg"
    )

CLI Usage:
    python cv_employee_detector_pusher.py --emp-id EMP-105 --emp-name Gaurav --cam-id cam06 --api-url http://65.2.158.148
=============================================================================
"""

import os
import json
import logging
import argparse
import urllib.request
import urllib.error
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [CV-EmployeeDetect]: %(message)s")
logger = logging.getLogger("cv_employee_detect")

DEFAULT_API_BASE = os.getenv("API_BASE_URL", "http://65.2.158.148")


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


def push_employee_detection(
    emp_id: str,
    emp_name: str = None,
    cam_id: str = "cam1",
    confidence: float = 0.95,
    snapshot_url: str = "",
    timestamp: str = None,
    api_base_url: str = None
):
    """
    Pushes an Employee Face Detection event from CV camera recognition model to backend.

    Args:
        emp_id (str): Employee ID (e.g. "EMP-101", "EMP-105").
        emp_name (str, optional): Employee Name (e.g. "Gaurav", "Rahul Sharma").
        cam_id (str): Camera ID where face was detected (e.g. "cam06", "cam01").
                      Backend automatically maps cam_id -> Section & Floor Location!
        confidence (float): Match confidence (0.0 to 1.0, e.g. 0.96).
        snapshot_url (str): S3 URL or URL of the face/camera snapshot.
        timestamp (str, optional): ISO timestamp string. Auto-generated if omitted.
        api_base_url (str, optional): Custom API base URL (e.g. "http://65.2.158.148").
    """

    if timestamp is None:
        timestamp = datetime.now().isoformat() + "Z"

    payload = {
        "emp_id": emp_id,
        "emp_name": emp_name or "Assigned Employee",
        "cam_id": cam_id,
        "confidence": confidence,
        "snapshot_url": snapshot_url,
        "timestamp": timestamp
    }

    candidates = get_api_candidates(api_base_url)
    json_bytes = json.dumps(payload).encode("utf-8")

    for base in candidates:
        endpoint = f"{base}/api/face-alerts/detect"
        try:
            req = urllib.request.Request(
                endpoint,
                data=json_bytes,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "CV-EmployeeDetect-Worker/1.0"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    result = json.loads(resp.read().decode())
                    logger.info(f"Successfully posted detection event for {emp_name or emp_id} on {cam_id} to {endpoint}: {result.get('status')}")
                    return result
        except (urllib.error.URLError, TimeoutError, Exception) as e:
            logger.warning(f"Failed connection attempt to {endpoint}: {e}. Retrying next candidate...")

    logger.error(f"All candidate endpoints failed for employee detection ({emp_id}).")
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GJ-Fashion CV Employee Detector Pusher CLI")
    parser.add_argument("--emp-id", type=str, default="EMP-105", help="Employee ID (e.g. EMP-105)")
    parser.add_argument("--emp-name", type=str, default="Gaurav", help="Employee Name")
    parser.add_argument("--cam-id", type=str, default="cam06", help="Camera ID (e.g. cam06)")
    parser.add_argument("--confidence", type=float, default=0.98, help="Confidence (0.0 - 1.0)")
    parser.add_argument("--snapshot-url", type=str, default="https://gj-snapshots.s3.ap-south-1.amazonaws.com/forensics/assign_employee/aarav.png", help="Snapshot URL")
    parser.add_argument("--api-url", type=str, default=None, help="API Base URL (default: http://65.2.158.148)")

    args = parser.parse_args()

    logger.info(f"Executing Employee Detector Pusher CLI for '{args.emp_name}' on camera '{args.cam_id}'...")
    push_employee_detection(
        emp_id=args.emp_id,
        emp_name=args.emp_name,
        cam_id=args.cam_id,
        confidence=args.confidence,
        snapshot_url=args.snapshot_url,
        api_base_url=args.api_url
    )


