"""
Filter pipeline processor.
Runs configured filters sequentially by priority.
"""

import logging
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


async def process_filter_functions(
    filters: list[dict],
    body: dict,
    user: dict,
    event_emitter: Callable | None = None,
    phase: str = "inlet",
) -> dict:
    """
    Run filters sequentially by priority (ascending).
    
    Filters can:
    - Modify messages (inject context, translate, etc)
    - Add/remove tools
    - Change target model
    - Emit status events to Flutter
    """
    if not filters:
        return body

    # Sort by priority (ascending - lower number = higher priority)
    sorted_filters = sorted(filters, key=lambda f: f.get("priority", 0))

    for filter_func in sorted_filters:
        try:
            filter_name = filter_func.get("name", "unknown")
            
            if phase == "inlet":
                inlet_fn = filter_func.get("inlet")
                if inlet_fn and callable(inlet_fn):
                    result = await inlet_fn(
                        body=body,
                        user=user,
                        event_emitter=event_emitter,
                    )
                    if result is not None:
                        body = result

            elif phase == "outlet":
                outlet_fn = filter_func.get("outlet")
                if outlet_fn and callable(outlet_fn):
                    result = await outlet_fn(
                        body=body,
                        response=body,
                        user=user,
                    )
                    if result is not None:
                        body = result

        except Exception as e:
            logger.error(f"Filter '{filter_func.get('name')}' error: {e}")
            # DO NOT stop pipeline because one filter failed
            continue

    return body


async def create_filter_from_config(filter_config: dict) -> dict | None:
    """
    Create filter function dict from configuration.
    Returns dict with 'name', 'inlet', 'outlet', 'priority' keys.
    """
    # This would dynamically load filter implementations
    # For now, return None as placeholder
    return None


# ============================================================================
# Built-in Filters
# ============================================================================


async def filter_translate_messages(
    body: dict,
    user: dict,
    **kwargs,
) -> dict | None:
    """
    Built-in filter: Translate user messages to target language.
    Add to filters config to enable.
    """
    # Implementation would call a translation model
    # For now, placeholder
    return None


async def filter_safety_check(
    body: dict,
    user: dict,
    **kwargs,
) -> dict | None:
    """
    Built-in filter: Check messages for safety/compliance.
    Can modify or flag messages based on content policy.
    """
    # Implementation would call a moderation model
    # For now, placeholder
    return None
