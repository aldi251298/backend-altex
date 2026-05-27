"""
Chat completion orchestrator.
Main entry point for chat completions with SSE streaming.
Mengikuti SRS Section 5.2: Stream Generator Implementation.
"""

import asyncio
import json
import logging
from typing import Any, AsyncGenerator

import aiohttp
from sqlalchemy import text

from constants import DEFAULT_MODEL_CACHE_TTL, SSE_TIMEOUT_SECONDS, time_ns, mask_api_key
from utils.streaming import (
    format_sse_data,
    format_sse_done,
    format_sse_error,
    create_status_event,
)

logger = logging.getLogger(__name__)

# ============================================================================
# Model Config Cache (OPT: reduce provider API calls)
# ============================================================================

_model_config_cache: dict[str, dict] = {}
_model_config_timestamps: dict[str, float] = {}


async def generate_chat_completion(
    request: Any,
    form_data: dict,
    user: dict,
    background_tasks: Any = None,
) -> AsyncGenerator[str, None]:
    """
    Main orchestrator for chat completions.
    
    Flow:
    1. Validate user & model access
    2. Apply model params
    3. Run preprocessing pipeline (filters, RAG, web search, tools)
    4. Stream to provider
    5. Handle tool calling loop
    6. Send SSE events back to client
    7. Save to DB after streaming
    """
    # Extract parameters
    model_id = form_data.get("model", "")
    messages = form_data.get("messages", [])
    stream = form_data.get("stream", True)
    files = form_data.get("files", [])
    web_search = form_data.get("web_search", False)
    extra_params = {
        k: v for k, v in form_data.items()
        if k not in ("model", "messages", "stream", "files", "web_search")
    }

    # Validate messages
    if not messages:
        yield format_sse_error(422, "Messages are required")
        yield format_sse_done()
        return

    # Generate chat/message IDs
    import uuid as uuid_module
    chat_id = form_data.get("chat_id", str(uuid_module.uuid4()))
    message_id = str(uuid_module.uuid4())

    # Get model config with cache (reduces provider API calls)
    model = await _get_model_config(model_id)
    if not model:
        yield format_sse_error(404, f"Model '{model_id}' tidak ditemukan")
        yield format_sse_done()
        return

    # Get provider config for the model (would query DB in production)
    provider = await _get_provider_for_model(model)
    if not provider:
        yield format_sse_error(503, "Provider untuk model tidak ditemukan")
        yield format_sse_done()
        return

    # Build request body
    body = {
        "model": model_id,
        "messages": messages,
        "stream": stream,
    }
    body.update(extra_params)

    # Build provider URL and headers
    provider_url = provider["base_url"].rstrip("/")
    provider_headers = await _get_provider_headers(provider)

    # ========================================================================
    # PREPROCESSING PIPELINE (SRS Section 4)
    # ========================================================================

    # [1] Apply system prompt & model params
    from utils.payload import (
        apply_system_prompt_to_body,
        apply_model_params_to_body,
        strip_unsupported_params,
    )
    body = apply_system_prompt_to_body(model.get("params", {}), body)
    body = apply_model_params_to_body(model.get("params", {}), body)

    # [2] Filter functions (INLET)
    from utils.filter import process_filter_functions
    filters = model.get("filters", [])
    body = await process_filter_functions(
        filters=filters,
        body=body,
        user=user,
        event_emitter=None,  # Would be set up for SSE event emission
        phase="inlet",
    )

    # [3] RAG: if files present
    if files:
        from utils.middleware import chat_completion_files_handler
        body = await chat_completion_files_handler(
            body=body,
            user=user,
            event_emitter=None,
        )

    # [4] Web search
    body.pop("web_search", None)  # Remove from body before sending to AI
    if web_search:
        from utils.middleware import chat_completion_web_search_handler
        body = await chat_completion_web_search_handler(
            body=body,
            user=user,
            event_emitter=None,
        )

    # [5] Tool specs injection
    from utils.tools import prepare_tools_for_request
    from env import settings
    body = await prepare_tools_for_request(
        body=body,
        model=model,
        user=user,
        settings=settings,
    )

    # [6] Strip unsupported params
    capabilities = model.get("capabilities", {})
    body = strip_unsupported_params(body, capabilities)

    # ========================================================================
    # STREAMING (SRS Section 5)
    # ========================================================================

    accumulated_content = ""
    accumulated_tool_calls = {}
    usage_data = None
    finish_reason = None

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

                async for raw_line in response.content:
                    # Check if client disconnected (SRS Section 6)
                    if request and hasattr(request, 'is_disconnected'):
                        if await request.is_disconnected():
                            logger.info(f"Client disconnected for message {message_id}")
                            break

                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data: "):
                        continue

                    data = line[6:]  # Remove "data: " prefix

                    if data == "[DONE]":
                        yield format_sse_done()
                        break

                    try:
                        chunk = json.loads(data)
                        choice = chunk.get("choices", [{}])[0]
                        delta = choice.get("delta", {})

                        # FILTER: Strip reasoning field to prevent leaking internal
                        # thinking process to the client (Qwen3.x outputs delta.reasoning)
                        if delta and "reasoning" in delta:
                            del delta["reasoning"]

                        # Accumulate content for DB save (from cleaned delta)
                        if delta.get("content"):
                            accumulated_content += delta["content"]

                        # Accumulate tool calls
                        if delta.get("tool_calls"):
                            for tc in delta["tool_calls"]:
                                idx = str(tc.get("index", 0))
                                if idx not in accumulated_tool_calls:
                                    accumulated_tool_calls[idx] = tc
                                else:
                                    existing = accumulated_tool_calls[idx]
                                    if tc.get("function", {}).get("arguments"):
                                        existing["function"]["arguments"] = (
                                            existing["function"].get("arguments", "") +
                                            tc["function"]["arguments"]
                                        )

                        # Track usage
                        if chunk.get("usage"):
                            usage_data = chunk["usage"]

                        finish_reason = choice.get("finish_reason")

                        # Forward chunk to client (reasoning already stripped from delta)
                        yield format_sse_data(chunk)

                    except json.JSONDecodeError:
                        logger.warning(f"Malformed SSE chunk (skipped): {data[:100]}")
                        continue

    except aiohttp.ClientError as e:
        logger.error(f"Provider connection error: {e}")
        yield format_sse_error(503, str(e))
        yield format_sse_done()

    # ========================================================================
    # POST-STREAMING: Save to DB (SRS Section 11)
    # ========================================================================

    # Save to DB - even if streaming was interrupted
    await _save_completion_to_db(
        chat_id=chat_id,
        message_id=message_id,
        content=accumulated_content,
        tool_calls=list(accumulated_tool_calls.values()),
        usage=usage_data,
        done=(finish_reason == "stop"),
        stopped=(finish_reason is None and bool(accumulated_content)),
        user_id=user["id"],
    )

    # Trigger background tasks if normal completion
    if finish_reason == "stop" and background_tasks:
        from utils.task import run_post_completion_tasks
        from env import settings as app_settings
        background_tasks.add_task(
            run_post_completion_tasks,
            chat_id=chat_id,
            messages=body["messages"] + [{
                "role": "assistant",
                "content": accumulated_content,
            }],
            model_id=model_id,
            user=user,
            is_new_chat=True,
            settings=app_settings,
        )


async def _get_model_config(model_id: str) -> dict:
    """
    Get model configuration from providers table and remote API.
    
    Flow:
    1. Check in-memory cache first (TTL: 5 minutes)
    2. Parse model_id to extract provider prefix (e.g., "openai.gpt-4o" -> "openai")
    3. Query providers table for matching active provider
    4. Fetch model details from provider's /models endpoint
    5. Return enriched config with capabilities, params, filters
    """
    import time
    
    # Check cache first (OPT: reduce provider API calls)
    current_time = time.time()
    if model_id in _model_config_cache:
        cached_time = _model_config_timestamps.get(model_id, 0)
        if current_time - cached_time < DEFAULT_MODEL_CACHE_TTL:
            return _model_config_cache[model_id]
    
    from database import async_session_factory
    from models.providers import Provider
    
    # Parse prefix from model_id (e.g., "openai.gpt-4o" -> provider="openai", model="gpt-4o")
    parts = model_id.split(".", 1)
    provider_prefix = parts[0] if len(parts) > 1 else model_id
    remote_model_id = parts[1] if len(parts) > 1 else model_id
    
    async with async_session_factory() as db:
        # Query active provider by prefix or name
        result = await db.execute(
            text("""
                SELECT id, name, base_url, api_key, auth_type, prefix, is_active, extra_config
                FROM providers
                WHERE is_active = true
                  AND (prefix = :prefix OR name = :name)
                LIMIT 1
            """),
            {"prefix": provider_prefix, "name": provider_prefix},
        )
        provider_row = result.fetchone()
        
        if not provider_row:
            # No specific provider found, return default config
            default_config = {
                "id": model_id,
                "capabilities": {"vision": False, "tools": True},
                "params": {},
                "filters": [],
                "provider": None,
            }
        else:
            # Build provider config
            provider_config = {
                "name": provider_row[1],
                "base_url": provider_row[2],
                "api_key": provider_row[3] or "",
                "auth_type": provider_row[4] or "bearer",
                "prefix": provider_row[5] or "",
                "extra_config": provider_row[7] if len(provider_row) > 7 else {},
            }
            
            # Fetch model details from provider API
            model_info = await _fetch_model_from_provider(provider_config, remote_model_id)
            
            default_config = {
                "id": model_id,
                "remote_id": remote_model_id,
                "capabilities": model_info.get("capabilities", {"vision": False, "tools": True}),
                "params": model_info.get("params", {}),
                "filters": model_info.get("filters", []),
                "provider": provider_config,
            }
    
    # Update cache (OPT: reduce provider API calls)
    _model_config_cache[model_id] = default_config
    _model_config_timestamps[model_id] = time.time()
    
    return default_config


async def _fetch_model_from_provider(provider: dict, model_id: str) -> dict:
    """
    Fetch model details from provider's /models endpoint.
    Returns model info with capabilities and params.
    """
    import asyncio
    
    provider_url = provider["base_url"].rstrip("/")
    headers = {"Content-Type": "application/json"}
    if provider.get("api_key"):
        headers["Authorization"] = f"Bearer {provider['api_key']}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{provider_url}/models/{model_id}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                if response.status == 200:
                    model_data = await response.json()
                    return _parse_model_response(model_data)
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.debug(f"Failed to fetch model {model_id} from {provider['name']}: {e}")
    
    # Fallback: try listing all models
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{provider_url}/models",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    models_list = data.get("data", [])
                    for m in models_list:
                        if m.get("id") == model_id:
                            return _parse_model_response(m)
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.debug(f"Failed to list models from {provider['name']}: {e}")
    
    # Default fallback
    return {
        "id": model_id,
        "capabilities": {"vision": False, "tools": True},
        "params": {},
        "filters": [],
    }


def _parse_model_response(model_data: dict) -> dict:
    """Parse model data from provider API response."""
    capabilities = {
        "vision": False,
        "tools": True,
    }
    
    # Detect capabilities from model ID or metadata
    model_id = model_data.get("id", "").lower()
    if any(term in model_id for term in ["vision", "img", "gpt-4o", "claude-3.5", "gemini-1.5"]):
        capabilities["vision"] = True
    if any(term in model_id for term in ["turbo", "pro", "haiku"]):
        capabilities["tools"] = True
    
    params = {}
    if isinstance(model_data.get("defaults"), dict):
        params = model_data["defaults"]
    
    return {
        "id": model_data.get("id", ""),
        "capabilities": capabilities,
        "params": params,
        "filters": [],
    }


async def _get_provider_for_model(model: dict) -> dict:
    """
    Get provider configuration for a model.
    
    If model already has provider info, return it.
    Otherwise, query providers table for active provider.
    """
    if model.get("provider"):
        p = model["provider"]
        return {
            "name": p.get("name", "default"),
            "base_url": p.get("base_url", "http://localhost:8000/v1"),
            "api_key": p.get("api_key", ""),
            "auth_type": p.get("auth_type", "bearer"),
            "prefix": p.get("prefix", ""),
        }
    
    # Fallback: query first active provider
    from database import async_session_factory
    from models.providers import Provider
    
    async with async_session_factory() as db:
        result = await db.execute(
            text("""
                SELECT name, base_url, api_key, auth_type, prefix
                FROM providers
                WHERE is_active = true
                LIMIT 1
            """)
        )
        row = result.fetchone()
        
        if row:
            return {
                "name": row[0],
                "base_url": row[1],
                "api_key": row[2] or "",
                "auth_type": row[3] or "bearer",
                "prefix": row[4] or "",
            }
    
    # Ultimate fallback - use openai_base_url from env
    from env import settings as app_settings
    fallback_url = app_settings.openai_base_url or "http://172.31.2.240:8000/v1"
    return {
        "name": "default",
        "base_url": fallback_url,
        "api_key": "",
        "auth_type": "bearer",
        "prefix": "",
    }


async def _get_provider_headers(provider: dict) -> dict:
    """Build request headers for provider based on auth type."""
    headers = {"Content-Type": "application/json"}
    api_key = provider.get("api_key", "")
    auth_type = provider.get("auth_type", "bearer")

    if auth_type == "bearer":
        headers["Authorization"] = f"Bearer {api_key}"
    elif auth_type == "none":
        pass  # No auth
    elif auth_type == "azure_ad":
        # Would use azure.identity for Azure AD
        headers["Authorization"] = f"Bearer {api_key}"
    elif auth_type == "session":
        pass  # Cookie-based
    elif auth_type == "system_oauth":
        pass  # OAuth token

    # Add extra headers
    for key, value in provider.get("extra_config", {}).get("extra_headers", {}).items():
        headers[key] = value

    return headers


async def _save_completion_to_db(
    chat_id: str,
    message_id: str,
    content: str,
    tool_calls: list,
    usage: dict | None,
    done: bool,
    stopped: bool,
    user_id: str,
) -> None:
    """
    Save completion result to database using PostgreSQL JSONB path operations.
    SRS Section 11.1: Uses jsonb_set for atomic update.
    """
    if not content and not tool_calls:
        return

    message_data = {
        "id": message_id,
        "role": "assistant",
        "content": content,
        "tool_calls": tool_calls if tool_calls else None,
        "done": done,
        "stopped": stopped,
        "timestamp": time_ns() // 1_000_000_000,  # Convert to nanoseconds -> seconds
    }

    if usage:
        message_data["usage"] = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

    # Ensure chat exists first
    from database import async_session_factory
    
    async with async_session_factory() as db:
        # Check if chat exists
        from sqlalchemy import select
        from models.chats import Chat
        result = await db.execute(
            select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id)
        )
        existing_chat = result.scalar_one_or_none()

        if not existing_chat:
            # Create chat if it doesn't exist
            import uuid
            existing_chat = Chat(
                id=chat_id,
                user_id=user_id,
                title="Chat",
                chat={
                    "title": "Chat",
                    "history": {"messages": {}, "currentId": message_id},
                    "models": [],
                    "tags": [],
                    "files": [],
                },
                created_at=time_ns(),
                updated_at=time_ns(),
                is_pinned=False,
                is_archived=False,
                is_shared=False,
            )
            db.add(existing_chat)
            await db.commit()

        # Use PostgreSQL jsonb_set for atomic message update (SRS Section 11.1)
        # Build JSONB path dynamically with f-string (bind param not valid in path)
        # NOTE: asyncpg doesn't support :param::jsonb syntax, so we use to_jsonb(text)
        # which safely converts a bind parameter string to jsonb.
        message_path = f"{{history,messages,{message_id}}}"
        message_json = json.dumps(message_data)
        current_id_json = json.dumps(message_id)

        await db.execute(
            text(f"""
                UPDATE chats
                SET
                    chat = jsonb_set(
                        jsonb_set(
                            chat,
                            '{message_path}',
                            to_jsonb(:message_data),
                            true
                        ),
                        '{{history,currentId}}',
                        to_jsonb(:current_id),
                        true
                    ),
                    updated_at = :updated_at
                WHERE id = :chat_id
            """),
            {
                "message_data": message_json,
                "current_id": current_id_json,
                "chat_id": chat_id,
                "updated_at": time_ns(),
            }
        )
        await db.commit()

    logger.info(f"Saved message {message_id} to chat {chat_id}")
