"""
Brave Search provider implementation.
Requires BRAVE_SEARCH_API_KEY environment variable.
"""

import asyncio
from typing import Any

import httpx


async def search_brave(
    api_key: str = "",
    query: str = "",
    count: int = 5,
) -> list[dict]:
    """
    Search using Brave Search API.
    
    Returns:
        List of dicts with 'title', 'url', 'snippet' keys
    """
    if not api_key:
        return []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": api_key,
                },
                params={
                    "q": query,
                    "count": min(count, 20),
                },
            )
            response.raise_for_status()
            data = response.json()

            results = data.get("web", {}).get("results", [])
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("description", ""),
                }
                for r in results
            ]
    except Exception as e:
        print(f"Brave search error: {e}")
        return []
