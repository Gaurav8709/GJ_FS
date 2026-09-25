"""
GJ-Fashion — Worker Schemas
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class WorkerCreate(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=150)
    role: str = "sales_associate"
    phone: str = ""
    shift: str = "day"


class WorkerUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    phone: Optional[str] = None
    shift: Optional[str] = None
    active: Optional[bool] = None


class WorkerResponse(BaseModel):
    id: int
    worker_id: str
    name: str
    role: str
    phone: str = ""
    shift: str
    active: bool
    created_at: Optional[str] = None

    model_config = {"from_attributes": True}


class AssignmentCreate(BaseModel):
    worker_id: int
    section_id: int
    shift: str = "day"
    date: Optional[datetime] = None


class AssignmentUpdate(BaseModel):
    shift: Optional[str] = None
    active: Optional[bool] = None


class AssignmentResponse(BaseModel):
    id: int
    worker_id: int
    section_id: int
    shift: str
    date: Optional[str] = None
    active: bool
    worker_name: Optional[str] = None
    section_name: Optional[str] = None

    model_config = {"from_attributes": True}
