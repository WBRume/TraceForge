"""
File upload routes.
"""

import os
import shutil
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.core.logging import get_logger
from app.dependencies import get_current_user
from app.domains.auth.models.user import User

router = APIRouter(prefix="/upload", tags=["Upload"])
logger = get_logger(__name__)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("", response_model=dict)
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Upload a file and return its local path metadata."""
    _ = current_user

    try:
        ext = os.path.splitext(file.filename or "")[1]
        unique_name = f"{uuid.uuid4()}{ext}"
        file_path = os.path.join(UPLOAD_DIR, unique_name)

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        return {
            "filename": file.filename,
            "path": file_path,
            "url": f"/api/upload/files/{unique_name}",
        }
    except Exception as exc:
        logger.exception(f"Upload API error: {exc}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}")


@router.get("/files/{file_name}")
async def get_uploaded_file(
    file_name: str,
    current_user: User = Depends(get_current_user),
):
    """Serve an uploaded file by generated file name."""
    _ = current_user
    upload_root = os.path.abspath(UPLOAD_DIR)
    file_path = os.path.abspath(os.path.join(upload_root, file_name))
    if not file_path.startswith(upload_root + os.sep):
        raise HTTPException(status_code=400, detail="Invalid file path")
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)
