"""
Admin authentication logic.
Session-based authentication with HTTP-only cookies.
"""

import hashlib
import secrets
import time
from typing import Optional

import bcrypt
from fastapi import Request, Response, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session_factory
from env import settings
from models.users import User
from constants import time_ns

# Session configuration
SESSION_COOKIE_NAME = "admin_session"
SESSION_DURATION_SECONDS = 7 * 24 * 60 * 60  # 7 days
CSRF_COOKIE_NAME = "csrf_token"


def hash_password(password: str) -> str:
    """Hash a password using bcrypt. Truncates to 72 bytes for bcrypt compatibility."""
    # bcrypt has a 72 byte password limit
    password_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash. Truncates to 72 bytes for bcrypt compatibility."""
    # bcrypt has a 72 byte password limit
    password_bytes = plain_password.encode('utf-8')[:72]
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def generate_session_token() -> str:
    """Generate a secure session token."""
    return secrets.token_urlsafe(32)


def generate_csrf_token() -> str:
    """Generate a CSRF token."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash a token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


class SessionManager:
    """In-memory session store for admin sessions."""

    def __init__(self):
        # In production, use Redis or database
        # Format: {token_hash: {user_id, email, name, role, expires_at}}
        self._sessions: dict = {}

    def create_session(
        self,
        token: str,
        user_id: str,
        email: str,
        name: str,
        role: str,
    ) -> dict:
        """Create a new session."""
        token_hash = hash_token(token)
        expires_at = time.time() + SESSION_DURATION_SECONDS

        session_data = {
            "user_id": user_id,
            "email": email,
            "name": name,
            "role": role,
            "expires_at": expires_at,
        }

        self._sessions[token_hash] = session_data
        return session_data

    def get_session(self, token: str) -> Optional[dict]:
        """Get session data by token."""
        token_hash = hash_token(token)
        session = self._sessions.get(token_hash)

        if not session:
            return None

        # Check expiration
        if session["expires_at"] < time.time():
            del self._sessions[token_hash]
            return None

        return session

    def delete_session(self, token: str) -> None:
        """Delete a session."""
        token_hash = hash_token(token)
        self._sessions.pop(token_hash, None)

    def cleanup_expired(self) -> int:
        """Remove expired sessions. Returns count of removed sessions."""
        now = time.time()
        expired = [
            token_hash
            for token_hash, session in self._sessions.items()
            if session["expires_at"] < now
        ]
        for token_hash in expired:
            del self._sessions[token_hash]
        return len(expired)


# Global session manager instance
session_manager = SessionManager()


async def authenticate_admin(
    db: AsyncSession,
    email: str,
    password: str,
) -> Optional[User]:
    """
    Authenticate an admin user.
    Returns User if valid, None otherwise.
    """
    result = await db.execute(
        select(User).where(User.email == email)
    )
    user = result.scalar_one_or_none()

    if not user:
        return None

    if not user.is_active:
        return None

    if user.role != "admin":
        return None

    if not verify_password(password, user.hashed_password):
        return None

    return user


def create_session_cookie(response: Response, token: str) -> None:
    """Set session cookie on response."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.environment == "production",
        samesite="strict",
        max_age=SESSION_DURATION_SECONDS,
        path="/admin",
    )


def create_csrf_cookie(response: Response, token: str) -> None:
    """Set CSRF cookie on response."""
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        httponly=False,  # Must be readable by JavaScript
        secure=settings.environment == "production",
        samesite="strict",
        max_age=SESSION_DURATION_SECONDS,
        path="/admin",
    )


def delete_session_cookies(response: Response) -> None:
    """Delete session cookies."""
    response.delete_cookie(SESSION_COOKIE_NAME, path="/admin")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/admin")


async def get_current_admin_session(request: Request) -> Optional[dict]:
    """
    Get current admin session from request.
    Returns session data or None.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None

    return session_manager.get_session(token)


async def verify_csrf(request: Request) -> bool:
    """
    Verify CSRF token from request.
    Returns True if valid, False otherwise.
    """
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return True

    # Get CSRF token from header (set by HTMX)
    header_token = request.headers.get("X-CSRF-Token")
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)

    if not header_token or not cookie_token:
        return False

    return secrets.compare_digest(header_token, cookie_token)


async def require_csrf(request: Request) -> None:
    """
    Require valid CSRF token for protected requests.
    Raises HTTPException if invalid.
    """
    if not await verify_csrf(request):
        raise HTTPException(
            status_code=403,
            detail="CSRF validation failed",
        )


async def create_default_admin() -> Optional[User]:
    """
    Create a default admin user if no admin exists.
    Credentials are taken from environment or defaults.
    """
    async with async_session_factory() as db:
        # Check if any admin exists
        result = await db.execute(
            select(User).where(User.role == "admin")
        )
        existing_admin = result.scalar_one_or_none()

        if existing_admin:
            return None

        # Create default admin
        # Get credentials from environment or use defaults
        admin_email = "admin@altex.local"
        admin_password = "admin123"  # Default, should be changed
        admin_name = "Admin"

        # Check env for override
        import os
        if admin_email_env := os.environ.get("ADMIN_EMAIL"):
            admin_email = admin_email_env
        if admin_password_env := os.environ.get("ADMIN_PASSWORD"):
            admin_password = admin_password_env
        if admin_name_env := os.environ.get("ADMIN_NAME"):
            admin_name = admin_name_env

        import uuid
        user = User(
            id=str(uuid.uuid4()),
            email=admin_email,
            name=admin_name,
            hashed_password=hash_password(admin_password),
            role="admin",
            is_active=True,
            settings={},
            created_at=time_ns(),
            updated_at=time_ns(),
        )

        db.add(user)
        await db.commit()
        await db.refresh(user)

        return user
