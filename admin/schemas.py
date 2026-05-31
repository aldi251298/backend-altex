"""
Pydantic schemas for admin operations.
Validation models for forms and API requests.
"""

import re
from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator


# ============================================================================
# Provider Schemas
# ============================================================================

class ProviderBase(BaseModel):
    """Base provider schema."""
    name: str
    base_url: str
    api_key: Optional[str] = None
    auth_type: str = "bearer"
    prefix: Optional[str] = None
    is_active: bool = True

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return v.rstrip("/")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or len(v.strip()) == 0:
            raise ValueError("Provider name is required")
        return v.strip()


class ProviderCreate(ProviderBase):
    """Schema for creating a provider."""
    extra_config: Optional[dict] = None


class ProviderUpdate(BaseModel):
    """Schema for updating a provider."""
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    auth_type: Optional[str] = None
    prefix: Optional[str] = None
    is_active: Optional[bool] = None
    extra_config: Optional[dict] = None

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not v.startswith(("http://", "https://")):
                raise ValueError("base_url must start with http:// or https://")
            return v.rstrip("/")
        return v


# ============================================================================
# User Schemas
# ============================================================================

class UserBase(BaseModel):
    """Base user schema."""
    email: EmailStr
    name: str
    role: str = "user"
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or len(v.strip()) == 0:
            raise ValueError("User name is required")
        return v.strip()

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("admin", "user"):
            raise ValueError("Role must be 'admin' or 'user'")
        return v


class UserCreate(UserBase):
    """Schema for creating a user."""
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserUpdate(BaseModel):
    """Schema for updating a user."""
    email: Optional[EmailStr] = None
    name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    settings: Optional[dict] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("admin", "user"):
            raise ValueError("Role must be 'admin' or 'user'")
        return v


class UserPasswordUpdate(BaseModel):
    """Schema for updating user password."""
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


# ============================================================================
# Auth Schemas
# ============================================================================

class AdminLogin(BaseModel):
    """Schema for admin login."""
    email: EmailStr
    password: str


class AdminSession(BaseModel):
    """Schema for admin session data."""
    user_id: str
    email: str
    name: str
    role: str


# ============================================================================
# Settings Schemas
# ============================================================================

class SettingsUpdate(BaseModel):
    """Schema for updating settings."""
    # RAG Settings
    embedding_engine: Optional[str] = None
    rag_embedding_model: Optional[str] = None
    embedding_dimension: Optional[int] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    rag_top_k: Optional[int] = None
    rag_relevance_threshold: Optional[float] = None

    # Web Search Settings
    enable_web_search: Optional[bool] = None
    web_search_engine: Optional[str] = None
    search_result_count: Optional[int] = None

    # Feature Flags
    enable_image_generation: Optional[bool] = None
    enable_code_interpreter: Optional[bool] = None
    enable_memory: Optional[bool] = None
    enable_title_generation: Optional[bool] = None
