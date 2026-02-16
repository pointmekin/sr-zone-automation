"""
SQLAlchemy ORM models for Trade and TradeSeries.

Implements the Series of 10 tracking system with proper relationships.
"""

from datetime import datetime
from sqlalchemy import String, Float, Boolean, Integer, ForeignKey, DateTime, Enum as SQLEnum, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.config.constants import TradeDirection, TradeStatus, TradeOutcome


class TradeSeries(Base, TimestampMixin):
    """
    Series of 10 trades for performance tracking.

    A series represents a block of 10 trades as defined in "The Mission".
    """

    __tablename__ = "trade_series"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    # Series metadata
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Account state
    starting_balance: Mapped[float] = mapped_column(Float, nullable=False)
    target_r_profit: Mapped[float] = mapped_column(Float, default=2.0, nullable=False)

    # Series status
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Optional notes
    notes: Mapped[str | None] = mapped_column(Text)

    # Relationships
    trades: Mapped[list["Trade"]] = relationship(
        "Trade",
        back_populates="series",
        cascade="all, delete-orphan",
        order_by="Trade.entry_time.desc()"
    )

    def __repr__(self) -> str:
        return f"<TradeSeries(id={self.id}, user_id={self.user_id}, is_complete={self.is_complete})>"


class Trade(Base, TimestampMixin):
    """
    Individual trade record with full details.

    Stores all trade information including entry, exit, risk parameters,
    and setup quality metrics.
    """

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    series_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("trade_series.id"),
        nullable=False,
        index=True
    )

    # Trade identification
    ticker: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(
        SQLEnum(TradeDirection),
        nullable=False
    )

    # Entry parameters
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    entry_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True
    )

    # Exit parameters
    exit_price: Mapped[float | None] = mapped_column(Float)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[TradeOutcome | None] = mapped_column(SQLEnum(TradeOutcome))
    status: Mapped[TradeStatus] = mapped_column(
        SQLEnum(TradeStatus),
        default=TradeStatus.OPEN,
        nullable=False
    )

    # Risk parameters
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    take_profit: Mapped[float] = mapped_column(Float, nullable=False)
    position_size: Mapped[float] = mapped_column(Float, nullable=False)
    risk_amount: Mapped[float] = mapped_column(Float, nullable=False)
    risk_reward: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    # Calculated fields (stored for performance)
    r_profit: Mapped[float | None] = mapped_column(Float)
    profit_loss: Mapped[float | None] = mapped_column(Float)

    # Setup quality metrics (for auditing)
    was_fresh_zone: Mapped[bool] = mapped_column(Boolean, default=True)
    had_three_pulse: Mapped[bool] = mapped_column(Boolean, default=True)
    wick_ratio: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)

    # Notes
    notes: Mapped[str | None] = mapped_column(Text)

    # Relationships
    series: Mapped["TradeSeries"] = relationship(
        "TradeSeries",
        back_populates="trades"
    )

    def __repr__(self) -> str:
        return (
            f"<Trade(id={self.id}, ticker='{self.ticker}', "
            f"direction={self.direction}, outcome={self.outcome})>"
        )

    @property
    def is_winner(self) -> bool:
        """True if trade was a win."""
        return self.outcome == TradeOutcome.WIN

    @property
    def is_loser(self) -> bool:
        """True if trade was a loss."""
        return self.outcome == TradeOutcome.LOSS

    @property
    def is_breakeven(self) -> bool:
        """True if trade was breakeven."""
        return self.outcome == TradeOutcome.BREAKEVEN

    @property
    def is_a_plus_setup(self) -> bool:
        """True if trade met A+ setup criteria."""
        return (
            self.was_fresh_zone and
            self.had_three_pulse and
            self.wick_ratio is not None and
            self.wick_ratio >= 3.0
        )
