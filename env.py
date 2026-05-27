"""
Environment variables configuration using Pydantic Settings.
All environment variables are loaded from .env file and os.environ.
"""

from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized settings using pydantic-settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Core ────────────────────────────────────────────────────────
    secret_key: str = ""
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_chat"
    environment: str = "development"  # development | production

    # ── Server ──────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 4
    log_level: str = "info"

    # ── Auth ────────────────────────────────────────────────────────
    enable_signup: bool = False
    access_token_expire_minutes: int = 10080  # 7 hari
    refresh_token_expire_days: int = 30
    bcrypt_cost_factor: int = 12
    allowed_cors_origins: List[str] = ["*"]

    # ── Embedding ───────────────────────────────────────────────────
    embedding_engine: str = "openai"  # openai | ollama | local
    rag_embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536

    # ── Chunking (bisa di-override via PersistentConfig) ────────────
    chunk_size: int = 1500
    chunk_overlap: int = 100
    rag_top_k: int = 5
    rag_relevance_threshold: float = 0.3
    enable_rag_query_generation: bool = True
    enable_rag_reranking: bool = False

    # ── Web Search ──────────────────────────────────────────────────
    enable_web_search: bool = False
    enable_web_search_auto: bool = False
    web_search_engine: str = "duckduckgo"  # searxng | brave | tavily | duckduckgo
    search_result_count: int = 5
    enable_web_content_extraction: bool = True

    # Search API Keys
    brave_search_api_key: str = ""
    tavily_api_key: str = ""
    searxng_query_url: str = ""

    # ── File Storage ────────────────────────────────────────────────
    storage_provider: str = "local"  # local | s3
    upload_dir: str = "/app/uploads"
    aws_s3_bucket_name: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "ap-southeast-1"

    # ── Task Model ──────────────────────────────────────────────────
    task_model: str = ""
    enable_title_generation: bool = True
    enable_tag_generation: bool = True

    # ── Features ────────────────────────────────────────────────────
    enable_image_generation: bool = False
    enable_code_interpreter: bool = False
    enable_memory: bool = False

    # ── Redis (opsional, untuk caching & task queue) ─────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Monitoring ──────────────────────────────────────────────────
    enable_metrics: bool = True
    sentry_dsn: str = ""

    # ── OpenAI Client ───────────────────────────────────────────────
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    def get_search_api_key(self, engine: str) -> str:
        """Get API key for specific search engine."""
        keys = {
            "brave": self.brave_search_api_key,
            "tavily": self.tavily_api_key,
            "searxng": self.searxng_query_url,
        }
        return keys.get(engine, "")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


# Singleton instance
settings = Settings()


def get_settings() -> Settings:
    """Dependency injection for settings."""
    return settings
