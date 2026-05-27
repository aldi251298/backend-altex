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


def strip_unsupported_params(body: dict, model_capabilities: dict) -> dict:
    """
    Remove parameters not supported by specific model.
    Example: 'tools' for models that don't support function calling.
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
