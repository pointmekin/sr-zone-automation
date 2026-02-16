"""
Trade journaling models for Series of 10 tracking.

Includes trade entry, response, and series statistics models
implementing "The Mission" risk management system.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field, field_validator, computed_field
from enum import Enum

from app.config.constants import (
    TradeDirection,
    TradeStatus,
    TradeOutcome,
    DEFAULT_RR_RATIO,
)


class TradeEntry(BaseModel):
    """
    Trade entry model for logging trades to the journal.

    Implements validation for stop loss and take profit placement
    according to trade direction.
    """

    series_id: int = Field(..., ge=1, description="Series of 10 ID")
    ticker: str = Field(..., min_length=1, description="Ticker symbol")
    direction: TradeDirection = Field(description="LONG or SHORT")
    entry_price: float = Field(..., gt=0, description="Entry price")
    stop_loss: float = Field(..., gt=0, description="Stop loss price")
    take_profit: float = Field(..., gt=0, description="Take profit price")
    position_size: float = Field(
        ...,
        gt=0,
        description="Position size in lots/units"
    )
    risk_amount: float = Field(..., gt=0, description="Risk amount in account currency")
    risk_reward: float = Field(
        default=DEFAULT_RR_RATIO,
        gt=0,
        description="Risk-reward ratio (1.0 = 1:1)"
    )

    # Optional fields
    entry_time: datetime = Field(
        default_factory=datetime.utcnow,
        description="Entry timestamp"
    )
    exit_price: Optional[float] = Field(
        default=None,
        description="Exit price (when trade is closed)"
    )
    exit_time: Optional[datetime] = Field(
        default=None,
        description="Exit timestamp"
    )
    outcome: Optional[TradeOutcome] = Field(
        default=None,
        description="Trade outcome: win, loss, or breakeven"
    )
    status: TradeStatus = Field(
        default=TradeStatus.OPEN,
        description="Trade status"
    )
    notes: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Trade notes"
    )

    # Setup quality metrics (for auditing)
    was_fresh_zone: bool = Field(
        default=True,
        description="Was the S/R zone fresh?"
    )
    had_three_pulse: bool = Field(
        default=True,
        description="Was there a Three Pulse pattern?"
    )
    wick_ratio: Optional[float] = Field(
        default=None,
        ge=0,
        description="Actual wick ratio of entry candle"
    )
    confidence: Optional[float] = Field(
        default=None,
        ge=0,
        le=1,
        description="Setup confidence score"
    )

    @field_validator("stop_loss")
    @classmethod
    def validate_stop_loss(cls, v: float, info) -> float:
        """Validate stop loss placement based on direction."""
        direction = info.data.get("direction")
        entry = info.data.get("entry_price")

        if direction and entry:
            if direction == TradeDirection.LONG and v >= entry:
                raise ValueError("Stop loss must be below entry price for LONG trades")
            if direction == TradeDirection.SHORT and v <= entry:
                raise ValueError("Stop loss must be above entry price for SHORT trades")

        return v

    @field_validator("take_profit")
    @classmethod
    def validate_take_profit(cls, v: float, info) -> float:
        """Validate take profit placement based on direction."""
        direction = info.data.get("direction")
        entry = info.data.get("entry_price")

        if direction and entry:
            if direction == TradeDirection.LONG and v <= entry:
                raise ValueError("Take profit must be above entry price for LONG trades")
            if direction == TradeDirection.SHORT and v >= entry:
                raise ValueError("Take profit must be below entry price for SHORT trades")

        return v

    @field_validator("risk_reward")
    @classmethod
    def validate_risk_reward(cls, v: float) -> float:
        """Ensure risk-reward ratio is reasonable."""
        if v < 0.5:
            raise ValueError("Risk-reward ratio must be at least 0.5")
        if v > 5.0:
            raise ValueError("Risk-reward ratio should not exceed 5.0")
        return v

    @computed_field
    @property
    def risk_per_unit(self) -> float:
        """Risk per unit in price terms."""
        return abs(self.entry_price - self.stop_loss)

    @computed_field
    @property
    def reward_per_unit(self) -> float:
        """Reward per unit in price terms."""
        return abs(self.take_profit - self.entry_price)

    @computed_field
    @property
    def actual_rr(self) -> float:
        """Actual risk-reward ratio based on entry/SL/TP."""
        if self.risk_per_unit == 0:
            return 0
        return self.reward_per_unit / self.risk_per_unit

    @computed_field
    @property
    def is_a_plus_setup(self) -> bool:
        """True if trade meets A+ setup criteria."""
        return (
            self.was_fresh_zone and
            self.had_three_pulse and
            self.wick_ratio is not None and
            self.wick_ratio >= 3.0
        )


class TradeResponse(TradeEntry):
    """
    Trade response model with additional computed fields.

    Includes calculated R profit and other derived metrics.
    """

    id: int = Field(..., ge=1, description="Trade ID")
    created_at: datetime = Field(description="When trade was logged")
    updated_at: datetime = Field(description="When trade was last updated")

    @computed_field
    @property
    def r_profit(self) -> Optional[float]:
        """
        Profit in R multiples.

        R = 1 means profit equal to risk (1:1 RR achieved)
        R = -1 means loss equal to risk (stopped out)
        """
        if not self.exit_price or not self.outcome:
            return None

        if self.direction == TradeDirection.LONG:
            price_change = self.exit_price - self.entry_price
        else:
            price_change = self.entry_price - self.exit_price

        risk_per_unit = self.risk_per_unit
        if risk_per_unit == 0:
            return None

        return price_change / risk_per_unit

    @computed_field
    @property
    def profit_loss(self) -> Optional[float]:
        """Profit/loss in account currency."""
        if not self.exit_price or not self.outcome:
            return None

        if self.direction == TradeDirection.LONG:
            price_change = self.exit_price - self.entry_price
        else:
            price_change = self.entry_price - self.exit_price

        return price_change * self.position_size

    @computed_field
    @property
    def pip_profit_loss(self) -> Optional[float]:
        """Profit/loss in pips (approximate)."""
        if not self.profit_loss:
            return None

        # Assume standard pip size for forex (adjust per pair as needed)
        pip_size = 0.0001
        if "JPY" in self.ticker or "XAU" in self.ticker:
            pip_size = 0.01

        return self.profit_loss / (self.position_size * pip_size) if self.position_size > 0 else 0

    @computed_field
    @property
    def is_winner(self) -> bool:
        """True if trade was a win."""
        return self.outcome == TradeOutcome.WIN

    @computed_field
    @property
    def is_loser(self) -> bool:
        """True if trade was a loss."""
        return self.outcome == TradeOutcome.LOSS

    @computed_field
    @property
    def duration_hours(self) -> Optional[float]:
        """Trade duration in hours."""
        if not self.exit_time:
            return None
        delta = self.exit_time - self.entry_time
        return delta.total_seconds() / 3600


class SeriesOfTen(BaseModel):
    """
    Series of 10 trades block for performance tracking.

    Implements the "Series of 10" evaluation system from "The Mission".
    """

    id: int = Field(..., ge=1, description="Series ID")
    user_id: int = Field(..., ge=1, description="User ID who owns this series")
    start_date: datetime = Field(description="Series start date")
    end_date: Optional[datetime] = Field(
        default=None,
        description="Series end date (when 10 trades completed)"
    )
    trades: list[TradeResponse] = Field(
        default_factory=list,
        max_length=10,
        description="List of trades in this series"
    )

    # Initial account state
    starting_balance: float = Field(
        ...,
        gt=0,
        description="Account balance at series start"
    )
    target_r_profit: float = Field(
        default=2.0,
        ge=0,
        description="Target R profit for the series"
    )

    @computed_field
    @property
    def trade_count(self) -> int:
        """Number of trades in the series."""
        return len(self.trades)

    @computed_field
    @property
    def is_complete(self) -> bool:
        """True if series has 10 trades."""
        return self.trade_count >= 10

    @computed_field
    @property
    def trades_remaining(self) -> int:
        """Number of trades remaining to complete the series."""
        return max(0, 10 - self.trade_count)

    @computed_field
    @property
    def completed_trades(self) -> list[TradeResponse]:
        """Trades that have been completed (have an outcome)."""
        return [t for t in self.trades if t.outcome is not None]

    @computed_field
    @property
    def win_count(self) -> int:
        """Number of winning trades."""
        return len([t for t in self.completed_trades if t.outcome == TradeOutcome.WIN])

    @computed_field
    @property
    def loss_count(self) -> int:
        """Number of losing trades."""
        return len([t for t in self.completed_trades if t.outcome == TradeOutcome.LOSS])

    @computed_field
    @property
    def breakeven_count(self) -> int:
        """Number of breakeven trades."""
        return len([t for t in self.completed_trades if t.outcome == TradeOutcome.BREAKEVEN])

    @computed_field
    @property
    def win_rate(self) -> float:
        """Win rate as a decimal (0.0 to 1.0)."""
        completed = len(self.completed_trades)
        if completed == 0:
            return 0.0
        return self.win_count / completed

    @computed_field
    @property
    def win_rate_percent(self) -> float:
        """Win rate as a percentage."""
        return self.win_rate * 100

    @computed_field
    @property
    def total_r_profit(self) -> float:
        """Total profit/loss in R multiples."""
        return sum([t.r_profit for t in self.completed_trades if t.r_profit is not None])

    @computed_field
    @property
    def expectancy(self) -> float:
        """Expected value per trade in R."""
        completed = len(self.completed_trades)
        if completed == 0:
            return 0.0
        return self.total_r_profit / completed

    @computed_field
    @property
    def is_profitable(self) -> bool:
        """True if series is profitable (total R > 0)."""
        return self.total_r_profit > 0

    @computed_field
    @property
    def a_plus_setup_count(self) -> int:
        """Number of A+ setups traded."""
        return len([t for t in self.trades if t.is_a_plus_setup])

    @computed_field
    @property
    def current_balance(self) -> Optional[float]:
        """Current account balance based on completed trades."""
        total_pnl = sum([t.profit_loss for t in self.completed_trades if t.profit_loss is not None])
        return self.starting_balance + total_pnl

    @computed_field
    @property
    def balance_change_percent(self) -> Optional[float]:
        """Percentage change in account balance."""
        if not self.current_balance:
            return None
        return ((self.current_balance - self.starting_balance) / self.starting_balance) * 100


class TradingStatistics(BaseModel):
    """Overall trading statistics across all series."""

    total_trades: int = Field(default=0, ge=0)
    total_series: int = Field(default=0, ge=0)
    completed_series: int = Field(default=0, ge=0)

    # Performance metrics
    overall_win_rate: float = Field(default=0.0, ge=0, le=1)
    total_r_profit: float = Field(default=0.0)
    overall_expectancy: float = Field(default=0.0)

    # Drawdown metrics
    max_drawdown: float = Field(default=0.0, ge=0)
    max_drawdown_percent: float = Field(default=0.0, ge=0)

    # Streaks
    current_streak: int = Field(default=0, description="Current win/loss streak")
    longest_win_streak: int = Field(default=0, ge=0)
    longest_loss_streak: int = Field(default=0, ge=0)

    # A+ setup tracking
    a_plus_setup_count: int = Field(default=0, ge=0)
    a_plus_win_rate: float = Field(default=0.0, ge=0, le=1)

    # Risk metrics
    total_risk_amount: float = Field(default=0.0, ge=0)
    total_profit_loss: float = Field(default=0.0)
    sharpe_ratio: Optional[float] = Field(default=None, description="Sharpe ratio")

    @computed_field
    @property
    def overall_win_rate_percent(self) -> float:
        """Overall win rate as a percentage."""
        return self.overall_win_rate * 100

    @computed_field
    @property
    def a_plus_win_rate_percent(self) -> float:
        """A+ setup win rate as a percentage."""
        return self.a_plus_win_rate * 100

    @computed_field
    @property
    def is_profitable(self) -> bool:
        """True if overall trading is profitable."""
        return self.total_r_profit > 0

    @computed_field
    @property
    def profit_factor(self) -> Optional[float]:
        """
        Profit factor (gross profit / gross loss).

        Values > 1.0 indicate profitability.
        """
        # This would require separate tracking of gross profit and loss
        # Placeholder for future implementation
        return None


class CreateSeriesRequest(BaseModel):
    """Request model for creating a new Series of 10."""

    starting_balance: float = Field(
        ...,
        gt=0,
        description="Initial account balance"
    )
    target_r_profit: float = Field(
        default=2.0,
        ge=0,
        description="Target R profit for this series"
    )
    notes: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Series notes"
    )


class UpdateTradeRequest(BaseModel):
    """Request model for updating a trade."""

    exit_price: Optional[float] = Field(default=None, gt=0)
    exit_time: Optional[datetime] = Field(default=None)
    outcome: Optional[TradeOutcome] = Field(default=None)
    status: Optional[TradeStatus] = Field(default=None)
    notes: Optional[str] = Field(default=None, max_length=1000)
