"""
GJ-Fashion — DetectionLog & Alert ORM Models
"""

import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Float, JSON
)
from app.database import Base


class DetectionLog(Base):
    """Periodic snapshot of detection counts per camera/zone."""
    __tablename__ = "detection_logs"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    camera_id       = Column(String(30), nullable=False)
    zone_id         = Column(Integer, nullable=True)
    zone_name       = Column(String(100), default="")
    person_count    = Column(Integer, default=0)
    required_count  = Column(Integer, default=0)
    status          = Column(String(30), default="ok")    # ok, warning, alert
    metadata_json   = Column(JSON, default=dict)         # extra data (bbox summary, etc.)
    created_at      = Column(DateTime, default=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "camera_id": self.camera_id,
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "person_count": self.person_count,
            "required_count": self.required_count,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Alert(Base):
    """Generated when a zone is in shortage for longer than the alert delay."""
    __tablename__ = "alerts"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    camera_id       = Column(String(30), nullable=False)
    zone_id         = Column(Integer, nullable=True)
    zone_name       = Column(String(100), default="")
    alert_type      = Column(String(50), default="worker_shortage")
    detected_count  = Column(Integer, default=0)
    required_count  = Column(Integer, default=0)
    message         = Column(Text, default="")
    screenshot_path = Column(String(500), nullable=True)
    acknowledged    = Column(Boolean, default=False)
    acknowledged_by = Column(String(50), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    created_at      = Column(DateTime, default=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "camera_id": self.camera_id,
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "alert_type": self.alert_type,
            "detected_count": self.detected_count,
            "required_count": self.required_count,
            "message": self.message,
            "screenshot_path": self.screenshot_path,
            "acknowledged": self.acknowledged,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
