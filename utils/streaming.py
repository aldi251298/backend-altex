"""
Streaming helpers for SSE (Server-Sent Events).
Handles event formatting and event emission.
"""

import asyncio
import json
from typing import Any, AsyncGenerator, Callable


# ============================================================================
# SSE Event Formatting
# ============================================================================


def _parse_sse_event(data: str) -> str | None:
    """
    Parse a single SSE event from a string. Returns the JSON data part or None.
    Handles: 'data: {json}\n\n' → '{json}'
    """
    if data.startswith("data: "):
        return data[6:]
    elif data.startswith("data:"):
        return data[5:]
    return None


def format_sse_chunk(data: dict, event_type: str = "chat.completion.chunk") -> str:
    """Format a chunk as SSE event."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def format_sse_data(data: dict) -> str:
    """Format data as SSE event (simplified)."""
    return f"data: {json.dumps(data)}\n\n"


def format_sse_done() -> str:
    """Signal end of stream."""
    return "data: [DONE]\n\n"


def format_sse_error(status_code: int, message: str, error_type: str = "provider_error") -> str:
    """Format error as SSE event - Flutter can handle consistently."""
    error = {
        "error": {
            "code": status_code,
            "message": message,
            "type": error_type,
        }
    }
    return f"data: {json.dumps(error)}\n\n"


# ============================================================================
# Status Events
# ============================================================================


def create_status_event(description: str, action: str, done: bool = False) -> dict:
    """Create a status event for Flutter progress indicator."""
    return {
        "type": "status",
        "data": {
            "description": description,
            "action": action,
            "done": done,
        }
    }


def create_citation_event(document: list, metadata: list, source: dict) -> dict:
    """Create a citation event for Flutter."""
    return {
        "type": "citation",
        "data": {
            "document": document,
            "metadata": metadata,
            "source": source,
        }
    }


# Status event constants
STATUS_SEARCHING = create_status_event(
    description="Mencari di web...",
    action="web_search",
    done=False,
)

STATUS_RETRIEVING = create_status_event(
    description="Mengambil konteks dari dokumen...",
    action="knowledge_retrieval",
    done=False,
)

STATUS_TOOLS_RUNNING = create_status_event(
    description="Menjalankan tools...",
    action="tool_execution",
    done=False,
)


# ============================================================================
# Event Emitter
# ============================================================================


async def create_event_emitter() -> tuple[Callable, "asyncio.Queue"]:
    """
    Create an event emitter that sends status events via queue.
    Returns (emit_function, event_queue) tuple.
    """
    import asyncio

    event_queue: asyncio.Queue = asyncio.Queue()

    async def emit(event_data: dict) -> None:
        """Emit an event to the queue."""
        sse_event = {
            "type": event_data.get("type", "status"),
            "data": event_data.get("data", event_data),
        }
        await event_queue.put(f"data: {json.dumps(sse_event)}\n\n")

    return emit, event_queue


async def event_queue_to_generator(
    event_queue: "asyncio.Queue",
) -> AsyncGenerator[str, None]:
    """Convert event queue to async generator for SSE."""
    import asyncio

    while True:
        try:
            event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
            yield event
        except asyncio.TimeoutError:
            break


# ============================================================================
# Stream Event Interleaving
# ============================================================================


async def interleaved_stream_generator(
    stream_generator: AsyncGenerator[str, None],
    event_queue: "asyncio.Queue",
) -> AsyncGenerator[str, None]:
    """
    Interleave SSE stream data with status events from queue.
    This allows status events to appear between streaming chunks.
    """
    import asyncio

    # Drain any initial events from queue
    while not event_queue.empty():
        try:
            event = event_queue.get_nowait()
            yield event
        except asyncio.QueueEmpty:
            break

    # Stream chunks while checking for events
    async for chunk in stream_generator:
        yield chunk

        # Check for pending events
        while not event_queue.empty():
            try:
                event = event_queue.get_nowait()
                yield event
            except asyncio.QueueEmpty:
                break
