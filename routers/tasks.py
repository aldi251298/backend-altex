"""
Background tasks router.
Manual endpoints untuk generate title dan tags.
"""

from fastapi import APIRouter
from utils.task import generate_chat_title, generate_chat_tags
from env import settings as app_settings

router = APIRouter()

# Anonymous user ID (no auth required)
ANONYMOUS_USER_ID = "anonymous"


@router.post("/title", summary="Manual generate title")
async def manual_generate_title(
    body: dict,
):
    """Generate title untuk chat. No auth required."""
    chat_id = body.get("chat_id")
    messages = body.get("messages", [])
    model_id = body.get("model", "")
    
    if not chat_id or not messages:
        raise HTTPException(status_code=422, detail="chat_id dan messages wajib diisi")
    
    user = {"id": ANONYMOUS_USER_ID}
    
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
):
    """Generate tags untuk chat. No auth required."""
    chat_id = body.get("chat_id")
    messages = body.get("messages", [])
    model_id = body.get("model", "")
    
    if not chat_id or not messages:
        raise HTTPException(status_code=422, detail="chat_id dan messages wajib diisi")
    
    tags = await generate_chat_tags(
        chat_id=chat_id,
        messages=messages,
        model_id=model_id,
        settings=app_settings,
    )
    
    return {"tags": tags}
