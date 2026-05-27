"""
User SQLAlchemy ORM model.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, MappedAsDataclass

from constants import time_ns
from database import Base


class User(Base):
    """User model for authentication and authorization."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True
    )  # UUID as string
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="user"
    )  # 'admin' | 'user'
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True
    )
    settings: Mapped[dict] = mapped_column(
        JSONB, default=dict
    )  # User preferences
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)

    def to_dict(self) -> dict:
        """Convert to dictionary (excluding password)."""
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "role": self.role,
            "is_active": self.is_active,
            "settings": self.settings,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_response(self) -> dict:
        """Convert to API response format."""
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "role": self.role,
            "is_active": self.is_active,
            "settings": self.settings,
        }

    @staticmethod
    async def create(
        db,
        email: str,
        name: str,
        hashed_password: str,
        role: str = "user",
    ) -> "User":
        """Create a new user."""
        import uuid

        now_ns = int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            name=name,
            hashed_password=hashed_password,
            role=role,
            is_active=True,
            settings={},
            created_at=now_ns,
            updated_at=now_ns,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def get_by_email(db, email: str) -> "User | None":
        """Get user by email."""
        from sqlalchemy import select

        result = await db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_id(db, user_id: str) -> "User | None":
        """Get user by ID."""
        from sqlalchemy import select

        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(db, page: int = 1, limit: int = 50) -> dict:
        """Get paginated list of users."""
        from sqlalchemy import func, select

        # Get total count
        count_result = await db.execute(select(func.count(User.id)))
        total = count_result.scalar()

        # Get paginated users
        offset = (page - 1) * limit
        result = await db.execute(
            select(User)
            .order_by(User.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        users = result.scalars().all()

        return {
            "data": [u.to_response() for u in users],
            "total": total,
            "page": page,
            "has_more": (page * limit) < total,
        }

    @staticmethod
    async def update(db, user_id: str, **kwargs) -> "User | None":
        """Update user fields."""
        from sqlalchemy import select

        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return None

        for key, value in kwargs.items():
            if hasattr(user, key) and key != "hashed_password":
                setattr(user, key, value)

        user.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def delete(db, user_id: str) -> bool:
        """Delete user by ID."""
        from sqlalchemy import select
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if user:
            await db.delete(user)
            await db.commit()
            return True
        return False
