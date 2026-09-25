"""
GJ-Fashion — Zone Schemas
"""

from pydantic import BaseModel, Field
from typing import List, Optional


class ZoneCreate(BaseModel):
    camera_id: int
    zone_name: str = Field(..., min_length=1, max_length=100)
    zone_type: str = "monitoring"
    polygon_points: List[List[float]] = Field(
        ..., description="List of [x,y] pairs, normalised 0.0–1.0"
    )
    color: str = "#00FF00"
    opacity: float = 0.15
    required_count: int = 1
    max_count: int = 0
    alert_enabled: bool = True


class ZoneUpdate(BaseModel):
    zone_name: Optional[str] = None
    zone_type: Optional[str] = None
    polygon_points: Optional[List[List[float]]] = None
    color: Optional[str] = None
    opacity: Optional[float] = None
    required_count: Optional[int] = None
    max_count: Optional[int] = None
    alert_enabled: Optional[bool] = None
    active: Optional[bool] = None


class ZoneResponse(BaseModel):
    id: int
    camera_id: int
    zone_name: str
    zone_type: str
    polygon_points: List[List[float]]
    color: str
    opacity: float
    required_count: int
    max_count: int
    alert_enabled: bool
    active: bool

    model_config = {"from_attributes": True}
