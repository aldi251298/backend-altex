"""
Audio router — Speech-to-Text (STT) and Text-to-Speech (TTS).
Proxies requests to the configured provider's OpenAI-compatible audio endpoints.
No auth required.
"""

import logging

import aiohttp
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse

from database import async_session_factory
from sqlalchemy import text

router = APIRouter()
logger = logging.getLogger(__name__)


async def _get_provider() -> dict | None:
    """Get first active provider config."""
    async with async_session_factory() as db:
        result = await db.execute(
            text("SELECT base_url, api_key, auth_type FROM providers WHERE is_active = true LIMIT 1")
        )
        row = result.fetchone()
    if not row:
        return None
    return {"base_url": row[0], "api_key": row[1] or "", "auth_type": row[2] or "none"}


def _provider_headers(provider: dict) -> dict:
    headers = {}
    if provider["auth_type"] == "bearer" and provider["api_key"]:
        headers["Authorization"] = f"Bearer {provider['api_key']}"
    return headers


# ============================================================================
# Speech-to-Text (Transcription)
# ============================================================================


@router.post("/transcriptions", summary="Speech-to-Text (Whisper-compatible)")
async def transcribe_audio(
    file: UploadFile = File(...),
    model: str = Form("whisper-1"),
    language: str | None = Form(None),
    prompt: str | None = Form(None),
    response_format: str = Form("json"),
    temperature: float = Form(0.0),
):
    """
    Transcribe audio to text using the provider's Whisper-compatible endpoint.
    Supports: mp3, mp4, mpeg, mpga, m4a, wav, webm
    """
    provider = await _get_provider()
    if not provider:
        raise HTTPException(status_code=503, detail="No active provider configured")

    provider_url = provider["base_url"].rstrip("/")
    headers = _provider_headers(provider)

    audio_content = await file.read()

    form_data = aiohttp.FormData()
    form_data.add_field("file", audio_content, filename=file.filename, content_type=file.content_type or "audio/mpeg")
    form_data.add_field("model", model)
    form_data.add_field("response_format", response_format)
    form_data.add_field("temperature", str(temperature))
    if language:
        form_data.add_field("language", language)
    if prompt:
        form_data.add_field("prompt", prompt)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{provider_url}/audio/transcriptions",
                headers=headers,
                data=form_data,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                content = await resp.read()
                if resp.status != 200:
                    raise HTTPException(
                        status_code=resp.status,
                        detail=f"Provider transcription error: {content.decode('utf-8', errors='replace')[:500]}",
                    )
                return Response(
                    content=content,
                    media_type=resp.content_type or "application/json",
                )
    except aiohttp.ClientError as e:
        logger.error("Transcription provider error: %s", e)
        raise HTTPException(status_code=503, detail=f"Provider connection error: {e}")


@router.post("/translations", summary="Audio translation to English (Whisper-compatible)")
async def translate_audio(
    file: UploadFile = File(...),
    model: str = Form("whisper-1"),
    prompt: str | None = Form(None),
    response_format: str = Form("json"),
    temperature: float = Form(0.0),
):
    """Translate audio to English text."""
    provider = await _get_provider()
    if not provider:
        raise HTTPException(status_code=503, detail="No active provider configured")

    provider_url = provider["base_url"].rstrip("/")
    headers = _provider_headers(provider)
    audio_content = await file.read()

    form_data = aiohttp.FormData()
    form_data.add_field("file", audio_content, filename=file.filename, content_type=file.content_type or "audio/mpeg")
    form_data.add_field("model", model)
    form_data.add_field("response_format", response_format)
    form_data.add_field("temperature", str(temperature))
    if prompt:
        form_data.add_field("prompt", prompt)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{provider_url}/audio/translations",
                headers=headers,
                data=form_data,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                content = await resp.read()
                if resp.status != 200:
                    raise HTTPException(status_code=resp.status, detail=content.decode("utf-8", errors="replace")[:500])
                return Response(content=content, media_type=resp.content_type or "application/json")
    except aiohttp.ClientError as e:
        raise HTTPException(status_code=503, detail=str(e))


# ============================================================================
# Text-to-Speech
# ============================================================================


@router.post("/speech", summary="Text-to-Speech (TTS)")
async def text_to_speech(body: dict):
    """
    Convert text to speech using the provider's TTS endpoint.
    Body: { "model": "tts-1", "input": "Hello world", "voice": "alloy", "response_format": "mp3", "speed": 1.0 }
    """
    provider = await _get_provider()
    if not provider:
        raise HTTPException(status_code=503, detail="No active provider configured")

    if not body.get("input"):
        raise HTTPException(status_code=422, detail="Field 'input' wajib diisi")

    provider_url = provider["base_url"].rstrip("/")
    headers = {**_provider_headers(provider), "Content-Type": "application/json"}

    tts_body = {
        "model": body.get("model", "tts-1"),
        "input": body["input"],
        "voice": body.get("voice", "alloy"),
        "response_format": body.get("response_format", "mp3"),
        "speed": body.get("speed", 1.0),
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{provider_url}/audio/speech",
                headers=headers,
                json=tts_body,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise HTTPException(status_code=resp.status, detail=error_text[:500])

                audio_content = await resp.read()
                fmt = tts_body["response_format"]
                mime_map = {
                    "mp3": "audio/mpeg",
                    "opus": "audio/opus",
                    "aac": "audio/aac",
                    "flac": "audio/flac",
                    "wav": "audio/wav",
                    "pcm": "audio/pcm",
                }
                return Response(
                    content=audio_content,
                    media_type=mime_map.get(fmt, "audio/mpeg"),
                    headers={"Content-Disposition": f'attachment; filename="speech.{fmt}"'},
                )
    except aiohttp.ClientError as e:
        logger.error("TTS provider error: %s", e)
        raise HTTPException(status_code=503, detail=str(e))


# ============================================================================
# List available voices (provider-specific)
# ============================================================================


@router.get("/voices", summary="List available TTS voices")
async def list_voices():
    """List available TTS voices from provider."""
    provider = await _get_provider()
    if not provider:
        return {"voices": _default_voices()}

    provider_url = provider["base_url"].rstrip("/")
    headers = _provider_headers(provider)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{provider_url}/audio/voices",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception:
        pass

    # Fallback to OpenAI standard voices
    return {"voices": _default_voices()}


def _default_voices() -> list[dict]:
    return [
        {"id": "alloy", "name": "Alloy", "gender": "neutral"},
        {"id": "echo", "name": "Echo", "gender": "male"},
        {"id": "fable", "name": "Fable", "gender": "male"},
        {"id": "onyx", "name": "Onyx", "gender": "male"},
        {"id": "nova", "name": "Nova", "gender": "female"},
        {"id": "shimmer", "name": "Shimmer", "gender": "female"},
    ]
