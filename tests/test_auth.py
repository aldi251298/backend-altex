"""
Tests untuk auth utilities.
Verifikasi JWT token creation dan password hashing.
"""

import pytest
from unittest.mock import patch


@pytest.fixture
def mock_settings():
    with patch('utils.auth.settings') as mock:
        mock.secret_key = "test-secret-key-that-is-long-enough-32chars!!"
        mock.access_token_expire_minutes = 60
        return mock


def test_password_hashing():
    """Verifikasi password hashing dan verification."""
    from utils.auth import hash_password, verify_password
    
    password = "secure-password-123"
    hashed = hash_password(password)
    
    assert hashed != password
    assert verify_password(password, hashed)
    assert not verify_password("wrong-password", hashed)


def test_token_creation(mock_settings):
    """Verifikasi JWT token creation."""
    from utils.auth import create_access_token, create_refresh_token
    
    access = create_access_token(
        user_id="test-user",
        email="test@example.com",
        role="user",
    )
    
    assert isinstance(access, str)
    assert len(access) > 0
    
    refresh = create_refresh_token(user_id="test-user")
    assert isinstance(refresh, str)
    assert len(refresh) > 0


def test_mask_api_key():
    """Verifikasi API key masking."""
    from constants import mask_api_key
    
    key = "sk-test-1234567890abcdef"
    masked = mask_api_key(key)
    
    assert masked != key
    assert masked.startswith("sk-t")
    assert "*" in masked
