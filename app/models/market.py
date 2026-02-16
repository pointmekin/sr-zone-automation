"""
Market data models for OHLCV candlesticks and related data.

Uses Pydantic v2 for validation and computed fields.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator, computed_field
from enum import Enum

from app.config.constants import TimeFrame


class TickerType(str, Enum):
    """Types of trading instruments."""
    FOREX = "forex"
    COMMODITY = "commodity"
    INDEX = "index"
    CRYPTO = "crypto"


class OHLCV(BaseModel):
    """
    OHLCV (Open, High, Low, Close, Volume) candlestick data.

    Includes computed fields for technical analysis such as body size,
    wick sizes, and candle direction.
    """

    timestamp: datetime = Field(description="Candle timestamp")
    open: float = Field(..., gt=0, description="Opening price")
    high: float = Field(..., gt=0, description="Highest price")
    low: float = Field(..., gt=0, description="Lowest price")
    close: float = Field(..., gt=0, description="Closing price")
    volume: float = Field(..., ge=0, description="Trading volume")

    @field_validator("high")
    @classmethod
    def validate_high(cls, v: float, info) -> float:
        """Ensure high is the highest price."""
        if "low" in info.data and v < info.data["low"]:
            raise ValueError("high must be >= low")
        return v

    @computed_field
    @property
    def body_size(self) -> float:
        """Candlestick body size (absolute difference between close and open)."""
        return abs(self.close - self.open)

    @computed_field
    @property
    def upper_wick(self) -> float:
        """Upper wick size (high - max(open, close))."""
        return self.high - max(self.open, self.close)

    @computed_field
    @property
    def lower_wick(self) -> float:
        """Lower wick size (min(open, close) - low)."""
        return min(self.open, self.close) - self.low

    @computed_field
    @property
    def total_wick(self) -> float:
        """Total wick size (upper + lower wick)."""
        return self.upper_wick + self.lower_wick

    @computed_field
    @property
    def is_bullish(self) -> bool:
        """True if candle is bullish (close > open)."""
        return self.close > self.open

    @computed_field
    @property
    def is_bearish(self) -> bool:
        """True if candle is bearish (close < open)."""
        return self.close < self.open

    @computed_field
    @property
    def range_size(self) -> float:
        """Total range of the candle (high - low)."""
        return self.high - self.low

    @computed_field
    @property
    def wick_to_body_ratio(self) -> Optional[float]:
        """Ratio of total wick to body size."""
        if self.body_size == 0:
            return None
        return self.total_wick / self.body_size

    @computed_field
    @property
    def body_to_range_ratio(self) -> float:
        """Ratio of body size to total range."""
        if self.range_size == 0:
            return 0
        return self.body_size / self.range_size


class MarketData(BaseModel):
    """
    Collection of OHLCV candles for a specific ticker and timeframe.

    Used as the primary data structure for technical analysis.
    """

    ticker: str = Field(description="Ticker symbol (e.g., EURUSD=X)")
    timeframe: TimeFrame = Field(description="Chart timeframe")
    data: list[OHLCV] = Field(default_factory=list, description="OHLCV candlesticks")
    fetched_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When data was fetched"
    )

    @computed_field
    @property
    def candle_count(self) -> int:
        """Number of candles in the dataset."""
        return len(self.data)

    @computed_field
    @property
    def date_range(self) -> tuple[datetime, datetime]:
        """Start and end timestamps of the data."""
        if not self.data:
            return (datetime.utcnow(), datetime.utcnow())
        return (self.data[0].timestamp, self.data[-1].timestamp)

    @computed_field
    @property
    def high_price(self) -> float:
        """Highest price in the dataset."""
        if not self.data:
            return 0.0
        return max(c.high for c in self.data)

    @computed_field
    @property
    def low_price(self) -> float:
        """Lowest price in the dataset."""
        if not self.data:
            return 0.0
        return min(c.low for c in self.data)

    @computed_field
    @property
    def avg_volume(self) -> float:
        """Average trading volume."""
        if not self.data:
            return 0.0
        return sum(c.volume for c in self.data) / len(self.data)

    def get_candle(self, index: int) -> Optional[OHLCV]:
        """
        Get candle by index (negative indexing supported).

        Args:
            index: Candle index (0 = oldest, -1 = most recent)

        Returns:
            OHLCV candle or None if index is out of range
        """
        if not self.data:
            return None
        try:
            return self.data[index]
        except IndexError:
            return None

    def get_candles_between(
        self,
        start: datetime,
        end: datetime
    ) -> list[OHLCV]:
        """
        Get candles between two timestamps.

        Args:
            start: Start timestamp (inclusive)
            end: End timestamp (inclusive)

        Returns:
            List of OHLCV candles
        """
        return [
            c for c in self.data
            if start <= c.timestamp <= end
        ]


class AnalysisRequest(BaseModel):
    """Request model for market analysis endpoints."""

    ticker: str = Field(
        ...,
        description="Ticker symbol (e.g., EURUSD=X, XAUUSD=X)",
        min_length=1
    )
    timeframe: TimeFrame = Field(
        default=TimeFrame.M15,
        description="Chart timeframe"
    )
    lookback_bars: int = Field(
        default=500,
        ge=100,
        le=2000,
        description="Number of bars to analyze"
    )
    sr_sensitivity: Optional[float] = Field(
        default=None,
        ge=0.01,
        le=0.2,
        description="S/R zone sensitivity (overrides default)"
    )


class AnalysisResponse(BaseModel):
    """Response model for market analysis endpoints."""

    ticker: str
    timeframe: str
    timestamp: datetime
    candle_count: int
    date_range: tuple[datetime, datetime]
    high_price: float
    low_price: float
