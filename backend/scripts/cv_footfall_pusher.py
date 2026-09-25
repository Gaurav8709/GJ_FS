"""
=============================================================================
GJ-Fashion AI Smart Showroom — Computer Vision (CV) Footfall Metadata Pusher
=============================================================================
This script provides a Python helper function and standalone test runner for
the Computer Vision (CV) team to push real-time Footfall analytics (+1/-1, 
gender breakdown, age breakdown) to the GJ-Fashion backend REST API.

API Endpoint:
    POST http://localhost:8000/api/footfall/listener-update

Usage in CV Pipeline:
    from cv_footfall_pusher import push_footfall_update

    push_footfall_update(
        cam_id="cam1",
        entries=1,
        exits=0,
        net_count=5,
        male_count=1,
        female_count=0,
        age_breakdown={"18_25": 1, "26_35": 0, "36_50": 0, "50_plus": 0}
    )
=============================================================================
"""

import os
import json
import logging
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [CV-Footfall]: %(message)s")
logger = logging.getLogger("cv_footfall")

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
FOOTFALL_ENDPOINT = f"{API_BASE_URL}/api/footfall/listener-update"


def push_footfall_update(
    cam_id: str,
    entries: int = 0,
    exits: int = 0,
    net_count: int = None,
    male_count: int = 0,
    female_count: int = 0,
    age_breakdown: dict = None,
    timestamp: str = None
):
    """
    Pushes real-time footfall detection payload from CV pipeline to backend.

    Args:
        cam_id (str): Camera ID (e.g., "cam1", "cam06").
        entries (int): Number of new entries (+1).
        exits (int): Number of exits (-1).
        net_count (int, optional): Current net occupancy.
        male_count (int): Male count in detection.
        female_count (int): Female count in detection.
        age_breakdown (dict): Dictionary with age keys: "0_9", "10_17", "18_25", "26_35", "36_50", "50_plus".
        timestamp (str, optional): ISO timestamp (e.g. "2026-09-25T12:23:02Z"). Auto-generated if omitted.
    """
    if age_breakdown is None:
        age_breakdown = {"0_9": 0, "10_17": 0, "18_25": 0, "26_35": 0, "36_50": 0, "50_plus": 0}

    if net_count is None:
        net_count = max(0, entries - exits)

    payload = {
        "cam_id": cam_id,
        "entries": entries,
        "exits": exits,
        "net_count": net_count,
        "male_count": male_count,
        "female_count": female_count,
        "age_breakdown": age_breakdown,
        "timestamp": timestamp
    }


    try:
        json_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            FOOTFALL_ENDPOINT,
            data=json_bytes,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "CV-Footfall-Worker/1.0"
            },
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            if resp.status == 200:
                result = json.loads(resp.read().decode())
                logger.info(f"Successfully pushed footfall update for {cam_id}: {result.get('status')}")
                return result
    except Exception as e:
        logger.error(f"Failed to push footfall update to {FOOTFALL_ENDPOINT}: {e}")
        return None


if __name__ == "__main__":
    logger.info("Testing Footfall Metadata Pusher...")
    # Send a sample test update
    push_footfall_update(
        cam_id="cam1",
        entries=1,
        exits=0,
        net_count=12,
        male_count=1,
        female_count=0,
        age_breakdown={"0_9": 0, "10_17": 0, "18_25": 1, "26_35": 0, "36_50": 0, "50_plus": 0}
    )

