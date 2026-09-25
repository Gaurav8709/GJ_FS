"""
GJ-Fashion — Detection & Alert Schemas
"""

from pydantic import BaseModel
from typing import Optional, List


class DetectionLogResponse(BaseModel):
    id: int
    camera_id: str
    zone_id: Optional[int] = None
    zone_name: str = ""
    person_count: int
    required_count: int
    status: str
    created_at: Optional[str] = None

    model_config = {"from_attributes": True}


class AlertResponse(BaseModel):
    id: int
    camera_id: str
    zone_id: Optional[int] = None
    zone_name: str = ""
    alert_type: str
    detected_count: int
    required_count: int
    message: str = ""
    screenshot_path: Optional[str] = None
    acknowledged: bool
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[str] = None
    created_at: Optional[str] = None

    model_config = {"from_attributes": True}


class AlertAcknowledge(BaseModel):
    acknowledged_by: str
