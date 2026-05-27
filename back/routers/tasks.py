"""
Background tasks router.
Manual endpoints untuk generate title dan tags.
"""

from fastapi import APIRouter, Depends
from utils.auth import get_verified_user
from utils.task import generate_chat_title, generate_chat_tags
from env import settings as app_settings

router = APIRouter()


@router.post("/title", summary="Manual generate title")
async def manual_generate_title(
    body: dict,
    user=Depends(get_verified_user),
):
    """
    Generate title untuk chat secara manual.
    """
    chat_id = body.get("chat_id")
    messages = body.get("messages", [])
    model_id = body.get("model", "")
    
    if not chat_id or not messages:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="chat_id dan messages wajib diisi")
    
    title = await generate_chat_title(
        chat_id=chat_id,
        messages=messages,
        model_id=model_id,
        user=user,
        settings=app_settings,
    )
    
    return {"title": title}


@router.post("/tags", summary="Manual generate tags")
async def manual_generate_tags(
    body: dict,
    user=Depends(get_verified_user),
):
    """
    Generate tags untuk chat secara manual.
    """
    chat_id = body.get("chat_id")
    messages = body.get("messages", [])
    model_id = body.get("model", "")
    
    if not chat_id or not messages:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="chat_id dan messages wajib diisi")
    
    tags = await generate_chat_tags(
        chat_id=chat_id,
        messages=messages,
        model_id=model_id,
        settings=app_settings,
    )
    
    return {"tags": tags}
