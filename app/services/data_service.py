"""
Data acquisition service using yfinance.

Fetches OHLCV data for Forex pairs and commodities with caching support.
"""

from datetime import datetime, timedelta
from typing import Optional, Union
import asyncio
from pathlib import Path

import yfinance as yf
import pandas as pd

from app.models.market import OHLCV, MarketData, TimeFrame
from app.config.settings import get_settings
from loguru import logger


class DataService:
    """
    Service for fetching market data from yfinance.

    Provides caching, async support, and automatic DataFrame to OHLCV conversion.
    """

    def __init__(self, cache_dir: Optional[str] = None):
        """
        Initialize the data service.

        Args:
            cache_dir: Directory for caching data (default: from settings)
        """
        settings = get_settings()
        self.cache_dir = Path(cache_dir or settings.yfinance_cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache for recently fetched data
        self._memory_cache: dict[str, pd.DataFrame] = {}

        logger.info(f"DataService initialized with cache_dir: {self.cache_dir}")

    async def fetch_data(
        self,
        ticker: str,
        timeframe: str = "15m",
        lookback_bars: int = 500,
        use_cache: bool = True
    ) -> MarketData:
        """
        Fetch OHLCV data from yfinance.

        Args:
            ticker: Ticker symbol (e.g., EURUSD=X, XAUUSD=X)
            timeframe: Chart timeframe (1m, 5m, 15m, 30m, 1h, 4h, 1d)
            lookback_bars: Number of bars to fetch
            use_cache: Use cached data if available

        Returns:
            MarketData object with OHLCV candles
        """
        cache_key = f"{ticker}_{timeframe}_{lookback_bars}"

        # Check memory cache
        if use_cache and cache_key in self._memory_cache:
            logger.debug(f"Using cached data for {cache_key}")
            df = self._memory_cache[cache_key]
        else:
            # Calculate start date based on timeframe and lookback
            interval = self._timeframe_to_interval(timeframe)
            start_date = self._calculate_start_date(interval, lookback_bars)

            logger.info(f"Fetching {ticker} data: {timeframe} from {start_date}")

            # Fetch data in a thread pool to avoid blocking
            df = await asyncio.to_thread(
                self._fetch_yfinance_data,
                ticker,
                interval,
                start_date
            )

            # Store in memory cache
            if use_cache and not df.empty:
                self._memory_cache[cache_key] = df
                # Limit cache size
                if len(self._memory_cache) > 20:
                    self._memory_cache.pop(next(iter(self._memory_cache)))

        if df.empty:
            logger.warning(f"No data received for {ticker}")
            return MarketData(
                ticker=ticker,
                timeframe=TimeFrame(timeframe),
                data=[],
                fetched_at=datetime.utcnow()
            )

        # Convert DataFrame to OHLCV objects
        ohlcv_list = self._df_to_ohlcv(df)

        return MarketData(
            ticker=ticker,
            timeframe=TimeFrame(timeframe),
            data=ohlcv_list,
            fetched_at=datetime.utcnow()
        )

    def _fetch_yfinance_data(
        self,
        ticker: str,
        interval: str,
        start_date: datetime
    ) -> pd.DataFrame:
        """
        Fetch data from yfinance (synchronous).

        Args:
            ticker: Ticker symbol
            interval: yfinance interval string
            start_date: Start date for data

        Returns:
            DataFrame with OHLCV data
        """
        try:
            ticker_obj = yf.Ticker(ticker)
            df = ticker_obj.history(
                start=start_date,
                interval=interval,
                auto_adjust=False,  # Keep raw prices
                prepost=False
            )
            return df
        except Exception as e:
            logger.error(f"Error fetching data for {ticker}: {e}")
            return pd.DataFrame()

    def _timeframe_to_interval(self, timeframe: str) -> str:
        """
        Convert timeframe string to yfinance interval format.

        Args:
            timeframe: Timeframe string (e.g., "15m", "1h", "4h")

        Returns:
            yfinance interval string
        """
        mapping = {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1h": "1h",
            "4h": "4h",
            "1d": "1d"
        }
        return mapping.get(timeframe, "1d")

    def _calculate_start_date(self, interval: str, bars: int) -> datetime:
        """
        Calculate start date based on interval and number of bars.

        Uses a multiplier to account for non-trading hours and weekends.

        Args:
            interval: yfinance interval string
            bars: Number of bars desired

        Returns:
            Start datetime
        """
        # Approximate bars per period (with buffer for non-trading hours)
        multipliers = {
            "1m": 2,    # Forex is 5 days/week, ~24 hours/day
            "5m": 2,
            "15m": 2,
            "30m": 2,
            "1h": 24,   # 1 day = 24 bars, but weekends closed
            "4h": 6,    # 4h bars: ~6 per day, 5 days/week
            "1d": 2     # 5 days/week, use 2x for weekends
        }

        multiplier = multipliers.get(interval, 2)

        # Calculate period in minutes
        period_minutes = self._interval_to_minutes(interval)
        total_minutes = period_minutes * bars * multiplier

        return datetime.utcnow() - timedelta(minutes=total_minutes)

    def _interval_to_minutes(self, interval: str) -> int:
        """Convert interval string to minutes."""
        if interval == "1d":
            return 1440  # 24 * 60

        unit = interval[-1]
        value = int(interval[:-1])

        if unit == "m":
            return value
        elif unit == "h":
            return value * 60
        else:
            return 1440  # Default to daily

    def _df_to_ohlcv(self, df: pd.DataFrame) -> list[OHLCV]:
        """
        Convert pandas DataFrame to list of OHLCV objects.

        Args:
            df: DataFrame with columns: Open, High, Low, Close, Volume

        Returns:
            List of OHLCV objects
        """
        ohlcv_list = []

        for timestamp, row in df.iterrows():
            # Convert timestamp to datetime
            if isinstance(timestamp, pd.Timestamp):
                ts = timestamp.to_pydatetime()
            else:
                ts = timestamp

            try:
                ohlcv = OHLCV(
                    timestamp=ts,
                    open=float(row['Open']),
                    high=float(row['High']),
                    low=float(row['Low']),
                    close=float(row['Close']),
                    volume=float(row['Volume'])
                )
                ohlcv_list.append(ohlcv)
            except (ValueError, KeyError) as e:
                logger.warning(f"Skipping invalid candle at {timestamp}: {e}")
                continue

        return ohlcv_list

    def clear_cache(self) -> None:
        """Clear the memory cache."""
        self._memory_cache.clear()
        logger.info("Memory cache cleared")

    async def fetch_multiple(
        self,
        tickers: list[str],
        timeframe: str = "15m",
        lookback_bars: int = 500
    ) -> dict[str, MarketData]:
        """
        Fetch data for multiple tickers concurrently.

        Args:
            tickers: List of ticker symbols
            timeframe: Chart timeframe
            lookback_bars: Number of bars to fetch

        Returns:
            Dictionary mapping ticker to MarketData
        """
        tasks = [
            self.fetch_data(ticker, timeframe, lookback_bars)
            for ticker in tickers
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        market_data_dict = {}
        for ticker, result in zip(tickers, results):
            if isinstance(result, Exception):
                logger.error(f"Error fetching {ticker}: {result}")
            else:
                market_data_dict[ticker] = result

        return market_data_dict
