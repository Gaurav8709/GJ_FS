"""Authenticated employee face enrollment from uploaded videos."""

import logging
import tempfile
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)

from app.config import settings
from app.services.face_embedding_service import (
    extract_video_embeddings,
    save_employee_embeddings,
    validate_employee_id,
)
from app.utils.auth import get_current_user_id

router = APIRouter(
    prefix="/api/recognition",
    tags=["Employee Recognition"],
)

logger = logging.getLogger("gjfashion.face_enrollment")

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


@router.post("/enroll-video")
async def enroll_employee_video(
    emp_id: str = Form(...),
    emp_name: str = Form(...),
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id),
):
    """Create real face embeddings from an employee video."""

    try:
        emp_id = validate_employee_id(emp_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    emp_name = emp_name.strip()
    if not emp_name:
        raise HTTPException(status_code=422, detail="emp_name cannot be empty.")

    filename = file.filename or ""
    extension = Path(filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Upload a supported video: mp4, mov, avi, mkv, webm, or m4v.",
        )

    max_bytes = int(settings.FACE_ENROLLMENT_MAX_UPLOAD_MB) * 1024 * 1024
    temp_path = None

    try:
        # Read at most one byte beyond the limit to detect oversized uploads.
        content = await file.read(max_bytes + 1)

        if not content:
            raise HTTPException(status_code=400, detail="Uploaded video is empty.")

        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Video exceeds the upload limit of "
                    f"{settings.FACE_ENROLLMENT_MAX_UPLOAD_MB} MB."
                ),
            )

        with tempfile.NamedTemporaryFile(
            suffix=extension,
            delete=False,
        ) as temp_file:
            temp_file.write(content)
            temp_path = temp_file.name

        result = extract_video_embeddings(temp_path, filename)

        output_path = save_employee_embeddings(
            emp_id=emp_id,
            emp_name=emp_name,
            result=result,
        )

        logger.info(
            "Face enrollment completed for employee %s by user %s",
            emp_id,
            user_id,
        )

        return {
            "status": "enrolled",
            "emp_id": emp_id,
            "emp_name": emp_name,
            "accepted_samples": result["accepted_samples"],
            "sampled_frames": result["sampled_frames"],
            "rejected_frames": result["rejected_frames"],
            "embedding_dimension": settings.FACE_EMBEDDING_DIM,
            "embedding_model": result["embedding_model"],
            "saved_file": output_path.name,
            "message": (
                "Face embeddings saved. The recognition index can now "
                "load this employee's templates."
            ),
        }

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Employee video enrollment failed.")
        raise HTTPException(
            status_code=500,
            detail="Video enrollment failed. Check the server logs.",
        ) from exc
    finally:
        await file.close()
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)