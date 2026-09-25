"""
GJ-Fashion — FRS, Forensics, Footfall, Face Alert, and Heatmap ORM Models
"""

import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Float, JSON
)
from app.database import Base


class ForensicClip(Base):
    """Stores Assigned Employee videos, metadata, and listener JSON outputs for CV embeddings."""
    __tablename__ = "forensic_clips"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    title       = Column(String(200), nullable=False)
    category    = Column(String(50), default="frs")              # frs, forensic, assign_employee
    cam_id      = Column(String(30), nullable=True)
    emp_id      = Column(String(50), nullable=True)
    emp_name    = Column(String(150), nullable=True)
    role        = Column(String(100), nullable=True)
    shift       = Column(String(50), default="Morning")           # Morning, Afternoon, Day, Night
    file_url    = Column(String(500), nullable=False)
    metadata_json = Column(JSON, nullable=True)                  # Tags, location, duration
    listener_json = Column(JSON, nullable=True)                  # JSON format generated for CV team
    status      = Column(String(30), default="processed")         # pending, processing, processed
    created_at  = Column(DateTime, default=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "cam_id": self.cam_id,
            "emp_id": self.emp_id,
            "emp_name": self.emp_name,
            "role": self.role,
            "shift": self.shift,
            "file_url": self.file_url,
            "metadata_json": self.metadata_json or {},
            "listener_json": self.listener_json or {},
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class FootfallRecord(Base):
    """Tracks real-time footfall (+1/-1), gender, and age group breakdown with timestamps."""
    __tablename__ = "footfall_records"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    cam_id      = Column(String(30), nullable=False)
    entries     = Column(Integer, default=0)                      # +1 count
    exits       = Column(Integer, default=0)                      # -1 count
    net_count   = Column(Integer, default=0)
    male_count  = Column(Integer, default=0)
    female_count = Column(Integer, default=0)
    age_0_9     = Column(Integer, default=0)
    age_10_17   = Column(Integer, default=0)
    age_18_25   = Column(Integer, default=0)
    age_26_35   = Column(Integer, default=0)
    age_36_50   = Column(Integer, default=0)
    age_50_plus = Column(Integer, default=0)
    timestamp   = Column(DateTime, default=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "cam_id": self.cam_id,
            "entries": self.entries,
            "exits": self.exits,
            "net_count": self.net_count,
            "male_count": self.male_count,
            "female_count": self.female_count,
            "age_breakdown": {
                "0_9": self.age_0_9 or 0,
                "10_17": self.age_10_17 or 0,
                "18_25": self.age_18_25 or 0,
                "26_35": self.age_26_35 or 0,
                "36_50": self.age_36_50 or 0,
                "50_plus": self.age_50_plus or 0,
            },
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }



class EmployeeFace(Base):
    """Master database for employee faces, IDs, and metadata for Face Alert detection."""
    __tablename__ = "employee_faces"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    emp_id      = Column(String(50), unique=True, nullable=False)
    emp_name    = Column(String(150), nullable=False)
    department  = Column(String(100), default="Sales")
    role        = Column(String(100), default="Staff")
    face_url    = Column(String(500), nullable=True)
    meta_info   = Column(JSON, nullable=True)
    created_at  = Column(DateTime, default=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "emp_id": self.emp_id,
            "emp_name": self.emp_name,
            "department": self.department,
            "role": self.role,
            "face_url": self.face_url or "",
            "meta_info": self.meta_info or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class CameraHeatmap(Base):
    """Camera-specific heatmaps sent by Computer Vision team."""
    __tablename__ = "camera_heatmaps"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    cam_id      = Column(String(30), nullable=False)
    image_url   = Column(String(500), nullable=False)
    peak_density = Column(Float, default=0.0)
    meta_info   = Column(JSON, nullable=True)
    created_at  = Column(DateTime, default=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "cam_id": self.cam_id,
            "image_url": self.image_url,
            "peak_density": self.peak_density,
            "meta_info": self.meta_info or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EmployeeDetectionLog(Base):
    """Stores real-time employee detection events sent by CV team when detected on any camera."""
    __tablename__ = "employee_detections"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    emp_id       = Column(String(50), nullable=False)
    emp_name     = Column(String(150), nullable=False)
    cam_id       = Column(String(30), nullable=False)
    location     = Column(String(100), nullable=True)
    confidence   = Column(Float, default=0.95)
    snapshot_url = Column(String(500), nullable=True)
    meta_info    = Column(JSON, nullable=True)
    timestamp    = Column(DateTime, default=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "emp_id": self.emp_id,
            "emp_name": self.emp_name,
            "cam_id": self.cam_id,
            "location": self.location or f"Camera {self.cam_id}",
            "confidence": self.confidence,
            "snapshot_url": self.snapshot_url or "",
            "meta_info": self.meta_info or {},
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }

