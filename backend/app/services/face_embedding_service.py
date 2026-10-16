"""Real face detection and 512-dimensional face embedding extraction."""

import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from insightface.app import FaceAnalysis

from app.config import settings

logger = logging.getLogger("gjfashion.face_embedding_service")

_ALLOWED_ID = re.compile(r"^[A-Za-z0-9_-]{1,50}$")
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}

_face_app = None


def validate_employee_id(emp_id: str) -> str:
    emp_id = emp_id.strip()
    if not _ALLOWED_ID.fullmatch(emp_id):
        raise ValueError(
            "emp_id must contain only letters, numbers, underscores, "
            "or hyphens, and be at most 50 characters."
        )
    return emp_id


def get_face_app():
    """Load InsightFace once and reuse it."""
    global _face_app

    if _face_app is None:
        providers = (
            ["CUDAExecutionProvider", "CPUExecutionProvider"]
            if settings.FACE_USE_GPU
            else ["CPUExecutionProvider"]
        )

        app = FaceAnalysis(
            name=settings.FACE_MODEL_PACK,
            providers=providers,
        )
        app.prepare(
            ctx_id=0 if settings.FACE_USE_GPU else -1,
            det_size=(settings.FACE_DET_SIZE, settings.FACE_DET_SIZE),
        )
        _face_app = app
        logger.info("InsightFace loaded using providers: %s", providers)

    return _face_app


def extract_video_embeddings(
    video_path: str,
    original_filename: str,
) -> dict[str, Any]:
    """Sample a video and extract embeddings from clear, unambiguous faces."""

    suffix = Path(original_filename).suffix.lower()
    if suffix not in _VIDEO_EXTENSIONS:
        raise ValueError(
            "Unsupported video extension. Use mp4, mov, avi, mkv, webm, or m4v."
        )

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError("The uploaded video could not be opened.")

    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

        if fps > 0 and frame_count > 0:
            duration = frame_count / fps
            if duration > settings.FACE_ENROLLMENT_MAX_SECONDS:
                raise ValueError(
                    f"Video is too long. Maximum duration is "
                    f"{settings.FACE_ENROLLMENT_MAX_SECONDS} seconds."
                )

        interval = max(float(settings.FACE_ENROLLMENT_SAMPLE_SECONDS), 0.1)
        sample_limit = int(settings.FACE_ENROLLMENT_MAX_SAMPLES)
        min_samples = int(settings.FACE_ENROLLMENT_MIN_SAMPLES)
        min_score = float(settings.FACE_MIN_DETECTION_SCORE)
        min_side = int(settings.FACE_MIN_SIDE_PIXELS)
        ambiguous_ratio = float(settings.FACE_AMBIGUOUS_AREA_RATIO)

        face_app = get_face_app()
        embeddings: list[list[float]] = []
        sampled_frames = 0
        rejected_frames = 0
        next_sample_time = 0.0
        frame_index = 0

        while len(embeddings) < sample_limit:
            ok, frame = cap.read()
            if not ok:
                break

            if fps > 0:
                timestamp = frame_index / fps
            else:
                timestamp = next_sample_time

            frame_index += 1

            if timestamp + 1e-6 < next_sample_time:
                continue

            next_sample_time = timestamp + interval
            sampled_frames += 1

            faces = face_app.get(frame)
            candidates = []

            for face in faces:
                score = float(getattr(face, "det_score", 0.0))
                bbox = np.asarray(face.bbox, dtype=np.float32)

                if bbox.size != 4 or score < min_score:
                    continue

                x1, y1, x2, y2 = bbox.tolist()
                width = max(0.0, x2 - x1)
                height = max(0.0, y2 - y1)

                if min(width, height) < min_side:
                    continue

                embedding = getattr(face, "normed_embedding", None)
                if embedding is None:
                    continue

                vector = np.asarray(embedding, dtype=np.float32)
                if (
                    vector.ndim != 1
                    or vector.size != settings.FACE_EMBEDDING_DIM
                    or not np.isfinite(vector).all()
                    or float(np.linalg.norm(vector)) <= 1e-12
                ):
                    continue

                candidates.append({
                    "area": width * height,
                    "score": score,
                    "embedding": vector,
                })

            if not candidates:
                rejected_frames += 1
                continue

            candidates.sort(key=lambda item: item["area"], reverse=True)
            largest_area = candidates[0]["area"]

            # Avoid enrolling a frame if another face is nearly as prominent.
            similarly_sized_faces = [
                item for item in candidates
                if item["area"] >= largest_area * ambiguous_ratio
            ]
            if len(similarly_sized_faces) > 1:
                rejected_frames += 1
                continue

            embeddings.append(candidates[0]["embedding"].tolist())

        if len(embeddings) < min_samples:
            raise ValueError(
                f"Only {len(embeddings)} clear face samples were found. "
                f"At least {min_samples} are required. Use a longer video "
                "with a clearly visible face and minimal movement."
            )

        return {
            "facial_embeddings": embeddings,
            "sampled_frames": sampled_frames,
            "rejected_frames": rejected_frames,
            "accepted_samples": len(embeddings),
            "embedding_model": f"insightface-{settings.FACE_MODEL_PACK}",
        }

    finally:
        cap.release()


def save_employee_embeddings(
    emp_id: str,
    emp_name: str,
    result: dict[str, Any],
) -> Path:
    """Save embeddings in the JSON format expected by FaceMatcher."""

    emp_id = validate_employee_id(emp_id)
    emp_name = emp_name.strip()

    if not emp_name:
        raise ValueError("emp_name cannot be empty.")

    embeddings_dir = Path(settings.FACE_EMBEDDINGS_DIR)
    embeddings_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "emp_id": emp_id,
        "emp_name": emp_name,
        "embedding_type": "face",
        "is_placeholder": False,
        "embedding_model": result["embedding_model"],
        "embedding_dimension": settings.FACE_EMBEDDING_DIM,
        "source": "video_enrollment",
        "accepted_samples": result["accepted_samples"],
        "facial_embeddings": result["facial_embeddings"],
    }

    destination = embeddings_dir / f"{emp_id}_embeddings.json"
    temporary = embeddings_dir / f".{emp_id}_embeddings.tmp"

    temporary.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    temporary.replace(destination)

    return destination