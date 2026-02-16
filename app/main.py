"""
FastAPI application for Naked Forex trading framework.

Main application entry point that sets up routes, middleware,
and lifecycle events.
"""

from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.config.settings import get_settings
from app.config.logging_config import setup_logging
from app.db.session import init_db, close_db
from app.api.routes import health, auth, analysis, signals, trades, visualization
from app.api.middleware.error_handlers import (
    validation_exception_handler,
    http_exception_handler,
    database_exception_handler,
    general_exception_handler
)
from app.services.pattern_detection import PatternDetectionService
from app.services.sr_detection import SRDetectionService
from app.services.discord_service import DiscordBotService
from app.core.tasks import BackgroundTaskManager
from loguru import logger


# Global services and task manager
_pattern_service: PatternDetectionService | None = None
_discord_service: DiscordBotService | None = None
_task_manager: BackgroundTaskManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Starting Naked Forex API...")

    settings = get_settings()

    # Setup logging
    setup_logging(
        log_level=settings.log_level,
        log_file=settings.log_file
    )

    # Initialize database
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

    # Initialize services
    global _pattern_service, _discord_service, _task_manager

    _pattern_service = PatternDetectionService()
    logger.info("Pattern detection service initialized")

    # Start Discord bot if configured
    if settings.discord_token.get_secret_value():
        _discord_service = DiscordBotService(_pattern_service)
        await _discord_service.start()

        # Start background scanning
        _task_manager = BackgroundTaskManager(_pattern_service, _discord_service)
        await _task_manager.start_scanning()
        logger.info("Background scanning started")
    else:
        logger.info("Discord bot not configured (no token provided)")

    logger.info("Naked Forex API started successfully")

    yield

    # Shutdown
    logger.info("Shutting down Naked Forex API...")

    # Stop background scanning
    if _task_manager:
        await _task_manager.stop_scanning()

    # Stop Discord bot
    if _discord_service:
        await _discord_service.stop()

    # Close database
    await close_db()

    logger.info("Naked Forex API stopped")


def create_application() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        Configured FastAPI app
    """
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="FastAPI application implementing the Nick Shawn Naked Forex trading framework",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        lifespan=lifespan
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register exception handlers
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)

    # Include routers
    app.include_router(health.router, prefix=settings.api_prefix)
    app.include_router(auth.router, prefix=settings.api_prefix)
    app.include_router(analysis.router, prefix=settings.api_prefix)
    app.include_router(signals.router, prefix=settings.api_prefix)
    app.include_router(trades.router, prefix=settings.api_prefix)
    app.include_router(visualization.router, prefix=settings.api_prefix)

    # Root endpoint
    @app.get("/")
    async def root():
        """Root endpoint with API information."""
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "status": "running",
            "docs": "/docs",
            "health": f"{settings.api_prefix}/health"
        }

    return app


# Create the application instance
app = create_application()


# Export services for testing/external access
def get_pattern_service() -> PatternDetectionService:
    """Get the global pattern service instance."""
    global _pattern_service
    if _pattern_service is None:
        _pattern_service = PatternDetectionService()
    return _pattern_service


def get_discord_service() -> DiscordBotService | None:
    """Get the global Discord service instance."""
    return _discord_service


def get_task_manager() -> BackgroundTaskManager | None:
    """Get the global task manager instance."""
    return _task_manager


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )
