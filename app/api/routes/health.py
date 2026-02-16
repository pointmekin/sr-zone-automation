"""
Health check endpoint.

Provides a simple endpoint to verify the API is running.
"""

from datetime import datetime
from fastapi import APIRouter

from app.config.settings import get_settings

router = APIRouter()


@router.get("/health", tags=["health"])
async def health_check():
    """
    Health check endpoint.

    Returns:
        API status and version information
    """
    settings = get_settings()

    return {
        "status": "healthy",
        "app_name": settings.app_name,
        "version": settings.app_version,
        "timestamp": datetime.utcnow().isoformat()
    }
