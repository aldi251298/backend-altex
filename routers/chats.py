"""
Chat history router — full CRUD + search, share, clone, folder, messages.
No auth required (anonymous user).
"""

import copy
import uuid as uuid_module

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from constants import time_ns
from database import async_session_factory
from models.chats import Chat

router = APIRouter()

ANONYMOUS_USER_ID = "anonymous"


# ============================================================================
# List / Create
# ============================================================================


@router.get("", summary="List chat (paginated, metadata only)")
async def list_chats(
    page: int = Query(1, ge=1),
    limit: int = Query(60, ge=1, le=200),
    archived: bool = Query(False),
    pinned_only: bool = Query(False),
    folder_id: str | None = Query(None),
):
    result = await Chat.get_list(
        user_id=ANONYMOUS_USER_ID,
        page=page,
        limit=limit,
        archived=archived,
        pinned_only=pinned_only,
    )
    if folder_id is not None:
        result["data"] = [c for c in result["data"] if c.get("folder_id") == folder_id]
    return result


@router.post("", summary="Buat chat baru", status_code=201)
async def create_chat(body: dict):
    """
    Buat chat baru.
    Supports both minimal {title, model} and full OpenWebUI-style {id, chat} payloads.
    """
    chat_data = body.get("chat")

    if chat_data and isinstance(chat_data, dict):
        # Full chat object (OpenWebUI style)
        chat_id = body.get("id") or str(uuid_module.uuid4())
        now = time_ns()
        title = chat_data.get("title", body.get("title", "Chat Baru"))
        chat_obj = Chat(
            id=chat_id,
            user_id=ANONYMOUS_USER_ID,
            title=title,
            chat=chat_data,
            created_at=now,
            updated_at=now,
            is_pinned=False,
            is_archived=False,
            is_shared=False,
        )
        async with async_session_factory() as db:
            db.add(chat_obj)
            await db.commit()
            await db.refresh(chat_obj)
        return _chat_response(chat_obj)

    chat = await Chat.create(
        user_id=ANONYMOUS_USER_ID,
        title=body.get("title", "Chat Baru"),
        model=body.get("model"),
    )
    return _chat_response(chat)


# ============================================================================
# Search
# ============================================================================


@router.get("/search", summary="Cari chat berdasarkan judul")
async def search_chats(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
):
    async with async_session_factory() as db:
        result = await db.execute(
            select(Chat)
            .where(
                Chat.user_id == ANONYMOUS_USER_ID,
                Chat.is_archived == False,
                Chat.title.ilike(f"%{q}%"),
            )
            .order_by(Chat.updated_at.desc())
            .limit(limit)
        )
        chats = result.scalars().all()

    return {"data": [c.to_metadata() for c in chats], "query": q, "total": len(chats)}


# ============================================================================
# Single chat CRUD
# ============================================================================


@router.get("/{chat_id}", summary="Get chat dengan full history")
async def get_chat(chat_id: str):
    async with async_session_factory() as db:
        chat = await Chat.get_by_id(db, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat tidak ditemukan")
    return _chat_response(chat)


@router.put("/{chat_id}", summary="Update chat")
async def update_chat(chat_id: str, body: dict):
    """
    Update chat. Supports:
    - {chat: {...}}  — full chat object replace (OpenWebUI style)
    - {title, is_pinned, folder_id, tags}  — partial update
    """
    async with async_session_factory() as db:
        result = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat = result.scalar_one_or_none()
        if not chat:
            raise HTTPException(status_code=404, detail="Chat tidak ditemukan")

        if "chat" in body and isinstance(body["chat"], dict):
            chat.chat = body["chat"]
            if "title" in body["chat"]:
                chat.title = body["chat"]["title"]

        if "title" in body:
            chat.title = body["title"]
            if isinstance(chat.chat, dict):
                chat.chat = {**chat.chat, "title": body["title"]}

        if "is_pinned" in body:
            chat.is_pinned = bool(body["is_pinned"])

        if "is_archived" in body:
            chat.is_archived = bool(body["is_archived"])

        if "folder_id" in body:
            chat.folder_id = body["folder_id"]

        if "tags" in body and isinstance(chat.chat, dict):
            chat.chat = {**chat.chat, "tags": body["tags"]}

        chat.updated_at = time_ns()
        await db.commit()
        await db.refresh(chat)

    return _chat_response(chat)


@router.delete("/{chat_id}", summary="Hapus chat")
async def delete_chat(chat_id: str):
    async with async_session_factory() as db:
        success = await Chat.delete(db, chat_id, ANONYMOUS_USER_ID)
    if not success:
        raise HTTPException(status_code=404, detail="Chat tidak ditemukan")
    return {"message": "Chat berhasil dihapus"}


@router.delete("", summary="Hapus semua chat")
async def delete_all_chats():
    async with async_session_factory() as db:
        count = await Chat.delete_all(db, ANONYMOUS_USER_ID)
    return {"message": f"Dihapus {count} chat"}


# ============================================================================
# Messages
# ============================================================================


@router.get("/{chat_id}/messages", summary="Get messages dari chat")
async def get_messages(chat_id: str):
    async with async_session_factory() as db:
        messages = await Chat.get_messages(db, chat_id, ANONYMOUS_USER_ID)
    if not messages:
        raise HTTPException(status_code=404, detail="Chat tidak ditemukan")
    return messages


@router.post("/{chat_id}/messages", summary="Tambah/update message")
async def upsert_message(chat_id: str, body: dict):
    """
    Upsert message dalam chat.
    Body: { "id": "...", "role": "user|assistant|tool", "content": "..." }
    """
    message_id = body.get("id") or str(uuid_module.uuid4())
    if not body.get("role"):
        raise HTTPException(status_code=422, detail="Field 'role' wajib diisi")

    async with async_session_factory() as db:
        chat = await Chat.get_by_id(db, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat tidak ditemukan")
        body["id"] = message_id
        await Chat.upsert_message(db, chat_id, message_id, body)

    return {"id": message_id, "message": "Message berhasil disimpan"}


@router.put("/{chat_id}/messages/{message_id}", summary="Update message spesifik")
async def update_message(chat_id: str, message_id: str, body: dict):
    async with async_session_factory() as db:
        chat = await Chat.get_by_id(db, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat tidak ditemukan")

        history = (chat.chat or {}).get("history", {})
        messages = history.get("messages", {})
        if message_id not in messages:
            raise HTTPException(status_code=404, detail="Message tidak ditemukan")

        existing = dict(messages[message_id])
        existing.update(body)
        existing["id"] = message_id
        await Chat.upsert_message(db, chat_id, message_id, existing)

    return {"id": message_id, "message": "Message berhasil diupdate"}


@router.delete("/{chat_id}/messages/{message_id}", summary="Hapus message spesifik")
async def delete_message(chat_id: str, message_id: str):
    from sqlalchemy import text

    async with async_session_factory() as db:
        chat = await Chat.get_by_id(db, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat tidak ditemukan")

        msg_path = "{" + f"history,messages,{message_id}" + "}"
        await db.execute(
            text(f"""
                UPDATE chats
                SET chat = chat #- '{msg_path}',
                    updated_at = :updated_at
                WHERE id = :chat_id
            """),
            {"chat_id": chat_id, "updated_at": time_ns()},
        )
        await db.commit()

    return {"message": "Message berhasil dihapus"}


# ============================================================================
# Archive / Pin / Share / Clone / Folder
# ============================================================================


@router.post("/{chat_id}/archive", summary="Toggle archive chat")
async def toggle_archive(chat_id: str, body: dict | None = None):
    async with async_session_factory() as db:
        result = await db.execute(
            select(Chat).where(Chat.id == chat_id, Chat.user_id == ANONYMOUS_USER_ID)
        )
        chat = result.scalar_one_or_none()
        if not chat:
            raise HTTPException(status_code=404, detail="Chat tidak ditemukan")

        if body and "is_archived" in body:
            chat.is_archived = bool(body["is_archived"])
        else:
            chat.is_archived = not chat.is_archived

        chat.updated_at = time_ns()
        await db.commit()
        await db.refresh(chat)

    return {"id": chat.id, "is_archived": chat.is_archived}


@router.post("/{chat_id}/pin", summary="Toggle pin chat")
async def toggle_pin(chat_id: str):
    async with async_session_factory() as db:
        chat = await Chat.toggle_pin(db, chat_id, ANONYMOUS_USER_ID)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat tidak ditemukan")
    return {"id": chat.id, "is_pinned": chat.is_pinned}


@router.post("/{chat_id}/share", summary="Toggle share chat")
async def toggle_share(chat_id: str):
    """Share/unshare chat. Returns share_id when shared."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(Chat).where(Chat.id == chat_id, Chat.user_id == ANONYMOUS_USER_ID)
        )
        chat = result.scalar_one_or_none()
        if not chat:
            raise HTTPException(status_code=404, detail="Chat tidak ditemukan")

        if chat.is_shared:
            chat.is_shared = False
            chat.share_id = None
        else:
            chat.is_shared = True
            chat.share_id = str(uuid_module.uuid4()).replace("-", "")[:12]

        chat.updated_at = time_ns()
        await db.commit()
        await db.refresh(chat)

    return {"id": chat.id, "is_shared": chat.is_shared, "share_id": chat.share_id}


@router.get("/share/{share_id}", summary="Get shared chat by share_id")
async def get_shared_chat(share_id: str):
    async with async_session_factory() as db:
        result = await db.execute(
            select(Chat).where(Chat.share_id == share_id, Chat.is_shared == True)
        )
        chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Shared chat tidak ditemukan")
    return {"id": chat.id, "title": chat.title, "updated_at": chat.updated_at, "chat": chat.chat}


@router.post("/{chat_id}/clone", summary="Clone chat")
async def clone_chat(chat_id: str):
    async with async_session_factory() as db:
        original = await Chat.get_by_id(db, chat_id)
        if not original:
            raise HTTPException(status_code=404, detail="Chat tidak ditemukan")

        now = time_ns()
        cloned_data = copy.deepcopy(original.chat) if isinstance(original.chat, dict) else {}
        cloned_title = f"[Clone] {original.title}"
        if isinstance(cloned_data, dict):
            cloned_data["title"] = cloned_title

        new_chat = Chat(
            id=str(uuid_module.uuid4()),
            user_id=ANONYMOUS_USER_ID,
            title=cloned_title,
            chat=cloned_data,
            created_at=now,
            updated_at=now,
            is_pinned=False,
            is_archived=False,
            is_shared=False,
        )
        db.add(new_chat)
        await db.commit()
        await db.refresh(new_chat)

    return _chat_response(new_chat)


@router.post("/{chat_id}/folder", summary="Pindahkan chat ke folder")
async def move_to_folder(chat_id: str, body: dict):
    folder_id = body.get("folder_id")
    async with async_session_factory() as db:
        result = await db.execute(
            select(Chat).where(Chat.id == chat_id, Chat.user_id == ANONYMOUS_USER_ID)
        )
        chat = result.scalar_one_or_none()
        if not chat:
            raise HTTPException(status_code=404, detail="Chat tidak ditemukan")
        chat.folder_id = folder_id
        chat.updated_at = time_ns()
        await db.commit()
        await db.refresh(chat)
    return {"id": chat.id, "folder_id": chat.folder_id}


# ============================================================================
# Helpers
# ============================================================================


def _chat_response(chat: Chat) -> dict:
    return {
        "id": chat.id,
        "title": chat.title,
        "is_pinned": chat.is_pinned,
        "is_archived": chat.is_archived,
        "is_shared": chat.is_shared,
        "share_id": chat.share_id,
        "folder_id": chat.folder_id,
        "created_at": chat.created_at,
        "updated_at": chat.updated_at,
        "chat": chat.chat,
    }
