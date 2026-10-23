"""Direction-aware per-camera line-crossing detection for footfall events."""

from __future__ import annotations

import threading
import time
from typing import Dict, Iterable, List, Optional, Tuple


Point = Tuple[float, float]


class FootfallCrossingDetector:
    """Detect a single event when a tracked person crosses a configured line.

    Coordinates use normalized frame positions (0..1).
    The entry_side setting determines which side counts as an entry.
    A dead band suppresses jitter near the line, and a cooldown prevents
    repeated events while a track flickers around the line.
    """

    def __init__(
        self,
        cam_id: str,
        gate: Optional[dict] = None,
        camera_name: Optional[str] = None,
    ):
        self.cam_id = cam_id
        self.camera_name = camera_name
        self._gate = self._normalize_gate(gate)
        self._track_state: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self.deadband = 0.012
        self.cooldown_seconds = 1.5

    @staticmethod
    def _normalize_gate(gate: Optional[dict]) -> Optional[dict]:
        if not gate or not gate.get("enabled"):
            return None

        try:
            start = tuple(float(v) for v in gate["line_start"])
            end = tuple(float(v) for v in gate["line_end"])
            entry_side = int(gate.get("entry_side", 1))

            if (
                len(start) != 2
                or len(end) != 2
                or start == end
                or entry_side not in (-1, 1)
            ):
                return None

            if not all(0 <= v <= 1 for v in (*start, *end)):
                return None

            return {
                "line_start": start,
                "line_end": end,
                "entry_side": entry_side,
            }

        except (KeyError, TypeError, ValueError):
            return None

    def update_gate(
        self,
        gate: Optional[dict],
        camera_name: Optional[str] = None,
    ) -> None:
        """Update gate configuration without restarting the camera."""
        with self._lock:
            self._gate = self._normalize_gate(gate)

            if camera_name is not None:
                self.camera_name = camera_name

            # Do not compare tracked points against an old gate position.
            self._track_state.clear()

    @staticmethod
    def _cross(a: Point, b: Point, p: Point) -> float:
        return (
            (b[0] - a[0]) * (p[1] - a[1])
            - (b[1] - a[1]) * (p[0] - a[0])
        )

    @staticmethod
    def _side(
        signed_distance: float,
        line_length: float,
        deadband: float,
    ) -> int:
        normalized_distance = signed_distance / max(line_length, 1e-9)

        if normalized_distance > deadband:
            return 1

        if normalized_distance < -deadband:
            return -1

        return 0

    @classmethod
    def _crossing_is_on_segment(
        cls,
        previous: Point,
        current: Point,
        start: Point,
        end: Point,
    ) -> bool:
        old_value = cls._cross(start, end, previous)
        new_value = cls._cross(start, end, current)
        denominator = old_value - new_value

        if abs(denominator) < 1e-9:
            return False

        t = old_value / denominator

        if not 0.0 <= t <= 1.0:
            return False

        crossing = (
            previous[0] + t * (current[0] - previous[0]),
            previous[1] + t * (current[1] - previous[1]),
        )

        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length_sq = dx * dx + dy * dy

        if length_sq < 1e-9:
            return False

        projection = (
            (crossing[0] - start[0]) * dx
            + (crossing[1] - start[1]) * dy
        ) / length_sq

        # Ignore crossings beyond the finite endpoints of the gate.
        return -0.02 <= projection <= 1.02

    def update(
        self,
        detections: Iterable,
        now: Optional[float] = None,
    ) -> List[Tuple[object, str]]:
        """Return [(detection, 'ENTRY' or 'EXIT')] for confirmed crossings."""
        now = time.monotonic() if now is None else now
        events: List[Tuple[object, str]] = []

        with self._lock:
            gate = self._gate

            if not gate:
                return events

            start: Point = gate["line_start"]
            end: Point = gate["line_end"]

            dx = end[0] - start[0]
            dy = end[1] - start[1]
            line_length = (dx * dx + dy * dy) ** 0.5

            if line_length < 1e-6:
                return events

            active_ids = set()

            for detection in detections:
                track_id = getattr(detection, "id", None)
                center = getattr(detection, "center_norm", None)

                if track_id is None or center is None or len(center) != 2:
                    continue

                key = str(track_id)
                active_ids.add(key)

                current: Point = (
                    float(center[0]),
                    float(center[1]),
                )

                signed = self._cross(start, end, current)
                side = self._side(
                    signed,
                    line_length,
                    self.deadband,
                )

                state = self._track_state.get(key)

                if state is None:
                    self._track_state[key] = {
                        "point": current,
                        "side": side,
                        "last_event": 0.0,
                        "missing_frames": 0,
                    }
                    continue

                previous: Point = state["point"]
                previous_side = state["side"]

                # The person crossed from one stable side to the other.
                if (
                    side != 0
                    and previous_side != 0
                    and side != previous_side
                ):
                    crosses_segment = self._crossing_is_on_segment(
                        previous,
                        current,
                        start,
                        end,
                    )

                    cooldown_ok = (
                        now - state["last_event"]
                        >= self.cooldown_seconds
                    )

                    if crosses_segment and cooldown_ok:
                        event_type = (
                            "ENTRY"
                            if side == gate["entry_side"]
                            else "EXIT"
                        )

                        events.append((detection, event_type))
                        state["last_event"] = now

                # Keep the last stable point while near the line.
                if side != 0:
                    state["side"] = side
                    state["point"] = current

                state["missing_frames"] = 0

            # Keep temporarily missing tracks through brief occlusions.
            # The tracker normally ages out after approximately 30 frames.
            for key in list(self._track_state):
                if key not in active_ids:
                    state = self._track_state[key]
                    state["missing_frames"] = (
                        state.get("missing_frames", 0) + 1
                    )

                    if state["missing_frames"] > 35:
                        del self._track_state[key]

        return events