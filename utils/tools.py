"""
Tool discovery, preparation, and parallel execution.
Supports: web search, URL fetch, code execution (sandbox), image generation,
          timestamp utilities, and user-defined tools from DB.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ============================================================================
# Tool-use system prompt — injected when tools are available
# ============================================================================

TOOL_USE_SYSTEM_PROMPT = """
## Tool Use Instructions

You have access to tools. Follow these rules strictly:

### WHEN to use tools
- `search_web`: Use IMMEDIATELY when the user asks about current events, news, prices, weather, sports scores, or any fact that may have changed after your training cutoff. Do NOT say "I don't have access to the internet" — use the tool instead.
- `fetch_url`: Use when the user provides a URL and wants you to read/summarize its content.
- `execute_code`: Use for any calculation, data processing, file parsing, or programming task where running code gives a more accurate result than guessing.
- `calculate`: Use for any math expression. Never compute math in your head when this tool is available.
- `get_current_time`: Use whenever the user asks about the current date or time.
- `generate_image`: Use ONLY when the user explicitly requests image/picture/photo CREATION or GENERATION. See strict rules below.

### generate_image — STRICT USAGE RULES
ONLY call `generate_image` when the user's intent is unambiguously to CREATE/GENERATE a visual image right now.

✅ CALL generate_image for:
- "buatkan gambar kucing", "generate an image of...", "create a picture of..."
- "tolong buat ilustrasi...", "gambarkan...", "draw me a..."
- "bikin foto...", "generate art of..."

❌ DO NOT call generate_image for:
- "ide desain logo" (design idea/concept discussion)
- "rencana desain aplikasi" (design plan)
- "bagaimana cara membuat gambar yang bagus?" (how-to question)
- "apa itu stable diffusion?" (informational question)
- "saya mau buat gambar nanti" (future intent, not a request now)
- "desain UI untuk aplikasi saya" (UI/UX design discussion)
- "rancangan arsitektur" (architecture plan)
- Any question about design, planning, or concepts — answer with text

When in doubt, answer with text. Only generate an image when the user's primary intent is to receive a generated image as output.

### General tool-use behavior
- Prefer calling tools in parallel when multiple independent tools are needed.
- Do NOT announce that you are going to use a tool — just use it.
- Do NOT say "I cannot access the internet" or "I don't have real-time data" when search_web is available.
- After receiving tool results, synthesize them into a clear, helpful response.
"""


# ============================================================================
# Built-in Tool Specifications (OpenAI function-calling format)
# ============================================================================

BUILTIN_TOOL_SPECS = {
    "search_web": {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "Search the web for current, up-to-date information. "
                "MUST use this tool when the user asks about: recent events, news, current prices, "
                "weather, sports scores, stock prices, or any fact that may have changed after training. "
                "Do NOT refuse to search — always use this tool for real-time queries."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query."},
                    "count": {"type": "integer", "description": "Number of results (default 5, max 10).", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    "fetch_url": {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": (
                "Fetch and extract readable text content from a URL. "
                "Use when the user provides a link and wants you to read, summarize, or analyze its content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch."},
                },
                "required": ["url"],
            },
        },
    },
    "execute_code": {
        "type": "function",
        "function": {
            "name": "execute_code",
            "description": (
                "Execute Python code and return the output. "
                "Use for: calculations, data processing, string manipulation, file parsing, "
                "sorting/filtering data, generating structured output, or any task where "
                "running code gives a more reliable result than reasoning alone."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute."},
                    "language": {"type": "string", "description": "Language (default: python).", "default": "python"},
                },
                "required": ["code"],
            },
        },
    },
    "generate_image": {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": (
                "Generate an actual image/picture using an AI image generation model. "
                "ONLY use this tool when the user explicitly requests to CREATE or GENERATE a visual image right now. "
                "Trigger phrases: 'buatkan gambar', 'generate image', 'create a picture', 'draw me', 'buat ilustrasi', 'gambarkan'. "
                "DO NOT use for: design ideas, design plans, UI/UX discussions, architecture plans, "
                "questions about design, 'rencana desain', 'ide rancangan', 'bagaimana cara membuat gambar', "
                "or any conceptual/planning discussion. "
                "When in doubt, respond with text instead of generating an image."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Detailed visual description of the image to generate."},
                    "size": {"type": "string", "description": "Image size: '1024x1024' (square), '1792x1024' (landscape), '1024x1792' (portrait).", "default": "1024x1024"},
                    "quality": {"type": "string", "description": "Quality: 'standard' or 'hd'.", "default": "standard"},
                },
                "required": ["prompt"],
            },
        },
    },
    "get_current_time": {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current date and time in UTC. Use whenever the user asks what time or date it is.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "calculate": {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": (
                "Evaluate a mathematical expression and return the exact result. "
                "ALWAYS use this for any arithmetic, algebra, or math computation — "
                "never compute math mentally when this tool is available."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Math expression to evaluate, e.g. '2 ** 10 + sqrt(144)'."},
                },
                "required": ["expression"],
            },
        },
    },
}


# ============================================================================
# Tool preparation
# ============================================================================


async def prepare_tools_for_request(
    body: dict,
    model: dict,
    user: dict,
    settings: Any = None,
) -> dict:
    """
    Inject tool specs into request body based on:
    - Model capabilities (tools=True required)
    - Feature flags from settings
    - User-defined tools from DB
    """
    capabilities = model.get("capabilities", {})
    if not capabilities.get("tools", False):
        # Model doesn't support tools — strip any existing tools
        body.pop("tools", None)
        body.pop("tool_choice", None)
        return body

    tools: list[dict] = []

    # Built-in tools based on feature flags
    if settings and getattr(settings, "enable_web_search", False):
        tools.append(BUILTIN_TOOL_SPECS["search_web"])
        tools.append(BUILTIN_TOOL_SPECS["fetch_url"])

    if settings and getattr(settings, "enable_code_interpreter", False):
        tools.append(BUILTIN_TOOL_SPECS["execute_code"])

    if settings and getattr(settings, "enable_image_generation", False):
        tools.append(BUILTIN_TOOL_SPECS["generate_image"])

    # Always available utilities
    tools.extend([
        BUILTIN_TOOL_SPECS["get_current_time"],
        BUILTIN_TOOL_SPECS["calculate"],
    ])

    # User-defined tools from DB
    try:
        from database import async_session_factory
        async with async_session_factory() as db:
            user_tools = await _get_user_tools(db, user.get("id", ""))
            tools.extend(user_tools)
    except Exception as e:
        logger.warning("Failed to load user tools: %s", e)

    # Merge with any tools already in body (from request)
    existing_tools = body.get("tools", [])
    if existing_tools:
        existing_names = {t.get("function", {}).get("name") for t in existing_tools}
        for t in tools:
            if t.get("function", {}).get("name") not in existing_names:
                existing_tools.append(t)
        body["tools"] = existing_tools
    else:
        body["tools"] = tools

    if not body.get("tool_choice"):
        body["tool_choice"] = "auto"

    # ── Inject TOOL_USE_SYSTEM_PROMPT ────────────────────────────────────────
    # Append to existing system message, or insert a new system message at index 0.
    # This ensures the model knows WHEN and HOW to use each tool.
    messages: list[dict] = body.get("messages", [])
    if messages:
        # Find existing system message
        sys_idx = next((i for i, m in enumerate(messages) if m.get("role") == "system"), None)
        if sys_idx is not None:
            existing_content = messages[sys_idx].get("content", "")
            if isinstance(existing_content, str):
                # Append tool instructions only if not already present
                if "Tool Use Instructions" not in existing_content:
                    messages[sys_idx]["content"] = existing_content + "\n\n" + TOOL_USE_SYSTEM_PROMPT
            elif isinstance(existing_content, list):
                # Multi-part content — append as text part
                has_tool_instructions = any(
                    "Tool Use Instructions" in (p.get("text", "") if isinstance(p, dict) else "")
                    for p in existing_content
                )
                if not has_tool_instructions:
                    existing_content.append({"type": "text", "text": TOOL_USE_SYSTEM_PROMPT})
        else:
            # No system message — prepend one
            messages.insert(0, {"role": "system", "content": TOOL_USE_SYSTEM_PROMPT})
        body["messages"] = messages

    return body


async def _get_user_tools(db, user_id: str) -> list[dict]:
    """Load user-defined tools from app_config table."""
    from sqlalchemy import text

    try:
        result = await db.execute(
            text("SELECT value FROM app_config WHERE config_path = :path"),
            {"path": f"users.{user_id}.tools"},
        )
        row = result.fetchone()
        if not row or not row[0]:
            return []

        tools_data = row[0]
        if isinstance(tools_data, str):
            tools_data = json.loads(tools_data)
        if not isinstance(tools_data, list):
            return []

        result_tools = []
        for tool in tools_data:
            if not isinstance(tool, dict) or not tool.get("active", True):
                continue
            result_tools.append({
                "type": "function",
                "function": {
                    "name": tool.get("name", "custom_tool"),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
                },
            })
        return result_tools
    except Exception as e:
        logger.debug("User tools load error: %s", e)
        return []


# ============================================================================
# Parallel tool execution
# ============================================================================


async def execute_tool_calls_parallel(tool_calls: list[dict]) -> list[dict]:
    """
    Execute all tool calls in PARALLEL using asyncio.gather.
    Returns list of {tool_call_id, output} dicts.
    """
    tasks = [_execute_single_tool(tc) for tc in tool_calls]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    output = []
    for tc, result in zip(tool_calls, results):
        tc_id = tc.get("id", "")
        if isinstance(result, Exception):
            logger.error("Tool '%s' raised exception: %s", tc.get("function", {}).get("name"), result)
            output.append({"tool_call_id": tc_id, "output": {"error": str(result)}})
        else:
            output.append(result)

    return output


async def _execute_single_tool(tool_call: dict) -> dict:
    """Execute a single tool call. Returns {tool_call_id, output}."""
    tool_name = tool_call.get("function", {}).get("name", "")
    raw_args = tool_call.get("function", {}).get("arguments", "{}")
    tool_call_id = tool_call.get("id", "")

    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
    except json.JSONDecodeError:
        return {"tool_call_id": tool_call_id, "output": f"Error: invalid JSON arguments: {raw_args}"}

    try:
        if tool_name == "search_web":
            output = await _tool_search_web(args.get("query", ""), args.get("count", 5))
        elif tool_name == "fetch_url":
            output = await _tool_fetch_url(args.get("url", ""))
        elif tool_name == "execute_code":
            output = await _tool_execute_code(args.get("code", ""), args.get("language", "python"))
        elif tool_name == "generate_image":
            output = await _tool_generate_image(args.get("prompt", ""), args.get("size", "1024x1024"), args.get("quality", "standard"))
        elif tool_name == "get_current_time":
            now = datetime.now(timezone.utc)
            output = {"utc": now.isoformat(), "timestamp": int(now.timestamp()), "timezone": "UTC"}
        elif tool_name == "calculate":
            output = _tool_calculate(args.get("expression", ""))
        else:
            output = {"error": f"Tool '{tool_name}' tidak tersedia"}

        return {"tool_call_id": tool_call_id, "output": output}

    except Exception as e:
        logger.error("Tool '%s' execution error: %s", tool_name, e, exc_info=True)
        return {"tool_call_id": tool_call_id, "output": {"error": f"Tool execution failed: {str(e)}"}}


# ============================================================================
# Tool implementations
# ============================================================================


async def _tool_search_web(query: str, count: int = 5) -> list[dict]:
    """Search the web using configured engine."""
    try:
        from utils.middleware import _web_search
        results = await _web_search(query=query, count=min(count, 10))
        return results
    except Exception as e:
        logger.error("Web search tool error: %s", e)
        return [{"error": str(e)}]


async def _tool_fetch_url(url: str) -> dict:
    """Fetch and extract content from URL."""
    try:
        from retrieval.web.utils import extract_web_content
        content = await extract_web_content(url)
        return {"url": url, "content": content[:8000], "length": len(content)}
    except Exception as e:
        logger.error("URL fetch error for %s: %s", url, e)
        return {"url": url, "error": str(e)}


async def _tool_execute_code(code: str, language: str = "python") -> dict:
    """
    Execute Python code in a restricted sandbox using exec().
    WARNING: This is a basic sandbox — do NOT expose to untrusted users.
    For production, use a proper sandbox (e.g., Docker, Pyodide, or E2B).
    """
    if language.lower() not in ("python", "py"):
        return {"error": f"Language '{language}' not supported. Only Python is available.", "language": language}

    import io
    import contextlib
    import traceback

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    # Restricted globals — no file system, no network, no os
    safe_globals = {
        "__builtins__": {
            "print": print,
            "len": len, "range": range, "enumerate": enumerate, "zip": zip,
            "map": map, "filter": filter, "sorted": sorted, "reversed": reversed,
            "list": list, "dict": dict, "set": set, "tuple": tuple,
            "str": str, "int": int, "float": float, "bool": bool, "bytes": bytes,
            "sum": sum, "min": max, "max": max, "abs": abs, "round": round,
            "isinstance": isinstance, "type": type, "repr": repr,
            "True": True, "False": False, "None": None,
        }
    }

    try:
        with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
            # Run in thread to avoid blocking event loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: exec(compile(code, "<sandbox>", "exec"), safe_globals))

        return {
            "output": stdout_capture.getvalue(),
            "stderr": stderr_capture.getvalue(),
            "language": language,
            "status": "success",
        }
    except Exception as e:
        return {
            "output": stdout_capture.getvalue(),
            "error": traceback.format_exc(),
            "language": language,
            "status": "error",
        }


async def _tool_generate_image(prompt: str, size: str = "1024x1024", quality: str = "standard") -> dict:
    """
    Generate image via OpenAI-compatible /images/generations endpoint.
    Requires a provider that supports image generation.
    """
    from env import settings as app_settings
    from database import async_session_factory
    from sqlalchemy import text

    async with async_session_factory() as db:
        result = await db.execute(
            text("SELECT base_url, api_key FROM providers WHERE is_active = true LIMIT 1")
        )
        row = result.fetchone()

    if not row:
        return {"error": "No active provider configured for image generation"}

    provider_url = row[0].rstrip("/")
    api_key = row[1] or ""

    import aiohttp
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{provider_url}/images/generations",
                headers=headers,
                json={"prompt": prompt, "n": 1, "size": size, "quality": quality},
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    images = data.get("data", [])
                    if images:
                        return {
                            "url": images[0].get("url", ""),
                            "b64_json": images[0].get("b64_json"),
                            "prompt": prompt,
                            "size": size,
                        }
                else:
                    error_text = await resp.text()
                    return {"error": f"Image generation failed: HTTP {resp.status} — {error_text[:200]}"}
    except Exception as e:
        return {"error": f"Image generation error: {str(e)}"}

    return {"error": "No image returned from provider"}


def _tool_calculate(expression: str) -> dict:
    """Safely evaluate a mathematical expression."""
    import math
    import ast

    allowed_names = {
        k: v for k, v in math.__dict__.items() if not k.startswith("_")
    }
    allowed_names.update({"abs": abs, "round": round, "min": min, "max": max, "sum": sum})

    try:
        # Parse and validate AST — only allow safe nodes
        tree = ast.parse(expression, mode="eval")
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.Call)):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id not in allowed_names:
                        return {"error": f"Function '{node.func.id}' not allowed"}
        result = eval(compile(tree, "<calc>", "eval"), {"__builtins__": {}}, allowed_names)
        return {"expression": expression, "result": result}
    except ZeroDivisionError:
        return {"error": "Division by zero"}
    except Exception as e:
        return {"error": f"Calculation error: {str(e)}"}
