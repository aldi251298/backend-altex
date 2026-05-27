"""
Chat completion router.
Supports SSE streaming, non-streaming, and tool calling loop.
No auth required.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse, StreamingResponse

from utils.chat import generate_chat_completion

router = APIRouter()
logger = logging.getLogger(__name__)

ANONYMOUS_USER_ID = "anonymous"

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
    "Access-Control-Allow-Origin": "*",
}


# ============================================================================
# POST /api/chat/completions  — main entry point
# ============================================================================


@router.post("/completions", summary="Chat completion (streaming SSE or JSON)")
async def chat_completions(
    request: Request,
    body: dict,
    background_tasks: BackgroundTasks,
):
    """
    Main chat completion endpoint.
    - stream=true  (default) → SSE text/event-stream
    - stream=false           → JSON response (waits for full completion)
    No authentication required.
    """
    messages = body.get("messages")
    if not messages:
        error = {"error": {"code": 422, "message": "Field 'messages' wajib diisi", "type": "validation_error"}}
        if body.get("stream", True):
            return StreamingResponse(
                content=iter([f"data: {json.dumps(error)}\n\n", "data: [DONE]\n\n"]),
                media_type="text/event-stream",
                headers=_SSE_HEADERS,
            )
        return JSONResponse(status_code=422, content=error)

    user = {"id": ANONYMOUS_USER_ID, "role": "user"}
    stream = body.get("stream", True)

    logger.info(
        "chat_completion_request user=%s model=%s msgs=%d files=%s web=%s stream=%s",
        user["id"],
        body.get("model", "unknown"),
        len(messages),
        bool(body.get("files")),
        body.get("web_search", False),
        stream,
    )

    # ── Streaming response ────────────────────────────────────────────────────
    if stream:
        async def stream_generator():
            try:
                async for chunk in generate_chat_completion(
                    request, body, user, background_tasks=background_tasks
                ):
                    yield chunk
            except Exception as e:
                logger.error("Chat completion stream error: %s", e, exc_info=True)
                yield f"data: {json.dumps({'error': {'code': 500, 'message': str(e), 'type': 'provider_error'}})}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            content=stream_generator(),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    # ── Non-streaming response ────────────────────────────────────────────────
    accumulated_content = ""
    accumulated_tool_calls: list[dict] = []
    usage_data: dict | None = None
    finish_reason: str | None = None
    error_chunk: dict | None = None

    try:
        async for chunk_str in generate_chat_completion(
            request, body, user, background_tasks=background_tasks
        ):
            if not chunk_str.startswith("data: "):
                continue
            data = chunk_str[6:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue

            if "error" in chunk:
                error_chunk = chunk
                break

            choice = (chunk.get("choices") or [{}])[0]
            delta = choice.get("delta", {})

            if delta.get("content"):
                accumulated_content += delta["content"]

            if delta.get("tool_calls"):
                for tc in delta["tool_calls"]:
                    idx = tc.get("index", 0)
                    while len(accumulated_tool_calls) <= idx:
                        accumulated_tool_calls.append({})
                    existing = accumulated_tool_calls[idx]
                    if not existing:
                        accumulated_tool_calls[idx] = dict(tc)
                    else:
                        fn = tc.get("function", {})
                        if fn.get("arguments"):
                            existing.setdefault("function", {})
                            existing["function"]["arguments"] = (
                                existing["function"].get("arguments", "") + fn["arguments"]
                            )

            if chunk.get("usage"):
                usage_data = chunk["usage"]

            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]

    except Exception as e:
        logger.error("Non-streaming completion error: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": 500, "message": str(e), "type": "provider_error"}},
        )

    if error_chunk:
        code = error_chunk.get("error", {}).get("code", 500)
        return JSONResponse(status_code=int(code) if isinstance(code, int) else 500, content=error_chunk)

    # Build OpenAI-compatible non-streaming response
    import time as _time
    import uuid as _uuid

    response = {
        "id": f"chatcmpl-{_uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(_time.time()),
        "model": body.get("model", ""),
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": accumulated_content or None,
                    "tool_calls": accumulated_tool_calls if accumulated_tool_calls else None,
                },
                "finish_reason": finish_reason or "stop",
            }
        ],
        "usage": usage_data or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    return JSONResponse(content=response)
