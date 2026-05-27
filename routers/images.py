"""
Image generation router.

Endpoints:
  POST /api/images/generate        — Main SSE pipeline (LLM enhance → image gen)
  POST /api/images/generations     — Direct image generation (no LLM, OpenAI-compatible)
  GET  /api/images/models          — List available image models from provider
  GET  /api/images/sizes           — List supported sizes
  POST /api/images/enhance-prompt  — Standalone LLM prompt enhancement (no image gen)

No auth required.
"""

import json
import logging

import aiohttp
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from utils.image import generate_image_pipeline, _resolve_providers, _build_headers

router = APIRouter()
logger = logging.getLogger(__name__)

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
    "Access-Control-Allow-Origin": "*",
}


# ============================================================================
# Request / Response models
# ============================================================================


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000, description="Image description")
    llm_model: str = Field("", description="LLM model for prompt enhancement (e.g. 'qwen3-27b')")
    image_model: str = Field("", description="Image generation model (e.g. 'flux-dev', 'stable-diffusion-xl')")
    size: str = Field("1024x1024", description="Image size: '512x512', '768x768', '1024x1024', '1024x1792', '1792x1024'")
    quality: str = Field("standard", description="Quality: 'standard' or 'hd'")
    style: str = Field("", description="Style hint for LLM enhancement (e.g. 'photorealistic', 'anime', 'oil painting')")
    steps: int | None = Field(None, ge=1, le=150, description="Inference steps — None = auto (model decides). Turbo/Schnell: 4-8, standard: 20-30, quality: 50+")
    guidance_scale: float = Field(7.5, ge=1.0, le=30.0, description="CFG guidance scale")
    negative_prompt: str = Field("", description="What to avoid in the image")
    n: int = Field(1, ge=1, le=4, description="Number of images to generate")
    enhance: bool = Field(True, description="Use LLM to enhance prompt before generation")
    response_format: str = Field("url", description="Response format: 'url' or 'b64_json'")
    seed: int | None = Field(None, description="Random seed for reproducibility")


class DirectImageRequest(BaseModel):
    """OpenAI-compatible direct image generation (no LLM enhancement)."""
    prompt: str = Field(..., min_length=1)
    model: str = Field("", description="Image model ID")
    n: int = Field(1, ge=1, le=4)
    size: str = Field("1024x1024")
    quality: str = Field("standard")
    response_format: str = Field("url")
    style: str | None = Field(None)
    steps: int | None = Field(None, ge=1, le=150, description="None = auto")
    guidance_scale: float | None = Field(None)
    negative_prompt: str | None = Field(None)
    seed: int | None = Field(None)


class EnhancePromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    model: str = Field("", description="LLM model to use")
    style: str = Field("", description="Style hint")


# ============================================================================
# POST /api/images/generate — Main SSE pipeline
# ============================================================================


@router.post(
    "/generate",
    summary="Generate image with LLM prompt enhancement (SSE streaming)",
    response_description="Server-Sent Events stream with status, prompt_enhanced, and image_result events",
)
async def generate_image(req: ImageGenerateRequest):
    """
    Full image generation pipeline via SSE:

    1. LLM enhances the prompt (if enhance=true)
    2. Enhanced prompt sent to image engine
    3. Result returned as SSE events

    SSE Event types:
    - `status`          — progress updates per phase
    - `prompt_enhanced` — {original, enhanced} prompt
    - `image_result`    — {images, enhanced_prompt, model, size, seed, created}
    - `error`           — {code, message}
    - `[DONE]`          — stream end marker
    """
    async def stream():
        try:
            async for chunk in generate_image_pipeline(
                prompt=req.prompt,
                llm_model=req.llm_model,
                image_model=req.image_model,
                size=req.size,
                quality=req.quality,
                style=req.style,
                steps=req.steps,
                guidance_scale=req.guidance_scale,
                negative_prompt=req.negative_prompt,
                n=req.n,
                enhance=req.enhance,
                response_format=req.response_format,
                seed=req.seed,
            ):
                yield chunk
        except Exception as e:
            logger.error("Image generation pipeline error: %s", e, exc_info=True)
            yield f"data: {json.dumps({'type':'error','error':{'code':500,'message':str(e)}})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        content=stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


# ============================================================================
# POST /api/images/generations — Direct (OpenAI-compatible, no SSE)
# ============================================================================


@router.post(
    "/generations",
    summary="Direct image generation — OpenAI-compatible JSON response (no LLM enhancement)",
)
async def direct_image_generation(req: DirectImageRequest):
    """
    OpenAI-compatible image generation endpoint.
    Returns JSON directly (no SSE, no LLM enhancement).
    Compatible with any client that uses OpenAI's images.generate() API.
    """
    _, img_provider = await _resolve_providers("", req.model)
    if not img_provider:
        raise HTTPException(status_code=503, detail="No active image provider configured")

    provider_url = img_provider["base_url"].rstrip("/")
    headers = _build_headers(img_provider)

    payload: dict = {
        "prompt": req.prompt,
        "n": req.n,
        "size": req.size,
        "response_format": req.response_format,
    }
    if req.model:
        payload["model"] = req.model
    if req.quality != "standard":
        payload["quality"] = req.quality
    if req.style:
        payload["style"] = req.style
    if req.steps:
        payload["steps"] = req.steps
    if req.guidance_scale:
        payload["guidance_scale"] = req.guidance_scale
    if req.negative_prompt:
        payload["negative_prompt"] = req.negative_prompt
    if req.seed is not None:
        payload["seed"] = req.seed

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{provider_url}/images/generations",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=180),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise HTTPException(
                        status_code=resp.status,
                        detail=f"Image engine error: {error_text[:500]}",
                    )
                data = await resp.json()
                return JSONResponse(content=data)

    except aiohttp.ClientConnectorError as e:
        raise HTTPException(status_code=503, detail=f"Cannot connect to image engine: {e}")
    except aiohttp.ClientError as e:
        raise HTTPException(status_code=503, detail=str(e))


# ============================================================================
# POST /api/images/enhance-prompt — Standalone prompt enhancement
# ============================================================================


@router.post(
    "/enhance-prompt",
    summary="Enhance image prompt using LLM (no image generation)",
)
async def enhance_prompt(req: EnhancePromptRequest):
    """
    Use LLM to enhance/expand an image prompt without generating the image.
    Useful for previewing the enhanced prompt before committing to generation.
    """
    from utils.image import _enhance_prompt, ENHANCE_SYSTEM_PROMPT

    llm_provider, _ = await _resolve_providers(req.model, "")
    if not llm_provider:
        raise HTTPException(status_code=503, detail="No active LLM provider configured")

    try:
        enhanced = await _enhance_prompt(
            original_prompt=req.prompt,
            style_hint=req.style,
            provider=llm_provider,
            model=req.model or llm_provider.get("default_model", ""),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Enhancement failed: {str(e)}")

    return {
        "original": req.prompt,
        "enhanced": enhanced,
        "model": req.model,
    }


# ============================================================================
# GET /api/images/models — List available image models
# ============================================================================


@router.get(
    "/models",
    summary="List available image generation models from provider",
)
async def list_image_models():
    """
    Fetch image models from the configured image provider.
    Falls back to a curated list of common models if provider doesn't support /models.
    """
    _, img_provider = await _resolve_providers("", "")
    if not img_provider:
        return {"data": _default_image_models()}

    provider_url = img_provider["base_url"].rstrip("/")
    headers = _build_headers(img_provider)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{provider_url}/models",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = data.get("data", [])
                    # Filter to image-capable models if possible
                    image_models = [
                        m for m in models
                        if any(t in m.get("id", "").lower() for t in [
                            "flux", "stable-diffusion", "sdxl", "sd3", "dall-e",
                            "imagen", "midjourney", "kandinsky", "playground",
                        ])
                    ] or models  # if no filter match, return all
                    return {"data": image_models, "provider": img_provider["name"]}
    except Exception as e:
        logger.warning("Failed to fetch image models from provider: %s", e)

    return {"data": _default_image_models()}


# ============================================================================
# GET /api/images/sizes — List supported sizes
# ============================================================================


@router.get(
    "/sizes",
    summary="List supported image sizes",
)
async def list_sizes():
    """Return supported image sizes with aspect ratio info, from 512×512 up to 4K."""
    return {
        "default": "1024x1024",
        "sizes": [
            # ── Square 1:1 ────────────────────────────────────────────────────
            {"value": "512x512",    "label": "512×512",    "aspect": "1:1",   "category": "square",    "note": "Small (fast)"},
            {"value": "768x768",    "label": "768×768",    "aspect": "1:1",   "category": "square",    "note": "Medium"},
            {"value": "1024x1024",  "label": "1024×1024",  "aspect": "1:1",   "category": "square",    "note": "Large (default)", "default": True},
            {"value": "1280x1280",  "label": "1280×1280",  "aspect": "1:1",   "category": "square",    "note": "XL"},
            {"value": "1536x1536",  "label": "1536×1536",  "aspect": "1:1",   "category": "square",    "note": "2K"},
            {"value": "2048x2048",  "label": "2048×2048",  "aspect": "1:1",   "category": "square",    "note": "2K Large"},
            {"value": "4096x4096",  "label": "4096×4096",  "aspect": "1:1",   "category": "square",    "note": "4K (very slow)"},

            # ── Portrait 3:4 ──────────────────────────────────────────────────
            {"value": "768x1024",   "label": "768×1024",   "aspect": "3:4",   "category": "portrait",  "note": "Portrait Medium"},
            {"value": "960x1280",   "label": "960×1280",   "aspect": "3:4",   "category": "portrait",  "note": "Portrait HD"},
            {"value": "1152x1536",  "label": "1152×1536",  "aspect": "3:4",   "category": "portrait",  "note": "Portrait 2K"},
            {"value": "1536x2048",  "label": "1536×2048",  "aspect": "3:4",   "category": "portrait",  "note": "Portrait 2K Large"},
            {"value": "2160x2880",  "label": "2160×2880",  "aspect": "3:4",   "category": "portrait",  "note": "Portrait 4K"},

            # ── Landscape 4:3 ─────────────────────────────────────────────────
            {"value": "1024x768",   "label": "1024×768",   "aspect": "4:3",   "category": "landscape", "note": "Landscape Medium"},
            {"value": "1280x960",   "label": "1280×960",   "aspect": "4:3",   "category": "landscape", "note": "Landscape HD"},
            {"value": "1536x1152",  "label": "1536×1152",  "aspect": "4:3",   "category": "landscape", "note": "Landscape 2K"},
            {"value": "2048x1536",  "label": "2048×1536",  "aspect": "4:3",   "category": "landscape", "note": "Landscape 2K Large"},
            {"value": "2880x2160",  "label": "2880×2160",  "aspect": "4:3",   "category": "landscape", "note": "Landscape 4K"},

            # ── Portrait 9:16 ─────────────────────────────────────────────────
            {"value": "576x1024",   "label": "576×1024",   "aspect": "9:16",  "category": "portrait",  "note": "Mobile Portrait"},
            {"value": "720x1280",   "label": "720×1280",   "aspect": "9:16",  "category": "portrait",  "note": "HD Portrait"},
            {"value": "1080x1920",  "label": "1080×1920",  "aspect": "9:16",  "category": "portrait",  "note": "Full HD Portrait"},
            {"value": "1440x2560",  "label": "1440×2560",  "aspect": "9:16",  "category": "portrait",  "note": "2K Portrait"},
            {"value": "2160x3840",  "label": "2160×3840",  "aspect": "9:16",  "category": "portrait",  "note": "4K Portrait"},

            # ── Landscape 16:9 ────────────────────────────────────────────────
            {"value": "1024x576",   "label": "1024×576",   "aspect": "16:9",  "category": "landscape", "note": "Mobile Landscape"},
            {"value": "1280x720",   "label": "1280×720",   "aspect": "16:9",  "category": "landscape", "note": "HD Landscape"},
            {"value": "1920x1080",  "label": "1920×1080",  "aspect": "16:9",  "category": "landscape", "note": "Full HD Landscape"},
            {"value": "2560x1440",  "label": "2560×1440",  "aspect": "16:9",  "category": "landscape", "note": "2K Landscape"},
            {"value": "3840x2160",  "label": "3840×2160",  "aspect": "16:9",  "category": "landscape", "note": "4K UHD Landscape"},

            # ── Portrait 2:3 ──────────────────────────────────────────────────
            {"value": "512x768",    "label": "512×768",    "aspect": "2:3",   "category": "portrait",  "note": "Portrait Small"},
            {"value": "683x1024",   "label": "683×1024",   "aspect": "2:3",   "category": "portrait",  "note": "Portrait Medium"},
            {"value": "1024x1536",  "label": "1024×1536",  "aspect": "2:3",   "category": "portrait",  "note": "Portrait Large"},
            {"value": "1365x2048",  "label": "1365×2048",  "aspect": "2:3",   "category": "portrait",  "note": "Portrait 2K"},

            # ── Landscape 3:2 ─────────────────────────────────────────────────
            {"value": "768x512",    "label": "768×512",    "aspect": "3:2",   "category": "landscape", "note": "Landscape Small"},
            {"value": "1024x683",   "label": "1024×683",   "aspect": "3:2",   "category": "landscape", "note": "Landscape Medium"},
            {"value": "1536x1024",  "label": "1536×1024",  "aspect": "3:2",   "category": "landscape", "note": "Landscape Large"},
            {"value": "2048x1365",  "label": "2048×1365",  "aspect": "3:2",   "category": "landscape", "note": "Landscape 2K"},

            # ── Portrait 4:5 (Instagram) ──────────────────────────────────────
            {"value": "819x1024",   "label": "819×1024",   "aspect": "4:5",   "category": "portrait",  "note": "Instagram Portrait"},
            {"value": "1024x1280",  "label": "1024×1280",  "aspect": "4:5",   "category": "portrait",  "note": "Instagram Portrait HD"},

            # ── Landscape 5:4 ─────────────────────────────────────────────────
            {"value": "1024x819",   "label": "1024×819",   "aspect": "5:4",   "category": "landscape", "note": "Landscape 5:4"},
            {"value": "1280x1024",  "label": "1280×1024",  "aspect": "5:4",   "category": "landscape", "note": "Landscape 5:4 HD"},

            # ── Ultrawide 21:9 ────────────────────────────────────────────────
            {"value": "1792x768",   "label": "1792×768",   "aspect": "21:9",  "category": "ultrawide", "note": "Ultrawide"},
            {"value": "2560x1080",  "label": "2560×1080",  "aspect": "21:9",  "category": "ultrawide", "note": "Ultrawide Full HD"},
            {"value": "3440x1440",  "label": "3440×1440",  "aspect": "21:9",  "category": "ultrawide", "note": "Ultrawide 2K"},

            # ── Cinematic 2.39:1 ──────────────────────────────────────────────
            {"value": "1024x428",   "label": "1024×428",   "aspect": "2.39:1","category": "cinematic", "note": "Cinematic"},
            {"value": "2048x856",   "label": "2048×856",   "aspect": "2.39:1","category": "cinematic", "note": "Cinematic 2K"},
            {"value": "4096x1714",  "label": "4096×1714",  "aspect": "2.39:1","category": "cinematic", "note": "Cinematic 4K"},

            # ── Tall/Phone 9:19.5 (modern smartphones) ───────────────────────
            {"value": "828x1792",   "label": "828×1792",   "aspect": "9:19.5","category": "portrait",  "note": "iPhone XR/11"},
            {"value": "1170x2532",  "label": "1170×2532",  "aspect": "9:19.5","category": "portrait",  "note": "iPhone 12/13/14"},
        ]
    }


# ============================================================================
# GET /api/images/styles — List style presets
# ============================================================================


@router.get(
    "/styles",
    summary="List style presets for prompt enhancement",
)
async def list_styles():
    """Return available style presets that can be passed as 'style' parameter."""
    return {
        "styles": [
            {"id": "",                  "label": "Auto",           "description": "Let LLM choose the best style"},
            {"id": "photorealistic",    "label": "Photorealistic", "description": "Hyper-realistic photography"},
            {"id": "anime",             "label": "Anime",          "description": "Japanese anime / manga style"},
            {"id": "digital-art",       "label": "Digital Art",    "description": "Digital illustration"},
            {"id": "oil-painting",      "label": "Oil Painting",   "description": "Classical oil painting"},
            {"id": "watercolor",        "label": "Watercolor",     "description": "Soft watercolor painting"},
            {"id": "sketch",            "label": "Sketch",         "description": "Pencil or charcoal sketch"},
            {"id": "3d-render",         "label": "3D Render",      "description": "3D CGI render"},
            {"id": "pixel-art",         "label": "Pixel Art",      "description": "Retro pixel art style"},
            {"id": "concept-art",       "label": "Concept Art",    "description": "Game/film concept art"},
            {"id": "cinematic",         "label": "Cinematic",      "description": "Movie-quality cinematic shot"},
            {"id": "minimalist",        "label": "Minimalist",     "description": "Clean, minimal design"},
            {"id": "fantasy",           "label": "Fantasy",        "description": "Epic fantasy illustration"},
            {"id": "sci-fi",            "label": "Sci-Fi",         "description": "Futuristic science fiction"},
        ]
    }


# ============================================================================
# Helpers
# ============================================================================


def _default_image_models() -> list[dict]:
    """Fallback list of common image generation models."""
    return [
        {"id": "flux-dev",              "name": "Flux Dev",              "type": "image"},
        {"id": "flux-schnell",          "name": "Flux Schnell (Fast)",   "type": "image"},
        {"id": "stable-diffusion-xl",   "name": "Stable Diffusion XL",  "type": "image"},
        {"id": "stable-diffusion-3",    "name": "Stable Diffusion 3",   "type": "image"},
        {"id": "dall-e-3",              "name": "DALL-E 3",              "type": "image"},
        {"id": "dall-e-2",              "name": "DALL-E 2",              "type": "image"},
    ]
