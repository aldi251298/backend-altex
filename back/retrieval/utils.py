"""
Chunking and embedding utilities for RAG pipeline.
"""

import logging
from typing import Any

from env import settings

logger = logging.getLogger(__name__)


def chunk_text(
    text: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[dict]:
    """
    Split text into chunks using RecursiveCharacterTextSplitter approach.
    
    Args:
        text: Input text
        chunk_size: Size of each chunk (default: 1500)
        chunk_overlap: Overlap between chunks (default: 100)
    
    Returns:
        List of dicts with 'text', 'index' keys
    """
    chunk_size = chunk_size or settings.chunk_size
    chunk_overlap = chunk_overlap or settings.chunk_overlap

    SEPARATORS = ["\n\n", "\n", ". ", " ", ""]
    chunks = _recursive_split(text, SEPARATORS, chunk_size, chunk_overlap)
    return [{"text": c, "index": i} for i, c in enumerate(chunks) if c.strip()]


def _recursive_split(
    text: str,
    separators: list[str],
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """Recursively split text by separators."""
    if not separators:
        # Hard split by character
        return [
            text[i:i + chunk_size]
            for i in range(0, len(text), chunk_size - chunk_overlap)
        ]

    separator = separators[0]
    splits = text.split(separator)
    good_splits = []

    for split in splits:
        if len(split) <= chunk_size:
            good_splits.append(split)
        else:
            # Recurse with next separator
            good_splits.extend(
                _recursive_split(split, separators[1:], chunk_size, chunk_overlap)
            )

    return _merge_for_overlap(good_splits, chunk_size, chunk_overlap)


def _merge_for_overlap(chunks: list[str], chunk_size: int, chunk_overlap: int) -> list[str]:
    """Merge small chunks with overlap."""
    result = []
    current = ""

    for chunk in chunks:
        if current:
            current += "\n\n" + chunk
        else:
            current = chunk

        if len(current) > chunk_size:
            result.append(current)
            # Keep overlap
            if chunk_overlap > 0:
                current = current[-chunk_overlap:]
            else:
                current = ""

    if current:
        result.append(current)

    return result


async def generate_embeddings_batch(
    texts: list[str],
    model: str | None = None,
    batch_size: int = 100,
) -> list[list[float]]:
    """
    Generate embeddings for a list of texts.
    
    Args:
        texts: List of text strings
        model: Embedding model name (default: from settings)
        batch_size: Batch size for processing
    
    Returns:
        List of embedding vectors
    """
    from env import settings as app_settings
    
    model = model or app_settings.rag_embedding_model
    engine = app_settings.embedding_engine
    
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]

        if engine == "openai":
            batch_embeddings = await _embed_openai(batch, model)
        elif engine == "ollama":
            batch_embeddings = await asyncio.gather(*[
                _embed_single_ollama(text, model)
                for text in batch
            ])
        elif engine == "local":
            batch_embeddings = await _embed_local(batch, model)
        else:
            raise ValueError(f"Unknown embedding engine: {engine}")

        all_embeddings.extend(batch_embeddings)

    return all_embeddings


async def _embed_openai(texts: list[str], model: str) -> list[list[float]]:
    """Generate embeddings using OpenAI-compatible API."""
    try:
        from openai import AsyncOpenAI
        from env import settings
        
        client = AsyncOpenAI(
            api_key=settings.openai_api_key or settings.secret_key,
            base_url=settings.openai_base_url,
        )
        
        response = await client.embeddings.create(
            model=model,
            input=texts,
        )
        return [e.embedding for e in response.data]
    except Exception as e:
        logger.error(f"OpenAI embedding error: {e}")
        # Return zero vector as fallback
        dim = settings.embedding_dimension
        return [[0.0] * dim for _ in texts]


async def _embed_single_ollama(text: str, model: str) -> list[float]:
    """Generate embedding using Ollama API."""
    import httpx
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "http://localhost:11434/api/embeddings",
                json={
                    "model": model,
                    "prompt": text,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("embedding", [0.0] * 768)
    except Exception as e:
        logger.error(f"Ollama embedding error: {e}")
        return [0.0] * 768


async def _embed_local(texts: list[str], model: str) -> list[list[float]]:
    """Generate embeddings using local SentenceTransformers."""
    try:
        import torch
        from sentence_transformers import SentenceTransformer
        
        st_model = SentenceTransformer(model)
        with torch.no_grad():
            embeddings = st_model.encode(texts).tolist()
        return embeddings
    except Exception as e:
        logger.error(f"Local embedding error: {e}")
        dim = 768  # Default dimension
        return [[0.0] * dim for _ in texts]


import asyncio
import json


def format_rag_context(chunks: list[dict]) -> str:
    """Format chunks as context for injection into prompt."""
    parts = ["[Informasi Konteks yang Relevan]"]
    for i, chunk in enumerate(chunks, 1):
        parts.append(
            f"<source>\n"
            f"  <source_id>{i}</source_id>\n"
            f"  <content>{chunk.get('text', '')}</content>\n"
            f"  <metadata>{json.dumps(chunk.get('metadata', {}))}</metadata>\n"
            f"</source>"
        )
    parts.append("[Akhir Konteks]")
    return "\n".join(parts)
