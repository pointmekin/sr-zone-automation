"""
Dependency injection for FastAPI routes.

Provides factory functions for injecting services and dependencies.
"""

from typing import AsyncGenerator

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings, Settings
from app.db.session import get_db
from app.db.models.user import User
from app.core.security import get_current_user as get_current_user_raw
from app.services.data_service import DataService
from app.services.sr_detection import SRDetectionService
from app.services.pattern_detection import PatternDetectionService
from app.services.risk_manager import RiskManager
from app.services.trade_journal import TradeJournalService
from app.services.visualization_service import VisualizationService
from loguru import logger


# Security
security = HTTPBearer()

# Global settings instance (cached)
_settings_cache: Settings | None = None


# Settings dependency
def get_app_settings() -> Settings:
    """Get application settings (cached singleton)."""
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = get_settings()
    return _settings_cache


# Database dependency (from db/session.py)
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    async for session in get_db():
        yield session


# Authentication dependency
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db_session)
) -> User:
    """
    Get the current authenticated user from JWT token.

    Raises:
        HTTPException: If token is invalid or user not found

    Returns:
        Current user
    """
    token = credentials.credentials

    user = await get_current_user_raw(token, db)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )

    return user


# Optional authentication (doesn't raise if no token provided)
async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        HTTPBearer(auto_error=False)
    ),
    db: AsyncSession = Depends(get_db_session)
) -> User | None:
    """
    Get the current user if authenticated, otherwise None.

    Returns:
        User object or None
    """
    if credentials is None:
        return None

    token = credentials.credentials
    return await get_current_user_raw(token, db)


# Service dependencies
async def get_data_service(
    settings: Settings = Depends(get_app_settings)
) -> DataService:
    """Get data service instance."""
    return DataService(cache_dir=settings.yfinance_cache_dir)


async def get_sr_service(
    settings: Settings = Depends(get_app_settings)
) -> SRDetectionService:
    """Get S/R detection service instance."""
    return SRDetectionService(
        sensitivity=settings.sr_sensitivity,
        min_touches=settings.min_zone_touches,
        lookback_pivots=settings.min_pivot_lookback
    )


async def get_pattern_service(
    settings: Settings = Depends(get_app_settings),
    sr_service: SRDetectionService = Depends(get_sr_service)
) -> PatternDetectionService:
    """Get pattern detection service instance."""
    return PatternDetectionService(
        wick_ratio=settings.wick_ratio,
        sr_service=sr_service
    )


async def get_risk_manager(
    settings: Settings = Depends(get_app_settings)
) -> RiskManager:
    """Get risk manager instance."""
    return RiskManager(
        max_risk_per_trade=settings.max_risk_per_trade,
        default_rr=settings.rr_target
    )


async def get_trade_journal(
    db: AsyncSession = Depends(get_db_session)
) -> TradeJournalService:
    """Get trade journal service instance."""
    return TradeJournalService(db_session=db)


async def get_viz_service() -> VisualizationService:
    """Get visualization service instance."""
    return VisualizationService()


# Rate limiting (optional, for future implementation)
async def check_rate_limit(
    user: User = Depends(get_optional_user)
) -> None:
    """
    Check rate limit for current user.

    Raises:
        HTTPException: If rate limit exceeded

    Note:
        Currently a placeholder. Implement with Redis for production.
    """
    settings = get_app_settings()

    if not settings.enable_rate_limit:
        return

    # TODO: Implement rate limiting with Redis
    # For now, just pass
    pass
