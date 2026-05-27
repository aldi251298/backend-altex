"""
Chat SQLAlchemy ORM model.
Stores chat metadata and full conversation history as JSONB.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, select, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, MappedAsDataclass

from constants import DEFAULT_CHAT_TITLE, time_ns
from database import Base, async_session_factory


class Chat(Base):
    """Chat model storing conversation history."""

    __tablename__ = "chats"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(
        Text, default=DEFAULT_CHAT_TITLE
    )
    chat: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    share_id: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    folder_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)

    def to_metadata(self) -> dict:
        """Extract chat metadata for list view (avoid full JSONB)."""
        # Try to extract model_id from chat JSON
        model_id = None
        if isinstance(self.chat, dict):
            model_id = self.chat.get("models", [None])[0]

        return {
            "id": self.id,
            "title": self.title,
            "model_id": model_id,
            "is_pinned": self.is_pinned,
            "updated_at": self.updated_at,
            "folder_id": self.folder_id,
        }

    @staticmethod
    async def create(
        user_id: str,
        title: str = DEFAULT_CHAT_TITLE,
        model: str | None = None,
    ) -> "Chat":
        """Create a new chat."""
        import uuid

        chat_data = {
            "title": title,
            "history": {"messages": {}, "currentId": None},
            "models": [model] if model else [],
            "tags": [],
            "files": [],
        }

        chat = Chat(
            id=str(uuid.uuid4()),
            user_id=user_id,
            title=title,
            chat=chat_data,
            created_at=time_ns(),
            updated_at=time_ns(),
            is_pinned=False,
            is_archived=False,
            is_shared=False,
        )

        async with async_session_factory() as db:
            db.add(chat)
            await db.commit()
            await db.refresh(chat)
        return chat

    @staticmethod
    async def get_list(
        user_id: str,
        page: int = 1,
        limit: int = 60,
        archived: bool = False,
        pinned_only: bool = False,
    ) -> dict:
        """Get paginated chat list (metadata only, not full JSONB)."""
        async with async_session_factory() as db:
            base_query = (
                select(Chat)
                .where(Chat.user_id == user_id)
                .where(Chat.is_archived == archived)
            )

            if pinned_only:
                base_query = base_query.where(Chat.is_pinned == True)

            # Get total count
            count_query = select(func.count(Chat.id)).where(
                Chat.user_id == user_id,
                Chat.is_archived == archived,
            )
            if pinned_only:
                count_query = count_query.where(Chat.is_pinned == True)

            count_result = await db.execute(count_query)
            total = count_result.scalar() or 0

            # Get paginated results
            offset = (page - 1) * limit
            query = (
                base_query
                .order_by(Chat.is_pinned.desc(), Chat.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )

            result = await db.execute(query)
            chats = result.scalars().all()

            return {
                "data": [chat.to_metadata() for chat in chats],
                "total": total,
                "page": page,
                "has_more": (page * limit) < total,
            }

    @staticmethod
    async def get_by_id(db, chat_id: str) -> "Chat | None":
        """Get chat by ID with full history."""
        result = await db.execute(select(Chat).where(Chat.id == chat_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def update(db, chat_id: str, **kwargs) -> "Chat | None":
        """Update chat fields."""
        result = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat = result.scalar_one_or_none()
        if not chat:
            return None

        for key, value in kwargs.items():
            if hasattr(chat, key):
                setattr(chat, key, value)

        chat.updated_at = time_ns()
        await db.commit()
        await db.refresh(chat)
        return chat

    @staticmethod
    async def upsert_message(
        db,
        chat_id: str,
        message_id: str,
        message_data: dict,
    ) -> bool:
        """
        Update a single message within chat JSONB.
        Uses PostgreSQL jsonb_set for atomic update.
        """
        import json

        from sqlalchemy import text

        msg_path = '{history,messages,' + message_id + '}'
        await db.execute(
            text(f"""
                UPDATE chats
                SET
                    chat = jsonb_set(
                        jsonb_set(
                            chat,
            '{msg_path}',
                            :message_data::jsonb,
                            true
                        ),
                        '{{history,currentId}}',
                        :current_id::jsonb,
                        true
                    ),
                    updated_at = :updated_at
                WHERE id = :chat_id
            """),
            {
                "message_data": json.dumps(message_data),
                "current_id": json.dumps(message_id),
                "chat_id": chat_id,
                "updated_at": time_ns(),
            }
        )
        await db.commit()
        return True

    @staticmethod
    async def update_title(db, chat_id: str, title: str) -> bool:
        """Update chat title."""
        chat = await Chat.get_by_id(db, chat_id)
        if not chat:
            return False

        chat.title = title
        if isinstance(chat.chat, dict):
            chat.chat["title"] = title
        chat.updated_at = time_ns()

        await db.commit()
        return True

    @staticmethod
    async def archive(db, chat_id: str, user_id: str) -> bool:
        """Archive a chat."""
        result = await db.execute(
            select(Chat).where(
                Chat.id == chat_id,
                Chat.user_id == user_id,
            )
        )
        chat = result.scalar_one_or_none()
        if not chat:
            return False

        chat.is_archived = True
        chat.updated_at = time_ns()
        await db.commit()
        return True

    @staticmethod
    async def toggle_pin(db, chat_id: str, user_id: str) -> "Chat | None":
        """Toggle pin status of a chat."""
        result = await db.execute(
            select(Chat).where(
                Chat.id == chat_id,
                Chat.user_id == user_id,
            )
        )
        chat = result.scalar_one_or_none()
        if not chat:
            return None

        chat.is_pinned = not chat.is_pinned
        chat.updated_at = time_ns()
        await db.commit()
        await db.refresh(chat)
        return chat

    @staticmethod
    async def delete(db, chat_id: str, user_id: str) -> bool:
        """Delete a chat."""
        result = await db.execute(
            select(Chat).where(
                Chat.id == chat_id,
                Chat.user_id == user_id,
            )
        )
        chat = result.scalar_one_or_none()
        if chat:
            await db.delete(chat)
            await db.commit()
            return True
        return False

    @staticmethod
    async def delete_all(db, user_id: str) -> int:
        """Delete all chats for a user."""
        result = await db.execute(
            select(Chat).where(Chat.user_id == user_id)
        )
        chats = result.scalars().all()
        count = len(chats)
        for chat in chats:
            await db.delete(chat)
        await db.commit()
        return count

    @staticmethod
    async def get_messages(db, chat_id: str, user_id: str) -> dict | None:
        """Get messages from a chat."""
        result = await db.execute(
            select(Chat).where(
                Chat.id == chat_id,
                Chat.user_id == user_id,
            )
        )
        chat = result.scalar_one_or_none()
        if not chat:
            return None

        history = chat.chat.get("history", {})
        messages = history.get("messages", {})

        # Convert to list sorted by timestamp
        message_list = []
        for msg_id, msg_data in messages.items():
            if isinstance(msg_data, dict):
                msg_data["id"] = msg_id
                message_list.append(msg_data)

        message_list.sort(key=lambda m: m.get("timestamp", 0))

        return {
            "id": chat.id,
            "title": chat.title,
            "messages": message_list,
            "model_id": chat.chat.get("models", [None])[0] if isinstance(chat.chat, dict) else None,
        }
