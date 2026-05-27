"""
Tests untuk chat completion utilities.
Verifikasi payload transformation dan model params.
"""

import pytest


def test_apply_system_prompt():
    """Verifikasi system prompt injection."""
    from utils.payload import apply_system_prompt_to_body
    
    body = {
        "messages": [
            {"role": "user", "content": "Hello"},
        ]
    }
    params = {"system": "You are a helpful assistant."}
    
    result = apply_system_prompt_to_body(params, body)
    
    assert result["messages"][0]["role"] == "system"
    assert "helpful assistant" in result["messages"][0]["content"]


def test_apply_model_params():
    """Verifikasi model params injection."""
    from utils.payload import apply_model_params_to_body
    
    body = {"messages": []}
    params = {"temperature": 0.7, "max_tokens": 2048, "top_p": None}
    
    result = apply_model_params_to_body(params, body)
    
    assert result["temperature"] == 0.7
    assert result["max_tokens"] == 2048
    assert "top_p" not in result  # None params should be skipped


def test_strip_unsupported_params():
    """Verifikasi parameter stripping."""
    from utils.payload import strip_unsupported_params
    
    body = {
        "messages": [],
        "tools": [{"type": "function"}],
        "tool_choice": "auto",
    }
    capabilities = {"tools": False, "vision": False}
    
    result = strip_unsupported_params(body, capabilities)
    
    assert "tools" not in result
    assert "tool_choice" not in result


def test_validate_messages():
    """Verifikasi message validation."""
    from utils.payload import validate_messages
    
    valid = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    assert validate_messages(valid) is True
    
    invalid = [
        {"role": "invalid", "content": "Hello"},
    ]
    assert validate_messages(invalid) is False
    
    assert validate_messages([]) is False
