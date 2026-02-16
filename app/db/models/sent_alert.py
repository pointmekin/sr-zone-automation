"""
SQLAlchemy ORM model for tracking sent Discord alerts.

Prevents duplicate alerts for the same trade setup by storing
alert history in the database.
"""

from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SentAlert(Base, TimestampMixin):
    """
    Tracks Discord alerts that have been sent for trade setups.

    This model enables persistent deduplication of alerts across
    server restarts by storing each unique setup that has been
    alerted.
    """

    __tablename__ = "sent_alerts"

    # Unique identifier for this alert record
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Setup identifying fields (the "key" components)
    ticker: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    candle_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True
    )
    entry_price: Mapped[str] = mapped_column(String(20), nullable=False)  # Stored as string for precision
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # 'buy' or 'sell'

    # Confidence level at time of alert
    confidence: Mapped[float | None] = mapped_column(default=None)

    # Whether this alert was successfully sent
    sent_successfully: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Create a unique constraint on the identifying fields
    __table_args__ = (
        UniqueConstraint(
            'ticker', 'timeframe', 'candle_timestamp', 'entry_price', 'direction',
            name='uq_sent_alerts_setup_key'
        ),
        Index('idx_sent_alerts_ticker_time', 'ticker', 'candle_timestamp'),
        Index('idx_sent_alerts_created', 'created_at'),
    )

    def __repr__(self) -> str:
        return (
            f"<SentAlert(id={self.id}, ticker='{self.ticker}', "
            f"timeframe='{self.timeframe}', direction='{self.direction}')>"
        )

    @classmethod
    def create_key_components(cls, setup) -> dict:
        """
        Extract key components from a SignalResponse setup.

        Args:
            setup: SignalResponse setup object

        Returns:
            Dictionary with ticker, timeframe, candle_timestamp, entry_price, direction
        """
        return {
            'ticker': setup.big_wick.ticker,
            'timeframe': setup.big_wick.timeframe,
            'candle_timestamp': setup.big_wick.timestamp,
            'entry_price': f"{setup.big_wick.entry_price:.5f}",
            'direction': 'buy' if setup.is_buy else 'sell',
            'confidence': setup.combined_confidence,
        }

    @property
    def setup_key(self) -> str:
        """
        Generate the unique setup key string.

        Returns:
            String representation of the unique setup
        """
        return (
            f"{self.ticker}|{self.timeframe}|"
            f"{self.candle_timestamp.isoformat()}|"
            f"{self.entry_price}|{self.direction}"
        )
