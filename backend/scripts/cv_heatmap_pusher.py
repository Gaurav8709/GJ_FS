"""
=============================================================================
GJ-Fashion AI Smart Showroom — Computer Vision (CV) Heatmap Generator & Pusher
=============================================================================
This script provides a Python helper for the Computer Vision (CV) team to generate 
and upload camera foot-traffic Heatmap images to the GJ-Fashion AI backend.

Workflow:
1. CV Model tracks customer bounding boxes / centroids on RTSP camera stream over time.
2. CV Pipeline overlays color-coded Kernel Density Estimation (KDE) heatmap onto the camera frame.
3. CV Pipeline uploads the heatmap image file & peak density metadata to backend API:
   POST http://localhost:8000/api/heatmaps/upload

Usage in CV Pipeline:
    from cv_heatmap_pusher import push_camera_heatmap

    push_camera_heatmap(
        cam_id="cam1",
        heatmap_image_path="heatmap_cam1.png",
        peak_density=0.85,
        meta_info={"peak_hour": "14:00-15:00", "hot_spot": "Rack A"}
    )
=============================================================================
"""

import os
import json
import logging
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [CV-Heatmap]: %(message)s")
logger = logging.getLogger("cv_heatmap")

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
HEATMAP_ENDPOINT = f"{API_BASE_URL}/api/heatmaps/upload"


def push_camera_heatmap(
    cam_id: str,
    heatmap_image_path: str,
    peak_density: float = 0.85,
    meta_info: dict = None
):
    """
    Uploads a camera heatmap image file and metadata to backend.

    Args:
        cam_id (str): Camera identifier (e.g. "cam1", "cam06").
        heatmap_image_path (str): Local path to generated PNG/JPG heatmap image file.
        peak_density (float): Traffic density index between 0.0 and 1.0 (e.g. 0.85).
        meta_info (dict, optional): Additional metadata (e.g. peak hours, high traffic zones).
    """
    if not os.path.exists(heatmap_image_path):
        logger.error(f"Heatmap image file not found: {heatmap_image_path}")
        return None

    if meta_info is None:
        meta_info = {"generated_by": "CV-Heatmap-Pipeline"}

    data = {
        "cam_id": cam_id,
        "peak_density": str(peak_density),
        "meta_info": json.dumps(meta_info)
    }

    try:
        filename = os.path.basename(heatmap_image_path)
        with open(heatmap_image_path, "rb") as f:
            files = {"file": (filename, f.read(), "image/png")}

        r = requests.post(HEATMAP_ENDPOINT, data=data, files=files)
        if r.status_code == 200:
            result = r.json()
            logger.info(f"Successfully uploaded Heatmap for {cam_id}: {result.get('image_url')}")
            return result
        else:
            logger.error(f"Failed to upload heatmap ({r.status_code}): {r.text}")
    except Exception as e:
        logger.error(f"Error uploading heatmap to {HEATMAP_ENDPOINT}: {e}")

    return None


if __name__ == "__main__":
    logger.info("Testing Heatmap Pusher...")
    # Create a simple dummy heatmap image for testing
    import numpy as np
    try:
        import cv2
        # Generate dummy 640x480 colormap image
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.circle(blank, (320, 240), 120, (0, 0, 255), -1) # Red hotspot
        blank = cv2.GaussianBlur(blank, (99, 99), 0)
        test_path = "test_heatmap.png"
        cv2.imwrite(test_path, blank)

        push_camera_heatmap(
            cam_id="cam1",
            heatmap_image_path=test_path,
            peak_density=0.88,
            meta_info={"peak_hour": "15:00 PM", "top_zone": "Men Formal Suits"}
        )
    except Exception as e:
        logger.warning(f"OpenCV test generation skipped: {e}")
