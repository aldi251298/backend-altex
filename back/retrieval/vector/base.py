"""
Abstract base class for vector store adapters.
"""

from abc import ABC, abstractmethod
from typing import Any


class VectorStoreBase(ABC):
    """Abstract base class for vector store implementations."""

    @abstractmethod
    async def upsert_collection(
        self,
        collection_name: str,
        documents: list[dict],
    ) -> int:
        """
        Upsert documents into a collection.
        
        Args:
            collection_name: Name of the vector collection
            documents: List of dicts with 'text', 'embedding', 'metadata' keys
        
        Returns:
            Number of documents upserted
        """
        ...

    @abstractmethod
    async def similarity_search(
        self,
        collection_name: str,
        query_embedding: list[float],
        top_k: int = 5,
        score_threshold: float = 0.3,
    ) -> list[dict]:
        """
        Search for similar documents.
        
        Args:
            collection_name: Name of the vector collection
            query_embedding: Embedding vector for the query
            top_k: Number of results to return
            score_threshold: Minimum similarity score
        
        Returns:
            List of dicts with 'text', 'metadata', 'score' keys
        """
        ...

    @abstractmethod
    async def delete_collection(self, collection_name: str) -> bool:
        """Delete a collection and all its documents."""
        ...

    @abstractmethod
    async def count_documents(self, collection_name: str) -> int:
        """Count documents in a collection."""
        ...

    @abstractmethod
    async def get_collection_info(self, collection_name: str) -> dict:
        """Get information about a collection."""
        ...
