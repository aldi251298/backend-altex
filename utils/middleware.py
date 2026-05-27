"""
Preprocessing pipeline for chat payloads.
RAG handler, web search handler, and middleware utilities.
"""

import asyncio
import json
import logging
from typing import Any, Callable

from sqlalchemy import select

logger = logging.getLogger(__name__)


async def chat_completion_files_handler(
    body: dict,
    user: dict,
    event_emitter: Callable | None = None,
) -> dict:
    """
    RAG handler: retrieve relevant chunks and inject into messages.
    """
    file_ids = [f["id"] for f in body.get("files", []) if f.get("type") == "file"]
    if not file_ids:
        return body

    # Emit status to Flutter
    if event_emitter:
        await event_emitter({
            "type": "status",
            "data": {"description": "Mengambil konteks dari dokumen...", "done": False}
        })

    # Get collection names from file IDs (placeholder - would query DB)
    collections = await _get_collection_names_by_ids(file_ids)
    if not collections:
        return body

    # Extract last user message for query
    user_query = _extract_last_user_message(body["messages"])
    if not user_query:
        return body

    # Generate retrieval query (placeholder)
    optimized_queries = [user_query]  # Would use LLM if enabled

    # Similarity search in pgvector (placeholder)
    all_chunks = []
    for collection in collections:
        for query in optimized_queries:
            # Placeholder: would call pgvector similarity search
            chunks = await _vector_similarity_search(
                collection_name=collection,
                query=query,
                top_k=5,
                score_threshold=0.3,
            )
            all_chunks.extend(chunks)

    # Deduplicate by content hash
    seen = set()
    unique_chunks = []
    for chunk in all_chunks:
        h = hash(chunk.get("text", ""))
        if h not in seen:
            seen.add(h)
            unique_chunks.append(chunk)

    # Inject as context into messages
    if unique_chunks:
        context_str = _format_rag_context(unique_chunks)
        body = _inject_context_to_messages(body, context_str)

        # Emit citation events to Flutter
        if event_emitter:
            for chunk in unique_chunks[:3]:  # Limit citations
                await event_emitter({
                    "type": "citation",
                    "data": {
                        "document": [chunk.get("text", "")],
                        "metadata": [chunk.get("metadata", {})],
                        "source": {"name": chunk.get("metadata", {}).get("source", "Unknown")},
                    }
                })

    if event_emitter:
        await event_emitter({
            "type": "status",
            "data": {
                "description": f"Ditemukan {len(unique_chunks)} konteks relevan",
                "done": True,
            }
        })

    # Remove 'files' from body before sending to AI provider
    body.pop("files", None)
    return body


async def chat_completion_web_search_handler(
    body: dict,
    user: dict,
    event_emitter: Callable | None = None,
) -> dict:
    """
    Web search handler: query search engines, extract content, inject results.
    """
    if event_emitter:
        await event_emitter({
            "type": "status",
            "data": {"description": "Membuat query pencarian...", "done": False}
        })

    # Extract last user message
    user_query = _extract_last_user_message(body["messages"])
    if not user_query:
        return body

    # Generate optimized queries (placeholder)
    queries = [user_query]

    if event_emitter:
        await event_emitter({
            "type": "status",
            "data": {
                "description": f"Mencari: {queries[0]}",
                "done": False,
            }
        })

    # Execute search (placeholder - would call retrieval/web modules)
    all_results = []
    for query in queries:
        results = await _web_search(query=query, count=5)
        all_results.append(results)

    valid_results = [r for r in all_results if r]

    if not valid_results:
        if event_emitter:
            await event_emitter({
                "type": "status",
                "data": {"description": "Pencarian tidak menghasilkan hasil", "done": True}
            })
        return body

    # Format context
    context_str = _format_search_context(valid_results)
    body = _inject_context_to_messages(body, context_str)

    # Emit citations
    if event_emitter:
        for results in valid_results:
            for result in results[:3]:
                await event_emitter({
                    "type": "citation",
                    "data": {
                        "document": [result.get("snippet", "")],
                        "metadata": [{
                            "source": result.get("url", ""),
                            "name": result.get("title", result.get("url", ""))
                        }],
                        "source": {
                            "name": result.get("title", result.get("url", "")),
                            "url": result.get("url", ""),
                        },
                    }
                })

    total_results = sum(len(r) for r in valid_results)
    if event_emitter:
        await event_emitter({
            "type": "status",
            "data": {
                "description": f"Pencarian selesai ({total_results} hasil)",
                "done": True,
            }
        })

    return body


# ============================================================================
# Helper Functions
# ============================================================================


async def _get_collection_names_by_ids(file_ids: list[str]) -> list[str]:
    """
    Get collection names from file IDs by querying the files table.
    
    Returns list of collection_name values for the given file IDs
    that belong to the current user context.
    """
    from database import async_session_factory
    from models.files import File
    
    if not file_ids:
        return []
    
    async with async_session_factory() as db:
        result = await db.execute(
            select(File.collection_name)
            .where(File.id.in_(file_ids))
        )
        return [row[0] for row in result.fetchall() if row[0]]


async def _vector_similarity_search(
    collection_name: str,
    query: str,
    top_k: int = 5,
    score_threshold: float = 0.3,
) -> list[dict]:
    """
    Perform similarity search in pgvector using PgVectorAdapter.
    
    1. First, generate embedding for the query using the embedding service.
    2. Query vector_store table using pgvector cosine similarity.
    3. Return matching chunks with text, metadata, and score.
    """
    from constants import embedding_engine, rag_embedding_model, embedding_dimension
    from retrieval.vector.pgvector import pgvector_client
    
    if pgvector_client is None:
        logger.warning("PgVectorAdapter not initialized, skipping vector search")
        return []
    
    # Generate embedding for the query
    query_embedding = await _generate_embedding(query)
    if not query_embedding:
        return []
    
    try:
        results = await pgvector_client.similarity_search(
            collection_name=collection_name,
            query_embedding=query_embedding,
            top_k=top_k,
            score_threshold=score_threshold,
        )
        return results
    except Exception as e:
        logger.error(f"Vector similarity search failed for '{collection_name}': {e}")
        return []


async def _generate_embedding(text: str) -> list[float] | None:
    """
    Generate embedding for text using configured embedding engine.
    
    Supports: openai, ollama, local
    """
    from env import settings as app_settings
    
    engine = app_settings.embedding_engine
    model = app_settings.rag_embedding_model
    dim = app_settings.embedding_dimension
    openai_key = app_settings.openai_api_key
    openai_base = app_settings.openai_base_url
    
    if engine == "openai":
        return await _generate_openai_embedding(openai_key, model, text, dim, openai_base)
    elif engine == "ollama":
        return await _generate_ollama_embedding(text, model, dim)
    else:
        logger.warning(f"Unsupported embedding engine: {engine}")
        return None


async def _generate_openai_embedding(
    api_key: str, model: str, text: str, dim: int, base_url: str = "https://api.openai.com/v1"
) -> list[float] | None:
    """Generate embedding using OpenAI-compatible API."""
    if not api_key:
        logger.warning("OpenAI API key not configured")
        return None
    
    import httpx
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/embeddings",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                json={
                    "model": model,
                    "input": text,
                    "dimensions": dim,
                },
            )
            response.raise_for_status()
            data = response.json()
            embedding = data.get("data", [{}])[0].get("embedding")
            return embedding
    except Exception as e:
        logger.error(f"OpenAI embedding generation failed: {e}")
        return None


async def _generate_ollama_embedding(
    text: str, model: str, dim: int
) -> list[float] | None:
    """Generate embedding using Ollama."""
    import httpx
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "http://localhost:11434/api/embeddings",
                json={
                    "model": model or "nomic-embed-text",
                    "prompt": text,
                },
            )
            response.raise_for_status()
            data = response.json()
            embedding = data.get("embedding")
            return embedding
    except Exception as e:
        logger.error(f"Ollama embedding generation failed: {e}")
        return None


async def _web_search(query: str, count: int = 5) -> list[dict]:
    """
    Search web using configured search engine.
    
    Supports: duckduckgo, brave, tavily, searxng
    """
    from env import settings as app_settings
    
    engine = app_settings.web_search_engine
    
    if engine == "brave":
        return await _web_search_brave(query, count, app_settings.brave_search_api_key)
    elif engine == "tavily":
        return await _web_search_tavily(query, count, app_settings.tavily_api_key)
    elif engine == "searxng":
        return await _web_search_searxng(query, count, app_settings.searxng_query_url)
    else:
        # Default to DuckDuckGo
        return await _web_search_duckduckgo(query, count)


async def _web_search_duckduckgo(query: str, count: int) -> list[dict]:
    """Search using DuckDuckGo (free, no API key required)."""
    try:
        from retrieval.web.duckduckgo import search_duckduckgo
        return await search_duckduckgo(query=query, count=count)
    except Exception as e:
        logger.error(f"DuckDuckGo search failed: {e}")
        return []


async def _web_search_brave(query: str, count: int, api_key: str) -> list[dict]:
    """Search using Brave Search API."""
    if not api_key:
        logger.warning("Brave API key not configured, falling back to DuckDuckGo")
        return await _web_search_duckduckgo(query, count)
    
    try:
        from retrieval.web.brave import search_brave
        return await search_brave(api_key=api_key, query=query, count=count)
    except Exception as e:
        logger.error(f"Brave search failed: {e}")
        return []


async def _web_search_tavily(query: str, count: int, api_key: str) -> list[dict]:
    """Search using Tavily API."""
    if not api_key:
        logger.warning("Tavily API key not configured, falling back to DuckDuckGo")
        return await _web_search_duckduckgo(query, count)
    
    try:
        import httpx
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": min(count, 10),
                    "search_depth": "basic",
                    "include_answer": False,
                },
            )
            response.raise_for_status()
            data = response.json()
            
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", ""),
                }
                for r in data.get("results", [])
            ]
    except Exception as e:
        logger.error(f"Tavily search failed: {e}")
        return []


async def _web_search_searxng(query: str, count: int, query_url: str) -> list[dict]:
    """Search using SearXNG instance."""
    if not query_url:
        logger.warning("SearXNG URL not configured, falling back to DuckDuckGo")
        return await _web_search_duckduckgo(query, count)
    
    try:
        import httpx
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                query_url.rstrip("/") + "/search",
                params={
                    "q": query,
                    "format": "json",
                    "pageno": 1,
                    "categories": "general",
                },
            )
            response.raise_for_status()
            data = response.json()
            
            results = data.get("results", [])
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", ""),
                }
                for r in results[:count]
            ]
    except Exception as e:
        logger.error(f"SearXNG search failed: {e}")
        return []


def _extract_last_user_message(messages: list[dict]) -> str:
    """Extract last user message content."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [
                    p.get("text", "")
                    for p in content
                    if p.get("type") == "text"
                ]
                return " ".join(text_parts)
            return str(content)
    return ""


def _format_rag_context(chunks: list[dict]) -> str:
    """Format chunks as context for injection into prompt."""
    parts = ["[Informasi Konteks yang Relevan]"]
    for i, chunk in enumerate(chunks, 1):
        parts.append(
            f"<source>\n"
            f"  <source_id>{i}</source_id>\n"
            f"  <content>{chunk.get('text', '')}</content>\n"
            f"  <metadata>Sumber: {chunk.get('metadata', {}).get('source', 'unknown')}</metadata>\n"
            f"</source>"
        )
    parts.append("[Akhir Konteks]")
    return "\n".join(parts)


def _format_search_context(results: list[list[dict]]) -> str:
    """Format search results as context."""
    parts = ["[Hasil Pencarian Web]"]
    for i, result_list in enumerate(results):
        for result in result_list:
            parts.append(
                f"<search_result>\n"
                f"  <title>{result.get('title', '')}</title>\n"
                f"  <url>{result.get('url', '')}</url>\n"
                f"  <snippet>{result.get('snippet', '')}</snippet>\n"
                f"</search_result>"
            )
    parts.append("[Akhir Hasil Pencarian]")
    return "\n".join(parts)


def _inject_context_to_messages(body: dict, context: str) -> dict:
    """Inject context string into messages."""
    if not context:
        return body

    # Find last user message and append context
    messages = body.get("messages", [])
    for msg in reversed(messages):
        if msg.get("role") == "user":
            current_content = msg.get("content", "")
            if isinstance(current_content, str):
                msg["content"] = f"{current_content}\n\n[Konteks]\n{context}"
            break

    return body
