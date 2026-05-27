"""
Retrieval router.
Web search dan RAG search endpoints.
"""

from fastapi import APIRouter, Depends

from retrieval.web.duckduckgo import search_duckduckgo
from retrieval.web.brave import search_brave
from retrieval.web.tavily import search_tavily
from retrieval.web.searxng import search_searxng
from retrieval.web.utils import extract_web_content
from env import settings

router = APIRouter()


@router.post("/web/search", summary="Manual web search (testing)")
async def web_search(
    body: dict,
):
    """
    Manual web search untuk testing.
    Supports: duckduckgo, brave, tavily, searxng
    """
    query = body.get("query", "")
    engine = body.get("engine", settings.web_search_engine)
    count = body.get("count", 5)
    
    if not query:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="query wajib diisi")
    
    search_results = []
    
    if engine == "duckduckgo":
        search_results = await search_duckduckgo(query=query, count=count)
    elif engine == "brave":
        search_results = await search_brave(
            api_key=settings.brave_search_api_key,
            query=query,
            count=count,
        )
    elif engine == "tavily":
        search_results = await search_tavily(
            api_key=settings.tavily_api_key,
            query=query,
            count=count,
        )
    elif engine == "searxng":
        search_results = await search_searxng(
            query=query,
            count=count,
            searxng_url=settings.searxng_query_url,
        )
    else:
        search_results = await search_duckduckgo(query=query, count=count)
    
    return {"results": search_results, "engine": engine}


@router.post("/web/extract", summary="Extract content dari URL")
async def extract_url(
    body: dict,
):
    """Extract readable content dari URL."""
    url = body.get("url", "")
    
    if not url:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="url wajib diisi")
    
    content = await extract_web_content(url)
    
    return {"url": url, "content": content[:5000]}  # Limit response size
