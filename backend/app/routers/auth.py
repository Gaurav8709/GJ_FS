"""
GJ-Fashion — Auth Router
POST /api/auth/login    — authenticate and return JWT
GET  /api/auth/me       — get current user info
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User, CameraAccess
from app.schemas.user import LoginRequest, LoginResponse, UserResponse
from app.utils.auth import (
    hash_password, verify_password, create_access_token, get_current_user_id,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate user and return a JWT token."""
    result = await db.execute(
        select(User).where(User.username == body.username, User.active == True)
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    token = create_access_token({"sub": str(user.id), "role": user.role})

    # Get camera access list
    access_result = await db.execute(
        select(CameraAccess.camera_id).where(CameraAccess.user_id == user.id)
    )
    cam_access = [row[0] for row in access_result.all()]

    return {
        "token": token,
        "user": {
            **user.to_dict(),
            "cam_access": cam_access,
        },
    }


@router.get("/me")
async def me(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get the current authenticated user's profile."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    access_result = await db.execute(
        select(CameraAccess.camera_id).where(CameraAccess.user_id == user.id)
    )
    cam_access = [row[0] for row in access_result.all()]

    return {**user.to_dict(), "cam_access": cam_access}
