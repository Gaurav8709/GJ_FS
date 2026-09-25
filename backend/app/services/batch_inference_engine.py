"""
GJ-Fashion — Batch Inference Engine
Runs a single background thread that aggregates frames from all active cameras,
runs a batched YOLO inference, and distributes the results back.
"""

import time
import threading
import logging

from app.config import settings
from app.services.camera_manager import CameraManager
from app.services.detection_engine import DetectionEngine

logger = logging.getLogger("gjfashion.batch_inference")

class BatchInferenceEngine:
    _instance = None

    def __init__(self):
        self._running = False
        self._thread = None
        self._engine = DetectionEngine.get_instance()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start(self):
        if self._running:
            return
        self._running = True
        logger.info("Starting Batch Inference Engine")
        self._thread = threading.Thread(target=self._loop, name="batch-inference", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        logger.info("Stopped Batch Inference Engine")

    def _loop(self):
        manager = CameraManager.get_instance()
        interval = 1.0 / settings.INFERENCE_FPS

        while self._running:
            start_time = time.time()
            
            processors = manager.get_all_processors()
            
            active_cam_ids = []
            batch_frames = []
            
            for cam_id, processor in processors.items():
                if processor.online:
                    frame = processor.get_frame_for_inference()
                    if frame is not None:
                        active_cam_ids.append(cam_id)
                        batch_frames.append(frame)
            
            if batch_frames:
                # Run batched inference
                batch_results = self._engine.detect_persons_batch(batch_frames)
                
                # Distribute results
                for cam_id, detections in zip(active_cam_ids, batch_results):
                    processor = processors.get(cam_id)
                    if processor:
                        processor.process_detections(detections)
            
            # Maintain inference rate
            elapsed = time.time() - start_time
            sleep_time = interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
