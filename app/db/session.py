"""
Database session management for SQLAlchemy with async support.

Uses aiosqlite for async SQLite operations and asyncpg for PostgreSQL.
"""

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import get_settings
from app.db.base import Base


# Global engine and session maker
_engine = None
_async_session_maker = None


def get_engine():
    """Get or create the database engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        # Use Postgres if configured, otherwise fall back to SQLite
        database_url = settings.postgres_url if settings.postgres_url else settings.database_url
        _engine = create_async_engine(
            database_url,
            echo=settings.debug,
            future=True
        )
    return _engine


def get_session_maker():
    """Get or create the async session maker."""
    global _async_session_maker
    if _async_session_maker is None:
        _async_session_maker = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False
        )
    return _async_session_maker


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency function to get a database session.

    Yields:
        AsyncSession: Database session

    Example:
        >>> @router.get("/trades")
        >>> async def get_trades(db: AsyncSession = Depends(get_db)):
        >>>     result = await db.execute(select(Trade))
        >>>     return result.scalars().all()
    """
    async_session_maker = get_session_maker()
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    Initialize the database by creating all tables.

    This should be called on application startup.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        # Import all models here to ensure they're registered with Base
        from app.db.models.user import User
        from app.db.models.trade import Trade, TradeSeries
        from app.db.models.sent_alert import SentAlert

        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """
    Close the database connection.

    This should be called on application shutdown.
    """
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        global _async_session_maker
        _async_session_maker = None
