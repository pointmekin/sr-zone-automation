"""
Risk management service implementing "The Mission" system.

Handles position sizing, risk-reward calculations, and trade validation.
"""

from decimal import Decimal
from typing import Optional, Tuple

from app.models.trades import TradeEntry, TradeDirection
from app.config.settings import get_settings
from app.config.constants import DEFAULT_RR_RATIO
from loguru import logger


class RiskManager:
    """
    Risk management service for position sizing and trade validation.

    Implements "The Mission" risk management principles:
    - Maximum 2% risk per trade
    - 1:1 risk-reward ratio default
    - Manual exit when price consolidates
    """

    def __init__(
        self,
        max_risk_per_trade: float | None = None,
        default_rr: float = DEFAULT_RR_RATIO
    ):
        """
        Initialize risk manager.

        Args:
            max_risk_per_trade: Maximum risk as fraction of capital (default: from settings)
            default_rr: Default risk-reward ratio
        """
        settings = get_settings()
        self.max_risk_per_trade = max_risk_per_trade or settings.max_risk_per_trade
        self.default_rr = default_rr

        logger.info(
            f"RiskManager initialized: max_risk={self.max_risk_per_trade*100}%, "
            f"default_rr={default_rr}"
        )

    def calculate_position_size(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss: float,
        risk_fraction: float | None = None
    ) -> float:
        """
        Calculate position size based on risk.

        Args:
            account_balance: Total account balance
            entry_price: Entry price
            stop_loss: Stop loss price
            risk_fraction: Risk as fraction of balance (default: max_risk_per_trade)

        Returns:
            Position size in units/lots

        Example:
            >>> rm = RiskManager()
            >>> size = rm.calculate_position_size(
            ...     account_balance=10000,
            ...     entry_price=1.1000,
            ...     stop_loss=1.0950
            ... )
        """
        risk_fraction = risk_fraction or self.max_risk_per_trade
        risk_amount = account_balance * risk_fraction

        # Risk per unit
        risk_per_unit = abs(entry_price - stop_loss)

        if risk_per_unit == 0:
            raise ValueError("Entry price and stop loss cannot be the same")

        position_size = risk_amount / risk_per_unit

        logger.info(
            f"Position size calculated: {position_size:.2f} units "
            f"(balance=${account_balance:.2f}, risk=${risk_amount:.2f})"
        )

        return position_size

    def calculate_take_profit(
        self,
        entry_price: float,
        stop_loss: float,
        direction: TradeDirection,
        risk_reward: float | None = None
    ) -> float:
        """
        Calculate take profit level based on risk-reward ratio.

        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            direction: Trade direction
            risk_reward: Risk-reward ratio (default: 1.0 for 1:1)

        Returns:
            Take profit price
        """
        risk_reward = risk_reward or self.default_rr
        risk = abs(entry_price - stop_loss)
        reward = risk * risk_reward

        if direction == TradeDirection.LONG:
            return entry_price + reward
        else:
            return entry_price - reward

    def validate_risk_parameters(
        self,
        trade: TradeEntry,
        account_balance: float
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate trade risk parameters.

        Checks:
        - Risk is within maximum allowed
        - Risk-reward ratio is acceptable
        - Position size is valid

        Args:
            trade: Trade entry to validate
            account_balance: Account balance

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check if risk is within limits
        if trade.risk_amount > account_balance * self.max_risk_per_trade:
            max_risk = account_balance * self.max_risk_per_trade
            return False, (
                f"Risk ${trade.risk_amount:.2f} exceeds maximum "
                f"of ${max_risk:.2f} ({self.max_risk_per_trade * 100}%)"
            )

        # Check risk-reward ratio
        actual_rr = abs(trade.take_profit - trade.entry_price) / abs(
            trade.stop_loss - trade.entry_price
        )
        if actual_rr < 0.8:
            return False, f"Risk-reward ratio {actual_rr:.2f} is below minimum 0.8"

        if actual_rr > 5.0:
            return False, f"Risk-reward ratio {actual_rr:.2f} exceeds maximum 5.0"

        # Check position size
        if trade.position_size <= 0:
            return False, "Position size must be positive"

        # Check that entry, SL, and TP are consistent with direction
        if trade.direction == TradeDirection.LONG:
            if trade.stop_loss >= trade.entry_price:
                return False, "Stop loss must be below entry for LONG trades"
            if trade.take_profit <= trade.entry_price:
                return False, "Take profit must be above entry for LONG trades"
        else:
            if trade.stop_loss <= trade.entry_price:
                return False, "Stop loss must be above entry for SHORT trades"
            if trade.take_profit >= trade.entry_price:
                return False, "Take profit must be below entry for SHORT trades"

        return True, None

    def suggest_manual_exit(
        self,
        entry_price: float,
        current_price: float,
        stop_loss: float,
        direction: TradeDirection,
        bars_since_entry: int,
        max_bars: int | None = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Suggest manual exit based on price action.

        Implements the "Mission FX" rule: exit if price consolidates
        against the trade for N bars (default: 5).

        Args:
            entry_price: Entry price
            current_price: Current market price
            stop_loss: Stop loss price
            direction: Trade direction
            bars_since_entry: Number of bars since entry
            max_bars: Maximum bars before suggesting exit (default: from settings)

        Returns:
            Tuple of (should_exit, reason)
        """
        settings = get_settings()
        max_bars = max_bars or settings.manual_exit_bars

        # Check if price is consolidating against trade
        if direction == TradeDirection.LONG:
            if current_price < entry_price:
                if bars_since_entry >= max_bars:
                    return (
                        True,
                        f"Price has been consolidating below entry for {bars_since_entry} bars"
                    )
        else:
            if current_price > entry_price:
                if bars_since_entry >= max_bars:
                    return (
                        True,
                        f"Price has been consolidating above entry for {bars_since_entry} bars"
                    )

        # Check if approaching stop loss (death spiral)
        risk_per_unit = abs(entry_price - stop_loss)
        if direction == TradeDirection.LONG:
            distance_to_sl = current_price - stop_loss
        else:
            distance_to_sl = stop_loss - current_price

        if distance_to_sl < (risk_per_unit * 0.3):  # Within 30% of SL
            return (
                True,
                f"Price within 30% of stop loss (${distance_to_sl:.5f} away)"
            )

        return False, None

    def calculate_lot_size(
        self,
        units: float,
        ticker: str = "EURUSD=X"
    ) -> float:
        """
        Convert position size to standard lots.

        Args:
            units: Position size in units
            ticker: Ticker symbol

        Returns:
            Position size in lots
        """
        # Standard lot size varies by instrument
        # For Forex: 1 standard lot = 100,000 units
        # For Gold (XAUUSD): 1 standard lot = 100 units

        if "XAU" in ticker:
            lot_size = 100
        else:
            lot_size = 100000

        lots = units / lot_size

        logger.info(f"Converted {units:.0f} units to {lots:.2f} lots")

        return lots

    def calculate_risk_amount(
        self,
        position_size: float,
        entry_price: float,
        stop_loss: float
    ) -> float:
        """
        Calculate risk amount in account currency.

        Args:
            position_size: Position size in units
            entry_price: Entry price
            stop_loss: Stop loss price

        Returns:
            Risk amount
        """
        risk_per_unit = abs(entry_price - stop_loss)
        risk_amount = position_size * risk_per_unit

        return risk_amount

    def suggest_scaling_in(
        self,
        initial_position_size: float,
        account_balance: float,
        entry_price: float,
        stop_loss: float
    ) -> dict:
        """
        Suggest scaling-in amounts for "smart scaling".

        The strategy advocates entering in 3 parts:
        1/3 at initial signal
        1/3 after confirmation
        1/3 after further validation

        Args:
            initial_position_size: Full target position size
            account_balance: Account balance
            entry_price: Entry price
            stop_loss: Stop loss price

        Returns:
            Dictionary with scaling amounts
        """
        # Calculate risk amounts
        total_risk = self.calculate_risk_amount(
            initial_position_size, entry_price, stop_loss
        )

        third_size = initial_position_size / 3
        third_risk = total_risk / 3

        return {
            'initial_size': third_size,
            'initial_risk': third_risk,
            'add_on_1_size': third_size,
            'add_on_1_risk': third_risk,
            'add_on_2_size': third_size,
            'add_on_2_risk': third_risk,
            'total_size': initial_position_size,
            'total_risk': total_risk
        }

    def calculate_expectancy(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float
    ) -> float:
        """
        Calculate mathematical expectancy.

        Expectancy = (Win Rate × Avg Win) - (Loss Rate × Avg Loss)

        Args:
            win_rate: Win rate as decimal (0.0 to 1.0)
            avg_win: Average win in R multiples
            avg_loss: Average loss in R multiples (typically 1.0)

        Returns:
            Expectancy per trade in R
        """
        loss_rate = 1.0 - win_rate
        expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)

        logger.info(
            f"Expectancy calculated: {expectancy:.3f}R "
            f"(win_rate={win_rate*100:.1f}%, avg_win={avg_win:.2f}R, avg_loss={avg_loss:.2f}R)"
        )

        return expectancy
