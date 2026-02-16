"""
Application configuration using Pydantic Settings.

Environment variables are loaded from .env file and can be overridden
by setting actual environment variables.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr, ConfigDict
from typing import List


class Settings(BaseSettings):
    """Application settings with environment-based configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Application
    app_name: str = Field(default="Naked Forex API", description="Application name")
    app_version: str = Field(default="0.1.0", description="Application version")
    debug: bool = Field(default=False, description="Debug mode")

    # API Configuration
    api_prefix: str = Field(default="/api/v1", description="API URL prefix")
    cors_origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:8000"],
        description="CORS allowed origins"
    )

    # Data Source Configuration
    yfinance_cache_dir: str = Field(default="./cache", description="yfinance cache directory")
    default_tickers: List[str] = Field(
        default=[
            "EURUSD=X",  # EUR/USD
            "GBPUSD=X",  # GBP/USD
            "USDJPY=X",  # USD/JPY
            "AUDUSD=X",  # AUD/USD
            "USDCAD=X",  # USD/CAD
            "XAUUSD=X",  # Gold
        ],
        description="Default ticker symbols to monitor"
    )

    # Trading Parameters - from Nick Shawn framework
    default_timeframe: str = Field(default="15m", description="Default chart timeframe")
    lookback_bars: int = Field(default=500, ge=100, le=2000, description="Number of bars to analyze")
    sr_sensitivity: float = Field(
        default=0.05,
        ge=0.01,
        le=0.2,
        description="S/R zone sensitivity (0.05 = 5% price difference)"
    )
    wick_ratio: float = Field(
        default=3.0,
        ge=2.0,
        le=10.0,
        description="Minimum wick-to-body ratio for Big Wick pattern"
    )
    rr_target: float = Field(
        default=1.0,
        ge=0.5,
        le=5.0,
        description="Default risk-reward ratio (1.0 = 1:1)"
    )

    # Risk Management
    max_risk_per_trade: float = Field(
        default=0.02,
        ge=0.005,
        le=0.1,
        description="Maximum risk per trade as fraction of capital (0.02 = 2%)"
    )
    risk_free_rate: float = Field(
        default=0.02,
        ge=0.0,
        le=0.2,
        description="Risk-free rate for Sharpe ratio calculation"
    )

    # Zone Detection Parameters
    fresh_zone_threshold: int = Field(
        default=100,
        ge=10,
        le=500,
        description="Bars since last touch to consider zone fresh"
    )
    min_pivot_lookback: int = Field(
        default=5,
        ge=3,
        le=20,
        description="Lookback period for pivot point detection"
    )
    min_zone_touches: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Minimum touches to qualify as a zone"
    )

    # Pattern Detection Parameters
    manual_exit_bars: int = Field(
        default=5,
        ge=3,
        le=20,
        description="Bars of consolidation against trade before suggesting manual exit"
    )
    three_pulse_tolerance: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum bar difference for three-pulse detection"
    )

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./naked_forex.db",
        description="Database connection URL"
    )

    # Authentication
    secret_key: SecretStr = Field(
        default="CHANGE_THIS_IN_PRODUCTION_USE_PYTHON_SECRETS",
        description="Secret key for JWT token signing"
    )
    algorithm: str = Field(default="HS256", description="JWT algorithm")
    access_token_expire_minutes: int = Field(
        default=60 * 24 * 7,  # 7 days
        ge=5,
        le=60 * 24 * 30,  # 30 days
        description="JWT token expiration time in minutes"
    )

    # Discord Bot
    discord_token: SecretStr = Field(
        default="",
        description="Discord bot token for alerts"
    )
    discord_channel_id: int = Field(
        default=0,
        description="Discord channel ID for sending alerts"
    )
    scan_interval_minutes: int = Field(
        default=15,
        ge=1,
        le=60,
        description="Interval between automatic signal scans (minutes)"
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    log_file: str = Field(default="logs/app.log", description="Log file path")

    # API Rate Limiting (optional)
    enable_rate_limit: bool = Field(default=False, description="Enable rate limiting")
    rate_limit_requests: int = Field(default=100, ge=1, description="Max requests per window")
    rate_limit_window_seconds: int = Field(default=60, ge=1, description="Rate limit window in seconds")


# Global settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    """
    Get application settings (singleton pattern).

    Returns:
        Settings: Application settings instance
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
