"""
File Upload Router
"""
import os
import shutil
import uuid
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from app.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/upload", tags=["Upload"])

UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

@router.post("", response_model=dict)
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    """上传文件并返回存储路径"""
    try:
        # Generate unique filename
        ext = os.path.splitext(file.filename)[1]
        unique_name = f"{uuid.uuid4()}{ext}"
        file_path = os.path.join(UPLOAD_DIR, unique_name)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        return {
            "filename": file.filename,
            "path": file_path,
            "url": f"/api/upload/files/{unique_name}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")
