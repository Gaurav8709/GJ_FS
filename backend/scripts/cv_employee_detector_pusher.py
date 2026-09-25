"""
=============================================================================
GJ-Fashion AI Smart Showroom — Computer Vision (CV) Employee Detector Pusher
=============================================================================
This script provides a Python helper for the Computer Vision (CV) team to push 
real-time Employee Detection events (when a face/employee is recognized on any 
camera) to the GJ-Fashion AI backend.

API Endpoint:
    POST http://localhost:8000/api/face-alerts/detect

Usage in CV Pipeline:
    from cv_employee_detector_pusher import push_employee_detection

    push_employee_detection(
        emp_id="EMP-105",
        emp_name="Gaurav",
        cam_id="cam06",  # Backend automatically maps cam06 -> GF - Menswear Section
        confidence=0.97,
        snapshot_url="https://gj-snapshots.s3.ap-south-1.amazonaws.com/detections/emp_105_cam06.jpg"
    )
=============================================================================
"""

import os
import json
import logging
import urllib.request
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [CV-EmployeeDetect]: %(message)s")
logger = logging.getLogger("cv_employee_detect")

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
DETECTION_ENDPOINT = f"{API_BASE_URL}/api/face-alerts/detect"


def push_employee_detection(
    emp_id: str,
    emp_name: str = None,
    cam_id: str = "cam1",
    confidence: float = 0.95,
    snapshot_url: str = "",
    timestamp: str = None
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

    try:
        json_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            DETECTION_ENDPOINT,
            data=json_bytes,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "CV-EmployeeDetect-Worker/1.0"
            },
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            if resp.status == 200:
                result = json.loads(resp.read().decode())
                logger.info(f"Successfully posted detection event for {emp_name or emp_id} on {cam_id}: {result.get('status')}")
                return result
    except Exception as e:
        logger.error(f"Failed to push detection event to {DETECTION_ENDPOINT}: {e}")
        return None


if __name__ == "__main__":
    logger.info("Testing Employee Detector Metadata Pusher...")
    # Send test detection event for Gaurav on cam06
    push_employee_detection(
        emp_id="EMP-105",
        emp_name="Gaurav",
        cam_id="cam06",
        confidence=0.98,
        snapshot_url="https://gj-snapshots.s3.ap-south-1.amazonaws.com/forensics/assign_employee/aarav.png"
    )

