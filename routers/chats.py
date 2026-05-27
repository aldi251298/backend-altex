"""
Chat history router.
CRUD operations for chat history.
"""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from database import async_session_factory
from models.chats import Chat

router = APIRouter()

# Anonymous user ID (no auth required)
ANONYMOUS_USER_ID = "anonymous"


@router.get("", summary="List chat (paginated, metadata only)")
async def list_chats(
    page: int = Query(1, ge=1),
    limit: int = Query(60, ge=1, le=100),
    archived: bool = Query(False),
    pinned_only: bool = Query(False),
):
    """List chat dengan pagination. No auth required."""
    result = await Chat.get_list(
        user_id=ANONYMOUS_USER_ID,
        page=page,
        limit=limit,
        archived=archived,
        pinned_only=pinned_only,
    )
    return result


@router.post("", summary="Buat chat baru", status_code=201)
async def create_chat(
    body: dict,
):
    """Buat chat baru. No auth required."""
    title = body.get("title", "Chat Baru")
    model = body.get("model")
    
    chat = await Chat.create(
        user_id=ANONYMOUS_USER_ID,
        title=title,
        model=model,
    )
    
    return chat.to_metadata()


@router.get("/{chat_id}", summary="Get chat dengan full history")
async def get_chat(
    chat_id: str,
):
    """Get chat dengan full conversation history. No auth required."""
    async with async_session_factory() as db:
        chat = await Chat.get_by_id(db, chat_id)
    
    if not chat:
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
):
    """Update chat metadata. No auth required."""
    async with async_session_factory() as db:
        chat = await Chat.get_by_id(db, chat_id)
        
        if not chat:
            raise HTTPException(
                status_code=404,
                detail="Chat tidak ditemukan",
            )
        
        if "title" in body:
            await Chat.update_title(db, chat_id, body["title"])
        
        if "is_pinned" in body:
            chat = await Chat.toggle_pin(db, chat_id, ANONYMOUS_USER_ID)
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
):
    """Hapus chat. No auth required."""
    async with async_session_factory() as db:
        success = await Chat.delete(db, chat_id, ANONYMOUS_USER_ID)
    
    if not success:
        raise HTTPException(
            status_code=404,
            detail="Chat tidak ditemukan",
        )
    
    return {"message": "Chat berhasil dihapus"}


@router.delete("", summary="Hapus semua chat user")
async def delete_all_chats(
):
    """Hapus semua chat. No auth required."""
    async with async_session_factory() as db:
        count = await Chat.delete_all(db, ANONYMOUS_USER_ID)
    return {"message": f"Dihapus {count} chat"}


@router.get("/{chat_id}/messages", summary="Get messages dari chat")
async def get_messages(
    chat_id: str,
):
    """Get semua messages dari chat. No auth required."""
    async with async_session_factory() as db:
        messages = await Chat.get_messages(db, chat_id, ANONYMOUS_USER_ID)
    
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
):
    """Tambah atau update message dalam chat. No auth required."""
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
):
    """Archive chat. No auth required."""
    async with async_session_factory() as db:
        success = await Chat.archive(db, chat_id, ANONYMOUS_USER_ID)
    
    if not success:
        raise HTTPException(
            status_code=404,
            detail="Chat tidak ditemukan",
        )
    
    return {"message": "Chat berhasil diarchive"}


@router.post("/{chat_id}/pin", summary="Pin/unpin chat")
async def toggle_pin(
    chat_id: str,
):
    """Toggle pin status chat. No auth required."""
    async with async_session_factory() as db:
        chat = await Chat.toggle_pin(db, chat_id, ANONYMOUS_USER_ID)
    
    if not chat:
        raise HTTPException(
            status_code=404,
            detail="Chat tidak ditemukan",
        )
    
    return {
        "id": chat.id,
        "is_pinned": chat.is_pinned,
    }
