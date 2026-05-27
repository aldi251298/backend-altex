"""
Model aggregation logic.
Fetches and aggregates models from all configured providers.
"""

import asyncio
import logging
import time
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# Model cache
MODEL_CACHE: dict[str, list] = {}
MODEL_CACHE_TIMESTAMPS: dict[str, float] = {}
MODEL_CACHE_TTL = 300  # 5 minutes


async def get_all_models(user: dict, providers: list, settings: Any = None) -> list[dict]:
    """
    Fetch and aggregate models from all configured providers.
    Uses cache TTL of 5 minutes to prevent hammering provider APIs.
    """
    now = time.time()
    cache_key = f"user_{user.get('role', 'user')}"  # Cache per role

    if (
        cache_key in MODEL_CACHE
        and now - MODEL_CACHE_TIMESTAMPS.get(cache_key, 0) < MODEL_CACHE_TTL
    ):
        return MODEL_CACHE[cache_key]

    all_models = []

    # Fetch from all providers in parallel
    fetch_tasks = [
        _fetch_models_from_provider(provider)
        for provider in providers
    ]
    provider_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    for provider, result in zip(providers, provider_results):
        if isinstance(result, Exception):
            logger.warning(f"Provider '{provider.name}' tidak bisa diakses: {result}")
            continue  # Skip failed provider - don't fail total

        for model in result:
            # Add prefix if configured
            if provider.prefix:
                model["id"] = f"{provider.prefix}.{model['id']}"

            # Enrich with metadata from DB (placeholder)
            # db_model = await Models.get_model_by_id(model["id"])
            # if db_model:
            #     model.update({ ... })

            model["provider"] = provider.name
            model["capabilities"] = model.get("capabilities", {
                "vision": False,
                "tools": False,
            })
            model["params"] = model.get("params", {})
            all_models.append(model)

    # Filter based on RBAC (placeholder)
    # if user.get("role") != "admin":
    #     allowed_model_ids = await Users.get_allowed_model_ids(user["id"])
    #     if allowed_model_ids:
    #         all_models = [m for m in all_models if m["id"] in allowed_model_ids]

    MODEL_CACHE[cache_key] = all_models
    MODEL_CACHE_TIMESTAMPS[cache_key] = now
    return all_models


async def _fetch_models_from_provider(provider: Any) -> list[dict]:
    """Fetch model list from a single provider with timeout."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{provider.base_url}/models",
                headers={"Authorization": f"Bearer {provider.api_key}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    raise Exception(f"HTTP {response.status}")
                data = await response.json()
                return data.get("data", [])
        except Exception as e:
            logger.warning(f"Failed to fetch models from {provider.name}: {e}")
            return []


async def refresh_model_cache() -> None:
    """Clear model cache to force refresh."""
    global MODEL_CACHE, MODEL_CACHE_TIMESTAMPS
    MODEL_CACHE.clear()
    MODEL_CACHE_TIMESTAMPS.clear()
