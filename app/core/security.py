"""
Security module for JWT authentication and password hashing.

Handles token creation, verification, and password management.
"""

import bcrypt
import hashlib
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.db.models.user import User
from loguru import logger


def _sha256_hash(password: str) -> str:
    """
    Pre-hash password with SHA-256 to avoid bcrypt's 72-byte limit.

    This is a security best practice recommended by NIST and allows
    passwords of any length.

    Args:
        password: Plain text password

    Returns:
        SHA-256 hashed password as hexadecimal string
    """
    return hashlib.sha256(password.encode()).hexdigest()

# Settings
settings = get_settings()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a hashed password.

    First hashes the password with SHA-256 to handle passwords
    longer than bcrypt's 72-byte limit, then verifies with bcrypt.

    Args:
        plain_password: Plain text password
        hashed_password: Hashed password from database

    Returns:
        True if password matches
    """
    # Pre-hash with SHA-256 to avoid bcrypt's 72-byte limit
    pre_hashed = _sha256_hash(plain_password)
    return bcrypt.checkpw(
        pre_hashed.encode(),
        hashed_password.encode()
    )


def get_password_hash(password: str) -> str:
    """
    Hash a password using SHA-256 + bcrypt.

    First hashes the password with SHA-256 to handle passwords
    longer than bcrypt's 72-byte limit, then applies bcrypt.

    Args:
        password: Plain text password

    Returns:
        Hashed password
    """
    # Pre-hash with SHA-256 to avoid bcrypt's 72-byte limit
    pre_hashed = _sha256_hash(password)
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pre_hashed.encode(), salt)
    return hashed.decode()


def create_access_token(
    data: dict,
    expires_delta: timedelta | None = None
) -> str:
    """
    Create a JWT access token.

    Args:
        data: Data to encode in the token (typically {"sub": user_id})
        expires_delta: Token expiration time (default: from settings)

    Returns:
        Encoded JWT token
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.access_token_expire_minutes
        )

    to_encode.update({"exp": expire})

    encoded_jwt = jwt.encode(
        to_encode,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm
    )

    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """
    Decode and verify a JWT token.

    Args:
        token: JWT token

    Returns:
        Decoded token payload or None if invalid
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.algorithm]
        )
        return payload
    except JWTError as e:
        logger.warning(f"Failed to decode token: {e}")
        return None


async def authenticate_user(
    db: AsyncSession,
    email: str,
    password: str
) -> User | None:
    """
    Authenticate a user by email and password.

    Args:
        db: Database session
        email: User email
        password: Plain text password

    Returns:
        User object if authentication successful, None otherwise
    """
    result = await db.execute(
        select(User).where(User.email == email)
    )
    user = result.scalar_one_or_none()

    if not user:
        return None

    if not verify_password(password, user.hashed_password):
        return None

    if not user.is_active:
        return None

    return user


async def get_current_user(
    token: str,
    db: AsyncSession
) -> User | None:
    """
    Get the current user from a JWT token.

    Args:
        token: JWT token
        db: Database session

    Returns:
        User object or None if token is invalid
    """
    payload = decode_access_token(token)

    if payload is None:
        return None

    user_id: str = payload.get("sub")
    if user_id is None:
        return None

    try:
        user_id_int = int(user_id)
    except ValueError:
        return None

    result = await db.execute(
        select(User).where(User.id == user_id_int)
    )
    user = result.scalar_one_or_none()

    return user


async def create_user(
    db: AsyncSession,
    email: str,
    password: str,
    full_name: str | None = None
) -> User:
    """
    Create a new user.

    Args:
        db: Database session
        email: User email
        password: Plain text password
        full_name: Optional full name

    Returns:
        Created user object
    """
    hashed_password = get_password_hash(password)

    user = User(
        email=email,
        hashed_password=hashed_password,
        full_name=full_name,
        is_active=True,
        is_superuser=False
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info(f"Created new user: {email}")

    return user


async def get_user_by_email(
    db: AsyncSession,
    email: str
) -> User | None:
    """
    Get a user by email.

    Args:
        db: Database session
        email: User email

    Returns:
        User object or None
    """
    result = await db.execute(
        select(User).where(User.email == email)
    )
    return result.scalar_one_or_none()


async def get_user_by_id(
    db: AsyncSession,
    user_id: int
) -> User | None:
    """
    Get a user by ID.

    Args:
        db: Database session
        user_id: User ID

    Returns:
        User object or None
    """
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    return result.scalar_one_or_none()


class TokenData:
    """Token data model."""

    def __init__(self, user_id: int | None = None):
        self.user_id = user_id
