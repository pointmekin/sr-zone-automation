"""
SQLAlchemy ORM model for User authentication.

Stores user credentials and profile information.
"""

from datetime import datetime
from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """
    User model for authentication and authorization.

    Attributes:
        id: Primary key
        email: User email (unique, used for login)
        hashed_password: Bcrypt hashed password
        is_active: Whether user account is active
        is_superuser: Whether user has admin privileges
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Optional profile fields
    full_name: Mapped[str | None] = mapped_column(String(255))
    trading_account_balance: Mapped[float | None] = mapped_column(default=10000.0)

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}')>"
