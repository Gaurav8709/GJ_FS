"""
GJ-Fashion AI Smart Showroom — Configuration
Loads all settings from .env via pydantic-settings.
"""
from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):

    
    # Employee vs customer classification
    EMPLOYEE_CLASSIFIER_MODEL_PATH: str = Field(default="best.pt")


    # Face recognition matching
    FACE_MATCH_THRESHOLD: float = Field(default=0.45)
    FACE_EMBEDDING_DIM: int = Field(default=512)

    # Face detection and video enrollment
    FACE_MODEL_PACK: str = Field(default="buffalo_l")
    FACE_USE_GPU: bool = Field(default=False)
    FACE_DET_SIZE: int = Field(default=640)
    FACE_MIN_DETECTION_SCORE: float = Field(default=0.60)
    FACE_MIN_SIDE_PIXELS: int = Field(default=40)
    FACE_AMBIGUOUS_AREA_RATIO: float = Field(default=0.60)

    FACE_EMBEDDINGS_DIR: str = Field(
        default=str(
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "cv_embeddings"
        )
    )

    FACE_ENROLLMENT_SAMPLE_SECONDS: float = Field(default=0.50)
    FACE_ENROLLMENT_MIN_SAMPLES: int = Field(default=3)
    FACE_ENROLLMENT_MAX_SAMPLES: int = Field(default=40)
    FACE_ENROLLMENT_MAX_SECONDS: int = Field(default=300)
    FACE_ENROLLMENT_MAX_UPLOAD_MB: int = Field(default=200)

    """Application settings loaded from environment variables / .env file."""

    # ── Database ──────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:password@localhost:5432/gjfashiondb",
        description="Async PostgreSQL / AWS RDS connection string",
    )

    # ── AWS S3 & RDS Configuration ───────────────────────────
    AWS_ACCESS_KEY_ID: Optional[str] = Field(default=None)
    AWS_SECRET_ACCESS_KEY: Optional[str] = Field(default=None)
    AWS_REGION: str = Field(default="ap-south-1")
    S3_BUCKET_NAME: Optional[str] = Field(default=None)

    # ── Security ──────────────────────────────────────────────
    SECRET_KEY: str = Field(default="change-me-in-production")
    JWT_ALGORITHM: str = Field(default="HS256")
    JWT_EXPIRY_HOURS: int = Field(default=24)

    # ── RTSP / Camera ────────────────────────────────────────
    RTSP_BASE: str = Field(
        default="rtsp://65.1.214.31:8554",
        description="Base RTSP URL — cameras append /gj/camN",
    )

    # ── YOLO ─────────────────────────────────────────────────
    YOLO_MODEL_PATH: str = Field(default="yolov8m.pt")
    YOLO_CONFIDENCE: float = Field(default=0.40)
    YOLO_MIN_BOX_AREA_RATIO: float = Field(
        default=0.0001,
        description="Min bbox area as ratio of frame area to filter noise",
    )

    # ── Alerts ───────────────────────────────────────────────
    ALERT_DELAY_SECONDS: int = Field(
        default=30,
        description="Seconds of continuous shortage before alert fires",
    )
    ALERT_COOLDOWN_SECONDS: int = Field(
        default=60,
        description="Minimum seconds between repeated alerts for same zone",
    )
    SCREENSHOT_DELAY_SECONDS: int = Field(default=15)

    # ── Paths ────────────────────────────────────────────────
    SCREENSHOTS_DIR: str = Field(default="screenshots")

    # ── Inference ────────────────────────────────────────────
    INFERENCE_FPS: float = Field(
        default=5.0,
        description="Target inference rate (frames per second)",
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


# Singleton — import this everywhere
settings = Settings()



 