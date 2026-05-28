"""
Files router.
Upload, list, dan delete files untuk RAG.
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from constants import ALLOWED_FILE_TYPES, MAX_FILE_SIZE
from database import async_session_factory
from models.files import File as FileModel

router = APIRouter()

# Anonymous user ID (no auth required)
ANONYMOUS_USER_ID = "anonymous"

ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".json", ".csv", ".jpg", ".jpeg", ".png", ".webp", ".gif"}


@router.post("/upload", summary="Upload file (multipart/form-data)", status_code=201)
async def upload_file(
    file: UploadFile = File(...),
):
    """Upload file untuk RAG. No auth required."""
    if file.content_type not in ALLOWED_FILE_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Tipe file tidak didukung: {file.content_type}",
        )
    
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if f".{ext}" not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Ekstensi file tidak didukung: .{ext}",
        )
    
    content = await file.read()
    
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File terlalu besar (max 50MB)",
        )
    
    import uuid
    import os
    from datetime import datetime, timezone
    from env import settings
    
    file_id = str(uuid.uuid4())
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    
    os.makedirs(settings.upload_dir, exist_ok=True)
    
    file_ext = os.path.splitext(file.filename)[1]
    storage_path = os.path.join(settings.upload_dir, f"{file_id}{file_ext}")
    with open(storage_path, "wb") as f:
        f.write(content)
    
    collection_name = f"col_{file_id.replace('-', '')}"
    await FileModel.create(
        file_id=file_id,
        user_id=ANONYMOUS_USER_ID,
        filename=file.filename,
        content_type=file.content_type,
        file_path=storage_path,
        collection_name=collection_name,
        chunk_count=0,
        size_bytes=len(content),
    )
    
    return {
        "id": file_id,
        "filename": file.filename,
        "collection_name": collection_name,
        "size": len(content),
        "chunk_count": 0,
        "created_at": now_ms,
    }


@router.get("", summary="List file")
async def list_files(
    page: int = 1,
):
    """List files. No auth required."""
    async with async_session_factory() as db:
        result = await FileModel.get_by_user(db, ANONYMOUS_USER_ID, page=page)
    return result


@router.get("/{file_id}", summary="Get file metadata")
async def get_file(
    file_id: str,
):
    """Get file metadata. No auth required."""
    async with async_session_factory() as db:
        file_obj = await FileModel.get_by_id(db, file_id)
    
    if not file_obj:
        raise HTTPException(status_code=404, detail="File tidak ditemukan")
    
    return file_obj.to_dict()


from fastapi.responses import FileResponse

@router.get("/{file_id}/download", summary="Download file")
async def download_file(file_id: str):
    """Serve file for multimodal image_url or direct download. No auth required."""
    async with async_session_factory() as db:
        file_obj = await FileModel.get_by_id(db, file_id)
    if not file_obj:
        raise HTTPException(status_code=404, detail="File tidak ditemukan")
    return FileResponse(
        file_obj.file_path,
        media_type=file_obj.content_type or "application/octet-stream",
        filename=file_obj.filename,
    )

@router.delete("/{file_id}", summary="Hapus file + koleksi vector")
async def delete_file(
    file_id: str,
):
    """Hapus file. No auth required."""
    async with async_session_factory() as db:
        success = await FileModel.delete(db, file_id, ANONYMOUS_USER_ID)
    
    if not success:
        raise HTTPException(status_code=404, detail="File tidak ditemukan")
    
    return {"message": "File berhasil dihapus"}
