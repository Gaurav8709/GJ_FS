"""Embedding-based employee recognition API.

The caller must supply a face embedding produced by the configured model.
This router does not accept raw images or generate vectors.
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.services.face_matcher import FaceMatcher

router = APIRouter(prefix="/api/recognition", tags=["Employee Recognition"])


def get_matcher() -> FaceMatcher:
    return FaceMatcher(
        threshold=settings.FACE_MATCH_THRESHOLD,
        expected_dimension=settings.FACE_EMBEDDING_DIM,
    )


class MatchRequest(BaseModel):
    embedding: List[float] = Field(..., min_length=1, max_length=2048)
    cam_id: Optional[str] = Field(default=None, max_length=50)
    track_id: Optional[str] = Field(default=None, max_length=100)


@router.post("/match")
async def match_employee(payload: MatchRequest):
    """Return the best employee match or Unknown."""
    try:
        result = get_matcher().match(payload.embedding)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result["cam_id"] = payload.cam_id
    result["track_id"] = payload.track_id
    return result


@router.get("/index/status")
async def recognition_index_status():
    """Report whether trusted employee face templates are available."""
    return get_matcher().index_status()
