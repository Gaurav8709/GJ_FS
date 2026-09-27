"""
=============================================================================
GJ-Fashion AI Smart Showroom — Computer Vision (CV) Heatmap Generator & Pusher
=============================================================================
This script provides a Python helper for the Computer Vision (CV) team to generate 
and upload camera foot-traffic Heatmap images to the GJ-Fashion AI backend.

API Endpoints:
    Production: POST http://65.2.158.148/api/heatmaps/upload (Port 80)
    Local:      POST http://localhost:8000/api/heatmaps/upload

Note:
    Do NOT use port 8000 for remote IP 65.2.158.148 as the server reverse-proxies
    API requests on standard HTTP port 80. This script automatically handles 
    retries and candidate URL fallbacks if port 8000 times out. Uses standard 
    library urllib.request (no external dependencies required).

Usage in CV Pipeline:
    from cv_heatmap_pusher import push_camera_heatmap

    push_camera_heatmap(
        cam_id="cam1",
        heatmap_image_path="heatmap_cam1.png",
        peak_density=0.85,
        meta_info={"peak_hour": "14:00-15:00", "hot_spot": "Rack A"}
    )

CLI Usage:
    python cv_heatmap_pusher.py --cam-id cam1 --image test_heatmap.png --density 0.85 --api-url http://65.2.158.148
=============================================================================
"""

import os
import json
import uuid
import logging
import argparse
import urllib.request
import urllib.error

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [CV-Heatmap]: %(message)s")
logger = logging.getLogger("cv_heatmap")

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


def push_camera_heatmap(
    cam_id: str,
    heatmap_image_path: str,
    peak_density: float = 0.85,
    meta_info: dict = None,
    api_base_url: str = None
):
    """
    Uploads a camera heatmap image file and metadata to backend using standard library urllib.request.

    Args:
        cam_id (str): Camera identifier (e.g. "cam1", "cam06").
        heatmap_image_path (str): Local path to generated PNG/JPG heatmap image file.
        peak_density (float): Traffic density index between 0.0 and 1.0 (e.g. 0.85).
        meta_info (dict, optional): Additional metadata (e.g. peak hours, high traffic zones).
        api_base_url (str, optional): Custom API base URL (e.g. "http://65.2.158.148").
    """
    if not os.path.exists(heatmap_image_path):
        logger.error(f"Heatmap image file not found: {heatmap_image_path}")
        return None

    if meta_info is None:
        meta_info = {"generated_by": "CV-Heatmap-Pipeline"}

    boundary = f"----FormBoundary{uuid.uuid4().hex}"
    body = bytearray()

    # Add text fields
    fields = {
        "cam_id": str(cam_id),
        "peak_density": str(peak_density),
        "meta_info": json.dumps(meta_info)
    }

    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(f"{value}\r\n".encode("utf-8"))

    # Add image file
    filename = os.path.basename(heatmap_image_path)
    with open(heatmap_image_path, "rb") as f:
        file_data = f.read()

    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8"))
    body.extend(b'Content-Type: image/png\r\n\r\n')
    body.extend(file_data)
    body.extend(b'\r\n')

    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    candidates = get_api_candidates(api_base_url)

    for base in candidates:
        endpoint = f"{base}/api/heatmaps/upload"
        try:
            req = urllib.request.Request(
                endpoint,
                data=bytes(body),
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "User-Agent": "CV-Heatmap-Worker/1.0"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    result = json.loads(resp.read().decode())
                    logger.info(f"Successfully uploaded Heatmap for {cam_id} to {endpoint}: {result.get('image_url')}")
                    return result
        except (urllib.error.URLError, TimeoutError, Exception) as e:
            logger.warning(f"Failed connection attempt to {endpoint}: {e}. Retrying next candidate...")

    logger.error(f"All candidate endpoints failed for heatmap upload ({cam_id}).")
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GJ-Fashion CV Heatmap Generator & Pusher CLI")
    parser.add_argument("--cam-id", type=str, default="cam1", help="Camera ID (e.g. cam1)")
    parser.add_argument("--image", type=str, default="test_heatmap.png", help="Path to heatmap image file")
    parser.add_argument("--density", type=float, default=0.88, help="Peak density (0.0 to 1.0)")
    parser.add_argument("--api-url", type=str, default=None, help="API Base URL (default: http://65.2.158.148)")

    args = parser.parse_args()

    # Create dummy test image if needed
    if not os.path.exists(args.image):
        try:
            import numpy as np
            import cv2
            blank = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.circle(blank, (320, 240), 120, (0, 0, 255), -1)
            blank = cv2.GaussianBlur(blank, (99, 99), 0)
            cv2.imwrite(args.image, blank)
        except Exception as e:
            logger.warning(f"Could not generate dummy heatmap image: {e}")

    if os.path.exists(args.image):
        logger.info(f"Executing Heatmap Pusher CLI for '{args.cam_id}' with image '{args.image}'...")
        push_camera_heatmap(
            cam_id=args.cam_id,
            heatmap_image_path=args.image,
            peak_density=args.density,
            meta_info={"peak_hour": "15:00 PM", "top_zone": "Men Formal Suits"},
            api_base_url=args.api_url
        )
    else:
        logger.error(f"Image file '{args.image}' does not exist.")


