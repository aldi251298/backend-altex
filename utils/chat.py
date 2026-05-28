"""
Chat completion orchestrator.
Handles: streaming, non-streaming, parallel tool calling, vision, RAG, web search.
No auth required — anonymous user only.
"""

import asyncio
import json
import logging
import time
import uuid as uuid_module
from typing import Any, AsyncGenerator

import aiohttp

from constants import (
    DEFAULT_MODEL_CACHE_TTL,
    MAX_TOOL_CALL_ITERATIONS,
    SSE_TIMEOUT_SECONDS,
    time_ns,
)
from utils.streaming import format_sse_data, format_sse_done, format_sse_error, _parse_sse_event

logger = logging.getLogger(__name__)

# ── In-memory model config cache (5 min TTL) ─────────────────────────────────
_model_cache: dict[str, dict] = {}
_model_cache_ts: dict[str, float] = {}


# ============================================================================
# Public entry point
# ============================================================================


async def generate_chat_completion(
    request: Any,
    form_data: dict,
    user: dict,
    background_tasks: Any = None,
) -> AsyncGenerator[str, None]:
    """
    Full chat completion pipeline:
    1. Resolve model + provider
    2. Apply system prompt / model params
    3. RAG (files)
    4. Web search
    5. Tool spec injection
    6. Stream to provider
    7. Parallel tool calling loop (if finish_reason == tool_calls)
    8. Save to DB
    9. Trigger background tasks (title/tag generation)
    """
    model_id = form_data.get("model", "")
    messages: list[dict] = form_data.get("messages", [])
    stream: bool = form_data.get("stream", True)
    files: list = form_data.get("files", [])
    web_search: bool = form_data.get("web_search", False)
    chat_id: str = form_data.get("chat_id") or str(uuid_module.uuid4())
    message_id: str = str(uuid_module.uuid4())

    # Extract thinking toggle flags (sent by Android client separately or as top-level fields)
    # These are forwarded to vLLM via chat_template_kwargs
    enable_thinking: bool | None = form_data.get("enable_thinking")   # None = not set (use model default)
    preserve_thinking: bool | None = form_data.get("preserve_thinking")

    extra_params = {
        k: v for k, v in form_data.items()
        if k not in ("model", "messages", "stream", "files", "web_search", "chat_id",
                     "enable_thinking", "preserve_thinking")
    }

    if not messages:
        yield format_sse_error(422, "Messages are required")
        yield format_sse_done()
        return

    # ── 1. Resolve model + provider ──────────────────────────────────────────
    model = await _get_model_config(model_id)
    if not model:
        yield format_sse_error(404, f"Model '{model_id}' tidak ditemukan")
        yield format_sse_done()
        return

    provider = await _get_provider_for_model(model)
    if not provider:
        yield format_sse_error(503, "Provider untuk model tidak ditemukan")
        yield format_sse_done()
        return

    # ── 2. Build base body ───────────────────────────────────────────────────
    body: dict = {"model": model_id, "messages": list(messages), "stream": True}
    body.update(extra_params)

    # ── 3. Apply system prompt + model params ────────────────────────────────
    from utils.payload import apply_system_prompt_to_body, apply_model_params_to_body, strip_unsupported_params, apply_thinking_params
    body = apply_system_prompt_to_body(model.get("params", {}), body)
    body = apply_model_params_to_body(model.get("params", {}), body)

    # ── 3b. Apply thinking toggle ────────────────────────────────────────────
    # Handles: enable_thinking=False → chat_template_kwargs={"enable_thinking": False}
    # Also handles chat_template_kwargs already in body (from extra_params pass-through)
    body = apply_thinking_params(body, enable_thinking, preserve_thinking)

    # ── 4. Filter pipeline (inlet) ───────────────────────────────────────────
    from utils.filter import process_filter_functions
    body = await process_filter_functions(
        filters=model.get("filters", []),
        body=body,
        user=user,
        event_emitter=None,
        phase="inlet",
    )

    # ── 5. RAG (files) ───────────────────────────────────────────────────────
    if files:
        from utils.middleware import chat_completion_files_handler
        body = await chat_completion_files_handler(body=body, user=user, event_emitter=None)

    # ── 6. Web search ────────────────────────────────────────────────────────
    body.pop("web_search", None)
    if web_search:
        from utils.middleware import chat_completion_web_search_handler
        body = await chat_completion_web_search_handler(body=body, user=user, event_emitter=None)

    # ── 7. Tool spec injection ───────────────────────────────────────────────
    from utils.tools import prepare_tools_for_request
    from env import settings as app_settings
    body = await prepare_tools_for_request(body=body, model=model, user=user, settings=app_settings)

    # ── 8. Strip unsupported params ──────────────────────────────────────────
    body = strip_unsupported_params(body, model.get("capabilities", {}))

    provider_url = provider["base_url"].rstrip("/")
    provider_headers = _build_provider_headers(provider)

    # ── 9. Streaming + tool calling loop ─────────────────────────────────────
    accumulated_content = ""
    accumulated_tool_calls: dict[str, dict] = {}
    usage_data: dict | None = None
    finish_reason: str | None = None
    tool_call_iterations = 0

    while True:
        iter_content = ""
        iter_tool_calls: dict[str, dict] = {}
        iter_finish_reason: str | None = None

        try:
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=SSE_TIMEOUT_SECONDS)
                async with session.post(
                    url=f"{provider_url}/chat/completions",
                    headers=provider_headers,
                    json=body,
                    timeout=timeout,
                ) as response:

                    if response.status != 200:
                        error_text = await response.text()
                        yield format_sse_error(response.status, error_text)
                        yield format_sse_done()
                        return

                    # ── Buffer-based SSE parser (TCP chunks ≠ SSE events) ──
                    sse_buffer = ""
                    stream_done = False
                    async for raw_chunk in response.content:
                        if stream_done:
                            break
                        # Client disconnect check
                        if request and hasattr(request, "is_disconnected"):
                            try:
                                if await request.is_disconnected():
                                    logger.info("Client disconnected, stopping stream")
                                    return
                            except Exception:
                                pass

                        # Accumulate chunk into buffer
                        sse_buffer += raw_chunk.decode("utf-8", errors="replace")

                        # Split on SSE event boundary (\n\n)
                        while "\n\n" in sse_buffer:
                            event_text, sse_buffer = sse_buffer.split("\n\n", 1)

                            # Parse each line in the event
                            for line in event_text.split("\n"):
                                line = line.strip()
                                if not line:
                                    continue

                                # Extract data payload
                                parsed_data = _parse_sse_event(line)
                                if parsed_data is None:
                                    continue

                                if parsed_data == "[DONE]":
                                    # Mark stream done without returning — let DB save complete
                                    iter_finish_reason = iter_finish_reason or "stop"
                                    stream_done = True
                                    break  # break while loop, async for guard will exit next iteration

                                try:
                                    chunk = json.loads(parsed_data)
                                except json.JSONDecodeError:
                                    logger.debug("Malformed SSE chunk (skipped): %s", parsed_data[:80])
                                    continue

                                choice = (chunk.get("choices") or [{}])[0]
                                delta = choice.get("delta", {})

                                # Strip internal reasoning (Qwen3 outputs delta.reasoning)
                                delta.pop("reasoning", None)
                                delta.pop("reasoning_content", None)

                                # Accumulate content
                                if delta.get("content"):
                                    iter_content += delta["content"]

                                # Accumulate tool calls (parallel: keyed by index)
                                if delta.get("tool_calls"):
                                    for tc in delta["tool_calls"]:
                                        idx = str(tc.get("index", 0))
                                        if idx not in iter_tool_calls:
                                            iter_tool_calls[idx] = {
                                                "id": tc.get("id", ""),
                                                "type": "function",
                                                "function": {
                                                    "name": tc.get("function", {}).get("name", ""),
                                                    "arguments": tc.get("function", {}).get("arguments", ""),
                                                },
                                                "index": int(idx),
                                            }
                                        else:
                                            existing = iter_tool_calls[idx]
                                            fn_args = tc.get("function", {}).get("arguments", "")
                                            if fn_args:
                                                existing["function"]["arguments"] += fn_args
                                            if tc.get("id") and not existing["id"]:
                                                existing["id"] = tc["id"]
                                            if tc.get("function", {}).get("name") and not existing["function"]["name"]:
                                                existing["function"]["name"] = tc["function"]["name"]

                                if chunk.get("usage"):
                                    usage_data = chunk["usage"]

                                iter_finish_reason = choice.get("finish_reason") or iter_finish_reason

                                # Skip forwarding empty delta chunks (Qwen3 sends many reasoning-only chunks)
                                if not delta and not choice.get("finish_reason") and not chunk.get("usage"):
                                    continue

                                # Forward chunk to client (with cleaned delta)
                                yield format_sse_data(chunk)

        except aiohttp.ClientConnectorError as e:
            logger.error("Provider connection refused: %s", e)
            yield format_sse_error(503, f"Cannot connect to provider: {e}")
            yield format_sse_done()
            return
        except aiohttp.ClientError as e:
            logger.error("Provider client error: %s", e)
            yield format_sse_error(503, str(e))
            yield format_sse_done()
            return
        except asyncio.TimeoutError:
            logger.error("Provider timeout after %ds", SSE_TIMEOUT_SECONDS)
            yield format_sse_error(504, "Provider response timeout")
            yield format_sse_done()
            return

        accumulated_content += iter_content
        finish_reason = iter_finish_reason

        # ── Tool calling loop ────────────────────────────────────────────────
        if iter_finish_reason == "tool_calls" and iter_tool_calls and tool_call_iterations < MAX_TOOL_CALL_ITERATIONS:
            tool_call_iterations += 1
            tool_calls_list = list(iter_tool_calls.values())

            # Emit tool-use status event to client
            status_event = {
                "type": "status",
                "data": {
                    "description": f"Menjalankan {len(tool_calls_list)} tool(s)...",
                    "action": "tool_execution",
                    "done": False,
                },
            }
            yield f"data: {json.dumps(status_event)}\n\n"

            # Execute all tool calls IN PARALLEL
            from utils.tools import execute_tool_calls_parallel
            tool_results = await execute_tool_calls_parallel(tool_calls_list)

            # Emit done status
            done_event = {
                "type": "status",
                "data": {"description": "Tools selesai dijalankan", "action": "tool_execution", "done": True},
            }
            yield f"data: {json.dumps(done_event)}\n\n"

            # Append assistant message with tool calls + tool results to history
            body["messages"].append({
                "role": "assistant",
                "content": iter_content or None,
                "tool_calls": tool_calls_list,
            })
            for result in tool_results:
                body["messages"].append({
                    "role": "tool",
                    "tool_call_id": result["tool_call_id"],
                    "content": json.dumps(result["output"]) if not isinstance(result["output"], str) else result["output"],
                })

            accumulated_tool_calls.update(iter_tool_calls)
            # Continue loop for next LLM call
            continue

        # No more tool calls — exit loop
        accumulated_tool_calls.update(iter_tool_calls)
        break

    # ── 10. Save to DB ───────────────────────────────────────────────────────
    await _save_completion_to_db(
        chat_id=chat_id,
        message_id=message_id,
        content=accumulated_content,
        tool_calls=list(accumulated_tool_calls.values()),
        usage=usage_data,
        done=(finish_reason == "stop"),
        stopped=(finish_reason is None and bool(accumulated_content)),
        user_id=user["id"],
        model_id=model_id,
    )

    # ── 11. Background tasks (title/tag generation) ──────────────────────────
    if finish_reason == "stop" and background_tasks:
        from utils.task import run_post_completion_tasks
        background_tasks.add_task(
            run_post_completion_tasks,
            chat_id=chat_id,
            messages=body["messages"] + [{"role": "assistant", "content": accumulated_content}],
            model_id=model_id,
            user=user,
            is_new_chat=True,
            settings=app_settings,
        )

    yield format_sse_done()


# ============================================================================
# Model config resolution
# ============================================================================


async def _get_model_config(model_id: str) -> dict | None:
    """
    Resolve model config from providers table.
    Supports prefix notation: "vllm.qwen3-27b" → provider prefix "vllm", model "qwen3-27b".
    Falls back to first active provider if no prefix match.
    """
    now = time.time()
    if model_id in _model_cache and now - _model_cache_ts.get(model_id, 0) < DEFAULT_MODEL_CACHE_TTL:
        return _model_cache[model_id]

    from database import async_session_factory
    from sqlalchemy import text

    parts = model_id.split(".", 1)
    provider_prefix = parts[0] if len(parts) > 1 else model_id
    remote_model_id = parts[1] if len(parts) > 1 else model_id

    async with async_session_factory() as db:
        result = await db.execute(
            text("""
                SELECT id, name, base_url, api_key, auth_type, prefix, extra_config
                FROM providers
                WHERE is_active = true
                  AND (prefix = :prefix OR name ILIKE :name)
                LIMIT 1
            """),
            {"prefix": provider_prefix, "name": provider_prefix},
        )
        row = result.fetchone()

        if not row:
            # No prefix match — try first active provider and use full model_id
            result2 = await db.execute(
                text("SELECT id, name, base_url, api_key, auth_type, prefix, extra_config FROM providers WHERE is_active = true LIMIT 1")
            )
            row = result2.fetchone()
            remote_model_id = model_id  # use full model_id as-is

    if not row:
        return None

    provider_config = {
        "name": row[1],
        "base_url": row[2],
        "api_key": row[3] or "",
        "auth_type": row[4] or "none",
        "prefix": row[5] or "",
        "extra_config": row[6] if row[6] else {},
    }

    # Detect capabilities from model name
    capabilities = _detect_capabilities(remote_model_id)

    config = {
        "id": model_id,
        "remote_id": remote_model_id,
        "capabilities": capabilities,
        "params": {},
        "filters": [],
        "provider": provider_config,
    }

    _model_cache[model_id] = config
    _model_cache_ts[model_id] = now
    return config


def _detect_capabilities(model_id: str) -> dict:
    """Detect model capabilities from model name heuristics."""
    mid = model_id.lower()
    vision = any(t in mid for t in ["vision", "vl", "gpt-4o", "claude-3", "gemini", "llava", "pixtral", "qwen-vl", "internvl"])
    tools = any(t in mid for t in ["gpt-4", "gpt-3.5", "claude", "qwen", "mistral", "llama-3", "gemini", "deepseek"])
    # Thinking / extended reasoning — Qwen3, QwQ, DeepSeek-R1, o1/o3, Claude 3.5+
    thinking = any(t in mid for t in ["qwen3", "qwq", "deepseek-r1", "r1", "o1", "o3", "claude-3-5", "claude-3-7"])
    return {
        "vision": vision,
        "tools": tools,
        "thinking": thinking,
        "streaming": True,
    }


async def _get_provider_for_model(model: dict) -> dict | None:
    if model.get("provider"):
        p = model["provider"]
        return {
            "name": p.get("name", "default"),
            "base_url": p.get("base_url", ""),
            "api_key": p.get("api_key", ""),
            "auth_type": p.get("auth_type", "none"),
            "prefix": p.get("prefix", ""),
            "extra_config": p.get("extra_config", {}),
        }

    # Fallback to env setting
    from env import settings as app_settings
    fallback = app_settings.openai_base_url or "http://localhost:8000/v1"
    return {
        "name": "default",
        "base_url": fallback,
        "api_key": app_settings.openai_api_key or "",
        "auth_type": "none" if not app_settings.openai_api_key else "bearer",
        "prefix": "",
        "extra_config": {},
    }


def _build_provider_headers(provider: dict) -> dict:
    """Build HTTP headers for provider request."""
    headers = {"Content-Type": "application/json"}
    api_key = provider.get("api_key", "")
    auth_type = provider.get("auth_type", "none")

    if auth_type == "bearer" and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    elif auth_type == "none":
        pass  # No auth — vLLM default
    elif auth_type == "azure_ad" and api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Extra headers from provider config
    extra = provider.get("extra_config", {})
    if isinstance(extra, dict):
        for k, v in extra.get("extra_headers", {}).items():
            headers[k] = v

    return headers


# ============================================================================
# DB persistence
# ============================================================================


async def _save_completion_to_db(
    chat_id: str,
    message_id: str,
    content: str,
    tool_calls: list,
    usage: dict | None,
    done: bool,
    stopped: bool,
    user_id: str,
    model_id: str = "",
) -> None:
    """
    Save assistant message to DB using atomic JSONB update.
    Creates chat row if it doesn't exist yet.
    """
    if not content and not tool_calls:
        return

    message_data: dict = {
        "id": message_id,
        "role": "assistant",
        "content": content,
        "tool_calls": tool_calls if tool_calls else None,
        "done": done,
        "stopped": stopped,
        "timestamp": time_ns(),
    }
    if usage:
        message_data["usage"] = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

    from database import async_session_factory
    from models.chats import Chat
    from sqlalchemy import select, text

    async with async_session_factory() as db:
        result = await db.execute(select(Chat).where(Chat.id == chat_id))
        existing = result.scalar_one_or_none()

        if not existing:
            existing = Chat(
                id=chat_id,
                user_id=user_id,
                title="Chat Baru",
                chat={
                    "title": "Chat Baru",
                    "history": {"messages": {}, "currentId": message_id},
                    "models": [model_id] if model_id else [],
                    "tags": [],
                    "files": [],
                },
                created_at=time_ns(),
                updated_at=time_ns(),
                is_pinned=False,
                is_archived=False,
                is_shared=False,
            )
            db.add(existing)
            await db.commit()

        # Atomic JSONB update — embed JSON as SQL literal to avoid asyncpg type error
        message_path = "{" + f"history,messages,{message_id}" + "}"
        message_sql = json.dumps(message_data).replace("'", "''")
        current_id_sql = json.dumps(message_id).replace("'", "''")

        await db.execute(
            text(f"""
                UPDATE chats
                SET
                    chat = jsonb_set(
                        jsonb_set(
                            chat,
                            '{message_path}',
                            '{message_sql}'::jsonb,
                            true
                        ),
                        '{{history,currentId}}',
                        '{current_id_sql}'::jsonb,
                        true
                    ),
                    updated_at = :updated_at
                WHERE id = :chat_id
            """),
            {"chat_id": chat_id, "updated_at": time_ns()},
        )
        await db.commit()

    logger.info("Saved message %s to chat %s", message_id, chat_id)


# ============================================================================
# Cache invalidation (called by provider update)
# ============================================================================


def invalidate_model_cache(model_id: str | None = None) -> None:
    """Invalidate model config cache. Pass None to clear all."""
    global _model_cache, _model_cache_ts
    if model_id:
        _model_cache.pop(model_id, None)
        _model_cache_ts.pop(model_id, None)
    else:
        _model_cache.clear()
        _model_cache_ts.clear()
