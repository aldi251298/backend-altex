"""
Chat completion router.
Entry point utama untuk chat dengan SSE streaming.
Mengikuti SRS Section 5: SSE Streaming Implementation.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from utils.auth import get_verified_user
from utils.chat import generate_chat_completion

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/completions",
    summary="SSE streaming chat completion (full pipeline)",
)
async def chat_completions(
    request: Request,
    body: dict,
    user=Depends(get_verified_user),
):
    """
    Entry point utama chat completion.
    Semua request chat harus melalui endpoint ini karena melewati pipeline lengkap.
    
    - Validasi JWT
    - System prompt injection
    - Filter pipeline
    - RAG retrieval
    - Web search
    - Tool specs injection
    - SSE streaming ke provider
    - Headers: Cache-Control: no-cache, Connection: keep-alive, X-Accel-Buffering: no
    """
    # Validate required fields
    messages = body.get("messages")
    if not messages:
        # Return error as SSE format
        error_chunk = {"error": {"code": 422, "message": "Field 'messages' wajib diisi", "type": "validation_error"}}
        error_sse = f"data: {json.dumps(error_chunk)}\n\n"
        
        return StreamingResponse(
            content=iter([error_sse, "data: [DONE]\n\n"]),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # KRITIS: disable Nginx buffering per SRS
                "Access-Control-Allow-Origin": "*",
            },
        )

    # Log request
    logger.info(
        "chat_completion_request",
        user_id=user["id"],
        model=body.get("model", "unknown"),
        message_count=len(messages),
        has_files=bool(body.get("files")),
        web_search=body.get("web_search", False),
    )

    # Generate SSE stream - use async generator wrapper
    async def stream_generator():
        try:
            async for chunk in generate_chat_completion(request, body, user, background_tasks):
                yield chunk
        except Exception as e:
            logger.error(f"Chat completion error: {e}")
            error_chunk = {"error": {"code": 500, "message": str(e), "type": "provider_error"}}
            yield f"data: {json.dumps(error_chunk)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        content=stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # KRITIS: disable Nginx buffering per SRS Section 5.1
            "Access-Control-Allow-Origin": "*",
        },
    )
