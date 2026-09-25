"""
GJ-Fashion — Floor & Section ORM Models
"""

import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text,
)
from sqlalchemy.orm import relationship
from app.database import Base


class Floor(Base):
    """A physical floor in the showroom building."""
    __tablename__ = "floors"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(100), unique=True, nullable=False)
    code        = Column(String(20), unique=True, nullable=False)
    description = Column(Text, default="")
    sort_order  = Column(Integer, default=0)
    active      = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    sections = relationship("Section", back_populates="floor", lazy="selectin")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "description": self.description or "",
            "sort_order": self.sort_order,
            "active": self.active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Section(Base):
    """A named section/area within a floor (e.g. 'Men\'s Formal', 'Accessories')."""
    __tablename__ = "sections"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    floor_id    = Column(Integer, ForeignKey("floors.id", ondelete="CASCADE"), nullable=False)
    name        = Column(String(150), nullable=False)
    code        = Column(String(30), unique=True, nullable=False)
    description = Column(Text, default="")
    sort_order  = Column(Integer, default=0)
    active      = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    floor = relationship("Floor", back_populates="sections")

    def to_dict(self):
        return {
            "id": self.id,
            "floor_id": self.floor_id,
            "name": self.name,
            "code": self.code,
            "description": self.description or "",
            "sort_order": self.sort_order,
            "active": self.active,
            "floor_name": self.floor.name if self.floor else None,
        }
