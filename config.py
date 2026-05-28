"""
PersistentConfig System

Konfigurasi yang:
1. Dibaca dari environment variable saat startup (priority tertinggi)
2. Jika tidak ada env var, dibaca dari database
3. Jika tidak ada di DB, gunakan default value
4. Perubahan via Admin API langsung efektif tanpa restart server
"""

import os
from typing import Any, Callable, Generic, Optional, TypeVar

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class PersistentConfig(Generic[T]):
    """
    Runtime configuration yang bisa diubah tanpa restart.
    
    Priority:
    1. Environment variable (tertinggi)
    2. Database (app_config table)
    3. Default value
    """

    def __init__(
        self,
        env_name: str,
        config_path: str,
        default_value: T,
        parser: Optional[Callable[[str], T]] = None,
    ):
        self.env_name = env_name
        self.config_path = config_path
        self.default_value = default_value
        self._parser = parser or (lambda x: x)
        self._value: T = self._load_initial_value()

    def _parse(self, value: str) -> T:
        """Parse string value to typed value."""
        try:
            return self._parser(value)
        except (ValueError, TypeError):
            return self.default_value

    def _load_initial_value(self) -> T:
        """Load initial value from highest priority source."""
        # Priority 1: Environment variable
        env_value = os.environ.get(self.env_name)
        if env_value is not None:
            return self._parse(env_value)

        # Priority 2: Database (akan di-load saat DB ready)
        db_value = self._load_from_db_sync()
        if db_value is not None:
            return db_value

        # Priority 3: Default
        return self.default_value

    def _load_from_db_sync(self) -> Optional[T]:
        """Load value from database synchronously (during startup)."""
        # During startup, DB may not be ready. Return None.
        # Will be loaded asynchronously when DB is ready.
        return None

    @property
    def value(self) -> T:
        """Get current configuration value."""
        return self._value

    @value.setter
    def value(self, new_value: T) -> None:
        """Set new value and persist to database."""
        self._value = new_value
        self._save_to_db_sync(new_value)

    def _save_to_db_sync(self, new_value: T) -> None:
        """Save value to database synchronously (during startup)."""
        # Will be overridden when DB session is available
        pass

    async def save_to_db(self, value: T, db: AsyncSession) -> None:
        """Save value to database asynchronously."""
        json_value = self._to_json(value)
        await db.execute(
            text("""
                INSERT INTO app_config (config_path, value, updated_at)
                VALUES (:config_path, :value, :updated_at)
                ON CONFLICT (config_path)
                DO UPDATE SET value = :value, updated_at = :updated_at
            """),
            {
                "config_path": self.config_path,
                "value": json_value,
                "updated_at": _get_timestamp_ns(),
            },
        )
        await db.commit()

    def _to_json(self, value: T) -> str:
        """Convert value to JSON string for database storage."""
        import json
        return json.dumps(value)


# ============================================================================
# PersistentConfig Instances
# ============================================================================


def _parse_int(value: str) -> int:
    return int(value)


def _parse_float(value: str) -> float:
    return float(value)


def _parse_bool(value: str) -> bool:
    return value.lower() in ("true", "1", "yes", "on")


# ── RAG Configuration ─────────────────────────────────────────────
CHUNK_SIZE = PersistentConfig(
    "CHUNK_SIZE", "rag.chunk_size", 1500, _parse_int
)
CHUNK_OVERLAP = PersistentConfig(
    "CHUNK_OVERLAP", "rag.chunk_overlap", 100, _parse_int
)
RAG_TOP_K = PersistentConfig(
    "RAG_TOP_K", "rag.top_k", 5, _parse_int
)
RAG_RELEVANCE_THRESHOLD = PersistentConfig(
    "RAG_RELEVANCE_THRESHOLD", "rag.threshold", 0.3, _parse_float
)
RAG_EMBEDDING_MODEL = PersistentConfig(
    "RAG_EMBEDDING_MODEL", "rag.embedding_model", "text-embedding-3-small"
)
ENABLE_RAG_QUERY_GENERATION = PersistentConfig(
    "ENABLE_RAG_QUERY_GENERATION", "rag.query_gen", True, _parse_bool
)
ENABLE_RAG_RERANKING = PersistentConfig(
    "ENABLE_RAG_RERANKING", "rag.reranking", False, _parse_bool
)

# ── Web Search Configuration ──────────────────────────────────────
ENABLE_WEB_SEARCH = PersistentConfig(
    "ENABLE_WEB_SEARCH", "websearch.enabled", True, _parse_bool
)
WEB_SEARCH_ENGINE = PersistentConfig(
    "WEB_SEARCH_ENGINE", "websearch.engine", "tavily"
)
SEARCH_RESULT_COUNT = PersistentConfig(
    "SEARCH_RESULT_COUNT", "websearch.count", 5, _parse_int
)
ENABLE_WEB_CONTENT_EXTRACTION = PersistentConfig(
    "ENABLE_WEB_CONTENT_EXTRACTION", "websearch.extract", True, _parse_bool
)

# ── Task Configuration ────────────────────────────────────────────
TASK_MODEL = PersistentConfig("TASK_MODEL", "tasks.model", "")
TITLE_GENERATION_PROMPT = PersistentConfig(
    "TITLE_GENERATION_PROMPT",
    "tasks.title_prompt",
    """Berdasarkan percakapan di bawah, buat judul yang singkat (maksimal 6 kata), 
deskriptif, dan dalam bahasa yang sama dengan percakapan. 
Hanya kembalikan judulnya saja, tanpa penjelasan atau tanda kutip.

Percakapan:
{messages}

Judul:"""
)
ENABLE_TITLE_GENERATION = PersistentConfig(
    "ENABLE_TITLE_GENERATION", "tasks.title_gen", True, _parse_bool
)
ENABLE_TAG_GENERATION = PersistentConfig(
    "ENABLE_TAG_GENERATION", "tasks.tag_gen", True, _parse_bool
)

# ── Feature Flags ─────────────────────────────────────────────────
ENABLE_IMAGE_GENERATION = PersistentConfig(
    "ENABLE_IMAGE_GENERATION", "features.image_gen", False, _parse_bool
)
ENABLE_CODE_INTERPRETER = PersistentConfig(
    "ENABLE_CODE_INTERPRETER", "features.code_interpreter", False, _parse_bool
)
ENABLE_MEMORY = PersistentConfig(
    "ENABLE_MEMORY", "features.memory", False, _parse_bool
)


# ============================================================================
# Config Manager
# ============================================================================


class ConfigManager:
    """Manages all PersistentConfig instances."""

    def __init__(self):
        self._configs = {
            # RAG
            "rag.chunk_size": CHUNK_SIZE,
            "rag.chunk_overlap": CHUNK_OVERLAP,
            "rag.top_k": RAG_TOP_K,
            "rag.threshold": RAG_RELEVANCE_THRESHOLD,
            "rag.embedding_model": RAG_EMBEDDING_MODEL,
            "rag.query_gen": ENABLE_RAG_QUERY_GENERATION,
            "rag.reranking": ENABLE_RAG_RERANKING,
            # Web Search
            "websearch.enabled": ENABLE_WEB_SEARCH,
            "websearch.engine": WEB_SEARCH_ENGINE,
            "websearch.count": SEARCH_RESULT_COUNT,
            "websearch.extract": ENABLE_WEB_CONTENT_EXTRACTION,
            # Tasks
            "tasks.model": TASK_MODEL,
            "tasks.title_prompt": TITLE_GENERATION_PROMPT,
            "tasks.title_gen": ENABLE_TITLE_GENERATION,
            "tasks.tag_gen": ENABLE_TAG_GENERATION,
            # Features
            "features.image_gen": ENABLE_IMAGE_GENERATION,
            "features.code_interpreter": ENABLE_CODE_INTERPRETER,
            "features.memory": ENABLE_MEMORY,
        }

    def get(self, config_path: str) -> Any:
        """Get config value by path."""
        config = self._configs.get(config_path)
        if config is None:
            raise KeyError(f"Unknown config path: {config_path}")
        return config.value

    def set(self, config_path: str, value: Any) -> None:
        """Set config value by path."""
        config = self._configs.get(config_path)
        if config is None:
            raise KeyError(f"Unknown config path: {config_path}")
        config.value = value

    def get_all(self) -> dict:
        """Get all configs with their paths, values, and defaults."""
        result = {}
        for path, config in self._configs.items():
            result[path] = {
                "value": config.value,
                "default": config.default_value,
            }
        return result

    def get_all_flat(self) -> dict:
        """Get all configs as flat dict of path -> value."""
        return {path: config.value for path, config in self._configs.items()}

    async def initialize_from_db(self, db: AsyncSession) -> None:
        """Load all configs from database (override env vars if DB has values)."""
        from sqlalchemy import text

        result = await db.execute(
            text("SELECT config_path, value FROM app_config")
        )
        rows = result.fetchall()

        for row in rows:
            config_path = row[0]
            raw_value = row[1]
            if config_path in self._configs:
                config_obj = self._configs[config_path]
                # Parse value to correct type (not raw string from DB)
                self._configs[config_path]._value = config_obj._parse(str(raw_value))

    def get_config_by_path(self, config_path: str) -> Optional[PersistentConfig]:
        """Get PersistentConfig object by path."""
        return self._configs.get(config_path)


# Singleton instance
config_manager = ConfigManager()


def _get_timestamp_ns() -> int:
    import time
    return int(time.time() * 1_000_000_000)
