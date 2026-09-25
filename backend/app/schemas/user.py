"""
GJ-Fashion — User & Auth Schemas
"""

from pydantic import BaseModel, Field
from typing import Optional, List


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    token: str
    user: dict


class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=80)
    password: str = Field(..., min_length=4)
    name: str = Field(..., min_length=1, max_length=150)
    role: str = "viewer"
    email: str = ""


class UserUpdate(BaseModel):
    name: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None
    active: Optional[bool] = None


class UserResponse(BaseModel):
    id: int
    username: str
    name: str
    role: str
    email: str = ""
    active: bool
    created_at: Optional[str] = None

    model_config = {"from_attributes": True}


class FloorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    code: str = Field(..., min_length=1, max_length=20)
    description: str = ""
    sort_order: int = 0


class FloorUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    active: Optional[bool] = None


class SectionCreate(BaseModel):
    floor_id: int
    name: str = Field(..., min_length=1, max_length=150)
    code: str = Field(..., min_length=1, max_length=30)
    description: str = ""
    sort_order: int = 0


class SectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    active: Optional[bool] = None
