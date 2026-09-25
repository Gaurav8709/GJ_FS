"""
GJ-Fashion — Camera Processor
Per-camera processing: reader thread + inference thread.

Architecture (adapted from Z-Factory CameraProcessor):
  ┌─────────────┐          ┌──────────────────┐
  │ Reader Thread│──frame──▶│  Ring Buffer (3)  │
  │  (30+ FPS)   │          │  self._ring       │
  └─────────────┘          └──────┬───────────┘
                                  │ latest frame
                           ┌──────▼───────────┐
                           │ Inference Thread  │  runs at ~3 FPS
                           │ YOLO + zone class │
                           └──────┬───────────┘
                                  │ cached results
                           ┌──────▼───────────┐
                           │ get_frame()       │  live frame + cached overlays
                           │  (called by MJPEG)│
                           └──────────────────┘

Key differences from Z-Factory:
  • Arbitrary polygon zones (not 3-column split)
  • Per-camera zone configs loaded from DB
  • Hot-reloadable zones via update_zones()
  • Detection state cached for live overlay compositing
"""

import cv2
import time
import threading
import logging
import datetime
import os
from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.config import settings
from app.services.detection_engine import Detection, DetectionEngine
from app.services.zone_engine import (
    ZoneConfig, classify_detections,
    draw_zone_overlays, draw_detection_boxes, draw_status_text,
)
from app.utils.tracker import CentroidTracker

logger = logging.getLogger("gjfashion.camera")


class DetectionState:
    """Thread-safe cached detection results for live frame compositing."""
    __slots__ = (
        "detections", "zone_results", "total_detected",
        "has_alert", "has_warning", "warning_countdown",
        "shortage_counters",
    )

    def __init__(self):
        self.detections: List[Detection] = []
        self.zone_results: Dict[int, List[Detection]] = {}
        self.total_detected: int = 0
        self.has_alert: bool = False
        self.has_warning: bool = False
        self.warning_countdown: int = 0
        self.shortage_counters: Dict[int, int] = {}


class CameraProcessor:
    """
    Per-camera processor managing an RTSP reader thread and inference thread.

    The reader thread continuously grabs frames into a ring buffer.
    The inference thread runs YOLO at ~3 FPS and caches detection state.
    get_frame() composites live frames with cached overlays for 30+ FPS streaming.
    """

    def __init__(
        self,
        cam_id: str,
        rtsp_url: str,
        zones: Optional[List[ZoneConfig]] = None,
        engine: Optional[DetectionEngine] = None,
    ):
        self.cam_id = cam_id
        self.rtsp_url = rtsp_url
        self._engine = engine or DetectionEngine.get_instance()

        # Zone configuration — can be updated at runtime
        self._zones: List[ZoneConfig] = zones or []
        self._zones_lock = threading.Lock()

        # Ring buffer for raw frames (reader → inference/streaming)
        self._ring: deque = deque(maxlen=3)
        self._frame_lock = threading.Lock()

        # Latest raw frame for streaming
        self._latest_frame: Optional[np.ndarray] = None

        # Cached detection state (inference → streaming)
        self._state = DetectionState()
        self._state_lock = threading.Lock()

        # Camera status
        self.online = False
        self._running = False
        self._cap: Optional[cv2.VideoCapture] = None

        # Alert tracking per zone
        self._alert_times: Dict[int, Optional[float]] = {}
        self._screenshots_taken: Dict[int, bool] = {}

        # Tracker for persistent object IDs
        self._tracker = CentroidTracker(max_disappeared=30, max_distance=80)

    # ── Lifecycle ────────────────────────────────────────────

    def start(self):
        """Start the reader daemon thread."""
        if self._running:
            return
        self._running = True
        logger.info(f"[{self.cam_id}] Starting camera processor: {self.rtsp_url}")
        threading.Thread(target=self._reader_loop, name=f"reader-{self.cam_id}", daemon=True).start()

    def stop(self):
        """Signal threads to stop (they'll exit on next iteration)."""
        self._running = False
        self.online = False
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        logger.info(f"[{self.cam_id}] Stopped camera processor")

    # ── Zone Config Hot-Reload ──────────────────────────────

    def update_zones(self, zones: List[ZoneConfig]):
        """Update zone configuration at runtime (thread-safe)."""
        with self._zones_lock:
            self._zones = zones
            # Reset shortage counters for new zone set
            self._state.shortage_counters = {z.id: 0 for z in zones}
            self._alert_times = {z.id: None for z in zones}
            self._screenshots_taken = {z.id: False for z in zones}
        logger.info(f"[{self.cam_id}] Updated zones: {[z.zone_name for z in zones]}")

    def get_zones(self) -> List[ZoneConfig]:
        """Get current zone configs (thread-safe copy)."""
        with self._zones_lock:
            return list(self._zones)

    # ── Reader Thread ───────────────────────────────────────

    def _reader_loop(self):
        """
        Continuously read frames from the RTSP stream.
        Auto-reconnects on failure with exponential backoff.
        """
        mock_img_path = f"camera_mocks/{self.cam_id}.png"
        has_mock = os.path.exists(mock_img_path)
        mock_frame = None
        if has_mock:
            mock_frame = cv2.imread(mock_img_path)
            if mock_frame is not None:
                mock_frame = cv2.resize(mock_frame, (640, 480))
            logger.info(f"[{self.cam_id}] Loaded mock frame: {mock_img_path}")

        while self._running:
            if has_mock and mock_frame is not None:
                self.online = True
                with self._frame_lock:
                    self._ring.append(mock_frame)
                    self._latest_frame = mock_frame
                time.sleep(1.0 / 30.0)
                continue

            if not self.rtsp_url or not self.rtsp_url.strip():
                self.online = False
                time.sleep(2.0)
                continue

            # Open capture
            try:
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
                self._cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception as e:
                logger.error(f"[{self.cam_id}] Failed to open capture: {e}")
                time.sleep(10)
                continue

            # Read loop
            while self._running:
                try:
                    ret, frame = self._cap.read()
                except Exception:
                    ret = False

                if not ret:
                    self.online = False
                    try:
                        self._cap.release()
                    except Exception:
                        pass
                    time.sleep(10)
                    break  # outer loop will reconnect

                self.online = True
                with self._frame_lock:
                    self._ring.append(frame)
                    self._latest_frame = frame

    # ── Inference Hooks ─────────────────────────────────────

    def get_frame_for_inference(self) -> Optional[np.ndarray]:
        """Get the latest raw frame for batched inference."""
        if not self.online:
            with self._state_lock:
                self._state = DetectionState()
            return None

        with self._frame_lock:
            if not self._ring:
                return None
            return self._ring[-1].copy()

    def process_detections(self, detections: List[Detection]):
        """
        Process detection results (called externally by BatchInferenceEngine).
        Caches detection results for live frame compositing.
        """
        if not self.online:
            return

        alert_delay = settings.ALERT_DELAY_SECONDS

        # Update tracker and assign IDs
        rects = [d.bbox for d in detections]
        objects = self._tracker.update(rects)

        # Match tracker output back to detections based on closest centroid
        # The tracker uses input order to register new ones, but for matching
        # existing ones we just find the closest center.
        for obj_id, centroid in objects.items():
            best_det = None
            best_dist = float('inf')
            for d in detections:
                if getattr(d, 'id', None) is not None:
                    continue  # already assigned
                
                dist = (d.center_px[0] - centroid[0])**2 + (d.center_px[1] - centroid[1])**2
                if dist < 1000: # reasonable pixel distance squared
                    if dist < best_dist:
                        best_dist = dist
                        best_det = d
                        
            if best_det is not None:
                best_det.id = obj_id

        # Get current zones
        with self._zones_lock:
            zones = list(self._zones)

        # Classify detections into zones
        zone_results = classify_detections(detections, zones)

        # Update shortage counters and alert state
        has_alert = False
        has_warning = False
        min_countdown = alert_delay

        for zone in zones:
            if not zone.alert_enabled or zone.required_count <= 0:
                continue

            detected = len(zone_results.get(zone.id, []))
            shortage = detected < zone.required_count

            if not shortage:
                self._state.shortage_counters[zone.id] = 0
                self._alert_times[zone.id] = None
                self._screenshots_taken[zone.id] = False
            else:
                counter = self._state.shortage_counters.get(zone.id, 0) + 1
                self._state.shortage_counters[zone.id] = counter

                if counter >= alert_delay:
                    has_alert = True
                    # Screenshot logic
                    if self._alert_times.get(zone.id) is None:
                        self._alert_times[zone.id] = time.time()
                    elif (
                        time.time() - self._alert_times[zone.id] >= settings.SCREENSHOT_DELAY_SECONDS
                        and not self._screenshots_taken.get(zone.id, False)
                    ):
                        # Use current latest frame for screenshot
                        with self._frame_lock:
                            ss_frame = self._latest_frame.copy() if self._latest_frame is not None else None
                        if ss_frame is not None:
                            self._capture_screenshot(ss_frame, zone)
                        self._screenshots_taken[zone.id] = True
                else:
                    has_warning = True
                    countdown = alert_delay - counter
                    min_countdown = min(min_countdown, countdown)

        # Cache the detection state
        with self._state_lock:
            self._state.detections = detections
            self._state.zone_results = zone_results
            self._state.total_detected = len(detections)
            self._state.has_alert = has_alert
            self._state.has_warning = has_warning
            self._state.warning_countdown = min_countdown

    # ── Frame Output ────────────────────────────────────────

    def get_frame(self, quality: int = 75, show_zones: bool = True) -> Optional[bytes]:
        """
        Get the current frame with cached detection overlays.

        This method is called at 30+ FPS by the MJPEG streaming endpoint.
        It composites the LIVE raw frame with CACHED detection results
        to keep streaming smooth while inference runs at ~3 FPS.

        Args:
            quality: JPEG encoding quality (0-100).
            show_zones: Whether to draw zone overlays on the frame.

        Returns:
            JPEG-encoded bytes, or None if no frame is available.
        """
        # Get latest raw frame
        with self._frame_lock:
            if self._latest_frame is not None and self.online:
                frame = self._latest_frame.copy()
            else:
                return self._offline_frame_bytes()

        # Get cached detection state
        with self._state_lock:
            detections = list(self._state.detections)
            zone_results = dict(self._state.zone_results)
            total_detected = self._state.total_detected
            has_alert = self._state.has_alert
            has_warning = self._state.has_warning
            warning_countdown = self._state.warning_countdown

        # Get zones
        with self._zones_lock:
            zones = list(self._zones)

        # Draw overlays on the live frame
        if zones and show_zones:
            frame = draw_zone_overlays(frame, zones, zone_results)
        frame = draw_detection_boxes(frame, detections, zones)
        if zones:
            frame = draw_status_text(
                frame, zones, zone_results,
                total_detected, has_alert, has_warning, warning_countdown,
            )

        # Live timestamp removed as per user request

        # Encode to JPEG
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes()

    def get_raw_frame(self) -> Optional[np.ndarray]:
        """Get the raw camera frame without any overlays."""
        with self._frame_lock:
            if self._latest_frame is not None and self.online:
                return self._latest_frame.copy()
        return None

    def get_status(self) -> dict:
        """Get current processor status as a dict."""
        with self._state_lock:
            zone_counts = {}
            for zone in self.get_zones():
                zone_counts[zone.zone_name] = {
                    "detected": len(self._state.zone_results.get(zone.id, [])),
                    "required": zone.required_count,
                    "shortage_counter": self._state.shortage_counters.get(zone.id, 0),
                }

        return {
            "cam_id": self.cam_id,
            "online": self.online,
            "total_detected": self._state.total_detected,
            "has_alert": self._state.has_alert,
            "has_warning": self._state.has_warning,
            "zones": zone_counts,
        }

    # ── Private Helpers ─────────────────────────────────────

    def _offline_frame_bytes(self) -> bytes:
        """Generate an 'OFFLINE' placeholder frame."""
        frame = np.full((480, 640, 3), 60, dtype=np.uint8)
        cv2.putText(
            frame, f"{self.cam_id} OFFLINE",
            (120, 250), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3,
        )
        _, buf = cv2.imencode(".jpg", frame)
        return buf.tobytes()

    def _capture_screenshot(self, frame: np.ndarray, zone: ZoneConfig):
        """Save an alert screenshot to the screenshots directory."""
        try:
            os.makedirs(settings.SCREENSHOTS_DIR, exist_ok=True)
            filename = f"{self.cam_id}_{zone.zone_name}_{int(time.time())}.jpg"
            filepath = os.path.join(settings.SCREENSHOTS_DIR, filename)
            cv2.imwrite(filepath, frame)
            logger.info(f"[{self.cam_id}] Screenshot saved: {filepath}")
        except Exception as e:
            logger.error(f"[{self.cam_id}] Screenshot failed: {e}")
