#!/usr/bin/env python3
"""
Database initialization script.

Creates all database tables and optionally creates an admin user.
Usage: python scripts/init_db.py [--admin-email EMAIL] [--admin-password PASSWORD]
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from loguru import logger

from app.db.session import get_engine, get_session_maker
from app.db.models.user import User
from app.db.models.trade import Trade, TradeSeries as DBTradeSeries
from app.db.base import Base
from app.config.settings import get_settings
from app.core.security import get_password_hash, create_user


async def create_tables():
    """Create all database tables."""
    settings = get_settings()

    logger.info(f"Creating database tables: {settings.database_url}")

    engine = get_engine()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database tables created successfully")


async def create_admin_user(email: str, password: str):
    """
    Create an admin user.

    Args:
        email: Admin email address
        password: Admin password
    """
    settings = get_settings()

    # Check if user already exists
    engine = get_engine()
    async_session_maker = get_session_maker()

    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.email == email)
        )
        existing_user = result.scalar_one_or_none()

        if existing_user:
            logger.info(f"Admin user already exists: {email}")
            return existing_user

        # Create admin user
        admin = User(
            email=email,
            hashed_password=get_password_hash(password),
            full_name="Admin",
            is_active=True,
            is_superuser=True,
            trading_account_balance=10000.0
        )

        session.add(admin)
        await session.commit()
        await session.refresh(admin)

        logger.info(f"Admin user created: {email} (ID: {admin.id})")

        return admin


async def main():
    """Main initialization function."""
    import argparse

    parser = argparse.ArgumentParser(description="Initialize Naked Forex database")
    parser.add_argument("--admin-email", default=None, help="Admin user email")
    parser.add_argument("--admin-password", default=None, help="Admin user password")

    args = parser.parse_args()

    # Setup logging
    from app.config.logging_config import setup_logging
    setup_logging()

    logger.info("Starting database initialization...")

    # Create tables
    await create_tables()

    # Create admin user if credentials provided
    if args.admin_email and args.admin_password:
        await create_admin_user(args.admin_email, args.admin_password)
    else:
        logger.info("No admin credentials provided, skipping admin user creation")
        logger.info("To create an admin user later, use the API:")
        logger.info("  POST /api/v1/auth/register")

    logger.info("Database initialization complete!")


if __name__ == "__main__":
    asyncio.run(main())
