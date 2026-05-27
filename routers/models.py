"""
Models router.
List dan manage AI models dari semua provider.
"""

from fastapi import APIRouter, HTTPException

from database import async_session_factory
from utils.models import get_all_models, refresh_model_cache
from models.providers import Provider

router = APIRouter()

# Anonymous user ID (no auth required)
ANONYMOUS_USER_ID = "anonymous"


@router.get("", summary="Aggregated list dari semua provider")
async def list_models(
):
    """
    Fetch dan aggregate models dari semua provider.
    No auth required.
    """
    async with async_session_factory() as db:
        providers = await Provider.get_active(db)
    models = await get_all_models(None, providers)
    
    return {"data": models}


@router.post("/refresh", summary="Force refresh cache model list")
async def refresh_models():
    """Force refresh model cache. No auth required."""
    await refresh_model_cache()
    return {"message": "Model cache berhasil di-refresh"}


@router.get("/{model_id}", summary="Detail model spesifik")
async def get_model_detail(
    model_id: str,
):
    """Get detail model spesifik. No auth required."""
    async with async_session_factory() as db:
        providers = await Provider.get_active(db)
    models = await get_all_models(None, providers)
    
    model = next((m for m in models if m["id"] == model_id), None)
    
    if not model:
        raise HTTPException(status_code=404, detail="Model tidak ditemukan")
    
    return model
