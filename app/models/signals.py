"""
Signal models for trading signals and patterns.

Includes Support/Resistance zones, Big Wick signals, Three Pulse signals,
and combined A+ setup signals.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator, computed_field
from enum import Enum

from app.config.constants import ZoneType, SignalType


class SRZone(BaseModel):
    """
    Support or Resistance zone.

    Represents a horizontal price level where the market has historically
    shown respect (reversals or rejections).
    """

    level: float = Field(..., gt=0, description="Central price level of the zone")
    zone_type: ZoneType = Field(description="Support or Resistance zone")
    strength: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Zone strength/confidence (0-1)"
    )
    is_fresh: bool = Field(
        default=True,
        description="True if zone hasn't been tested recently"
    )
    touches: int = Field(
        default=0,
        ge=0,
        description="Number of times price has touched this zone"
    )
    last_touch_date: Optional[datetime] = Field(
        default=None,
        description="Timestamp of most recent touch"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When zone was detected"
    )

    # Zone width parameter (half-width on each side)
    zone_width_percent: float = Field(
        default=0.005,
        ge=0.001,
        le=0.02,
        description="Zone width as percentage (0.005 = 0.5% each side)"
    )

    @computed_field
    @property
    def price_range(self) -> tuple[float, float]:
        """Price range of the zone (lower_bound, upper_bound)."""
        half_width = self.level * self.zone_width_percent
        if self.zone_type == ZoneType.SUPPORT:
            # For support, zone extends below the level
            return (self.level - half_width, self.level + half_width * 0.5)
        else:
            # For resistance, zone extends above the level
            return (self.level - half_width * 0.5, self.level + half_width)

    @computed_field
    @property
    def zone_width(self) -> float:
        """Total width of the zone in price units."""
        lower, upper = self.price_range
        return upper - lower

    @computed_field
    @property
    def is_strong(self) -> bool:
        """True if zone has high strength (>0.7)."""
        return self.strength > 0.7

    def contains_price(self, price: float) -> bool:
        """
        Check if a price is within this zone.

        Args:
            price: Price to check

        Returns:
            True if price is within the zone
        """
        lower, upper = self.price_range
        return lower <= price <= upper

    def distance_to_price(self, price: float) -> float:
        """
        Calculate distance from price to zone center.

        Args:
            price: Price to check

        Returns:
            Distance in price units (positive if above, negative if below)
        """
        return price - self.level


class BigWickSignal(BaseModel):
    """
    Big Wick candlestick signal.

    A Big Wick is a rejection candle with a wick significantly larger
    than its body, occurring at a key S/R zone.
    """

    ticker: str = Field(description="Ticker symbol")
    timeframe: str = Field(description="Chart timeframe")
    timestamp: datetime = Field(description="When signal was detected")
    signal_type: SignalType = Field(description="Type of signal")
    entry_price: float = Field(..., gt=0, description="Suggested entry price")
    stop_loss: float = Field(..., gt=0, description="Suggested stop loss level")
    take_profit: float = Field(..., gt=0, description="Suggested take profit level")
    risk_reward: float = Field(..., ge=0, description="Risk-reward ratio")
    wick_ratio: float = Field(..., ge=0, description="Wick-to-body ratio")
    sr_zone: SRZone = Field(description="Associated S/R zone")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Signal confidence (0-1)"
    )

    # Candle details
    candle_open: float = Field(..., gt=0)
    candle_high: float = Field(..., gt=0)
    candle_low: float = Field(..., gt=0)
    candle_close: float = Field(..., gt=0)
    candle_volume: float = Field(..., ge=0)

    @field_validator("wick_ratio")
    @classmethod
    def validate_wick_ratio(cls, v: float) -> float:
        """Ensure wick ratio meets minimum threshold."""
        if v < 2.0:
            raise ValueError("Wick ratio must be >= 2.0 for Big Wick pattern")
        return v

    @field_validator("signal_type")
    @classmethod
    def validate_signal_type(cls, v: SignalType) -> SignalType:
        """Ensure signal type is valid for Big Wick."""
        valid_types = {
            SignalType.BIG_WICK_BULLISH,
            SignalType.BIG_WICK_BEARISH,
            SignalType.A_PLUS_BUY,
            SignalType.A_PLUS_SELL
        }
        if v not in valid_types:
            raise ValueError(f"Signal type must be one of {valid_types}")
        return v

    @computed_field
    @property
    def is_bullish(self) -> bool:
        """True if this is a bullish (buy) signal."""
        return self.signal_type in {
            SignalType.BIG_WICK_BULLISH,
            SignalType.A_PLUS_BUY
        }

    @computed_field
    @property
    def is_bearish(self) -> bool:
        """True if this is a bearish (sell) signal."""
        return self.signal_type in {
            SignalType.BIG_WICK_BEARISH,
            SignalType.A_PLUS_SELL
        }

    @computed_field
    @property
    def risk_amount(self) -> float:
        """Risk per unit in price terms."""
        return abs(self.entry_price - self.stop_loss)

    @computed_field
    @property
    def reward_amount(self) -> float:
        """Reward per unit in price terms."""
        return abs(self.take_profit - self.entry_price)

    @computed_field
    @property
    def is_high_confidence(self) -> bool:
        """True if confidence exceeds 0.7."""
        return self.confidence > 0.7


class ThreePulseSignal(BaseModel):
    """
    Three Pulse exhaustion pattern signal.

    The Three Pulse pattern describes market momentum moving in
    three distinct waves before exhaustion occurs.
    """

    ticker: str = Field(description="Ticker symbol")
    timeframe: str = Field(description="Chart timeframe")
    start_time: datetime = Field(description="Pattern start time")
    end_time: datetime = Field(description="Pattern end time (exhaustion)")
    signal_type: SignalType = Field(description="Bullish or bearish signal")
    pulse_count: int = Field(..., ge=3, description="Number of pulses detected")
    pulses: list[datetime] = Field(
        default_factory=list,
        description="Timestamps of each pulse"
    )
    exhaustion_point: float = Field(..., gt=0, description="Price at exhaustion point")
    sr_zone: SRZone = Field(description="Associated S/R zone")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Signal confidence (0-1)"
    )

    # Pattern details
    consolidation_start: Optional[datetime] = Field(
        default=None,
        description="Start of consolidation phase"
    )
    breakout_time: Optional[datetime] = Field(
        default=None,
        description="Breakout from consolidation"
    )

    @computed_field
    @property
    def is_bullish(self) -> bool:
        """True if this is a bullish signal."""
        return self.signal_type == SignalType.THREE_PULSE_BULLISH

    @computed_field
    @property
    def is_bearish(self) -> bool:
        """True if this is a bearish signal."""
        return self.signal_type == SignalType.THREE_PULSE_BEARISH

    @computed_field
    @property
    def pattern_duration_hours(self) -> float:
        """Duration of the pattern in hours."""
        delta = self.end_time - self.start_time
        return delta.total_seconds() / 3600

    @computed_field
    @property
    def is_three_pulses(self) -> bool:
        """True if exactly three pulses detected."""
        return self.pulse_count == 3


class SignalResponse(BaseModel):
    """
    Combined A+ setup signal response.

    An A+ setup requires:
    1. Fresh S/R zone
    2. Three Pulse exhaustion pattern
    3. Big Wick rejection candle
    """

    signal_type: SignalType = Field(description="Type of A+ setup")
    big_wick: BigWickSignal = Field(description="Big Wick component")
    three_pulse: ThreePulseSignal = Field(description="Three Pulse component")
    combined_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Combined confidence score"
    )

    # Additional metadata
    detected_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When A+ setup was detected"
    )
    notes: Optional[str] = Field(
        default=None,
        description="Additional notes about the setup"
    )

    @field_validator("signal_type")
    @classmethod
    def validate_signal_type(cls, v: SignalType) -> SignalType:
        """Ensure signal type is valid for A+ setup."""
        if v not in {SignalType.A_PLUS_BUY, SignalType.A_PLUS_SELL}:
            raise ValueError("A+ setup must be A_PLUS_BUY or A_PLUS_SELL")
        return v

    @computed_field
    @property
    def is_buy(self) -> bool:
        """True if this is a buy setup."""
        return self.signal_type == SignalType.A_PLUS_BUY

    @computed_field
    @property
    def is_sell(self) -> bool:
        """True if this is a sell setup."""
        return self.signal_type == SignalType.A_PLUS_SELL

    @computed_field
    @property
    def is_high_confidence(self) -> bool:
        """True if combined confidence exceeds 0.7."""
        return self.combined_confidence > 0.7


class SignalListResponse(BaseModel):
    """Response model for listing multiple signals."""

    signals: list[SignalResponse] = Field(default_factory=list)
    total_count: int = Field(default=0, ge=0)
    buy_signals: int = Field(default=0, ge=0)
    sell_signals: int = Field(default=0, ge=0)
    high_confidence_count: int = Field(default=0, ge=0)

    @computed_field
    @property
    def has_signals(self) -> bool:
        """True if there are any signals."""
        return self.total_count > 0
