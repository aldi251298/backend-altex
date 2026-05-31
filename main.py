"""
Main FastAPI application entry point.
Mounts routers, middleware, and initializes dependencies.
No auth required — anonymous user only.
"""

import logging
import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import config_manager
from database import async_session_factory, close_db, init_db
from env import settings

# ── Structlog configuration ───────────────────────────────────────────────────
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

log = structlog.get_logger()


# ============================================================================
# Application Lifespan
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    log.info("backend_starting", environment=settings.environment, version="1.0.0")

    # Initialize DB tables
    try:
        await init_db()
        log.info("database_initialized")
    except Exception as e:
        log.error("database_initialization_failed", error=str(e))

    # Initialize pgvector
    try:
        from retrieval.vector import initialize_pgvector
        initialize_pgvector(async_session_factory)
        log.info("pgvector_initialized")
    except Exception as e:
        log.warning("pgvector_init_failed", error=str(e))

    # Load config from DB
    try:
        async with async_session_factory() as db:
            await config_manager.initialize_from_db(db)
        log.info("config_loaded_from_db")
    except Exception as e:
        log.warning("config_load_failed", error=str(e))

    # Create default admin user if no admin exists
    try:
        from admin.auth import create_default_admin
        admin = await create_default_admin()
        if admin:
            log.info("default_admin_created", email=admin.email)
    except Exception as e:
        log.warning("default_admin_creation_failed", error=str(e))

    yield

    await close_db()
    log.info("backend_shutdown")


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="AI Chat Backend",
    description=(
        "Backend for AI Chat — OpenWebUI-inspired, vLLM-compatible.\n\n"
        "Features: SSE streaming, parallel tool calling, RAG, web search, "
        "vision, speech (STT/TTS), chat history, provider management."
    ),
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — allow all origins (personal project, no auth)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics (optional)
if settings.enable_metrics:
    try:
        from prometheus_fastapi_instrumentator import Instrumentator
        Instrumentator().instrument(app).expose(app)
    except ImportError:
        log.warning("prometheus_fastapi_instrumentator not installed, metrics disabled")


# ============================================================================
# Health Check
# ============================================================================


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": int(time.time() * 1000),
        "environment": settings.environment,
        "version": "2.0.0",
    }


@app.get("/", tags=["Health"])
async def root():
    """Root endpoint — redirect hint."""
    return {
        "message": "AI Chat Backend is running",
        "docs": "/docs",
        "health": "/health",
        "api": "/api",
    }


# ============================================================================
# Static Files & Templates
# ============================================================================

# Mount static files for admin panel
app.mount("/admin/static", StaticFiles(directory="static"), name="admin-static")

# Templates instance (for use in admin router)
templates = Jinja2Templates(directory="templates")


# ============================================================================
# Router Mounting
# ============================================================================


def mount_routers():
    """Mount all router modules."""
    from routers import chat, chats, models, providers, files, retrieval, tasks
    from routers import config as config_router
    from routers import audio as audio_router

    # ── Provider Management ──────────────────────────────────────────────────
    app.include_router(
        providers.router,
        prefix="/api/providers",
        tags=["Providers"],
    )

    # ── Model Management ─────────────────────────────────────────────────────
    app.include_router(
        models.router,
        prefix="/api/models",
        tags=["Models"],
    )

    # ── Chat Completion (SSE Streaming + non-streaming) ───────────────────────
    app.include_router(
        chat.router,
        prefix="/api/chat",
        tags=["Chat Completion"],
    )

    # ── Chat History ─────────────────────────────────────────────────────────
    app.include_router(
        chats.router,
        prefix="/api/chats",
        tags=["Chat History"],
    )

    # ── Files & RAG ──────────────────────────────────────────────────────────
    app.include_router(
        files.router,
        prefix="/api/files",
        tags=["Files & RAG"],
    )

    # ── Retrieval (Web Search) ────────────────────────────────────────────────
    app.include_router(
        retrieval.router,
        prefix="/api/retrieval",
        tags=["Retrieval"],
    )

    # ── Background Tasks ─────────────────────────────────────────────────────
    app.include_router(
        tasks.router,
        prefix="/api/tasks",
        tags=["Tasks"],
    )

    # ── App Configuration ─────────────────────────────────────────────────────
    app.include_router(
        config_router.router,
        prefix="/api/config",
        tags=["Config"],
    )

    # ── Audio (STT / TTS) ─────────────────────────────────────────────────────
    app.include_router(
        audio_router.router,
        prefix="/api/audio",
        tags=["Audio"],
    )

    # ── Image Generation (SSE pipeline: LLM enhance → image engine) ───────────
    from routers import images as images_router
    app.include_router(
        images_router.router,
        prefix="/api/images",
        tags=["Image Generation"],
    )

    # ── Admin WebUI ───────────────────────────────────────────────────────────
    from admin import admin_router
    app.include_router(admin_router)

    log.info("routers_mounted")


mount_routers()


# ============================================================================
# Global Exception Handler
# ============================================================================


@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception):
    """Catch-all exception handler — returns JSON."""
    from fastapi.responses import JSONResponse

    log.error(
        "unhandled_exception",
        path=str(request.url.path),
        error=str(exc),
        exc_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "S001",
                "message": "Terjadi kesalahan internal",
                "type": "internal_error",
            }
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        workers=1 if settings.is_development else settings.workers,
        reload=settings.is_development,
        log_level=settings.log_level,
    )
