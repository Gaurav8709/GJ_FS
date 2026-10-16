"""Cosine-similarity matching for trusted employee face embeddings.

This service does not detect faces or generate embeddings. It only matches a
query embedding produced by a real face-recognition model.
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

logger = logging.getLogger("gjfashion.face_matcher")
DEFAULT_EMBEDDINGS_DIR = Path(__file__).resolve().parents[2] / "scripts" / "cv_embeddings"


class FaceMatcher:
    def __init__(
        self,
        embeddings_dir: Optional[Path] = None,
        threshold: float = 0.45,
        expected_dimension: int = 512,
    ) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0 and 1")
        if expected_dimension < 1:
            raise ValueError("expected_dimension must be positive")
        self.embeddings_dir = Path(embeddings_dir or DEFAULT_EMBEDDINGS_DIR)
        self.threshold = float(threshold)
        self.expected_dimension = int(expected_dimension)

    @staticmethod
    def _normalise(vector: Sequence[float], dimension: int) -> Optional[np.ndarray]:
        try:
            value = np.asarray(vector, dtype=np.float32)
        except (TypeError, ValueError):
            return None
        if value.ndim != 1 or value.size != dimension or not np.isfinite(value).all():
            return None
        norm = float(np.linalg.norm(value))
        if norm <= 1e-12:
            return None
        return value / norm

    def _load_templates(self) -> List[Dict[str, Any]]:
        templates: List[Dict[str, Any]] = []
        if not self.embeddings_dir.exists():
            return templates

        for path in sorted(self.embeddings_dir.glob("*_embeddings.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Skipping unreadable embedding file %s: %s", path, exc)
                continue

            # Fail closed: legacy listener outputs may contain random vectors.
            if payload.get("embedding_type") != "face" or payload.get("is_placeholder") is not False:
                continue
            emp_id = str(payload.get("emp_id") or "").strip()
            emp_name = str(payload.get("emp_name") or "").strip()
            vectors = payload.get("facial_embeddings")
            if not emp_id or not isinstance(vectors, list) or not vectors:
                continue
            if all(isinstance(item, (int, float)) for item in vectors):
                vectors = [vectors]

            for raw in vectors:
                if not isinstance(raw, list):
                    continue
                vector = self._normalise(raw, self.expected_dimension)
                if vector is None:
                    logger.warning("Skipping invalid vector in %s", path)
                    continue
                templates.append({
                    "emp_id": emp_id,
                    "emp_name": emp_name or emp_id,
                    "embedding_model": payload.get("embedding_model"),
                    "vector": vector,
                })
        return templates

    def index_status(self) -> Dict[str, Any]:
        templates = self._load_templates()
        return {
            "status": "ready" if templates else "empty",
            "employee_count": len({t["emp_id"] for t in templates}),
            "template_count": len(templates),
            "embedding_dimension": self.expected_dimension,
            "similarity_metric": "cosine_similarity",
            "threshold": self.threshold,
        }

    def match(self, embedding: Sequence[float]) -> Dict[str, Any]:
        query = self._normalise(embedding, self.expected_dimension)
        if query is None:
            raise ValueError(
                f"embedding must be a finite, non-zero vector of "
                f"{self.expected_dimension} values"
            )

        templates = self._load_templates()
        if not templates:
            return {
                "recognized": False, "status": "no_embeddings",
                "emp_id": None, "emp_name": None, "similarity": None,
                "threshold": self.threshold, "embedding_model": None,
            }

        best_by_employee: Dict[str, Dict[str, Any]] = {}
        for item in templates:
            score = float(np.dot(query, item["vector"]))
            previous = best_by_employee.get(item["emp_id"])
            if previous is None or score > previous["similarity"]:
                best_by_employee[item["emp_id"]] = {
                    "emp_id": item["emp_id"],
                    "emp_name": item["emp_name"],
                    "similarity": score,
                    "embedding_model": item["embedding_model"],
                }

        best = max(best_by_employee.values(), key=lambda item: item["similarity"])
        accepted = best["similarity"] >= self.threshold
        return {
            "recognized": accepted,
            "status": "matched" if accepted else "unknown",
            "emp_id": best["emp_id"] if accepted else None,
            "emp_name": best["emp_name"] if accepted else None,
            "similarity": round(best["similarity"], 6),
            "threshold": self.threshold,
            "embedding_model": best["embedding_model"] if accepted else None,
        }
