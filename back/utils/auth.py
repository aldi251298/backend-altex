"""
Auth utilities: JWT token creation, validation, and password hashing.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from constants import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    DEFAULT_BCRYPT_COST_FACTOR,
    REFRESH_TOKEN_EXPIRE_DAYS,
)
from env import settings

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT security
security = HTTPBearer()

# JWT Configuration
SECRET_KEY = settings.secret_key
ALGORITHM = "HS256"

if not SECRET_KEY or len(SECRET_KEY) < 32:
    raise ValueError(
        "SECRET_KEY must be at least 32 characters. "
        "Set it in environment variable or .env file."
    )


# ============================================================================
# Password Hashing
# ============================================================================


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password, rounds=DEFAULT_BCRYPT_COST_FACTOR)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password)


# ============================================================================
# JWT Token Management
# ============================================================================


def create_access_token(
    user_id: str,
    email: str,
    role: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a JWT access token."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_delta.minutes if expires_delta else ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """Create a JWT refresh token."""
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    payload = {
        "sub": user_id,
        "iat": datetime.now(timezone.utc),
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Returns payload dict."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token tidak valid: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ============================================================================
# Dependency: Get Verified User
# ============================================================================


async def get_verified_user() -> dict:
    """
    FastAPI dependency to validate JWT and extract user info.
    Returns user dict with sub (user_id), email, role.
    
    NOTE: For free version, always returns a dummy user without authentication.
    No Authorization header required.
    """
    # For free version, always return a dummy user
    # Skip JWT validation entirely
    return {
        "id": "free_user_001",
        "email": "user@altexchat.com",
        "role": "user",
    }


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
) -> Optional[dict]:
    """
    Get user if token is provided, None otherwise.
    Useful for endpoints that work with or without auth.
    """
    if credentials is None:
        return None

    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            return None
        return {
            "id": payload.get("sub"),
            "email": payload.get("email"),
            "role": payload.get("role"),
        }
    except JWTError:
        return None


# ============================================================================
# Device User Management
# ============================================================================


async def get_or_create_device_user(device_id: str) -> dict:
    """
    Get or create a user for a device ID.
    Creates a user in the database if it doesn't exist.
    """
    from database import async_session_factory
    from models.users import User
    from constants import time_ns
    
    async with async_session_factory() as db:
        # Check if user exists
        from sqlalchemy import select
        result = await db.execute(
            select(User).where(User.id == device_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            # Create new device user
            user = User(
                id=device_id,
                email=f"{device_id}@device.altexchat.com",
                name=f"Device User {device_id[:8]}",
                hashed_password=hash_password(""),  # Empty password for device users
                role="user",
                is_active=True,
                settings={},
                created_at=time_ns(),
                updated_at=time_ns(),
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        
        return {
            "id": user.id,
            "email": user.email,
            "role": user.role,
        }


async def get_device_user(device_id: str = None) -> dict:
    """
    FastAPI dependency to get or create device user.
    Looks for X-Device-ID header.
    """
    from fastapi import Request
    from fastapi.params import Depends
    
    async def device_user_dependency(request: Request):
        # Get device ID from header or generate one
        device_id = request.headers.get("X-Device-ID")
        if not device_id:
            # Try to get from query params for backward compatibility
            device_id = request.query_params.get("device_id")
        
        if not device_id:
            # Generate a random device ID
            import uuid
            device_id = f"device_{uuid.uuid4().hex[:16]}"
        
        return await get_or_create_device_user(device_id)
    
    return Depends(device_user_dependency)
