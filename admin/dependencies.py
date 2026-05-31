"""
Common dependencies for admin routes.
Authentication and authorization dependencies.
"""

from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from admin.auth import (
    get_current_admin_session,
    generate_csrf_token,
    SESSION_COOKIE_NAME,
)


async def get_current_admin(request: Request) -> dict:
    """
    Dependency to get current admin user.
    Returns session data if authenticated.
    Raises HTTPException redirecting to login if not.
    """
    session = await get_current_admin_session(request)

    if not session:
        # For HTMX requests, return a redirect header
        if request.headers.get("HX-Request") == "true":
            raise HTTPException(
                status_code=200,
                headers={"HX-Redirect": "/admin/login"},
            )
        raise HTTPException(
            status_code=302,
            headers={"Location": "/admin/login"},
        )

    return session


async def get_optional_admin(request: Request) -> Optional[dict]:
    """
    Dependency to optionally get current admin user.
    Returns session data if authenticated, None otherwise.
    """
    return await get_current_admin_session(request)


async def require_admin_role(admin: dict = Depends(get_current_admin)) -> dict:
    """
    Dependency to require admin role.
    Returns session data if admin, raises 403 otherwise.
    """
    if admin.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Admin access required",
        )
    return admin


def get_csrf_token(request: Request) -> str:
    """
    Get CSRF token from cookie or generate new one.
    """
    token = request.cookies.get("csrf_token")
    if not token:
        token = generate_csrf_token()
    return token


async def get_template_context(
    request: Request,
    admin: Optional[dict] = Depends(get_optional_admin),
) -> dict:
    """
    Get common template context for admin pages.
    Includes request, admin session, and CSRF token.
    """
    csrf_token = get_csrf_token(request)

    return {
        "request": request,
        "admin": admin,
        "csrf_token": csrf_token,
        "is_htmx": request.headers.get("HX-Request") == "true",
    }


class AdminDep:
    """
    Class-based dependency for admin authentication.
    Can be used as a parameter in route functions.
    """

    def __init__(
        self,
        request: Request,
    ):
        self.request = request
        self._session: Optional[dict] = None

    async def __call__(self) -> "AdminDep":
        """Authenticate and get session."""
        self._session = await get_current_admin_session(self.request)

        if not self._session:
            if self.request.headers.get("HX-Request") == "true":
                raise HTTPException(
                    status_code=200,
                    headers={"HX-Redirect": "/admin/login"},
                )
            raise HTTPException(
                status_code=302,
                headers={"Location": "/admin/login"},
            )

        return self

    @property
    def session(self) -> dict:
        """Get session data."""
        return self._session or {}

    @property
    def user_id(self) -> str:
        """Get user ID."""
        return self._session.get("user_id", "") if self._session else ""

    @property
    def email(self) -> str:
        """Get user email."""
        return self._session.get("email", "") if self._session else ""

    @property
    def name(self) -> str:
        """Get user name."""
        return self._session.get("name", "") if self._session else ""

    @property
    def role(self) -> str:
        """Get user role."""
        return self._session.get("role", "") if self._session else ""

    def is_admin(self) -> bool:
        """Check if user is admin."""
        return self.role == "admin"
