"""
Tavily Search provider implementation.
Requires TAVILY_API_KEY environment variable.
"""

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
        print("[TAVILY] No API key provided")
        return []

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                headers={
                    "Content-Type": "application/json",
                },
                json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": min(count, 10),
                    "include_answer": False,
                    "include_raw_content": False,
                    "include_images": False,
                },
            )
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            formatted_results = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", ""),
                }
                for r in results
            ]
            
            print(f"[TAVILY] Found {len(formatted_results)} results for query: {query}")
            return formatted_results
            
    except httpx.HTTPStatusError as e:
        print(f"[TAVILY] HTTP error {e.response.status_code}: {e.response.text}")
        return []
    except Exception as e:
        print(f"[TAVILY] Search error: {e}")
        return []
