"""
=============================================================================
GJ-Fashion AI Smart Showroom — Computer Vision (CV) Footfall Metadata Pusher
=============================================================================
This script provides a Python helper function and standalone test runner for
the Computer Vision (CV) team to push real-time Footfall analytics (+1/-1, 
gender breakdown, age breakdown) to the GJ-Fashion backend REST API.

API Endpoints:
    Production: POST http://65.2.158.148/api/footfall/listener-update (Port 80)
    Local:      POST http://localhost:8000/api/footfall/listener-update

Note:
    Do NOT use port 8000 for remote IP 65.2.158.148 as the server reverse-proxies
    API requests on standard HTTP port 80. This script automatically handles 
    retries and candidate URL fallbacks if port 8000 times out.

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

CLI Usage:
    python cv_footfall_pusher.py --cam-id cam6 --entries 1 --exits 0 --api-url http://65.2.158.148
=============================================================================
"""

import os
import json
import logging
import argparse
import urllib.request
import urllib.error

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [CV-Footfall]: %(message)s")
logger = logging.getLogger("cv_footfall")

DEFAULT_API_BASE = os.getenv("API_BASE_URL", "http://65.2.158.148")


def get_api_candidates(base_url: str = None) -> list:
    """Generates candidate API base URLs to handle port 80 vs port 8000 fallback gracefully."""
    if not base_url:
        base_url = DEFAULT_API_BASE
    
    base_url = base_url.rstrip("/")
    candidates = [base_url]

    # If user provided 65.2.158.148:8000, port 8000 will time out. Candidate without :8000 will succeed on port 80.
    if ":8000" in base_url:
        no_port = base_url.replace(":8000", "")
        if no_port not in candidates:
            candidates.append(no_port)
    elif "localhost" not in base_url and "127.0.0.1" not in base_url:
        with_port = f"{base_url}:8000"
        if with_port not in candidates:
            candidates.append(with_port)

    # Standard fallback URLs
    for fallback in ["http://65.2.158.148", "http://localhost:8000"]:
        if fallback not in candidates:
            candidates.append(fallback)

    return candidates


def push_footfall_update(
    cam_id: str,
    entries: int = 0,
    exits: int = 0,
    net_count: int = None,
    male_count: int = 0,
    female_count: int = 0,
    age_breakdown: dict = None,
    timestamp: str = None,
    api_base_url: str = None
):
    """
    Pushes real-time footfall detection payload from CV pipeline to backend.

    Args:
        cam_id (str): Camera ID (e.g., "cam1", "cam6", "cam06").
        entries (int): Number of new entries (+1).
        exits (int): Number of exits (-1).
        net_count (int, optional): Current net occupancy.
        male_count (int): Male count in detection.
        female_count (int): Female count in detection.
        age_breakdown (dict): Dictionary with age keys: "0_9", "10_17", "18_25", "26_35", "36_50", "50_plus".
        timestamp (str, optional): ISO timestamp (e.g. "2026-09-25T12:23:02Z"). Auto-generated if omitted.
        api_base_url (str, optional): Custom API base URL (e.g. "http://65.2.158.148").
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

    candidates = get_api_candidates(api_base_url)
    json_bytes = json.dumps(payload).encode("utf-8")

    for base in candidates:
        endpoint = f"{base}/api/footfall/listener-update"
        try:
            req = urllib.request.Request(
                endpoint,
                data=json_bytes,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "CV-Footfall-Worker/1.0"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    result = json.loads(resp.read().decode())
                    logger.info(f"Successfully pushed footfall update for {cam_id} to {endpoint}: {result.get('status')}")
                    return result
        except (urllib.error.URLError, TimeoutError, Exception) as e:
            logger.warning(f"Failed connection attempt to {endpoint}: {e}. Retrying next candidate...")

    logger.error(f"All candidate endpoints failed for footfall update ({cam_id}).")
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GJ-Fashion CV Footfall Pusher CLI")
    parser.add_argument("--cam-id", type=str, default="cam1", help="Camera ID (e.g. cam1, cam6)")
    parser.add_argument("--entries", type=int, default=1, help="Entries count")
    parser.add_argument("--exits", type=int, default=0, help="Exits count")
    parser.add_argument("--male-count", type=int, default=1, help="Male count")
    parser.add_argument("--female-count", type=int, default=0, help="Female count")
    parser.add_argument("--api-url", type=str, default=None, help="API Base URL (default: http://65.2.158.148)")
    
    args = parser.parse_args()

    logger.info(f"Executing Footfall Pusher CLI for camera '{args.cam_id}'...")
    push_footfall_update(
        cam_id=args.cam_id,
        entries=args.entries,
        exits=args.exits,
        male_count=args.male_count,
        female_count=args.female_count,
        api_base_url=args.api_url
    )


