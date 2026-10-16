
"""Employee/customer classification using a trained YOLO classification model."""

import logging
from typing import List, Tuple, Optional

from app.config import settings

logger = logging.getLogger("gjfashion.employee_classifier")


class EmployeeClassifier:
    """Loads best.pt once and classifies cropped person images."""

    _instance: Optional["EmployeeClassifier"] = None

    def __init__(self):
        self._model = None
        self._load_attempted = False

    @classmethod
    def get_instance(cls) -> "EmployeeClassifier":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_model(self) -> bool:
        if self._model is not None:
            return True

        if self._load_attempted:
            return False

        self._load_attempted = True

        try:
            from ultralytics import YOLO

            path = settings.EMPLOYEE_CLASSIFIER_MODEL_PATH
            logger.info("Loading employee classifier: %s", path)

            self._model = YOLO(path)

            if self._model.task != "classify":
                logger.error(
                    "Expected a classification model, got task=%s",
                    self._model.task,
                )
                self._model = None
                return False

            logger.info(
                "Employee classifier loaded. Classes: %s",
                self._model.names,
            )
            return True

        except Exception:
            logger.exception("Could not load employee classifier")
            self._model = None
            return False

    @staticmethod
    def _normalize_label(raw_label: str) -> str:
        label = raw_label.strip().lower().replace("_", " ").replace("-", " ")

        if label == "employee":
            return "employee"

        if label in {"person", "customer", "non employee", "nonemployee"}:
            return "customer"

        return "unknown"

    def classify_crops(
        self,
        crops: List,
    ) -> List[Tuple[str, float]]:
        """
        Classify BGR person crops.

        Returns one (label, confidence) pair per crop.
        Labels are employee, customer, or unknown.
        """
        if not crops:
            return []

        if not self._load_model():
            return [("unknown", 0.0) for _ in crops]

        try:
            results = self._model.predict(
                source=crops,
                verbose=False,
            )

            predictions = []

            for result in results:
                if result.probs is None:
                    predictions.append(("unknown", 0.0))
                    continue

                class_id = int(result.probs.top1)
                confidence = float(result.probs.top1conf)

                names = self._model.names
                raw_label = (
                    names.get(class_id, "unknown")
                    if isinstance(names, dict)
                    else names[class_id]
                )

                label = self._normalize_label(str(raw_label))
                predictions.append((label, confidence))

            if len(predictions) != len(crops):
                logger.error("Classifier returned an unexpected result count")
                return [("unknown", 0.0) for _ in crops]

            return predictions

        except Exception:
            logger.exception("Employee classification failed")
            return [("unknown", 0.0) for _ in crops]
