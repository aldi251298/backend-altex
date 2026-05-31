"""
DuckDuckGo search provider implementation.
Free, no API key required.
"""

import asyncio
from typing import Any

from duckduckgo_search import DDGS


async def search_duckduckgo(
    api_key: str | None = None,  # Not used for DuckDuckGo
    query: str = "",
    count: int = 5,
) -> list[dict]:
    """
    Search using DuckDuckGo.
    
    Returns:
        List of dicts with 'title', 'url', 'snippet' keys
    """
    try:
        ddgs = DDGS()
        results = await asyncio.to_thread(
            ddgs.text,
            query,
            max_results=count,
        )
        
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            }
            for r in results
        ]
    except Exception as e:
        print(f"DuckDuckGo search error: {e}")
        return []
