"""
Task utilities for background tasks.
Title generation, tag generation, and post-completion processing.
"""

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TITLE_PROMPT = """Berdasarkan percakapan di bawah, buat judul yang singkat (maksimal 6 kata), 
deskriptif, dan dalam bahasa yang sama dengan percakapan. 
Hanya kembalikan judulnya saja, tanpa penjelasan atau tanda kutip.

Percakapan:
{messages}

Judul:"""


async def generate_chat_title(
    chat_id: str,
    messages: list[dict],
    model_id: str,
    user: dict,
    settings: Any = None,
) -> str:
    """
    Generate chat title via LLM in background.
    Called after streaming completes - NOT blocking response.
    """
    # Take only first 2 messages (enough for context)
    context = messages[:2]

    formatted = "\n".join([
        f"{m.get('role', 'unknown').upper()}: {str(m.get('content', ''))[:500]}"
        for m in context
    ])

    prompt_template = (
        getattr(settings, "title_generation_prompt", None) or DEFAULT_TITLE_PROMPT
    )
    prompt = prompt_template.format(messages=formatted)

    try:
        # Use lightweight task model if configured
        task_model = getattr(settings, "task_model", None) or model_id

        # Call provider via aiohttp (non-streaming)
        from database import async_session_factory
        from sqlalchemy import text as sa_text

        async with async_session_factory() as db:
            row = await db.execute(
                sa_text(
                    "SELECT base_url, api_key FROM providers WHERE is_active = true LIMIT 1"
                )
            )
            provider_row = row.fetchone()

        if provider_row:
            import aiohttp

            provider_url = provider_row[0].rstrip("/")
            api_key = provider_row[1] or ""
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            payload = {
                "model": task_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 50,
                "stream": False,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{provider_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = (
                            data.get("choices", [{}])[0]
                            .get("message", {})
                            .get("content")
                        )
                        title = (content.strip() if content else None) or "Chat Baru"
                    else:
                        raise Exception(f"HTTP {resp.status}")
        else:
            # No provider configured — fall back to first user message
            raise Exception("No active provider")

    except Exception as e:
        logger.warning(f"Title generation gagal: {e}")
        # Fallback: take first 50 chars of first user message
        user_msg = next(
            (m.get("content", "Chat Baru") for m in messages if m.get("role") == "user"),
            "Chat Baru"
        )
        title = str(user_msg)[:50]
        if len(user_msg) > 50:
            title += "..."

    # Sanitize: remove quotes, limit length
    title = str(title).strip('"\'').strip() if title else "Chat Baru"
    if len(title) > 100:
        title = title[:97] + "..."

    # Update DB (placeholder)
    # await Chats.update_chat_title(chat_id, title)

    logger.info(f"Title generated for chat {chat_id}: '{title}'")
    return title


async def generate_chat_tags(
    chat_id: str,
    messages: list[dict],
    model_id: str,
    settings: Any = None,
) -> list[str]:
    """
    Generate tags for chat via LLM in background.
    """
    try:
        # Placeholder - would call LLM to generate tags
        # context = messages[:5]
        # prompt = generate tags prompt
        # response = await call_provider(...)
        # tags = response.content.split(",")
        tags = ["ai", "chat"]
    except Exception as e:
        logger.warning(f"Tag generation gagal: {e}")
        tags = []

    # Update DB (placeholder)
    # await Chats.update_tags(chat_id, tags)

    return tags


async def run_post_completion_tasks(
    chat_id: str,
    messages: list[dict],
    model_id: str,
    user: dict,
    is_new_chat: bool,
    settings: Any = None,
) -> None:
    """
    Runner for all background tasks after streaming completes.
    Called via FastAPI BackgroundTasks - non-blocking.
    """
    tasks = []

    if is_new_chat and settings and hasattr(settings, 'enable_title_generation') and settings.enable_title_generation:
        tasks.append(generate_chat_title(chat_id, messages, model_id, user, settings))

    if settings and hasattr(settings, 'enable_tag_generation') and settings.enable_tag_generation:
        tasks.append(generate_chat_tags(chat_id, messages, model_id, settings))

    # Run all tasks in parallel
    await asyncio.gather(*tasks, return_exceptions=True)
