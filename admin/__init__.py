"""
Admin module for WebUI.
Provides admin panel routes, authentication, and management interfaces.
"""

from admin.router import router as admin_router

__all__ = ["admin_router"]
