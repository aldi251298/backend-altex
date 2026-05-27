"""
Chat history router.
CRUD operations for chat history.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from database import async_session_factory
from models.chats import Chat
from utils.auth import get_verified_user

router = APIRouter()


# ============================================================================
# Endpoints
# ============================================================================


@router.get("", summary="List chat (paginated, metadata only)")
async def list_chats(
    page: int = Query(1, ge=1),
    limit: int = Query(60, ge=1, le=100),
    archived: bool = Query(False),
    pinned_only: bool = Query(False),
    user=Depends(get_verified_user),
):
    """
    List chat dengan pagination.
    HANYA return metadata (BUKAN full JSONB) untuk performa.
    """
    result = await Chat.get_list(
        user_id=user["id"],
        page=page,
        limit=limit,
        archived=archived,
        pinned_only=pinned_only,
    )
    return result


@router.post("", summary="Buat chat baru", status_code=201)
async def create_chat(
    body: dict,
    user=Depends(get_verified_user),
):
    """Buat chat baru."""
    title = body.get("title", "Chat Baru")
    model = body.get("model")
    
    chat = await Chat.create(
        user_id=user["id"],
        title=title,
        model=model,
    )
    
    return chat.to_metadata()


@router.get("/{chat_id}", summary="Get chat dengan full history")
async def get_chat(
    chat_id: str,
    user=Depends(get_verified_user),
):
    """Get chat dengan full conversation history."""
    async with async_session_factory() as db:
        chat = await Chat.get_by_id(db, chat_id)
    
    if not chat or chat.user_id != user["id"]:
        raise HTTPException(
            status_code=404,
            detail="Chat tidak ditemukan",
        )
    
    return {
        "id": chat.id,
        "title": chat.title,
        "is_pinned": chat.is_pinned,
        "is_archived": chat.is_archived,
        "updated_at": chat.updated_at,
        "chat": chat.chat,
    }


@router.put("/{chat_id}", summary="Update chat (title, tags, pinned)")
async def update_chat(
    chat_id: str,
    body: dict,
    user=Depends(get_verified_user),
):
    """Update chat metadata."""
    async with async_session_factory() as db:
        chat = await Chat.get_by_id(db, chat_id)
        
        if not chat or chat.user_id != user["id"]:
            raise HTTPException(
                status_code=404,
                detail="Chat tidak ditemukan",
            )
        
        # Update allowed fields
        if "title" in body:
            await Chat.update_title(db, chat_id, body["title"])
        
        if "is_pinned" in body:
            chat = await Chat.toggle_pin(db, chat_id, user["id"])
            if not chat:
                raise HTTPException(
                    status_code=404,
                    detail="Chat tidak ditemukan",
                )
        
        if "tags" in body:
            chat.chat["tags"] = body["tags"]
            await db.commit()
        
        return {
            "id": chat.id,
            "title": chat.title,
            "is_pinned": chat.is_pinned,
            "tags": chat.chat.get("tags", []),
            "updated_at": chat.updated_at,
        }


@router.delete("/{chat_id}", summary="Hapus chat")
async def delete_chat(
    chat_id: str,
    user=Depends(get_verified_user),
):
    """Hapus chat."""
    async with async_session_factory() as db:
        success = await Chat.delete(db, chat_id, user["id"])
    
    if not success:
        raise HTTPException(
            status_code=404,
            detail="Chat tidak ditemukan",
        )
    
    return {"message": "Chat berhasil dihapus"}


@router.delete("", summary="Hapus semua chat user")
async def delete_all_chats(
    user=Depends(get_verified_user),
):
    """Hapus semua chat milik user."""
    async with async_session_factory() as db:
        count = await Chat.delete_all(db, user["id"])
    return {"message": f"Dihapus {count} chat"}


@router.get("/{chat_id}/messages", summary="Get messages dari chat")
async def get_messages(
    chat_id: str,
    user=Depends(get_verified_user),
):
    """Get semua messages dari chat."""
    async with async_session_factory() as db:
        messages = await Chat.get_messages(db, chat_id, user["id"])
    
    if not messages:
        raise HTTPException(
            status_code=404,
            detail="Chat tidak ditemukan",
        )
    
    return messages


@router.post("/{chat_id}/messages", summary="Tambah/update message")
async def upsert_message(
    chat_id: str,
    message_id: str,
    message_data: dict,
    user=Depends(get_verified_user),
):
    """Tambah atau update message dalam chat."""
    async with async_session_factory() as db:
        success = await Chat.upsert_message(db, chat_id, message_id, message_data)
    
    if not success:
        raise HTTPException(
            status_code=404,
            detail="Chat tidak ditemukan",
        )
    
    return {"message": "Message berhasil disimpan"}


@router.post("/{chat_id}/archive", summary="Archive chat")
async def archive_chat(
    chat_id: str,
    user=Depends(get_verified_user),
):
    """Archive chat."""
    async with async_session_factory() as db:
        success = await Chat.archive(db, chat_id, user["id"])
    
    if not success:
        raise HTTPException(
            status_code=404,
            detail="Chat tidak ditemukan",
        )
    
    return {"message": "Chat berhasil diarchive"}


@router.post("/{chat_id}/pin", summary="Pin/unpin chat")
async def toggle_pin(
    chat_id: str,
    user=Depends(get_verified_user),
):
    """Toggle pin status chat."""
    async with async_session_factory() as db:
        chat = await Chat.toggle_pin(db, chat_id, user["id"])
    
    if not chat:
        raise HTTPException(
            status_code=404,
            detail="Chat tidak ditemukan",
        )
    
    return {
        "id": chat.id,
        "is_pinned": chat.is_pinned,
    }
