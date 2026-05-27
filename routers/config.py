"""
App config router.
Get/update application configuration (RAG, web search, features, etc.)
No auth required.
"""

from fastapi import APIRouter, HTTPException
from env import settings

router = APIRouter()


@router.get("", summary="Get app configuration")
async def get_config():
    """Return current application configuration."""
    return {
        "environment": settings.environment,
        # RAG
        "rag": {
            "embedding_engine": settings.embedding_engine,
            "embedding_model": settings.rag_embedding_model,
            "embedding_dimension": settings.embedding_dimension,
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "top_k": settings.rag_top_k,
            "relevance_threshold": settings.rag_relevance_threshold,
            "enable_query_generation": settings.enable_rag_query_generation,
            "enable_reranking": settings.enable_rag_reranking,
        },
        # Web search
        "web_search": {
            "enabled": settings.enable_web_search,
            "auto": settings.enable_web_search_auto,
            "engine": settings.web_search_engine,
            "result_count": settings.search_result_count,
            "content_extraction": settings.enable_web_content_extraction,
        },
        # Features
        "features": {
            "image_generation": settings.enable_image_generation,
            "code_interpreter": settings.enable_code_interpreter,
            "memory": settings.enable_memory,
            "title_generation": settings.enable_title_generation,
            "tag_generation": settings.enable_tag_generation,
        },
        # Storage
        "storage": {
            "provider": settings.storage_provider,
            "upload_dir": settings.upload_dir,
        },
        # Task model
        "task_model": settings.task_model,
    }


@router.get("/models", summary="Get model-related config")
async def get_model_config():
    """Return model configuration."""
    return {
        "task_model": settings.task_model,
        "enable_title_generation": settings.enable_title_generation,
        "enable_tag_generation": settings.enable_tag_generation,
    }


@router.get("/rag", summary="Get RAG configuration")
async def get_rag_config():
    """Return RAG configuration."""
    return {
        "embedding_engine": settings.embedding_engine,
        "embedding_model": settings.rag_embedding_model,
        "embedding_dimension": settings.embedding_dimension,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "top_k": settings.rag_top_k,
        "relevance_threshold": settings.rag_relevance_threshold,
        "enable_query_generation": settings.enable_rag_query_generation,
        "enable_reranking": settings.enable_rag_reranking,
    }


@router.get("/features", summary="Get feature flags")
async def get_features():
    """Return feature flags."""
    return {
        "web_search": settings.enable_web_search,
        "web_search_auto": settings.enable_web_search_auto,
        "image_generation": settings.enable_image_generation,
        "code_interpreter": settings.enable_code_interpreter,
        "memory": settings.enable_memory,
        "title_generation": settings.enable_title_generation,
        "tag_generation": settings.enable_tag_generation,
    }
