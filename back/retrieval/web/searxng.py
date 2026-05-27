"""
SearXNG Search provider implementation.
Self-hosted metasearch engine.
"""

import asyncio
from typing import Any

import httpx


async def search_searxng(
    api_key: str | None = None,  # Not used for SearXNG
    query: str = "",
    count: int = 5,
    searxng_url: str = "",
) -> list[dict]:
    """
    Search using SearXNG instance.
    
    Args:
        api_key: Not used
        query: Search query
        count: Number of results
        searxng_url: SearXNG query API URL
    
    Returns:
        List of dicts with 'title', 'url', 'snippet' keys
    """
    if not searxng_url:
        return []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                searxng_url,
                params={
                    "q": query,
                    "format": "json",
                    "pageno": 1,
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
        print(f"SearXNG search error: {e}")
        return []
