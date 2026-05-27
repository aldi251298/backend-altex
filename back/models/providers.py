"""
Provider SQLAlchemy ORM model.
Stores AI provider connections and configurations.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, MappedAsDataclass
from sqlalchemy import select

from constants import time_ns
from database import Base, async_session_factory


class Provider(Base):
    """AI provider connection model."""

    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_type: Mapped[str] = mapped_column(
        String(30), default="bearer"
    )  # bearer | azure_ad | system_oauth | session | none
    prefix: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    extra_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[int] = mapped_column(nullable=False)
    updated_at: Mapped[int] = mapped_column(nullable=False)

    def to_dict(self, mask_key: bool = True) -> dict:
        """Convert to dictionary (optionally mask API key)."""
        result = {
            "id": self.id,
            "name": self.name,
            "base_url": self.base_url,
            "auth_type": self.auth_type,
            "prefix": self.prefix,
            "is_active": self.is_active,
            "extra_config": self.extra_config,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if mask_key:
            result["api_key"] = "****" if self.api_key else None
        else:
            result["api_key"] = self.api_key
        return result

    @staticmethod
    async def create(
        name: str,
        base_url: str,
        api_key: str | None = None,
        auth_type: str = "bearer",
        prefix: str | None = None,
        extra_config: dict | None = None,
    ) -> "Provider":
        """Create a new provider."""
        import uuid

        provider = Provider(
            id=str(uuid.uuid4()),
            name=name,
            base_url=base_url,
            api_key=api_key,
            auth_type=auth_type,
            prefix=prefix,
            is_active=True,
            extra_config=extra_config or {},
            created_at=time_ns(),
            updated_at=time_ns(),
        )

        async with async_session_factory() as db:
            db.add(provider)
            await db.commit()
            await db.refresh(provider)
        return provider

    @staticmethod
    async def get_by_id(db, provider_id: str) -> "Provider | None":
        """Get provider by ID."""
        result = await db.execute(
            select(Provider).where(Provider.id == provider_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(db) -> list["Provider"]:
        """Get all providers."""
        result = await db.execute(select(Provider).order_by(Provider.created_at.desc()))
        return list(result.scalars().all())

    @staticmethod
    async def get_active(db) -> list["Provider"]:
        """Get all active providers."""
        result = await db.execute(
            select(Provider)
            .where(Provider.is_active == True)
            .order_by(Provider.name)
        )
        return list(result.scalars().all())

    @staticmethod
    async def update(
        db,
        provider_id: str,
        **kwargs,
    ) -> "Provider | None":
        """Update provider fields."""
        result = await db.execute(
            select(Provider).where(Provider.id == provider_id)
        )
        provider = result.scalar_one_or_none()
        if not provider:
            return None

        for key, value in kwargs.items():
            if hasattr(provider, key):
                setattr(provider, key, value)

        provider.updated_at = time_ns()
        await db.commit()
        await db.refresh(provider)
        return provider

    @staticmethod
    async def delete(db, provider_id: str) -> bool:
        """Delete provider."""
        result = await db.execute(
            select(Provider).where(Provider.id == provider_id)
        )
        provider = result.scalar_one_or_none()
        if provider:
            await db.delete(provider)
            await db.commit()
            return True
        return False

    @staticmethod
    async def get_by_name(db, name: str) -> "Provider | None":
        """Get provider by name."""
        result = await db.execute(
            select(Provider).where(Provider.name == name)
        )
        return result.scalar_one_or_none()
