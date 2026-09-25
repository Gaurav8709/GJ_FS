"""
GJ-Fashion AI Smart Showroom — Configuration
Loads all settings from .env via pydantic-settings.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
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
