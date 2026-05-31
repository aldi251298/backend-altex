"""
Main admin router with all routes.
Provides HTML pages and form handlers for admin panel.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func

from constants import time_ns
from database import async_session_factory
from models.providers import Provider
from models.users import User
from models.chats import Chat
from models.files import File

from admin.auth import (
    authenticate_admin,
    create_session_cookie,
    create_csrf_cookie,
    delete_session_cookies,
    generate_session_token,
    generate_csrf_token,
    hash_password,
    require_csrf,
    session_manager,
    create_default_admin,
)
from admin.dependencies import get_current_admin, get_template_context
from admin.schemas import ProviderCreate, ProviderUpdate, UserCreate, UserUpdate


router = APIRouter(prefix="/admin", tags=["Admin WebUI"])

# Setup Jinja2 templates
templates = Jinja2Templates(directory="templates")


# ============================================================================
# Template Helpers
# ============================================================================

def format_timestamp(ts: int) -> str:
    """Format nanosecond timestamp to readable date."""
    from datetime import datetime
    dt = datetime.fromtimestamp(ts / 1_000_000_000)
    return dt.strftime("%Y-%m-%d %H:%M")


def format_size(bytes: int) -> str:
    """Format bytes to human readable size."""
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes < 1024:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024
    return f"{bytes:.1f} TB"


# Register template filters
templates.env.filters["timestamp"] = format_timestamp
templates.env.filters["size"] = format_size


# ============================================================================
# Auth Routes
# ============================================================================

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render login page."""
    # Check if already logged in - use get_current_admin_session to avoid redirect loop
    from admin.auth import get_current_admin_session
    session = await get_current_admin_session(request)
    if session:
        return RedirectResponse(url="/admin/dashboard", status_code=302)

    csrf_token = generate_csrf_token()
    response = templates.TemplateResponse(
        "login.html",
        {"request": request, "csrf_token": csrf_token},
    )
    create_csrf_cookie(response, csrf_token)
    return response


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    """Process login form."""
    async with async_session_factory() as db:
        user = await authenticate_admin(db, email, password)

        if not user:
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": "Invalid credentials or not an admin account",
                    "csrf_token": generate_csrf_token(),
                },
                status_code=401,
            )

        # Create session
        token = generate_session_token()
        session_manager.create_session(
            token,
            user_id=user.id,
            email=user.email,
            name=user.name,
            role=user.role,
        )

        # Redirect to dashboard
        response = RedirectResponse(url="/admin/dashboard", status_code=302)
        create_session_cookie(response, token)

        # Also set CSRF cookie
        csrf_token = generate_csrf_token()
        create_csrf_cookie(response, csrf_token)

        return response


@router.post("/logout")
async def logout(request: Request):
    """Logout and clear session."""
    token = request.cookies.get("admin_session")
    if token:
        session_manager.delete_session(token)

    response = RedirectResponse(url="/admin/login", status_code=302)
    delete_session_cookies(response)
    return response


# ============================================================================
# Dashboard
# ============================================================================

@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, admin: dict = Depends(get_current_admin)):
    """Render dashboard with stats."""
    async with async_session_factory() as db:
        # Provider stats
        provider_result = await db.execute(
            select(
                func.count(Provider.id).label("total"),
                func.sum(func.cast(Provider.is_active, type_=func.count())).label("active"),
            )
        )
        provider_stats = provider_result.first()

        # User stats
        user_result = await db.execute(
            select(
                func.count(User.id).label("total"),
                func.sum(func.cast(User.is_active, type_=func.count())).label("active"),
            )
        )
        user_stats = user_result.first()

        # Chat stats
        chat_result = await db.execute(select(func.count(Chat.id)))
        chat_total = chat_result.scalar() or 0

        # File stats
        file_result = await db.execute(
            select(
                func.count(File.id).label("count"),
                func.sum(File.size_bytes).label("total_size"),
            )
        )
        file_stats = file_result.first()

        # Recent providers
        recent_providers_result = await db.execute(
            select(Provider).order_by(Provider.created_at.desc()).limit(5)
        )
        recent_providers = list(recent_providers_result.scalars().all())

    stats = {
        "providers": {
            "total": provider_stats.total or 0,
            "active": provider_stats.active or 0,
        },
        "users": {
            "total": user_stats.total or 0,
            "active": user_stats.active or 0,
        },
        "chats": {
            "total": chat_total,
        },
        "files": {
            "total": file_stats.count or 0,
            "size_mb": (file_stats.total_size or 0) / (1024 * 1024),
        },
    }

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "admin": admin,
            "stats": stats,
            "recent_providers": recent_providers,
        },
    )


# ============================================================================
# Provider Management
# ============================================================================

@router.get("/providers", response_class=HTMLResponse)
async def providers_list(request: Request, admin: dict = Depends(get_current_admin)):
    """Render provider list page."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(Provider).order_by(Provider.created_at.desc())
        )
        providers = list(result.scalars().all())

    return templates.TemplateResponse(
        "providers/list.html",
        {"request": request, "admin": admin, "providers": providers},
    )


@router.get("/providers/new", response_class=HTMLResponse)
async def provider_new(request: Request, admin: dict = Depends(get_current_admin)):
    """Render new provider form."""
    return templates.TemplateResponse(
        "providers/form.html",
        {"request": request, "admin": admin, "provider": None, "is_edit": False},
    )


@router.get("/providers/{provider_id}", response_class=HTMLResponse)
async def provider_edit(
    request: Request,
    provider_id: str,
    admin: dict = Depends(get_current_admin),
):
    """Render edit provider form."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(Provider).where(Provider.id == provider_id)
        )
        provider = result.scalar_one_or_none()

        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")

    return templates.TemplateResponse(
        "providers/form.html",
        {"request": request, "admin": admin, "provider": provider, "is_edit": True},
    )


@router.post("/providers", response_class=HTMLResponse)
async def provider_create(
    request: Request,
    admin: dict = Depends(get_current_admin),
    name: str = Form(...),
    base_url: str = Form(...),
    api_key: Optional[str] = Form(None),
    auth_type: str = Form("bearer"),
    prefix: Optional[str] = Form(None),
    is_active: bool = Form(False),
):
    """Create a new provider."""
    # Validate
    if not name or not base_url:
        return templates.TemplateResponse(
            "providers/form.html",
            {
                "request": request,
                "admin": admin,
                "provider": None,
                "is_edit": False,
                "error": "Name and Base URL are required",
            },
            status_code=400,
        )

    async with async_session_factory() as db:
        provider = Provider(
            id=str(uuid.uuid4()),
            name=name,
            base_url=base_url.rstrip("/"),
            api_key=api_key if api_key else None,
            auth_type=auth_type,
            prefix=prefix if prefix else None,
            is_active=is_active,
            extra_config={},
            created_at=time_ns(),
            updated_at=time_ns(),
        )

        db.add(provider)
        await db.commit()
        await db.refresh(provider)

    # Return row partial for HTMX
    return templates.TemplateResponse(
        "providers/row.html",
        {"request": request, "provider": provider},
    )


@router.put("/providers/{provider_id}", response_class=HTMLResponse)
async def provider_update(
    request: Request,
    provider_id: str,
    admin: dict = Depends(get_current_admin),
    name: str = Form(...),
    base_url: str = Form(...),
    api_key: Optional[str] = Form(None),
    auth_type: str = Form("bearer"),
    prefix: Optional[str] = Form(None),
    is_active: bool = Form(False),
):
    """Update a provider."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(Provider).where(Provider.id == provider_id)
        )
        provider = result.scalar_one_or_none()

        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")

        provider.name = name
        provider.base_url = base_url.rstrip("/")
        provider.auth_type = auth_type
        provider.is_active = is_active
        provider.updated_at = time_ns()

        if prefix:
            provider.prefix = prefix

        # Only update API key if provided
        if api_key and api_key != "****":
            provider.api_key = api_key

        await db.commit()
        await db.refresh(provider)

    # Return updated row
    return templates.TemplateResponse(
        "providers/row.html",
        {"request": request, "provider": provider},
    )


@router.delete("/providers/{provider_id}")
async def provider_delete(
    request: Request,
    provider_id: str,
    admin: dict = Depends(get_current_admin),
):
    """Delete a provider."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(Provider).where(Provider.id == provider_id)
        )
        provider = result.scalar_one_or_none()

        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")

        await db.delete(provider)
        await db.commit()

    return HTMLResponse(content="", status_code=200)


@router.post("/providers/{provider_id}/toggle")
async def provider_toggle(
    request: Request,
    provider_id: str,
    admin: dict = Depends(get_current_admin),
):
    """Toggle provider active status."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(Provider).where(Provider.id == provider_id)
        )
        provider = result.scalar_one_or_none()

        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")

        provider.is_active = not provider.is_active
        provider.updated_at = time_ns()

        await db.commit()
        await db.refresh(provider)

    return templates.TemplateResponse(
        "providers/row.html",
        {"request": request, "provider": provider},
    )


@router.get("/providers/{provider_id}/row", response_class=HTMLResponse)
async def provider_row(
    request: Request,
    provider_id: str,
    admin: dict = Depends(get_current_admin),
):
    """Get provider row for HTMX updates."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(Provider).where(Provider.id == provider_id)
        )
        provider = result.scalar_one_or_none()

        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")

    return templates.TemplateResponse(
        "providers/row.html",
        {"request": request, "provider": provider},
    )


@router.post("/providers/{provider_id}/test")
async def provider_test(
    request: Request,
    provider_id: str,
    admin: dict = Depends(get_current_admin),
):
    """Test provider connection."""
    import httpx

    async with async_session_factory() as db:
        result = await db.execute(
            select(Provider).where(Provider.id == provider_id)
        )
        provider = result.scalar_one_or_none()

        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")

    try:
        async with httpx.AsyncClient() as client:
            headers = {}
            if provider.api_key:
                headers["Authorization"] = f"Bearer {provider.api_key}"

            response = await client.get(
                f"{provider.base_url}/models",
                headers=headers,
                timeout=10.0,
            )

            if response.status_code == 200:
                return {"success": True, "message": "Connection successful"}
            else:
                return {
                    "success": False,
                    "message": f"HTTP {response.status_code}: {response.text[:100]}",
                }

    except httpx.TimeoutException:
        return {"success": False, "message": "Connection timeout"}
    except Exception as e:
        return {"success": False, "message": str(e)[:100]}


# ============================================================================
# User Management
# ============================================================================

@router.get("/users", response_class=HTMLResponse)
async def users_list(
    request: Request,
    admin: dict = Depends(get_current_admin),
    page: int = Query(1, ge=1),
):
    """Render user list page."""
    limit = 20
    offset = (page - 1) * limit

    async with async_session_factory() as db:
        # Get total count
        count_result = await db.execute(select(func.count(User.id)))
        total = count_result.scalar() or 0

        # Get users
        result = await db.execute(
            select(User).order_by(User.created_at.desc()).limit(limit).offset(offset)
        )
        users = list(result.scalars().all())

    total_pages = (total + limit - 1) // limit

    return templates.TemplateResponse(
        "users/list.html",
        {
            "request": request,
            "admin": admin,
            "users": users,
            "page": page,
            "total_pages": total_pages,
            "total": total,
        },
    )


@router.get("/users/new", response_class=HTMLResponse)
async def user_new(request: Request, admin: dict = Depends(get_current_admin)):
    """Render new user form."""
    return templates.TemplateResponse(
        "users/form.html",
        {"request": request, "admin": admin, "user": None, "is_edit": False},
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def user_edit(
    request: Request,
    user_id: str,
    admin: dict = Depends(get_current_admin),
):
    """Render edit user form."""
    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

    return templates.TemplateResponse(
        "users/form.html",
        {"request": request, "admin": admin, "user": user, "is_edit": True},
    )


@router.post("/users", response_class=HTMLResponse)
async def user_create(
    request: Request,
    admin: dict = Depends(get_current_admin),
    email: str = Form(...),
    name: str = Form(...),
    password: str = Form(...),
    role: str = Form("user"),
    is_active: bool = Form(False),
):
    """Create a new user."""
    # Validate
    if not email or not name or not password:
        return templates.TemplateResponse(
            "users/form.html",
            {
                "request": request,
                "admin": admin,
                "user": None,
                "is_edit": False,
                "error": "Email, name, and password are required",
            },
            status_code=400,
        )

    if len(password) < 8:
        return templates.TemplateResponse(
            "users/form.html",
            {
                "request": request,
                "admin": admin,
                "user": None,
                "is_edit": False,
                "error": "Password must be at least 8 characters",
            },
            status_code=400,
        )

    async with async_session_factory() as db:
        # Check if email exists
        existing = await db.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            return templates.TemplateResponse(
                "users/form.html",
                {
                    "request": request,
                    "admin": admin,
                    "user": None,
                    "is_edit": False,
                    "error": "Email already registered",
                },
                status_code=400,
            )

        user = User(
            id=str(uuid.uuid4()),
            email=email,
            name=name,
            hashed_password=hash_password(password),
            role=role,
            is_active=is_active,
            settings={},
            created_at=time_ns(),
            updated_at=time_ns(),
        )

        db.add(user)
        await db.commit()
        await db.refresh(user)

    return RedirectResponse(url="/admin/users", status_code=302)


@router.post("/users/{user_id}", response_class=HTMLResponse)
async def user_update(
    request: Request,
    user_id: str,
    admin: dict = Depends(get_current_admin),
    email: str = Form(...),
    name: str = Form(...),
    role: str = Form("user"),
    is_active: bool = Form(False),
    password: Optional[str] = Form(None),
):
    """Update a user."""
    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.email = email
        user.name = name
        user.role = role
        user.is_active = is_active
        user.updated_at = time_ns()

        # Update password if provided
        if password and len(password) >= 8:
            user.hashed_password = hash_password(password)

        await db.commit()
        await db.refresh(user)

    return RedirectResponse(url="/admin/users", status_code=302)


@router.post("/users/{user_id}/toggle")
async def user_toggle(
    request: Request,
    user_id: str,
    admin: dict = Depends(get_current_admin),
):
    """Toggle user active status."""
    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.is_active = not user.is_active
        user.updated_at = time_ns()

        await db.commit()

    return RedirectResponse(url="/admin/users", status_code=302)


@router.delete("/users/{user_id}")
async def user_delete(
    request: Request,
    user_id: str,
    admin: dict = Depends(get_current_admin),
):
    """Delete a user."""
    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        await db.delete(user)
        await db.commit()

    return HTMLResponse(content="", status_code=200)


# ============================================================================
# Chat Management
# ============================================================================

@router.get("/chats", response_class=HTMLResponse)
async def chats_list(
    request: Request,
    admin: dict = Depends(get_current_admin),
    page: int = Query(1, ge=1),
):
    """Render chat list page."""
    limit = 20
    offset = (page - 1) * limit

    async with async_session_factory() as db:
        # Get total count
        count_result = await db.execute(select(func.count(Chat.id)))
        total = count_result.scalar() or 0

        # Get chats
        result = await db.execute(
            select(Chat).order_by(Chat.updated_at.desc()).limit(limit).offset(offset)
        )
        chats = list(result.scalars().all())

    total_pages = (total + limit - 1) // limit

    return templates.TemplateResponse(
        "chats/list.html",
        {
            "request": request,
            "admin": admin,
            "chats": chats,
            "page": page,
            "total_pages": total_pages,
            "total": total,
        },
    )


@router.delete("/chats/{chat_id}")
async def chat_delete(
    request: Request,
    chat_id: str,
    admin: dict = Depends(get_current_admin),
):
    """Delete a chat."""
    async with async_session_factory() as db:
        result = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat = result.scalar_one_or_none()

        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")

        await db.delete(chat)
        await db.commit()

    return HTMLResponse(content="", status_code=200)


# ============================================================================
# Model Configuration
# ============================================================================

@router.get("/models", response_class=HTMLResponse)
async def models_list(request: Request, admin: dict = Depends(get_current_admin)):
    """Render model configuration page."""
    async with async_session_factory() as db:
        # Get active providers
        result = await db.execute(
            select(Provider).where(Provider.is_active == True)
        )
        providers = list(result.scalars().all())

    # For now, just show the model configuration page
    return templates.TemplateResponse(
        "models/list.html",
        {"request": request, "admin": admin, "providers": providers},
    )


# ============================================================================
# Settings
# ============================================================================

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, admin: dict = Depends(get_current_admin)):
    """Render settings page."""
    from config import config_manager
    from env import settings as app_settings

    # Get all config values
    config_data = {
        # RAG
        "embedding_engine": app_settings.embedding_engine,
        "rag_embedding_model": app_settings.rag_embedding_model,
        "embedding_dimension": app_settings.embedding_dimension,
        "chunk_size": app_settings.chunk_size,
        "chunk_overlap": app_settings.chunk_overlap,
        "rag_top_k": app_settings.rag_top_k,
        "rag_relevance_threshold": app_settings.rag_relevance_threshold,
        # Web Search
        "enable_web_search": app_settings.enable_web_search,
        "web_search_engine": app_settings.web_search_engine,
        "search_result_count": app_settings.search_result_count,
        # Features
        "enable_image_generation": app_settings.enable_image_generation,
        "enable_code_interpreter": app_settings.enable_code_interpreter,
        "enable_memory": app_settings.enable_memory,
        "enable_title_generation": app_settings.enable_title_generation,
    }

    return templates.TemplateResponse(
        "settings/index.html",
        {"request": request, "admin": admin, "config": config_data},
    )


@router.post("/settings")
async def settings_update(
    request: Request,
    admin: dict = Depends(get_current_admin),
):
    """Update settings."""
    from config import config_manager
    from env import settings as app_settings

    form_data = await request.form()

    # Update each setting
    # In a real implementation, you'd persist these to the database
    # For now, we just acknowledge the update

    return RedirectResponse(url="/admin/settings", status_code=302)
