"""
ComfyUI API adapter.

ComfyUI uses a workflow-based JSON API (not OpenAI-compatible).
This module handles:
  1. Loading/building workflow templates
  2. Injecting dynamic values (prompt, size, seed, steps, cfg)
  3. Submitting workflow to ComfyUI /prompt endpoint
  4. Polling /history/{prompt_id} until completion
  5. Fetching generated image bytes via /view endpoint
  6. Returning result in OpenAI-compatible format (url or b64_json)

ComfyUI API endpoints used:
  POST /prompt          — submit workflow, returns {prompt_id}
  GET  /history/{id}   — poll status + get output filenames
  GET  /view?filename=  — fetch image bytes
  GET  /system_stats    — health check
  GET  /object_info     — list available nodes/models
"""

import asyncio
import base64
import json
import logging
import time
import uuid
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# ── Default workflow template ─────────────────────────────────────────────────
# Minimal Flux/SDXL workflow with named nodes we can inject into.
# Node IDs are stable strings so injection is reliable.
#
# Topology:
#   CheckpointLoaderSimple → CLIPTextEncode (positive)
#                          → CLIPTextEncode (negative)
#   EmptyLatentImage       → KSampler → VAEDecode → SaveImage
#
DEFAULT_WORKFLOW: dict = {
    "1": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {
            "ckpt_name": "flux1-dev.safetensors"  # overridden by model param
        }
    },
    "2": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "beautiful landscape",  # overridden by prompt
            "clip": ["1", 1]
        }
    },
    "3": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "blurry, low quality, watermark, text, ugly",  # overridden by negative_prompt
            "clip": ["1", 1]
        }
    },
    "4": {
        "class_type": "EmptyLatentImage",
        "inputs": {
            "width": 1024,   # overridden by size
            "height": 1024,  # overridden by size
            "batch_size": 1
        }
    },
    "5": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 42,           # overridden by seed
            "steps": 20,          # overridden by steps
            "cfg": 7.5,           # overridden by guidance_scale
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
            "model": ["1", 0],
            "positive": ["2", 0],
            "negative": ["3", 0],
            "latent_image": ["4", 0]
        }
    },
    "6": {
        "class_type": "VAEDecode",
        "inputs": {
            "samples": ["5", 0],
            "vae": ["1", 2]
        }
    },
    "7": {
        "class_type": "SaveImage",
        "inputs": {
            "filename_prefix": "api_output",
            "images": ["6", 0]
        }
    }
}

# Flux-specific workflow (no negative prompt, uses FluxGuidance)
FLUX_WORKFLOW: dict = {
    "1": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "flux1-dev.safetensors"}
    },
    "2": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "beautiful landscape",
            "clip": ["1", 1]
        }
    },
    "3": {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 1024, "height": 1024, "batch_size": 1}
    },
    "4": {
        "class_type": "FluxGuidance",
        "inputs": {
            "guidance": 3.5,
            "conditioning": ["2", 0]
        }
    },
    "5": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 42,
            "steps": 20,
            "cfg": 1.0,
            "sampler_name": "euler",
            "scheduler": "simple",
            "denoise": 1.0,
            "model": ["1", 0],
            "positive": ["4", 0],
            "negative": ["2", 0],  # empty negative for flux
            "latent_image": ["3", 0]
        }
    },
    "6": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["5", 0], "vae": ["1", 2]}
    },
    "7": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "api_output", "images": ["6", 0]}
    }
}


# ============================================================================
# Main ComfyUI generation function
# ============================================================================


# ============================================================================
# Workflow loader — load from provider config or fall back to built-in template
# ============================================================================


def _load_workflow(provider_extra: dict, model: str) -> tuple[dict, str]:
    """
    Load the workflow to use for generation.

    Priority:
    1. provider.extra_config.workflow  — user-exported workflow JSON from ComfyUI web UI
       (most flexible: supports LoRA, ControlNet, custom nodes, exact sampler settings)
    2. Built-in template based on model name (flux vs standard)

    Returns (workflow_dict, source) where source is "custom" or "template".

    HOW TO USE CUSTOM WORKFLOW:
    1. Build your workflow in ComfyUI web UI
    2. Click "Save (API Format)" button (enable dev mode first: Settings → Dev Mode)
    3. Copy the JSON content
    4. When registering the provider via POST /api/providers, set:
       extra_config = {
           "engine": "comfyui",
           "workflow": { ...paste the JSON here... },
           "workflow_prompt_node": "6",    // node ID containing the positive prompt text
           "workflow_negative_node": "7",  // node ID containing the negative prompt text (optional)
           "workflow_latent_node": "5",    // node ID of EmptyLatentImage (for size injection)
           "workflow_ksampler_node": "3",  // node ID of KSampler (for steps/seed/cfg injection)
           "workflow_checkpoint_node": "4" // node ID of CheckpointLoaderSimple (for model injection)
       }
    5. If node IDs are not specified, the loader will auto-detect by class_type.
    """
    import copy

    workflow_json = provider_extra.get("workflow")
    if workflow_json and isinstance(workflow_json, dict) and workflow_json:
        return copy.deepcopy(workflow_json), "custom"

    # Fall back to built-in template
    is_flux = "flux" in (model or "").lower()
    base = FLUX_WORKFLOW if is_flux else DEFAULT_WORKFLOW
    return copy.deepcopy(base), "template"


def _inject_into_workflow(
    workflow: dict,
    provider_extra: dict,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    steps: int,
    guidance_scale: float,
    seed: int,
    model: str,
) -> dict:
    """
    Inject generation parameters into a workflow dict.

    For custom workflows: uses node IDs from provider_extra config, or auto-detects by class_type.
    For template workflows: uses the fixed node IDs from DEFAULT_WORKFLOW / FLUX_WORKFLOW.
    """
    # Build a map of class_type → node_id for auto-detection
    class_to_nodes: dict[str, list[str]] = {}
    for node_id, node in workflow.items():
        ct = node.get("class_type", "")
        class_to_nodes.setdefault(ct, []).append(node_id)

    def _get_node_id(config_key: str, class_type: str, index: int = 0) -> str | None:
        """Get node ID from explicit config or auto-detect by class_type."""
        explicit = provider_extra.get(config_key)
        if explicit:
            return str(explicit)
        nodes = class_to_nodes.get(class_type, [])
        return nodes[index] if len(nodes) > index else None

    # ── Positive prompt ──────────────────────────────────────────────────────
    pos_id = _get_node_id("workflow_prompt_node", "CLIPTextEncode", 0)
    if pos_id and pos_id in workflow:
        workflow[pos_id]["inputs"]["text"] = prompt

    # ── Negative prompt ──────────────────────────────────────────────────────
    neg_id = _get_node_id("workflow_negative_node", "CLIPTextEncode", 1)
    if neg_id and neg_id in workflow and negative_prompt:
        workflow[neg_id]["inputs"]["text"] = negative_prompt

    # ── Latent image size ────────────────────────────────────────────────────
    latent_id = _get_node_id("workflow_latent_node", "EmptyLatentImage", 0)
    if latent_id and latent_id in workflow:
        workflow[latent_id]["inputs"]["width"] = width
        workflow[latent_id]["inputs"]["height"] = height

    # ── KSampler — steps, seed, cfg ──────────────────────────────────────────
    ksampler_id = _get_node_id("workflow_ksampler_node", "KSampler", 0)
    if ksampler_id and ksampler_id in workflow:
        inp = workflow[ksampler_id]["inputs"]
        inp["seed"] = seed
        inp["steps"] = steps
        inp["cfg"] = guidance_scale

    # ── Checkpoint model ─────────────────────────────────────────────────────
    ckpt_id = _get_node_id("workflow_checkpoint_node", "CheckpointLoaderSimple", 0)
    if ckpt_id and ckpt_id in workflow and model:
        workflow[ckpt_id]["inputs"]["ckpt_name"] = _normalize_model_name(model)

    # ── FluxGuidance (Flux-specific) ─────────────────────────────────────────
    flux_nodes = class_to_nodes.get("FluxGuidance", [])
    for fid in flux_nodes:
        workflow[fid]["inputs"]["guidance"] = guidance_scale

    return workflow


# ============================================================================
# Per-model step resolver
# ============================================================================


def _resolve_steps(model: str, steps: int | None, provider_default: int | None = None) -> int:
    """
    Resolve the number of inference steps. Priority order:

    1. Explicit user request (steps != None)          — always respected
    2. provider.extra_config.default_steps            — admin-configured per-provider
    3. Keyword detection from model name              — best-effort for known families
    4. Generic fallback (20)                          — safe default

    Why provider_default matters:
    Custom model names like "dreamshaper-8", "animagine-xl-3.1", "my-finetune-v2"
    won't match any keyword. The admin should set extra_config.default_steps
    on the provider to handle these cases correctly.

    Keyword detection covers well-known families:
    Model family          | Default steps | Notes
    ----------------------|---------------|---------------------------
    flux-schnell / turbo  |  4            | Distilled, max ~8
    flux-dev              | 20            | Standard Flux
    sdxl-turbo / sd-turbo |  4            | Distilled turbo
    lcm / lightning       |  4            | LCM/Lightning distilled
    sd3 / sd3.5           | 28            | Recommended by Stability
    sdxl                  | 30            | Standard SDXL
    sd 1.x / 2.x          | 20            | Classic SD
    playground            | 25            | Playground v2/v2.5
    animagine / pony      | 28            | Popular SDXL finetunes
    dreamshaper           | 25            | DreamShaper series
    (unknown)             | 20            | Safe generic default
    """
    # 1. Explicit user override — always wins
    if steps is not None:
        return steps

    # 2. Provider-level default (set in extra_config.default_steps)
    if provider_default is not None:
        return provider_default

    # 3. Keyword detection from model name
    m = (model or "").lower()

    # Distilled / turbo / lightning — very few steps needed
    if any(k in m for k in ("schnell", "turbo", "lightning", "lcm", "hyper")):
        return 4
    # Flux Dev
    if "flux" in m:
        return 20
    # Stable Diffusion 3 / 3.5
    if any(k in m for k in ("sd3", "sd-3", "stable-diffusion-3", "sd3.5")):
        return 28
    # Popular SDXL finetunes (animagine, pony, etc.)
    if any(k in m for k in ("animagine", "pony", "illustrious")):
        return 28
    # DreamShaper series
    if "dreamshaper" in m:
        return 25
    # SDXL base
    if "sdxl" in m or "xl" in m:
        return 30
    # Playground
    if "playground" in m:
        return 25
    # Classic SD 1.x / 2.x
    if any(k in m for k in ("stable-diffusion", "sd-1", "sd-2", "sd1", "sd2")):
        return 20

    # 4. Generic fallback
    return 20


async def generate_via_comfyui(
    comfyui_url: str,
    prompt: str,
    model: str = "",
    width: int = 1024,
    height: int = 1024,
    steps: int | None = None,
    guidance_scale: float = 7.5,
    negative_prompt: str = "",
    seed: int | None = None,
    response_format: str = "url",
    poll_interval: float = 1.5,
    timeout: int = 180,
    provider_default_steps: int | None = None,
    provider_extra: dict | None = None,
) -> dict:
    """
    Full ComfyUI generation cycle:
    1. Load workflow (custom from provider config, or built-in template)
    2. Inject dynamic params (prompt, size, steps, seed, model)
    3. POST to /prompt
    4. Poll /history/{prompt_id}
    5. Fetch image from /view
    6. Return OpenAI-compatible result

    Workflow priority:
      provider.extra_config.workflow (exported from ComfyUI web UI)
      → built-in template (DEFAULT_WORKFLOW / FLUX_WORKFLOW)

    Steps priority:
      user explicit → provider extra_config.default_steps → keyword detection → 20

    comfyui_url is always taken from provider.base_url in the DB — never hardcoded.

    Returns:
        {"images": [{"url": ..., "b64_json": ...}], "seed": int}
    """
    base_url = comfyui_url.rstrip("/")
    extra = provider_extra or {}
    resolved_steps = _resolve_steps(model, steps, provider_default_steps)
    actual_seed = seed if seed is not None else int(time.time() * 1000) % (2**31)

    logger.info(
        "ComfyUI steps: requested=%s provider_default=%s resolved=%d model=%s",
        steps, provider_default_steps, resolved_steps, model,
    )

    # Load workflow (custom or template) then inject all params
    workflow, workflow_source = _load_workflow(extra, model)
    logger.info("ComfyUI workflow source: %s", workflow_source)

    workflow = _inject_into_workflow(
        workflow=workflow,
        provider_extra=extra,
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        steps=resolved_steps,
        guidance_scale=guidance_scale,
        seed=actual_seed,
        model=model,
    )

    client_id = str(uuid.uuid4())

    # Submit workflow
    prompt_id = await _submit_workflow(base_url, workflow, client_id)
    logger.info("ComfyUI job submitted: prompt_id=%s", prompt_id)

    # Poll until done
    output_images = await _poll_until_done(
        base_url=base_url,
        prompt_id=prompt_id,
        poll_interval=poll_interval,
        timeout=timeout,
    )

    if not output_images:
        raise RuntimeError("ComfyUI completed but returned no images")

    # Fetch image bytes and build result
    images = []
    actual_seed = None

    for img_info in output_images:
        filename = img_info.get("filename", "")
        subfolder = img_info.get("subfolder", "")
        img_type = img_info.get("type", "output")

        img_bytes = await _fetch_image(base_url, filename, subfolder, img_type)

        if response_format == "b64_json":
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            images.append({"b64_json": b64})
        else:
            # Build a URL that Android can fetch directly from ComfyUI
            img_url = f"{base_url}/view?filename={filename}&subfolder={subfolder}&type={img_type}"
            images.append({"url": img_url})

    return {"images": images, "seed": actual_seed or seed}


# ============================================================================
# Workflow building
# ============================================================================


def _build_workflow(
    base_workflow: dict,
    prompt: str,
    model: str,
    width: int,
    height: int,
    steps: int,          # always resolved (never None) by this point
    guidance_scale: float,
    negative_prompt: str,
    seed: int,
) -> dict:
    """Deep-copy workflow and inject all dynamic values."""
    import copy
    wf = copy.deepcopy(base_workflow)

    for node_id, node in wf.items():
        class_type = node.get("class_type", "")
        inputs = node.get("inputs", {})

        if class_type == "CheckpointLoaderSimple" and model:
            # Normalize model name to filename
            ckpt = _normalize_model_name(model)
            inputs["ckpt_name"] = ckpt

        elif class_type == "CLIPTextEncode":
            # Positive prompt: first CLIPTextEncode that isn't connected to negative
            # We identify by checking if it's the positive node (node "2" in our templates)
            if node_id == "2":
                inputs["text"] = prompt
            elif node_id == "3" and negative_prompt:
                inputs["text"] = negative_prompt

        elif class_type == "EmptyLatentImage":
            inputs["width"] = width
            inputs["height"] = height

        elif class_type == "KSampler":
            inputs["seed"] = seed
            inputs["steps"] = steps
            inputs["cfg"] = guidance_scale

        elif class_type == "FluxGuidance":
            inputs["guidance"] = guidance_scale

    return wf


def _normalize_model_name(model: str) -> str:
    """
    Convert model ID to ComfyUI checkpoint filename.
    ComfyUI expects the exact filename in models/checkpoints/.
    """
    model_lower = model.lower()

    # Common mappings
    mappings = {
        "flux-dev": "flux1-dev.safetensors",
        "flux-schnell": "flux1-schnell.safetensors",
        "flux1-dev": "flux1-dev.safetensors",
        "flux1-schnell": "flux1-schnell.safetensors",
        "stable-diffusion-xl": "sd_xl_base_1.0.safetensors",
        "sdxl": "sd_xl_base_1.0.safetensors",
        "stable-diffusion-3": "sd3_medium.safetensors",
        "sd3": "sd3_medium.safetensors",
    }

    for key, filename in mappings.items():
        if key in model_lower:
            return filename

    # If it already looks like a filename, use as-is
    if model.endswith((".safetensors", ".ckpt", ".pt")):
        return model

    # Default: assume it's a safetensors file
    return f"{model}.safetensors"


# ============================================================================
# ComfyUI API calls
# ============================================================================


async def _submit_workflow(base_url: str, workflow: dict, client_id: str) -> str:
    """POST workflow to ComfyUI /prompt. Returns prompt_id."""
    payload = {
        "prompt": workflow,
        "client_id": client_id,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{base_url}/prompt",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise RuntimeError(f"ComfyUI /prompt error HTTP {resp.status}: {error_text[:300]}")

            data = await resp.json()
            prompt_id = data.get("prompt_id")
            if not prompt_id:
                raise RuntimeError(f"ComfyUI returned no prompt_id: {data}")

            return prompt_id


async def _poll_until_done(
    base_url: str,
    prompt_id: str,
    poll_interval: float = 1.5,
    timeout: int = 180,
) -> list[dict]:
    """
    Poll GET /history/{prompt_id} until the job is complete.
    Returns list of output image info dicts.
    """
    deadline = time.time() + timeout

    async with aiohttp.ClientSession() as session:
        while time.time() < deadline:
            await asyncio.sleep(poll_interval)

            try:
                async with session.get(
                    f"{base_url}/history/{prompt_id}",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        continue

                    history = await resp.json()

                    if prompt_id not in history:
                        # Job not done yet
                        continue

                    job = history[prompt_id]
                    status = job.get("status", {})

                    # Check for error
                    if status.get("status_str") == "error":
                        messages = status.get("messages", [])
                        raise RuntimeError(f"ComfyUI job failed: {messages}")

                    # Check for completion
                    outputs = job.get("outputs", {})
                    if not outputs:
                        continue

                    # Collect all output images
                    all_images = []
                    for node_id, node_output in outputs.items():
                        images = node_output.get("images", [])
                        all_images.extend(images)

                    if all_images:
                        logger.info(
                            "ComfyUI job %s done, %d image(s)", prompt_id, len(all_images)
                        )
                        return all_images

            except aiohttp.ClientError as e:
                logger.warning("ComfyUI poll error: %s", e)
                continue

    raise asyncio.TimeoutError(f"ComfyUI job {prompt_id} timed out after {timeout}s")


async def _fetch_image(
    base_url: str,
    filename: str,
    subfolder: str = "",
    img_type: str = "output",
) -> bytes:
    """Fetch image bytes from ComfyUI /view endpoint."""
    params = {"filename": filename, "type": img_type}
    if subfolder:
        params["subfolder"] = subfolder

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{base_url}/view",
            params=params,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"ComfyUI /view error HTTP {resp.status} for {filename}")
            return await resp.read()


# ============================================================================
# ComfyUI health check + model list
# ============================================================================


async def check_comfyui_health(base_url: str) -> dict:
    """Check if ComfyUI is running and return system stats."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{base_url.rstrip('/')}/system_stats",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {"healthy": True, "stats": data}
                return {"healthy": False, "error": f"HTTP {resp.status}"}
    except Exception as e:
        return {"healthy": False, "error": str(e)}


async def list_comfyui_models(base_url: str) -> list[str]:
    """List available checkpoint models from ComfyUI."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{base_url.rstrip('/')}/object_info/CheckpointLoaderSimple",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    ckpt_names = (
                        data.get("CheckpointLoaderSimple", {})
                        .get("input", {})
                        .get("required", {})
                        .get("ckpt_name", [[]])[0]
                    )
                    return ckpt_names if isinstance(ckpt_names, list) else []
    except Exception as e:
        logger.warning("Failed to list ComfyUI models: %s", e)
    return []
