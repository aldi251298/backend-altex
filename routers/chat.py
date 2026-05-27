"""
Chat completion router.
Entry point utama untuk chat dengan SSE streaming.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from utils.chat import generate_chat_completion

router = APIRouter()
logger = logging.getLogger(__name__)

# Anonymous user ID (no auth required)
ANONYMOUS_USER_ID = "anonymous"


@router.post(
    "/completions",
    summary="SSE streaming chat completion (full pipeline)",
)
async def chat_completions(
    request: Request,
    body: dict,
):
    """
    Entry point utama chat completion.
    No authentication required.
    """
    messages = body.get("messages")
    if not messages:
        error_chunk = {"error": {"code": 422, "message": "Field 'messages' wajib diisi", "type": "validation_error"}}
        error_sse = f"data: {json.dumps(error_chunk)}\n\n"
        
        return StreamingResponse(
            content=iter([error_sse, "data: [DONE]\n\n"]),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
            },
        )

    user = {"id": ANONYMOUS_USER_ID}
    
    logger.info(
        "chat_completion_request",
        user_id=user["id"],
        model=body.get("model", "unknown"),
        message_count=len(messages),
        has_files=bool(body.get("files")),
        web_search=body.get("web_search", False),
    )

    async def stream_generator():
        try:
            # Note: background_tasks needs to be passed if used in generate_chat_completion
            async for chunk in generate_chat_completion(request, body, user, background_tasks=None):
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
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )
