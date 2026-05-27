"""
Tool discovery and execution utilities.
Handles tool specification preparation and parallel execution.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ============================================================================
# Built-in Tool Specifications
# ============================================================================

BUILTIN_TOOL_SPECS = {
    "search_web": {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for information using the configured search engine.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    "fetch_url": {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch and extract content from a URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch.",
                    },
                },
                "required": ["url"],
            },
        },
    },
    "execute_code": {
        "type": "function",
        "function": {
            "name": "execute_code",
            "description": "Execute Python code in a sandboxed environment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The Python code to execute.",
                    },
                    "language": {
                        "type": "string",
                        "description": "The programming language (default: python).",
                    },
                },
                "required": ["code"],
            },
        },
    },
    "generate_image": {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Generate an image from a text description.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The image generation prompt.",
                    },
                    "size": {
                        "type": "string",
                        "description": "Image size (e.g., '1024x1024').",
                    },
                },
                "required": ["prompt"],
            },
        },
    },
    "get_current_timestamp": {
        "type": "function",
        "function": {
            "name": "get_current_timestamp",
            "description": "Get the current timestamp in UTC.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    "calculate_timestamp": {
        "type": "function",
        "function": {
            "name": "calculate_timestamp",
            "description": "Calculate timestamp from a date string.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_string": {
                        "type": "string",
                        "description": "The date string to parse.",
                    },
                    "format": {
                        "type": "string",
                        "description": "The expected date format.",
                    },
                },
                "required": ["date_string"],
            },
        },
    },
}


# ============================================================================
# Tool Preparation
# ============================================================================


async def get_user_tools(db, user_id: str) -> list[dict]:
    """
    Get user-defined tools from database.
    
    Queries the app_config table for tools stored under
    'users.{user_id}.tools' path as JSONB array.
    
    Returns list of tool dicts with OpenAI-compatible format.
    """
    from sqlalchemy import text
    
    result = await db.execute(
        text("""
            SELECT value
            FROM app_config
            WHERE config_path = :config_path
        """),
        {"config_path": f"users.{user_id}.tools"},
    )
    row = result.fetchone()
    
    if not row or not row[0]:
        return []
    
    tools_data = row[0]
    if isinstance(tools_data, str):
        import json
        try:
            tools_data = json.loads(tools_data)
        except json.JSONDecodeError:
            return []
    
    if not isinstance(tools_data, list):
        return []
    
    # Filter active tools and ensure OpenAI-compatible format
    user_tools = []
    for tool in tools_data:
        if not isinstance(tool, dict):
            continue
        
        # Check if tool is active (default True)
        active = tool.get("active", True)
        if not active:
            continue
        
        # Convert to OpenAI-compatible format
        openai_tool = {
            "type": "function",
            "function": {
                "name": tool.get("name", "custom_tool"),
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters", {
                    "type": "object",
                    "properties": {},
                }),
            },
        }
        user_tools.append(openai_tool)
    
    return user_tools


async def prepare_tools_for_request(
    body: dict,
    model: dict,
    user: dict,
    settings: Any = None,
) -> dict:
    """
    Prepare tool specifications based on:
    1. Built-in tools (based on active features)
    2. User-defined tools (from DB)
    3. Filter based on model capabilities
    """
    model_capabilities = model.get("capabilities", {})

    if not model_capabilities.get("tools", False):
        return body

    tools = []

    # Built-in tools based on feature flags
    if settings and hasattr(settings, 'enable_web_search') and settings.enable_web_search:
        tools.append(BUILTIN_TOOL_SPECS["search_web"])
        tools.append(BUILTIN_TOOL_SPECS["fetch_url"])

    if settings and hasattr(settings, 'enable_code_interpreter') and settings.enable_code_interpreter:
        tools.append(BUILTIN_TOOL_SPECS["execute_code"])

    if settings and hasattr(settings, 'enable_image_generation') and settings.enable_image_generation:
        tools.append(BUILTIN_TOOL_SPECS["generate_image"])

    # Always available
    tools.extend([
        BUILTIN_TOOL_SPECS["get_current_timestamp"],
        BUILTIN_TOOL_SPECS["calculate_timestamp"],
    ])

    # User-defined tools from DB
    try:
        from database import async_session_factory
        async with async_session_factory() as db:
            user_tools = await get_user_tools(db, user.get("id", ""))
            for ut in user_tools:
                if ut.get("active") or ut.get("type") == "function":
                    tools.append(ut)
    except Exception as e:
        logger.warning(f"Failed to load user tools: {e}")

    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"

    return body


# ============================================================================
# Tool Execution
# ============================================================================


async def execute_tool_calling_loop(
    request: Any,
    body: dict,
    provider_url: str,
    provider_headers: dict,
    event_emitter: Callable | None = None,
) -> tuple[list[dict], str | None]:
    """
    Main tool calling loop.
    Continues iterating until AI returns finish_reason="stop"
    or reaches maximum iterations.
    
    Returns:
        tuple of (accumulated_tool_calls, final_content, finish_reason)
    """
    from constants import MAX_TOOL_CALL_ITERATIONS

    iteration = 0
    total_tool_calls = 0
    accumulated_content = ""
    final_finish_reason = None

    while iteration < MAX_TOOL_CALL_ITERATIONS:
        iteration_tool_calls = []
        iteration_content = ""
        finish_reason = None

        # Send to provider (placeholder - actual streaming handled elsewhere)
        # result = await call_provider(...)
        # parse streaming response...

        # For now, return accumulated state
        final_finish_reason = finish_reason
        
        if finish_reason != "tool_calls" or not iteration_tool_calls:
            break

        total_tool_calls += len(iteration_tool_calls)
        accumulated_content += iteration_content

        if total_tool_calls > MAX_TOOL_CALL_ITERATIONS:
            logger.warning("Maximum tool call iterations reached")
            break

        # Emit status to Flutter
        if event_emitter:
            await event_emitter({
                "type": "status",
                "data": {
                    "description": f"Menjalankan {len(iteration_tool_calls)} tool(s)...",
                    "done": False,
                }
            })

        # Execute all tool calls in PARALLEL via asyncio.gather
        tool_results = await asyncio.gather(*[
            _execute_single_tool(tc, event_emitter)
            for tc in iteration_tool_calls
        ])

        if event_emitter:
            await event_emitter({
                "type": "status",
                "data": {"description": "Tools selesai", "done": True}
            })

        # Update message history for next iteration
        body["messages"].append({
            "role": "assistant",
            "content": iteration_content or None,
            "tool_calls": iteration_tool_calls,
        })

        for result in tool_results:
            body["messages"].append({
                "role": "tool",
                "tool_call_id": result["tool_call_id"],
                "content": json.dumps(result["output"]),
            })

        iteration += 1

    return [
        accumulated_content,
        final_finish_reason,
    ]


async def _execute_single_tool(
    tool_call: dict,
    event_emitter: Callable | None = None,
) -> dict:
    """
    Execute a single tool.
    Error is returned as string, not exception,
    so AI can handle tool failure gracefully.
    """
    tool_name = tool_call.get("function", {}).get("name", "")
    raw_args = tool_call.get("function", {}).get("arguments", "{}")
    tool_call_id = tool_call.get("id", "")

    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError:
        return {
            "tool_call_id": tool_call_id,
            "output": f"Error: invalid JSON arguments: {raw_args}",
        }

    try:
        if tool_name == "search_web":
            result = await _tool_search_web(args.get("query", ""))
        elif tool_name == "fetch_url":
            result = await _tool_fetch_url(args.get("url", ""))
        elif tool_name == "execute_code":
            result = await _tool_execute_code(
                args.get("code", ""),
                args.get("language", "python")
            )
        elif tool_name == "get_current_timestamp":
            result = {
                "timestamp": datetime.utcnow().isoformat(),
                "timezone": "UTC",
            }
        elif tool_name == "calculate_timestamp":
            result = _tool_calculate_timestamp(
                args.get("date_string", ""),
                args.get("format", None),
            )
        elif tool_name == "generate_image":
            result = await _tool_generate_image(
                args.get("prompt", ""),
                args.get("size", "1024x1024"),
            )
        else:
            result = {"error": f"Tool '{tool_name}' tidak tersedia di server"}

        return {"tool_call_id": tool_call_id, "output": result}

    except Exception as e:
        logger.error(f"Tool '{tool_name}' execution error: {e}")
        return {
            "tool_call_id": tool_call_id,
            "output": {"error": f"Tool execution failed: {str(e)}"},
        }


# ============================================================================
# Tool Implementations (Placeholders)
# ============================================================================


async def _tool_search_web(query: str) -> list[dict]:
    """Search the web."""
    return [{"title": "Result", "url": "https://example.com", "snippet": "Result for: " + query}]


async def _tool_fetch_url(url: str) -> str:
    """Fetch URL content."""
    return f"Content from {url}"


async def _tool_execute_code(code: str, language: str) -> dict:
    """Execute code in sandbox."""
    return {
        "output": "Code execution result",
        "language": language,
        "status": "completed",
    }


async def _tool_generate_image(prompt: str, size: str) -> dict:
    """Generate an image."""
    return {
        "image_url": f"https://example.com/generated/{prompt}.png",
        "prompt": prompt,
        "size": size,
    }


def _tool_calculate_timestamp(date_string: str, format: str | None = None) -> dict:
    """Calculate timestamp from date string."""
    return {
        "timestamp": int(datetime.utcnow().timestamp()),
        "iso_format": datetime.utcnow().isoformat(),
    }
