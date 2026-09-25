"""
GJ-Fashion — Geometry Utilities
Point-in-polygon (ray casting) and polygon helpers.
All coordinates are normalised 0.0 – 1.0.
"""

from typing import List, Tuple

# Type alias for a polygon: list of [x, y] pairs (normalised 0.0–1.0)
Polygon = List[List[float]]


def point_in_polygon(px: float, py: float, polygon: Polygon) -> bool:
    """
    Ray-casting algorithm to test if point (px, py) lies inside *polygon*.

    Args:
        px: X coordinate (normalised 0.0–1.0).
        py: Y coordinate (normalised 0.0–1.0).
        polygon: List of [x, y] vertex pairs forming a closed polygon.

    Returns:
        True if the point is inside the polygon.
    """
    n = len(polygon)
    if n < 3:
        return False

    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        # Check if ray from (px, py) going right crosses edge (i, j)
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def polygon_to_pixel_coords(
    polygon: Polygon, frame_width: int, frame_height: int
) -> List[Tuple[int, int]]:
    """
    Convert normalised polygon coordinates to pixel coordinates.

    Args:
        polygon: [[x, y], ...] normalised 0.0–1.0.
        frame_width: Frame width in pixels.
        frame_height: Frame height in pixels.

    Returns:
        List of (x_px, y_px) integer tuples.
    """
    return [
        (int(pt[0] * frame_width), int(pt[1] * frame_height))
        for pt in polygon
    ]


def polygon_centroid(polygon: Polygon) -> Tuple[float, float]:
    """
    Compute the centroid of a polygon.

    Returns:
        (cx, cy) normalised coordinates.
    """
    if not polygon:
        return (0.5, 0.5)
    cx = sum(pt[0] for pt in polygon) / len(polygon)
    cy = sum(pt[1] for pt in polygon) / len(polygon)
    return (cx, cy)


def hex_to_bgr(hex_color: str) -> Tuple[int, int, int]:
    """
    Convert a hex colour string (#RRGGBB) to OpenCV BGR tuple.

    Args:
        hex_color: e.g. '#FF0000' (red).

    Returns:
        (B, G, R) integer tuple.
    """
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return (0, 255, 0)  # default green
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return (b, g, r)
