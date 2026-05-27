"""
Main FastAPI application entry point.
Mounts routers, middleware, and initializes dependencies.
"""

import logging
import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from config import config_manager
from database import async_session_factory, close_db, init_db
from env import settings

# Configure structlog
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
    """Application lifespan handler for startup/shutdown events."""
    # Startup
    log.info(
        "backend_starting",
        environment=settings.environment,
        version="1.0.0",
    )

    # Initialize database
    try:
        await init_db()
        log.info("database_initialized")
    except Exception as e:
        log.error("database_initialization_failed", error=str(e))

    # Initialize pgvector
    from retrieval.vector import initialize_pgvector
    initialize_pgvector(async_session_factory)
    log.info("pgvector_initialized")

    # Initialize config from DB
    try:
        async with async_session_factory() as db:
            await config_manager.initialize_from_db(db)
        log.info("config_loaded_from_db")
    except Exception as e:
        log.warning("config_load_failed", error=str(e))

    yield

    # Shutdown
    await close_db()
    log.info("backend_shutdown")


# ============================================================================
# FastAPI Application
# ============================================================================


app = FastAPI(
    title="AI Chat Backend",
    description="Backend for AI Chat with FastAPI",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus Metrics
if settings.enable_metrics:
    Instrumentator().instrument(app).expose(app)

# ============================================================================
# Health Check
# ============================================================================


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": int(time.time() * 1000),
        "environment": settings.environment,
    }


# ============================================================================
# Router Mounting
# ============================================================================


def mount_routers():
    """Mount all router modules to the FastAPI app."""
    # Import routers here to avoid circular imports
    from routers import chat, chats, models, providers, files, retrieval, tasks

    # Provider Management
    app.include_router(
        providers.router,
        prefix="/api/providers",
        tags=["Providers"],
    )

    # Model Management
    app.include_router(
        models.router,
        prefix="/api/models",
        tags=["Models"],
    )

    # Chat Completion (SSE Streaming)
    app.include_router(
        chat.router,
        prefix="/api/chat",
        tags=["Chat"],
    )

    # Chat History
    app.include_router(
        chats.router,
        prefix="/api/chats",
        tags=["Chats"],
    )

    # Files & RAG
    app.include_router(
        files.router,
        prefix="/api/files",
        tags=["Files"],
    )

    # Retrieval (Web Search)
    app.include_router(
        retrieval.router,
        prefix="/api/retrieval",
        tags=["Retrieval"],
    )

    # Background Tasks
    app.include_router(
        tasks.router,
        prefix="/api/tasks",
        tags=["Tasks"],
    )

    log.info("routers_mounted")


# Mount routers
mount_routers()


# ============================================================================
# Global Exception Handler
# ============================================================================


@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception):
    """Handle unexpected exceptions - returns proper JSON response."""
    from fastapi.responses import JSONResponse
    
    log.error(
        "unhandled_exception",
        path=request.url.path,
        error=str(exc),
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "S001",
                "message": "Terjadi kesalahan internal",
            }
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        workers=settings.workers if not settings.is_development else 1,
        reload=settings.is_development,
        log_level=settings.log_level,
    )
