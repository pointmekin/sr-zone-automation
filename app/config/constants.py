"""
Trading constants and default parameters for the Naked Forex framework.

Based on Nick Shawn's "Naked Forex" methodology and "The Mission" risk management system.
"""

from enum import Enum
from typing import Final


# Timeframe constants
class TimeFrame(str, Enum):
    """Supported chart timeframes."""
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


# Signal type constants
class SignalType(str, Enum):
    """Types of trading signals."""
    BIG_WICK_BULLISH = "big_wick_bullish"
    BIG_WICK_BEARISH = "big_wick_bearish"
    THREE_PULSE_BULLISH = "three_pulse_bullish"
    THREE_PULSE_BEARISH = "three_pulse_bearish"
    A_PLUS_BUY = "a_plus_buy"
    A_PLUS_SELL = "a_plus_sell"


# Zone type constants
class ZoneType(str, Enum):
    """Types of support/resistance zones."""
    SUPPORT = "support"
    RESISTANCE = "resistance"


# SR Detection Profile presets
class SRDetectionProfile(str, Enum):
    """SR Detection preset profiles for different trading styles."""
    CONSERVATIVE = "conservative"  # Wider zones, fewer signals, higher confidence
    BALANCED = "balanced"  # Current working parameters (0.5 ATR zone width)
    AGGRESSIVE = "aggressive"  # Tighter zones, more signals, scalping-focused
    CUSTOM = "custom"  # User-defined parameters


# Trade direction constants
class TradeDirection(str, Enum):
    """Trade directions."""
    LONG = "long"
    SHORT = "short"


# Trade status constants
class TradeStatus(str, Enum):
    """Trade statuses."""
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


# Trade outcome constants
class TradeOutcome(str, Enum):
    """Trade outcomes."""
    WIN = "win"
    LOSS = "loss"
    BREAKEVEN = "breakeven"


# Trading session constants
class TradingSession(str, Enum):
    """Forex trading sessions."""
    ASIAN = "asian"
    LONDON = "london"
    NEW_YORK = "new_york"
    OVERLAP = "overlap"


# Default trading parameters
DEFAULT_LOOKBACK_BARS: Final[int] = 500
DEFAULT_SR_SENSITIVITY: Final[float] = 0.05  # 5%
DEFAULT_WICK_RATIO: Final[float] = 3.0
DEFAULT_RR_RATIO: Final[float] = 1.0
DEFAULT_MAX_RISK: Final[float] = 0.02  # 2%

# Zone detection thresholds
FRESH_ZONE_THRESHOLD_BARS: Final[int] = 100
MIN_PIVOT_LOOKBACK: Final[int] = 5
MIN_ZONE_TOUCHES: Final[int] = 2

# Improved SR Detection Parameters
USE_ATR_THRESHOLDS: Final[bool] = True
SENSITIVITY_ATR_MULTIPLIER: Final[float] = 0.3  # 0.3 ATR units for clustering (tighter)
ZONE_WIDTH_ATR_MULTIPLIER: Final[float] = 0.5  # 0.5 ATR units for zone width (wide buffer)
ATR_PERIOD: Final[int] = 14
MIN_PIVOT_DISTANCE_BARS: Final[int] = 5  # Minimum bars between pivots (reduced)
USE_VOLUME_CONFIRMATION: Final[bool] = False  # Disabled by default
VOLUME_CONFIRMATION_THRESHOLD: Final[float] = 0.5  # 50% of average volume
MAX_ZONE_AGE_BARS: Final[int] = 500
RECENCY_WEIGHT: Final[float] = 0.4
TOUCH_WEIGHT: Final[float] = 0.6
ROUND_NUMBER_PROXIMITY: Final[float] = 0.001  # 0.1% for round numbers
OVERLAP_REMOVAL_THRESHOLD: Final[float] = 0.7  # 70% overlap
MIN_ZONE_STRENGTH: Final[float] = 0.0  # No minimum by default

# Pattern detection thresholds
MANUAL_EXIT_BARS: Final[int] = 5
THREE_PULSE_TOLERANCE: Final[int] = 5

# Series of 10 parameters
SERIES_OF_10_SIZE: Final[int] = 10

# Confidence thresholds
A_PLUS_MIN_CONFIDENCE: Final[float] = 0.70  # 70%
HIGH_CONFIDENCE: Final[float] = 0.80  # 80%
MEDIUM_CONFIDENCE: Final[float] = 0.60  # 60%

# SR Detection Profile Presets
# Each preset defines complete parameter sets for different trading styles
SR_DETECTION_PRESETS: Final[dict[str, dict]] = {
    "conservative": {
        # Wider zones, fewer pivots, stricter filtering
        "use_atr_thresholds": True,
        "sensitivity_atr_multiplier": 0.4,  # Tighter clustering
        "zone_width_atr_multiplier": 0.7,  # Wider zone buffer
        "atr_period": 14,
        "min_pivot_distance_bars": 10,  # Fewer pivots
        "use_volume_confirmation": False,
        "overlap_removal_threshold": 0.7,
        "min_zone_strength": 0.4,  # Filter weak zones
        "recency_weight": 0.5,
        "touch_weight": 0.5,
        "round_number_proximity": 0.001,
        "min_pivot_lookback": 7,  # Larger lookback
        "min_zone_touches": 3,  # Require more touches
        "fresh_zone_threshold": 100,
    },
    "balanced": {
        # Current working values (default)
        "use_atr_thresholds": True,
        "sensitivity_atr_multiplier": 0.3,  # Current working value
        "zone_width_atr_multiplier": 0.5,  # Current working value
        "atr_period": 14,
        "min_pivot_distance_bars": 5,
        "use_volume_confirmation": False,
        "overlap_removal_threshold": 0.7,
        "min_zone_strength": 0.0,
        "recency_weight": 0.4,
        "touch_weight": 0.6,
        "round_number_proximity": 0.001,
        "min_pivot_lookback": 5,
        "min_zone_touches": 2,
        "fresh_zone_threshold": 100,
    },
    "aggressive": {
        # Tighter zones, more pivots, more signals
        "use_atr_thresholds": True,
        "sensitivity_atr_multiplier": 0.2,  # Very tight clustering
        "zone_width_atr_multiplier": 0.3,  # Narrower zones
        "atr_period": 14,
        "min_pivot_distance_bars": 3,  # More pivots
        "use_volume_confirmation": False,
        "overlap_removal_threshold": 0.8,  # Stricter overlap removal
        "min_zone_strength": 0.0,  # Accept all zones
        "recency_weight": 0.3,  # Less emphasis on recency
        "touch_weight": 0.7,
        "round_number_proximity": 0.001,
        "min_pivot_lookback": 3,  # Smaller lookback
        "min_zone_touches": 2,
        "fresh_zone_threshold": 50,  # Shorter fresh window
    },
}

# Forex pairs metadata
FOREX_PAIRS: Final[dict[str, dict]] = {
    "EURUSD=X": {
        "name": "EUR/USD",
        "pip_size": 0.0001,
        "session": "london_new_york",
        "spread_avg": 1.2,
    },
    "GBPUSD=X": {
        "name": "GBP/USD",
        "pip_size": 0.0001,
        "session": "london_new_york",
        "spread_avg": 1.5,
    },
    "USDJPY=X": {
        "name": "USD/JPY",
        "pip_size": 0.01,
        "session": "asian_london_new_york",
        "spread_avg": 1.1,
    },
    "AUDUSD=X": {
        "name": "AUD/USD",
        "pip_size": 0.0001,
        "session": "asian_new_york",
        "spread_avg": 1.3,
    },
    "USDCAD=X": {
        "name": "USD/CAD",
        "pip_size": 0.0001,
        "session": "new_york",
        "spread_avg": 1.4,
    },
    "XAUUSD=X": {
        "name": "Gold",
        "pip_size": 0.01,
        "session": "london_new_york",
        "spread_avg": 30.0,
    },
}

# Timeframe mappings for yfinance
TIMEFRAME_TO_YFINANCE: Final[dict[str, str]] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}

# Error messages
ERROR_MESSAGES: Final[dict[str, str]] = {
    "invalid_ticker": "Invalid ticker symbol. Must be a valid Forex pair or commodity.",
    "invalid_timeframe": f"Invalid timeframe. Must be one of: {[t.value for t in TimeFrame]}",
    "wick_ratio_too_low": f"Wick ratio must be >= {DEFAULT_WICK_RATIO} for Big Wick pattern",
    "stop_loss_invalid_long": "Stop loss must be below entry price for LONG trades",
    "stop_loss_invalid_short": "Stop loss must be above entry price for SHORT trades",
    "take_profit_invalid_long": "Take profit must be above entry price for LONG trades",
    "take_profit_invalid_short": "Take profit must be below entry price for SHORT trades",
    "risk_too_high": f"Risk per trade cannot exceed {DEFAULT_MAX_RISK * 100}% of account balance",
    "series_complete": "Series of 10 is complete. Start a new series to log more trades.",
}

# Success messages
SUCCESS_MESSAGES: Final[dict[str, str]] = {
    "trade_logged": "Trade logged successfully",
    "series_created": "New Series of 10 created",
    "series_completed": "Series of 10 completed successfully",
    "signal_detected": "A+ setup detected",
}

# Discord embed colors
DISCORD_COLORS: Final[dict[str, int]] = {
    "buy": 0x00FF00,  # Green
    "sell": 0xFF0000,  # Red
    "info": 0x0099FF,  # Blue
    "warning": 0xFFAA00,  # Orange
    "success": 0x00FF00,  # Green
}
