"""
GJ-Fashion — YOLO Detection Engine
Singleton YOLO model wrapper for person detection.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from app.config import settings

logger = logging.getLogger("gjfashion.detection")


@dataclass
class Detection:
    """Single person detection result."""
    bbox: Tuple[int, int, int, int]         # (x1, y1, x2, y2) pixel coords
    confidence: float
    center_px: Tuple[int, int]              # pixel center (cx, cy)
    center_norm: Tuple[float, float]        # normalised center (cx, cy) 0.0–1.0
    id: Optional[int] = None                # persistent object ID
    zone_id: Optional[int] = None           # assigned after zone classification
    zone_name: Optional[str] = None

    
    employee_class: Optional[str] = None
    employee_class_confidence: Optional[float] = None



class DetectionEngine:
    """
    Singleton YOLO model loader and person detector.

    Usage:
        engine = DetectionEngine.get_instance()
        detections = engine.detect_persons(frame)
    """
    _instance: Optional["DetectionEngine"] = None

    def __init__(self):
        self._model = None

    @classmethod
    def get_instance(cls) -> "DetectionEngine":
        """Get or create the singleton detection engine."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load_model(self):
        """
        Lazy-load the YOLO model if available.
        If ultralytics is not installed, runs cleanly in CV Listener mode.
        """
        if self._model is not None:
            return
        try:
            from ultralytics import YOLO
            logger.info(f"Loading YOLO model: {settings.YOLO_MODEL_PATH}")
            self._model = YOLO(settings.YOLO_MODEL_PATH)
            logger.info("YOLO model loaded successfully")
        except ImportError:
            logger.info("Ultralytics package not installed. Backend running in CV Listener Mode.")
            self._model = False
        except Exception as e:
            logger.warning(f"Could not load YOLO model ({e}). Backend running in CV Listener Mode.")
            self._model = False

    @property
    def model(self):
        if self._model is None:
            self.load_model()
        return self._model
    
    def _classify_detections(self, frame, detections):
        """Classify each detected person's crop."""
        if not detections:
            return

        from app.services.employee_classifier import EmployeeClassifier

        height, width = frame.shape[:2]
        crops = []
        valid_detections = []

        for detection in detections:
            x1, y1, x2, y2 = detection.bbox

            # Keep crop coordinates inside the image.
            x1 = max(0, min(width, x1))
            x2 = max(0, min(width, x2))
            y1 = max(0, min(height, y1))
            y2 = max(0, min(height, y2))

            if x2 <= x1 or y2 <= y1:
                detection.employee_class = "unknown"
                detection.employee_class_confidence = 0.0
                continue

            crop = frame[y1:y2, x1:x2]

            if crop.size == 0:
                detection.employee_class = "unknown"
                detection.employee_class_confidence = 0.0
                continue

            crops.append(crop)
            valid_detections.append(detection)

        classifier = EmployeeClassifier.get_instance()
        predictions = classifier.classify_crops(crops)

        for detection, (label, confidence) in zip(
            valid_detections, predictions
        ):
            detection.employee_class = label
            detection.employee_class_confidence = confidence

    def detect_persons(
        self,
        frame: np.ndarray,
        confidence: Optional[float] = None,
    ) -> List[Detection]:
        """
        Run YOLO inference on a frame and return person detections only.

        Args:
            frame: BGR numpy array from OpenCV.
            confidence: Override confidence threshold (default from settings).

        Returns:
            List of Detection objects for class 0 (person) only.
        """
        if not self.model:
            return []

        conf = confidence or settings.YOLO_CONFIDENCE
        h, w = frame.shape[:2]
        frame_area = h * w
        min_area = frame_area * settings.YOLO_MIN_BOX_AREA_RATIO

        detections: List[Detection] = []

        try:
            results = self.model(frame, conf=conf, verbose=False)
            for result in results:
                if result.boxes is None:
                    continue
                for box in result.boxes:
                    # Class 0 = person
                    if int(box.cls[0]) != 0:
                        continue

                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    box_area = (x2 - x1) * (y2 - y1)

                    # Filter tiny/noisy detections
                    if box_area < min_area:
                        continue

                    cx = (x1 + x2) // 2
                    cy = (y1 + y2) // 2

                    detections.append(Detection(
                        bbox=(x1, y1, x2, y2),
                        confidence=float(box.conf[0]),
                        center_px=(cx, cy),
                        center_norm=(cx / w, cy / h),
                    ))
        except Exception as e:
            logger.error(f"YOLO inference error: {e}")

        self._classify_detections(frame, detections)
        return detections

    def detect_persons_batch(
        self,
        frames: List[np.ndarray],
        confidence: Optional[float] = None,
    ) -> List[List[Detection]]:
        """
        Run YOLO inference on a batch of frames and return person detections.

        Args:
            frames: List of BGR numpy arrays from OpenCV.
            confidence: Override confidence threshold (default from settings).

        Returns:
            List of Lists of Detection objects for class 0 (person) only.
        """
        if not frames:
            return []

        if not self.model:
            return [[] for _ in range(len(frames))]

        conf = confidence or settings.YOLO_CONFIDENCE
        batch_detections: List[List[Detection]] = [[] for _ in range(len(frames))]

        try:
            # model(frames) works for list of numpy arrays
            results = self.model(frames, conf=conf, verbose=False)
            
            for i, result in enumerate(results):
                h, w = frames[i].shape[:2]
                frame_area = h * w
                min_area = frame_area * settings.YOLO_MIN_BOX_AREA_RATIO

                if result.boxes is None:
                    continue
                    
                for box in result.boxes:
                    # Class 0 = person
                    if int(box.cls[0]) != 0:
                        continue

                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    box_area = (x2 - x1) * (y2 - y1)

                    # Filter tiny/noisy detections
                    if box_area < min_area:
                        continue

                    cx = (x1 + x2) // 2
                    cy = (y1 + y2) // 2

                    batch_detections[i].append(Detection(
                        bbox=(x1, y1, x2, y2),
                        confidence=float(box.conf[0]),
                        center_px=(cx, cy),
                        center_norm=(cx / w, cy / h),
                    ))
        except Exception as e:
            logger.error(f"YOLO batch inference error: {e}")

        for frame, detections in zip(frames, batch_detections):
            self._classify_detections(frame, detections)



        return batch_detections
