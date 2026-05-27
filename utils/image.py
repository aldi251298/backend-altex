"""
Image generation pipeline utility.

Supports two engine types (auto-detected from provider config):
  1. OpenAI-compatible  — POST /images/generations (DALL-E, A1111 with API, etc.)
  2. ComfyUI            — workflow-based API (POST /prompt + polling)

Flow:
  1. (Optional) LLM prompt enhancement — non-streaming, fast (~1-3s)
  2. Image generation via detected engine
  3. Emit SSE events per phase to client
"""

import asyncio
import json
import logging
import time
from typing import AsyncGenerator

import aiohttp

logger = logging.getLogger(__name__)

# ── Prompt enhancement system prompt ─────────────────────────────────────────
ENHANCE_SYSTEM_PROMPT = """\
You are an expert image prompt engineer specializing in text-to-image models \
(Stable Diffusion, Flux, SDXL, DALL-E).

Your ONLY task: take the user's image generation request and expand it into a \
detailed, vivid, high-quality prompt optimized for image generation.

CRITICAL RULES — read carefully:
- Output ONLY the enhanced image prompt — nothing else
- NO explanations, NO preamble, NO quotes, NO markdown, NO labels
- Do NOT output phrases like "Here is the enhanced prompt:" or "Enhanced:"
- Do NOT ask clarifying questions
- Always write in English (translate if needed)
- Add: lighting description, art style, mood/atmosphere, camera angle, \
  quality boosters (e.g. "8k", "highly detailed", "photorealistic" or \
  "digital art", "concept art" depending on style)
- Keep the core subject and intent intact
- Maximum 200 words

IMPORTANT — this function is ONLY called when the user has already confirmed \
they want an image generated. You are NOT deciding whether to generate an image. \
You are ONLY improving the prompt text. Always produce an enhanced prompt.
"""

# ── SSE event helpers ─────────────────────────────────────────────────────────

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _status(description: str, phase: str, done: bool = False) -> str:
    return _sse({
        "type": "status",
        "data": {"description": description, "phase": phase, "done": done},
    })


def _done() -> str:
    return "data: [DONE]\n\n"


def _error(code: int, message: str) -> str:
    return _sse({"type": "error", "error": {"code": code, "message": message}})


# ============================================================================
# Size parsing helper
# ============================================================================


def parse_size(size: str) -> tuple[int, int]:
    """
    Parse size string to (width, height).
    Accepts: "1024x1024", "1024x1792", etc.
    Returns (width, height) tuple.
    """
    try:
        parts = size.lower().replace(" ", "").split("x")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except (ValueError, AttributeError):
        pass
    return 1024, 1024  # safe default


# ============================================================================
# Main pipeline
# ============================================================================


async def generate_image_pipeline(
    prompt: str,
    *,
    llm_model: str = "",
    image_model: str = "",
    size: str = "1024x1024",
    quality: str = "standard",
    style: str = "",
    steps: int | None = None,
    guidance_scale: float = 7.5,
    negative_prompt: str = "",
    n: int = 1,
    enhance: bool = True,
    response_format: str = "url",
    seed: int | None = None,
) -> AsyncGenerator[str, None]:
    """
    Full SSE pipeline: LLM enhancement → image generation.

    Yields SSE strings:
      {"type":"status", "data":{...}}
      {"type":"prompt_enhanced", "data":{"original":..., "enhanced":...}}
      {"type":"image_result", "data":{"images":[...], "enhanced_prompt":..., ...}}
      {"type":"error", "error":{...}}
      data: [DONE]
    """
    original_prompt = prompt.strip()
    enhanced_prompt = original_prompt
    width, height = parse_size(size)

    # ── Resolve providers ────────────────────────────────────────────────────
    llm_provider, img_provider = await _resolve_providers(llm_model, image_model)

    if not img_provider:
        yield _error(503, "No active image provider configured. Add a provider in /api/providers.")
        yield _done()
        return

    # ── Phase 1: LLM Prompt Enhancement ─────────────────────────────────────
    if enhance and llm_provider:
        yield _status("Memperluas prompt dengan AI...", "enhancing", done=False)

        try:
            enhanced_prompt = await _enhance_prompt(
                original_prompt=original_prompt,
                style_hint=style,
                provider=llm_provider,
                model=llm_model or llm_provider.get("default_model", ""),
            )
            logger.info("Prompt enhanced: '%s...' → '%s...'", original_prompt[:40], enhanced_prompt[:40])
        except Exception as e:
            logger.warning("LLM enhancement failed (%s), using original prompt", e)
            enhanced_prompt = original_prompt
            yield _status("Enhancement gagal, menggunakan prompt asli", "enhancing", done=True)
        else:
            yield _status("Prompt berhasil diperluas", "enhancing", done=True)
    else:
        if enhance and not llm_provider:
            yield _status("LLM provider tidak tersedia, skip enhancement", "enhancing", done=True)

    # Always emit prompt_enhanced event for consistency
    yield _sse({
        "type": "prompt_enhanced",
        "data": {"original": original_prompt, "enhanced": enhanced_prompt},
    })

    # ── Phase 2: Image Generation ────────────────────────────────────────────
    yield _status("Generating image...", "generating", done=False)

    # Detect engine type from provider config
    engine_type = _detect_engine_type(img_provider)
    logger.info("Using image engine: %s (provider: %s)", engine_type, img_provider["name"])

    try:
        if engine_type == "comfyui":
            result = await _generate_comfyui(
                provider=img_provider,
                prompt=enhanced_prompt,
                model=image_model,
                width=width,
                height=height,
                steps=steps,
                guidance_scale=guidance_scale,
                negative_prompt=negative_prompt,
                seed=seed,
                response_format=response_format,
            )
        else:
            # OpenAI-compatible (A1111, DALL-E, etc.)
            result = await _generate_openai_compat(
                provider=img_provider,
                prompt=enhanced_prompt,
                model=image_model,
                size=size,
                quality=quality,
                steps=steps,
                guidance_scale=guidance_scale,
                negative_prompt=negative_prompt,
                n=n,
                response_format=response_format,
                seed=seed,
            )

    except asyncio.TimeoutError:
        yield _error(504, "Image generation timeout — model mungkin sedang loading, coba lagi")
        yield _done()
        return
    except aiohttp.ClientConnectorError as e:
        yield _error(503, f"Tidak bisa terhubung ke image engine: {e}")
        yield _done()
        return
    except Exception as e:
        logger.error("Image generation error: %s", e, exc_info=True)
        yield _error(500, f"Image generation gagal: {str(e)}")
        yield _done()
        return

    yield _status("Gambar berhasil dibuat!", "generating", done=True)

    # ── Phase 3: Emit result ─────────────────────────────────────────────────
    yield _sse({
        "type": "image_result",
        "data": {
            "images": result.get("images", []),
            "original_prompt": original_prompt,
            "enhanced_prompt": enhanced_prompt,
            "model": image_model,
            "size": size,
            "width": width,
            "height": height,
            "steps": steps,
            "seed": result.get("seed"),
            "engine": engine_type,
            "created": int(time.time()),
        },
    })

    yield _done()


# ============================================================================
# Engine detection
# ============================================================================


def _detect_engine_type(provider: dict) -> str:
    """
    Detect image engine type from provider config.

    Detection order:
    1. extra_config.engine = "comfyui" | "openai" | "a1111"
    2. base_url contains ":8188" (ComfyUI default port)
    3. extra_config.type = "comfyui"
    4. Default: "openai" (OpenAI-compatible)
    """
    extra = provider.get("extra_config", {}) or {}

    # Explicit engine override
    engine = extra.get("engine", "").lower()
    if engine in ("comfyui", "comfy"):
        return "comfyui"
    if engine in ("openai", "a1111", "automatic1111", "diffusers"):
        return "openai"

    # Port-based detection
    base_url = provider.get("base_url", "")
    if ":8188" in base_url or "/comfyui" in base_url.lower():
        return "comfyui"

    # Type hint
    ptype = extra.get("type", "").lower()
    if ptype == "comfyui":
        return "comfyui"

    return "openai"  # default


# ============================================================================
# OpenAI-compatible image generation
# ============================================================================


async def _generate_openai_compat(
    provider: dict,
    prompt: str,
    model: str,
    size: str,
    quality: str,
    steps: int | None,
    guidance_scale: float,
    negative_prompt: str,
    n: int,
    response_format: str,
    seed: int | None,
) -> dict:
    """Call OpenAI-compatible /images/generations endpoint."""
    provider_url = provider["base_url"].rstrip("/")
    headers = _build_headers(provider)

    payload: dict = {
        "prompt": prompt,
        "n": max(1, min(n, 4)),
        "size": size,
        "response_format": response_format,
    }
    if model:
        payload["model"] = model
    if quality != "standard":
        payload["quality"] = quality
    if steps is not None:          # only send if explicitly set — let engine use its own default
        payload["steps"] = steps
    if guidance_scale != 7.5:
        payload["guidance_scale"] = guidance_scale
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt
    if seed is not None:
        payload["seed"] = seed

    from env import settings as app_settings
    timeout_secs = getattr(app_settings, "image_max_timeout", 180)

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{provider_url}/images/generations",
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout_secs),
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise RuntimeError(f"Image engine HTTP {resp.status}: {error_text[:500]}")
            data = await resp.json()

    images = []
    for item in data.get("data", []):
        img: dict = {}
        if item.get("url"):
            img["url"] = item["url"]
        if item.get("b64_json"):
            img["b64_json"] = item["b64_json"]
        if item.get("revised_prompt"):
            img["revised_prompt"] = item["revised_prompt"]
        images.append(img)

    return {"images": images, "seed": data.get("seed")}


# ============================================================================
# ComfyUI image generation
# ============================================================================


async def _generate_comfyui(
    provider: dict,
    prompt: str,
    model: str,
    width: int,
    height: int,
    steps: int | None,
    guidance_scale: float,
    negative_prompt: str,
    seed: int | None,
    response_format: str,
) -> dict:
    """Call ComfyUI via workflow API."""
    from utils.comfyui import generate_via_comfyui
    from env import settings as app_settings

    comfyui_url = provider["base_url"].rstrip("/")
    timeout_secs = getattr(app_settings, "image_max_timeout", 180)

    # Read provider-level config from extra_config:
    #   default_steps  — fallback steps for custom model names
    #   workflow       — custom workflow JSON exported from ComfyUI web UI (API format)
    #   workflow_*_node — node ID overrides for custom workflow injection
    extra = provider.get("extra_config", {}) or {}
    provider_default_steps: int | None = extra.get("default_steps") or None
    if provider_default_steps is not None:
        try:
            provider_default_steps = int(provider_default_steps)
        except (TypeError, ValueError):
            provider_default_steps = None

    return await generate_via_comfyui(
        comfyui_url=comfyui_url,
        prompt=prompt,
        model=model,
        width=width,
        height=height,
        steps=steps,
        guidance_scale=guidance_scale,
        negative_prompt=negative_prompt,
        seed=seed,
        response_format=response_format,
        timeout=timeout_secs,
        provider_default_steps=provider_default_steps,
        provider_extra=extra,
    )


# ============================================================================
# LLM Prompt Enhancement
# ============================================================================


async def _enhance_prompt(
    original_prompt: str,
    style_hint: str,
    provider: dict,
    model: str,
) -> str:
    """Call LLM non-streaming to enhance the image prompt."""
    provider_url = provider["base_url"].rstrip("/")
    headers = _build_headers(provider)

    user_content = original_prompt
    if style_hint:
        user_content = f"{original_prompt}\n\nStyle hint: {style_hint}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": ENHANCE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 300,
        "temperature": 0.7,
        "stream": False,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{provider_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise RuntimeError(f"LLM HTTP {resp.status}: {error_text[:200]}")

            data = await resp.json()
            enhanced = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
                .strip('"\'')
            )

            return enhanced or original_prompt


# ============================================================================
# Provider resolution
# ============================================================================


async def _resolve_providers(llm_model: str, image_model: str) -> tuple[dict | None, dict | None]:
    """
    Resolve LLM provider and image provider from DB.

    Priority:
    1. Match by model prefix (e.g. "img.flux-dev" → provider with prefix "img")
    2. Match by extra_config.type ("image"/"comfyui" for image, "llm"/"chat" for LLM)
    3. Fallback: first active provider for both
    """
    from database import async_session_factory
    from sqlalchemy import text

    async with async_session_factory() as db:
        result = await db.execute(
            text("""
                SELECT name, base_url, api_key, auth_type, prefix, extra_config
                FROM providers
                WHERE is_active = true
                ORDER BY created_at ASC
            """)
        )
        rows = result.fetchall()

    if not rows:
        return None, None

    providers = [
        {
            "name": r[0],
            "base_url": r[1],
            "api_key": r[2] or "",
            "auth_type": r[3] or "none",
            "prefix": r[4] or "",
            "extra_config": r[5] if r[5] else {},
        }
        for r in rows
    ]

    llm_provider: dict | None = None
    img_provider: dict | None = None

    # 1. Match by model prefix
    if llm_model and "." in llm_model:
        prefix = llm_model.split(".")[0]
        llm_provider = next((p for p in providers if p["prefix"] == prefix), None)

    if image_model and "." in image_model:
        prefix = image_model.split(".")[0]
        img_provider = next((p for p in providers if p["prefix"] == prefix), None)

    # 2. Match by extra_config.type
    for p in providers:
        ec = p.get("extra_config", {}) or {}
        ptype = ec.get("type", "").lower()

        if not img_provider and ptype in ("image", "image_gen", "diffusion", "comfyui", "comfy"):
            img_provider = p
        if not llm_provider and ptype in ("llm", "chat", ""):
            llm_provider = p

    # 3. Fallback: first provider
    if not llm_provider and providers:
        llm_provider = providers[0]
    if not img_provider and providers:
        img_provider = providers[0]

    return llm_provider, img_provider


def _build_headers(provider: dict) -> dict:
    headers = {"Content-Type": "application/json"}
    api_key = provider.get("api_key", "")
    auth_type = provider.get("auth_type", "none")
    if auth_type == "bearer" and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    extra = provider.get("extra_config", {}) or {}
    for k, v in extra.get("extra_headers", {}).items():
        headers[k] = v
    return headers
