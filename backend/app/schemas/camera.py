"""
GJ-Fashion — Camera Schemas
"""

from pydantic import BaseModel, Field
from typing import Optional


class CameraCreate(BaseModel):
    cam_id: str = Field(..., min_length=1, max_length=30)
    name: str = Field(..., min_length=1, max_length=150)
    rtsp_url: str = ""
    web_rtsp_url: Optional[str] = ""
    codec: Optional[str] = "H.264"
    section_id: Optional[int] = None
    floor_id: Optional[int] = None
    location: str = ""
    active: bool = True
    footfall_enabled: Optional[bool] = True
    heatmap_enabled: Optional[bool] = True
    analytics_config: Optional[str] = ""
    inside_point: Optional[str] = None


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    rtsp_url: Optional[str] = None
    web_rtsp_url: Optional[str] = None
    codec: Optional[str] = None
    section_id: Optional[int] = None
    floor_id: Optional[int] = None
    location: Optional[str] = None
    active: Optional[bool] = None
    footfall_enabled: Optional[bool] = None
    heatmap_enabled: Optional[bool] = None
    analytics_config: Optional[str] = None
    inside_point: Optional[str] = None


class CameraResponse(BaseModel):
    id: int
    cam_id: str
    name: str
    rtsp_url: str
    web_rtsp_url: Optional[str] = ""
    codec: Optional[str] = "H.264"
    section_id: Optional[int] = None
    floor_id: Optional[int] = None
    location: str = ""
    active: bool
    footfall_enabled: bool = True
    heatmap_enabled: bool = True
    analytics_config: Optional[str] = ""
    inside_point: Optional[str] = None
    zone_count: int = 0
    created_at: Optional[str] = None

    model_config = {"from_attributes": True}
