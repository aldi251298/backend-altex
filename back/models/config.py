"""
AppConfig SQLAlchemy ORM model.
Stores PersistentConfig values in database.
"""

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, MappedAsDataclass
from sqlalchemy import select

from constants import time_ns
from database import Base


class AppConfig(Base):
    """Application configuration model for PersistentConfig."""

    __tablename__ = "app_config"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    config_path: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False
    )
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[int] = mapped_column(nullable=False)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "config_path": self.config_path,
            "value": self.value,
            "updated_at": self.updated_at,
        }

    @staticmethod
    async def get_by_path(db, config_path: str) -> "AppConfig | None":
        """Get config by path."""
        result = await db.execute(
            select(AppConfig).where(AppConfig.config_path == config_path)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(db) -> dict:
        """Get all configs as dict of path -> value."""
        result = await db.execute(select(AppConfig))
        configs = result.scalars().all()
        return {c.config_path: c.value for c in configs}

    @staticmethod
    async def set_value(
        db, config_path: str, value, updated_at: int | None = None
    ) -> "AppConfig":
        """Set or update a config value."""
        import uuid

        existing = await AppConfig.get_by_path(db, config_path)
        if existing:
            existing.value = value
            existing.updated_at = updated_at or time_ns()
            await db.commit()
            await db.refresh(existing)
            return existing
        else:
            config = AppConfig(
                id=str(uuid.uuid4()),
                config_path=config_path,
                value=value,
                updated_at=updated_at or time_ns(),
            )
            db.add(config)
            await db.commit()
            await db.refresh(config)
            return config

    @staticmethod
    async def delete(db, config_path: str) -> bool:
        """Delete a config."""
        config = await AppConfig.get_by_path(db, config_path)
        if config:
            await db.delete(config)
            await db.commit()
            return True
        return False
