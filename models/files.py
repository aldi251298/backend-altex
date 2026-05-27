"""
File SQLAlchemy ORM model.
Stores metadata for uploaded files used in RAG.
"""

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, MappedAsDataclass
from sqlalchemy import select, func

from constants import time_ns
from database import Base, async_session_factory


class File(Base):
    """File upload metadata model."""

    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    collection_name: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[int] = mapped_column(nullable=False)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "filename": self.filename,
            "content_type": self.content_type,
            "file_path": self.file_path,
            "collection_name": self.collection_name,
            "chunk_count": self.chunk_count,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
        }

    @staticmethod
    async def create(
        file_id: str,
        user_id: str,
        filename: str,
        content_type: str,
        file_path: str,
        collection_name: str,
        chunk_count: int = 0,
        size_bytes: int = 0,
    ) -> "File":
        """Create a new file record."""
        file_obj = File(
            id=file_id,
            user_id=user_id,
            filename=filename,
            content_type=content_type,
            file_path=file_path,
            collection_name=collection_name,
            chunk_count=chunk_count,
            size_bytes=size_bytes,
            created_at=time_ns(),
        )

        async with async_session_factory() as db:
            db.add(file_obj)
            await db.commit()
            await db.refresh(file_obj)
        return file_obj

    @staticmethod
    async def get_by_id(db, file_id: str) -> "File | None":
        """Get file by ID."""
        result = await db.execute(
            select(File).where(File.id == file_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_collection_name(db, collection_name: str) -> "File | None":
        """Get file by collection name."""
        result = await db.execute(
            select(File).where(File.collection_name == collection_name)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_user(db, user_id: str, page: int = 1, limit: int = 50) -> dict:
        """Get paginated file list for a user."""
        # Get total count
        count_result = await db.execute(
            select(func.count(File.id)).where(File.user_id == user_id)
        )
        total = count_result.scalar() or 0

        # Get paginated files
        offset = (page - 1) * limit
        result = await db.execute(
            select(File)
            .where(File.user_id == user_id)
            .order_by(File.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        files = result.scalars().all()

        return {
            "data": [f.to_dict() for f in files],
            "total": total,
            "page": page,
            "has_more": (page * limit) < total,
        }

    @staticmethod
    async def delete(db, file_id: str, user_id: str) -> bool:
        """Delete file record."""
        result = await db.execute(
            select(File).where(
                File.id == file_id,
                File.user_id == user_id,
            )
        )
        file_obj = result.scalar_one_or_none()
        if file_obj:
            await db.delete(file_obj)
            await db.commit()
            return True
        return False

    @staticmethod
    async def get_collection_names_by_ids(db, file_ids: list[str]) -> list[str]:
        """Get collection names for multiple file IDs."""
        if not file_ids:
            return []

        result = await db.execute(
            select(File.collection_name).where(File.id.in_(file_ids))
        )
        return [row[0] for row in result.all()]
