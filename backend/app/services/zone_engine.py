"""
GJ-Fashion — Zone Engine
Point-in-polygon zone classification and OpenCV overlay drawing.
"""

import logging
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from app.services.detection_engine import Detection
from app.utils.geometry import point_in_polygon, polygon_to_pixel_coords, hex_to_bgr

logger = logging.getLogger("gjfashion.zone")


# ── Zone data transfer object ───────────────────────────────
class ZoneConfig:
    """Lightweight zone config used during inference (not an ORM model)."""
    __slots__ = (
        "id", "zone_name", "zone_type", "polygon_points",
        "color", "opacity", "required_count", "max_count",
        "alert_enabled",
    )

    def __init__(
        self,
        id: int,
        zone_name: str,
        polygon_points: List[List[float]],
        zone_type: str = "monitoring",
        color: str = "#00FF00",
        opacity: float = 0.15,
        required_count: int = 1,
        max_count: int = 0,
        alert_enabled: bool = True,
    ):
        self.id = id
        self.zone_name = zone_name
        self.zone_type = zone_type
        
        parsed_points = []
        if polygon_points:
            import json
            if isinstance(polygon_points, str):
                try:
                    polygon_points = json.loads(polygon_points)
                except Exception:
                    pass
            if isinstance(polygon_points, list):
                for pt in polygon_points:
                    if isinstance(pt, dict) and "x" in pt and "y" in pt:
                        parsed_points.append([float(pt["x"]), float(pt["y"])])
                    elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        parsed_points.append([float(pt[0]), float(pt[1])])
        self.polygon_points = parsed_points
        self.color = color
        self.opacity = opacity
        self.required_count = required_count
        self.max_count = max_count
        self.alert_enabled = alert_enabled


# ── Zone Classification ─────────────────────────────────────

def classify_detections(
    detections: List[Detection],
    zones: List[ZoneConfig],
) -> Dict[int, List[Detection]]:
    """
    Classify each detection into zones based on centre-point polygon test.

    Args:
        detections: Person detections with normalised centres.
        zones: Active zone configurations for this camera.

    Returns:
        Dict mapping zone_id -> list of detections inside that zone.
    """
    zone_results: Dict[int, List[Detection]] = {z.id: [] for z in zones}

    for det in detections:
        px, py = det.center_norm
        for zone in zones:
            if point_in_polygon(px, py, zone.polygon_points):
                det.zone_id = zone.id
                det.zone_name = zone.zone_name
                zone_results[zone.id].append(det)
                break  # first matching zone wins

    return zone_results


# ── Drawing Helpers ──────────────────────────────────────────

def draw_zone_overlays(
    frame: np.ndarray,
    zones: List[ZoneConfig],
    zone_results: Dict[int, List[Detection]],
) -> np.ndarray:
    h, w = frame.shape[:2]
    overlay = frame.copy()

    for zone in zones:
        if "customer" in zone.zone_name.lower():
            continue
            
        pts = polygon_to_pixel_coords(zone.polygon_points, w, h)
        if len(pts) < 3:
            continue

        pts_np = np.array(pts, dtype=np.int32)
        color = hex_to_bgr(zone.color)

        # Fill polygon on overlay
        cv2.fillPoly(overlay, [pts_np], color)

        # Draw polygon border
        cv2.polylines(frame, [pts_np], isClosed=True, color=color, thickness=2)

    # Blend overlay with original frame (0.15 opacity)
    frame = cv2.addWeighted(overlay, 0.15, frame, 0.85, 0)
    return frame


def draw_detection_boxes(
    frame: np.ndarray,
    detections: List[Detection],
    zones: List[ZoneConfig],
) -> np.ndarray:
    """
    Draw bounding boxes around detected persons.
    Box colour matches the assigned zone colour.

    Args:
        frame: BGR image.
        detections: Person detections.
        zones: Zone configurations (for colour lookup).

    Returns:
        Frame with bounding boxes drawn.
    """
    zone_color_map = {z.id: hex_to_bgr(z.color) for z in zones}
    default_color = (0, 255, 255)  # cyan for unassigned

    for det in detections:
        x1, y1, x2, y2 = det.bbox
        color = zone_color_map.get(det.zone_id, default_color)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

    return frame


def draw_status_text(
    frame: np.ndarray,
    zones: List[ZoneConfig],
    zone_results: Dict[int, List[Detection]],
    total_detected: int,
    has_alert: bool,
    has_warning: bool,
    warning_countdown: int = 0,
) -> np.ndarray:
    """
    Draw status overlay text (counts, alert status) on the frame.
    """
    return frame
