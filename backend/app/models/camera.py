"""
GJ-Fashion — Camera & CameraZone ORM Models
"""

import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Float, JSON
)
from sqlalchemy.orm import relationship
from app.database import Base


class Camera(Base):
    """An RTSP camera feed in the showroom."""
    __tablename__ = "cameras"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    cam_id      = Column(String(30), unique=True, nullable=False)   # cam1, cam2, ...
    name        = Column(String(150), nullable=False)
    rtsp_url    = Column(String(500), nullable=False)
    web_rtsp_url= Column(String(500), default="", nullable=True)
    codec       = Column(String(50), default="H.264", nullable=True)
    section_id  = Column(Integer, ForeignKey("sections.id", ondelete="SET NULL"), nullable=True)
    floor_id    = Column(Integer, ForeignKey("floors.id", ondelete="SET NULL"), nullable=True)
    location    = Column(String(200), default="")                   # human description
    active      = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    zones = relationship("CameraZone", back_populates="camera", lazy="selectin",
                         cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "cam_id": self.cam_id,
            "name": self.name,
            "rtsp_url": self.rtsp_url or "",
            "web_rtsp_url": self.web_rtsp_url or "",
            "codec": self.codec or "H.264",
            "section_id": self.section_id,
            "floor_id": self.floor_id,
            "location": self.location or "",
            "active": self.active,
            "zone_count": len(self.zones) if self.zones else 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class CameraZone(Base):
    """
    A polygon zone drawn on a camera view.
    polygon_points is JSONB: [[x1,y1],[x2,y2],...] — normalized 0.0–1.0.
    color is BGR hex string, e.g. '#00FF00'.
    """
    __tablename__ = "camera_zones"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    camera_id       = Column(Integer, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False)
    zone_name       = Column(String(100), nullable=False)
    zone_type       = Column(String(50), default="monitoring")      # monitoring, restricted, entrance
    polygon_points  = Column(JSON, nullable=False)                 # [[x,y], ...] normalised
    color           = Column(String(20), default="#00FF00")         # overlay colour
    opacity         = Column(Float, default=0.15)
    required_count  = Column(Integer, default=1)                    # min workers required
    max_count       = Column(Integer, default=0)                    # 0 = unlimited
    alert_enabled   = Column(Boolean, default=True)
    active          = Column(Boolean, default=True)
    created_at      = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    camera = relationship("Camera", back_populates="zones")

    def to_dict(self):
        return {
            "id": self.id,
            "camera_id": self.camera_id,
            "zone_name": self.zone_name,
            "zone_type": self.zone_type,
            "polygon_points": self.polygon_points,
            "color": self.color,
            "opacity": self.opacity,
            "required_count": self.required_count,
            "max_count": self.max_count,
            "alert_enabled": self.alert_enabled,
            "active": self.active,
        }
