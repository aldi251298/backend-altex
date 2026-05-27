"""
pgvector adapter - Primary vector store implementation.
Uses PostgreSQL with pgvector extension for vector similarity search.
"""

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from retrieval.vector.base import VectorStoreBase

logger = logging.getLogger(__name__)


class PgVectorAdapter(VectorStoreBase):
    """pgvector adapter for PostgreSQL."""

    def __init__(self, session_factory):
        """
        Initialize with SQLAlchemy async session factory.
        
        Args:
            session_factory: Async session factory from database.py
        """
        self._session_factory = session_factory

    async def _get_session(self) -> AsyncSession:
        """Get a new database session."""
        from database import async_session_factory
        return async_session_factory()

    async def upsert_collection(
        self,
        collection_name: str,
        documents: list[dict],
    ) -> int:
        """
        Upsert documents into pgvector collection.
        
        Each document should have:
        - id: unique identifier
        - text: the text content
        - embedding: vector embedding (list of floats)
        - metadata: optional metadata dict
        """
        if not documents:
            return 0

        async with self._session_factory() as db:
            from constants import time_ns

            for doc in documents:
                await db.execute(
                    text("""
                        INSERT INTO vector_store (id, collection_name, content, embedding, metadata, created_at)
                        VALUES (:id, :collection_name, :content, :embedding, :metadata, :created_at)
                        ON CONFLICT (id)
                        DO UPDATE SET
                            content = EXCLUDED.content,
                            embedding = EXCLUDED.embedding,
                            metadata = EXCLUDED.metadata,
                            updated_at = :updated_at
                    """),
                    {
                        "id": doc["id"],
                        "collection_name": collection_name,
                        "content": doc["text"],
                        "embedding": doc["embedding"],
                        "metadata": str(doc.get("metadata", "{}")),
                        "created_at": time_ns(),
                        "updated_at": time_ns(),
                    }
                )

            await db.commit()
            return len(documents)

    async def similarity_search(
        self,
        collection_name: str,
        query_embedding: list[float],
        top_k: int = 5,
        score_threshold: float = 0.3,
    ) -> list[dict]:
        """
        Search for similar documents using cosine similarity.
        
        Returns documents sorted by similarity score (descending).
        """
        async with self._session_factory() as db:
            # Use IVFFlat index for fast similarity search
            # Convert list to PostgreSQL vector string format: [0.1,0.2,0.3]
            embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
            
            result = await db.execute(
                text("""
                    SELECT id, content, metadata,
                           1 - (embedding <=> :query_embedding::vector) AS score
                    FROM vector_store
                    WHERE collection_name = :collection_name
                      AND 1 - (embedding <=> :query_embedding::vector) >= :score_threshold
                    ORDER BY embedding <=> :query_embedding::vector
                    LIMIT :top_k
                """),
                {
                    "query_embedding": embedding_str,
                    "collection_name": collection_name,
                    "score_threshold": score_threshold,
                    "top_k": top_k,
                }
            )

            rows = result.fetchall()
            return [
                {
                    "id": row[0],
                    "text": row[1],
                    "metadata": self._parse_metadata(row[2]),
                    "score": float(row[3]),
                }
                for row in rows
            ]

    async def delete_collection(self, collection_name: str) -> bool:
        """Delete a collection and all its documents."""
        async with self._session_factory() as db:
            await db.execute(
                text("DELETE FROM vector_store WHERE collection_name = :collection_name"),
                {"collection_name": collection_name}
            )
            await db.commit()
            return True

    async def count_documents(self, collection_name: str) -> int:
        """Count documents in a collection."""
        async with self._session_factory() as db:
            result = await db.execute(
                text("SELECT COUNT(*) FROM vector_store WHERE collection_name = :collection_name"),
                {"collection_name": collection_name}
            )
            return result.scalar() or 0

    async def get_collection_info(self, collection_name: str) -> dict:
        """Get information about a collection."""
        async with self._session_factory() as db:
            result = await db.execute(
                text("""
                    SELECT COUNT(*) as doc_count,
                           MIN(created_at) as first_created,
                           MAX(created_at) as last_created
                    FROM vector_store
                    WHERE collection_name = :collection_name
                """),
                {"collection_name": collection_name}
            )
            row = result.fetchone()
            return {
                "collection_name": collection_name,
                "document_count": row[0] or 0,
                "first_created": row[1],
                "last_created": row[2],
            }

    @staticmethod
    def _parse_metadata(metadata_str: str) -> dict:
        """Parse metadata JSON string to dict."""
        import json
        try:
            return json.loads(metadata_str)
        except (json.JSONDecodeError, TypeError):
            return {}


# Singleton instance - will be initialized with actual session factory
pgvector_client: PgVectorAdapter | None = None


def initialize_pgvector(session_factory):
    """Initialize the global pgvector client."""
    global pgvector_client
    pgvector_client = PgVectorAdapter(session_factory)
    return pgvector_client
