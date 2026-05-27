"""
Provider management router.
CRUD operations dan test connection untuk AI providers.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

import httpx

from database import async_session_factory
from models.providers import Provider
from utils.auth import get_verified_user
from constants import time_ns

router = APIRouter()


# ============================================================================
# Endpoints
# ============================================================================


@router.get("", summary="List semua provider")
async def list_providers():
    """List semua provider (aktif dan non-aktif)."""
    async with async_session_factory() as db:
        providers = await Provider.get_all(db)
    return {"data": [p.to_dict() for p in providers]}


@router.post("", summary="Tambah provider baru", status_code=201)
async def create_provider(
    body: dict,
    user=Depends(get_verified_user),
):
    """Tambah provider baru."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Hanya admin yang bisa tambah provider")
    
    name = body.get("name")
    base_url = body.get("base_url")
    
    if not name or not base_url:
        raise HTTPException(
            status_code=422,
            detail="name dan base_url wajib diisi",
        )
    
    provider = await Provider.create(
        name=name,
        base_url=base_url,
        api_key=body.get("api_key"),
        auth_type=body.get("auth_type", "bearer"),
        prefix=body.get("prefix"),
        extra_config=body.get("extra_config", {}),
    )
    
    return provider.to_dict()


@router.get("/{provider_id}", summary="Detail provider")
async def get_provider(
    provider_id: str,
):
    """Get detail provider."""
    async with async_session_factory() as db:
        provider = await Provider.get_by_id(db, provider_id)
    
    if not provider:
        raise HTTPException(status_code=404, detail="Provider tidak ditemukan")
    
    return provider.to_dict()


@router.put("/{provider_id}", summary="Update provider")
async def update_provider(
    provider_id: str,
    body: dict,
    user=Depends(get_verified_user),
):
    """Update provider."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Hanya admin yang bisa update provider")
    
    async with async_session_factory() as db:
        provider = await Provider.get_by_id(db, provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider tidak ditemukan")
        
        updated = await Provider.update(
            db,
            provider_id,
            **{k: v for k, v in body.items() if k != "id"},
        )
        
        return updated.to_dict() if updated else {}


@router.delete("/{provider_id}", summary="Hapus provider")
async def delete_provider(
    provider_id: str,
    user=Depends(get_verified_user),
):
    """Hapus provider."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Hanya admin yang bisa hapus provider")
    
    async with async_session_factory() as db:
        success = await Provider.delete(db, provider_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Provider tidak ditemukan")
    
    return {"message": "Provider berhasil dihapus"}


@router.post("/{provider_id}/test", summary="Test koneksi ke provider")
async def test_provider_connection(
    provider_id: str,
):
    """Test koneksi ke provider."""
    async with async_session_factory() as db:
        provider = await Provider.get_by_id(db, provider_id)
    
    if not provider:
        raise HTTPException(status_code=404, detail="Provider tidak ditemukan")
    
    start_time = time_ns()
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{provider.base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {provider.api_key or ''}"},
            )
            
            elapsed = (time_ns() - start_time) / 1_000_000  # ms
            
            if response.status_code == 200:
                return {
                    "success": True,
                    "message": "Koneksi berhasil",
                    "response_time_ms": round(elapsed, 2),
                }
            else:
                return {
                    "success": False,
                    "message": f"HTTP {response.status_code}",
                    "response_time_ms": round(elapsed, 2),
                }
    
    except Exception as e:
        return {
            "success": False,
            "message": f"Koneksi gagal: {str(e)}",
            "response_time_ms": 0,
        }
