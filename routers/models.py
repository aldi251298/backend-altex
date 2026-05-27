"""
Models router.
List dan manage AI models dari semua provider.
"""

from fastapi import APIRouter, Depends

from database import async_session_factory
from utils.auth import get_verified_user
from utils.models import get_all_models, refresh_model_cache
from models.providers import Provider

router = APIRouter()


@router.get("", summary="Aggregated list dari semua provider")
async def list_models(
    user=Depends(get_verified_user),
):
    """
    Fetch dan aggregate models dari semua provider.
    Menggunakan cache 5 menit.
    """
    async with async_session_factory() as db:
        providers = await Provider.get_active(db)
    models = await get_all_models(user, providers)
    
    return {"data": models}


@router.post("/refresh", summary="Force refresh cache model list")
async def refresh_models():
    """Force refresh model cache."""
    await refresh_model_cache()
    return {"message": "Model cache berhasil di-refresh"}


@router.get("/{model_id}", summary="Detail model spesifik")
async def get_model_detail(
    model_id: str,
    user=Depends(get_verified_user),
):
    """Get detail model spesifik."""
    async with async_session_factory() as db:
        providers = await Provider.get_active(db)
    models = await get_all_models(user, providers)
    
    model = next((m for m in models if m["id"] == model_id), None)
    
    if not model:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Model tidak ditemukan")
    
    return model
