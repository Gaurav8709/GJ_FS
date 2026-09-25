"""
GJ-Fashion — User & CameraAccess ORM Models
"""

import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text,
)
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    """Application user (admin, manager, viewer)."""
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    username        = Column(String(80), unique=True, nullable=False)
    password_hash   = Column(String(255), nullable=False)
    name            = Column(String(150), nullable=False)
    role            = Column(String(30), default="viewer")  # admin, manager, viewer
    email           = Column(String(200), default="")
    active          = Column(Boolean, default=True)
    created_at      = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    camera_access = relationship("CameraAccess", back_populates="user", lazy="selectin")

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "name": self.name,
            "role": self.role,
            "email": self.email or "",
            "active": self.active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class CameraAccess(Base):
    """Grants a user access to view a specific camera."""
    __tablename__ = "camera_access"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    camera_id   = Column(String(30), nullable=False)    # cam1, cam2 ...
    granted_by  = Column(String(80), nullable=True)
    created_at  = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="camera_access")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "camera_id": self.camera_id,
            "granted_by": self.granted_by,
        }
