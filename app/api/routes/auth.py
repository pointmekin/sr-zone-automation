"""
Authentication routes.

Handles user registration, login, and token management.
"""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user, get_app_settings
from app.core.security import (
    create_access_token,
    authenticate_user,
    create_user,
    get_user_by_email
)
from app.db.models.user import User
from loguru import logger


router = APIRouter(prefix="/auth", tags=["authentication"])


# Request/Response Models
class UserRegister(BaseModel):
    """User registration request."""
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str | None = Field(None, max_length=255)


class UserLogin(BaseModel):
    """User login request."""
    email: EmailStr
    password: str


class Token(BaseModel):
    """Token response."""
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """User response."""
    id: int
    email: str
    full_name: str | None
    is_active: bool
    trading_account_balance: float | None


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserRegister,
    db: Annotated[AsyncSession, Depends(get_db_session)]
):
    """
    Register a new user.

    - **email**: User email address (must be unique)
    - **password**: Password (min 8 characters)
    - **full_name**: Optional full name
    """
    # Check if user already exists
    existing_user = await get_user_by_email(db, user_data.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Create user
    user = await create_user(
        db,
        email=user_data.email,
        password=user_data.password,
        full_name=user_data.full_name
    )

    # Create access token
    access_token = create_access_token(data={"sub": str(user.id)})

    logger.info(f"New user registered: {user.email}")

    return Token(access_token=access_token)


@router.post("/login", response_model=Token)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db_session)]
):
    """
    Login with email and password.

    Uses OAuth2 password flow for compatibility with OpenAPI.
    """
    user = await authenticate_user(db, form_data.username, form_data.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": str(user.id)})

    logger.info(f"User logged in: {user.email}")

    return Token(access_token=access_token)


@router.post("/login/json", response_model=Token)
async def login_json(
    credentials: UserLogin,
    db: Annotated[AsyncSession, Depends(get_db_session)]
):
    """
    Login with JSON body.

    Alternative to OAuth2 password flow for API clients.
    """
    user = await authenticate_user(db, credentials.email, credentials.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": str(user.id)})

    logger.info(f"User logged in: {user.email}")

    return Token(access_token=access_token)


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: Annotated[User, Depends(get_current_user)]
):
    """
    Get current user information.

    Requires authentication.
    """
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
        trading_account_balance=current_user.trading_account_balance
    )
