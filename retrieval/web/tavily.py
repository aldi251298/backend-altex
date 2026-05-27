"""
Tavily Search provider implementation.
Requires TAVILY_API_KEY environment variable.
"""

import asyncio
from typing import Any

import httpx


async def search_tavily(
    api_key: str = "",
    query: str = "",
    count: int = 5,
) -> list[dict]:
    """
    Search using Tavily API.
    
    Returns:
        List of dicts with 'title', 'url', 'snippet' keys
    """
    if not api_key:
        return []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": min(count, 10),
                    "include_answer": False,
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
                for r in results
            ]
    except Exception as e:
        print(f"Tavily search error: {e}")
        return []
