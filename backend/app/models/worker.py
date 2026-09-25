"""
GJ-Fashion — Worker & WorkerAssignment ORM Models
"""

import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text,
)
from sqlalchemy.orm import relationship
from app.database import Base


class Worker(Base):
    """A showroom worker / sales associate."""
    __tablename__ = "workers"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    worker_id   = Column(String(50), unique=True, nullable=False)   # W-001, W-002
    name        = Column(String(150), nullable=False)
    role        = Column(String(80), default="sales_associate")
    phone       = Column(String(20), default="")
    shift       = Column(String(30), default="day")                 # day, night, rotating
    active      = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    assignments = relationship("WorkerAssignment", back_populates="worker", lazy="selectin")

    def to_dict(self):
        return {
            "id": self.id,
            "worker_id": self.worker_id,
            "name": self.name,
            "role": self.role,
            "phone": self.phone or "",
            "shift": self.shift,
            "active": self.active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class WorkerAssignment(Base):
    """Assigns a worker to a section for a given date/shift."""
    __tablename__ = "worker_assignments"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    worker_id   = Column(Integer, ForeignKey("workers.id", ondelete="CASCADE"), nullable=False)
    section_id  = Column(Integer, ForeignKey("sections.id", ondelete="CASCADE"), nullable=False)
    shift       = Column(String(30), default="day")
    date        = Column(DateTime, default=datetime.datetime.utcnow)
    active      = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    worker  = relationship("Worker", back_populates="assignments")
    section = relationship("Section")

    def to_dict(self):
        return {
            "id": self.id,
            "worker_id": self.worker_id,
            "section_id": self.section_id,
            "shift": self.shift,
            "date": self.date.isoformat() if self.date else None,
            "active": self.active,
            "worker_name": self.worker.name if self.worker else None,
            "section_name": self.section.name if self.section else None,
        }
