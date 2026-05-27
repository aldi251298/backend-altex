"""
Payload transformation utilities.
Handles system prompt injection, model params, and parameter stripping.
"""


def apply_system_prompt_to_body(params: dict, body: dict) -> dict:
    """
    Inject system prompt with priority:
    chat-level override > model-default > global-default
    """
    system = params.get("system")
    if system:
        # Check if there's already a system message
        existing_system = next(
            (m for m in body.get("messages", []) if m.get("role") == "system"),
            None,
        )
        if existing_system:
            # Override existing system
            existing_system["content"] = system
        else:
            # Insert at beginning
            body["messages"] = [
                {"role": "system", "content": system}
            ] + body.get("messages", [])
    return body


def apply_model_params_to_body(params: dict, body: dict) -> dict:
    """
    Apply model parameters: only inject if value is not None.
    Prevents overriding provider defaults which may be better.
    """
    param_map = {
        "temperature": "temperature",
        "max_tokens": "max_tokens",
        "top_p": "top_p",
        "frequency_penalty": "frequency_penalty",
        "presence_penalty": "presence_penalty",
        "stop": "stop",
        "seed": "seed",
        "top_k": "top_k",  # Some providers (Anthropic, Ollama)
    }

    for src, dst in param_map.items():
        value = params.get(src)
        if value is not None:
            body[dst] = value

    return body


# Thinking-related params that must NEVER be stripped — always pass through to vLLM
_THINKING_PASSTHROUGH_KEYS = frozenset({
    "chat_template_kwargs",
    "enable_thinking",
    "preserve_thinking",
    "thinking",          # Anthropic-style {"type":"enabled","budget_tokens":...}
})


def strip_unsupported_params(body: dict, model_capabilities: dict) -> dict:
    """
    Remove parameters not supported by specific model.

    Thinking params (chat_template_kwargs, enable_thinking, preserve_thinking)
    are ALWAYS passed through to the provider unchanged — vLLM / Qwen3 needs them.
    """
    if not model_capabilities.get("tools", False):
        body.pop("tools", None)
        body.pop("tool_choice", None)

    if not model_capabilities.get("vision", False):
        # Convert multimodal messages to text only
        for msg in body.get("messages", []):
            if isinstance(msg.get("content"), list):
                text_parts = [
                    p.get("text", "")
                    for p in msg["content"]
                    if p.get("type") == "text"
                ]
                msg["content"] = " ".join(text_parts)

    # Thinking params — never strip, always forward to provider
    # These are set by the Android client toggle and consumed by vLLM chat template
    # enable_thinking=False  → disables <think> blocks in Qwen3
    # preserve_thinking=True → keeps <think> blocks in output (for display)
    # chat_template_kwargs   → vLLM-specific, passed directly to Jinja template
    # (no action needed — they're already in body via extra_params pass-through)

    return body


def apply_thinking_params(body: dict, enable_thinking: bool | None, preserve_thinking: bool | None = None) -> dict:
    """
    Apply thinking toggle params to the request body.

    Called when the Android client sends explicit thinking control flags
    (separate from the main body, e.g. as top-level request fields).

    vLLM Qwen3 usage:
      - enable_thinking=False  → chat_template_kwargs={"enable_thinking": False}
      - preserve_thinking=True → chat_template_kwargs={"preserve_thinking": True}

    These can be combined: disable thinking output but preserve existing think blocks.
    """
    if enable_thinking is None and preserve_thinking is None:
        return body

    # Build or merge chat_template_kwargs
    ctk: dict = body.get("chat_template_kwargs") or {}

    if enable_thinking is not None:
        ctk["enable_thinking"] = enable_thinking

    if preserve_thinking is not None:
        ctk["preserve_thinking"] = preserve_thinking

    if ctk:
        body["chat_template_kwargs"] = ctk

    return body


def validate_messages(messages: list) -> bool:
    """Validate message format."""
    if not messages:
        return False

    for msg in messages:
        if not isinstance(msg, dict):
            return False
        if "role" not in msg or "content" not in msg:
            return False
        if msg["role"] not in ("system", "user", "assistant", "tool"):
            return False

    return True


def extract_last_user_message(messages: list) -> str:
    """Extract the last user message content."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                # Multimodal content
                text_parts = [
                    p.get("text", "")
                    for p in content
                    if p.get("type") == "text"
                ]
                return " ".join(text_parts)
            return str(content)
    return ""
