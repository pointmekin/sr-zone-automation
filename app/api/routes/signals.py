"""
Signal detection routes.

Provides endpoints for detecting trading signals including
Big Wick, Three Pulse, and A+ setups.
"""

import asyncio
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.deps import (
    get_current_user,
    get_pattern_service,
    get_optional_user,
    get_data_service
)
from app.models.signals import BigWickSignal, ThreePulseSignal, SignalResponse, ScanSummary, ScanAllSummaryResponse
from app.db.models.user import User
from app.services.pattern_detection import PatternDetectionService
from app.services.data_service import DataService
from loguru import logger


router = APIRouter(prefix="/signals", tags=["signals"])


class TickerScanError(Exception):
    """Exception raised during ticker scan processing."""
    def __init__(self, ticker: str, stage: str, cause: Exception):
        self.ticker = ticker
        self.stage = stage  # 'fetch_current', 'detect_setups', 'filter'
        self.cause = cause
        super().__init__(f"Error scanning {ticker} at {stage}: {cause}")


router = APIRouter(prefix="/signals", tags=["signals"])


class SignalListResponse(BaseModel):
    """Response model for signal lists."""
    ticker: str
    timeframe: str
    signal_count: int
    buy_signals: int
    sell_signals: int
    signals: List


@router.post("/big-wick", response_model=SignalListResponse)
async def detect_big_wick_signals(
    ticker: str = Query(..., description="Ticker symbol (e.g., EURUSD=X)"),
    timeframe: str = Query(default="15m", description="Chart timeframe"),
    lookback_bars: int = Query(default=500, ge=100, le=2000, description="Lookback bars"),
    current_user: Annotated[User | None, Depends(get_optional_user)] = None,
    pattern_service: Annotated[PatternDetectionService, Depends(get_pattern_service)] = None
):
    """
    Detect Big Wick candlestick patterns at S/R zones.

    Returns list of Big Wick signals with entry, stop loss, and take profit levels.

    A valid Big Wick must:
    - Have wick_ratio >= 3.0 (configurable)
    - Occur at or near a known S/R zone
    - Be larger than preceding candles
    """
    if pattern_service is None:
        pattern_service = get_pattern_service()

    logger.info(f"Detecting Big Wick signals for {ticker} {timeframe}")

    signals = await pattern_service.detect_big_wick(
        ticker=ticker,
        timeframe=timeframe,
        lookback_bars=lookback_bars
    )

    buy_count = len([s for s in signals if s.is_bullish])
    sell_count = len([s for s in signals if s.is_bearish])

    logger.info(f"Found {len(signals)} Big Wick signals ({buy_count} buy, {sell_count} sell)")

    return SignalListResponse(
        ticker=ticker,
        timeframe=timeframe,
        signal_count=len(signals),
        buy_signals=buy_count,
        sell_signals=sell_count,
        signals=signals
    )


@router.post("/three-pulse", response_model=SignalListResponse)
async def detect_three_pulse_signals(
    ticker: str = Query(..., description="Ticker symbol"),
    timeframe: str = Query(default="15m", description="Chart timeframe"),
    lookback_bars: int = Query(default=500, ge=100, le=2000, description="Lookback bars"),
    current_user: Annotated[User | None, Depends(get_optional_user)] = None,
    pattern_service: Annotated[PatternDetectionService, Depends(get_pattern_service)] = None
):
    """
    Detect Three Pulse exhaustion patterns.

    Returns list of Three Pulse patterns with pulse counts and locations.

    The Three Pulse pattern consists of:
    1. Range/consolidation period
    2. First pulse (breakout)
    3. Second pulse (FOMO continuation)
    4. Third pulse (exhaustion/stop hunt)
    """
    if pattern_service is None:
        pattern_service = get_pattern_service()

    logger.info(f"Detecting Three Pulse signals for {ticker} {timeframe}")

    signals = await pattern_service.detect_three_pulse(
        ticker=ticker,
        timeframe=timeframe,
        lookback_bars=lookback_bars
    )

    buy_count = len([s for s in signals if s.is_bullish])
    sell_count = len([s for s in signals if s.is_bearish])

    logger.info(f"Found {len(signals)} Three Pulse signals ({buy_count} buy, {sell_count} sell)")

    return SignalListResponse(
        ticker=ticker,
        timeframe=timeframe,
        signal_count=len(signals),
        buy_signals=buy_count,
        sell_signals=sell_count,
        signals=signals
    )


@router.post("/a-setups", response_model=SignalListResponse)
async def detect_a_plus_setups(
    ticker: str = Query(..., description="Ticker symbol"),
    timeframe: str = Query(default="15m", description="Chart timeframe"),
    lookback_bars: int = Query(default=500, ge=100, le=2000, description="Lookback bars"),
    min_confidence: float = Query(default=0.7, ge=0.5, le=1.0, description="Minimum confidence"),
    current_user: Annotated[User | None, Depends(get_optional_user)] = None,
    pattern_service: Annotated[PatternDetectionService, Depends(get_pattern_service)] = None
):
    """
    Detect A+ setups: Fresh S/R zone + Three Pulse + Big Wick.

    This is the complete Naked Forex setup according to Nick Shawn.

    An A+ setup requires all three components:
    1. Fresh Support/Resistance zone
    2. Three Pulse exhaustion pattern
    3. Big Wick rejection candle

    Returns only high-confidence setups (>= min_confidence).
    """
    if pattern_service is None:
        pattern_service = get_pattern_service()

    logger.info(f"Detecting A+ setups for {ticker} {timeframe} (min_confidence={min_confidence})")

    setups = await pattern_service.detect_a_plus_setups(
        ticker=ticker,
        timeframe=timeframe,
        lookback_bars=lookback_bars,
        min_confidence=min_confidence
    )

    buy_count = len([s for s in setups if s.is_buy])
    sell_count = len([s for s in setups if s.is_sell])

    logger.info(f"Found {len(setups)} A+ setups ({buy_count} buy, {sell_count} sell)")

    return SignalListResponse(
        ticker=ticker,
        timeframe=timeframe,
        signal_count=len(setups),
        buy_signals=buy_count,
        sell_signals=sell_count,
        signals=setups
    )


async def _process_single_ticker_scan(
    ticker: str,
    timeframe: str,
    min_confidence: float,
    data_service: DataService,
    pattern_service: PatternDetectionService,
    semaphore: asyncio.Semaphore
) -> tuple[str, Optional[SignalResponse]]:
    """
    Process a single ticker scan for A+ setups.

    Args:
        ticker: Ticker symbol to scan
        timeframe: Chart timeframe
        min_confidence: Minimum confidence threshold
        data_service: Data service instance
        pattern_service: Pattern detection service instance
        semaphore: Semaphore for concurrency control

    Returns:
        Tuple of (ticker, setup) where setup is SignalResponse or None

    Raises:
        TickerScanError: If processing fails at any stage
    """
    async with semaphore:
        try:
            # Stage 1: Fetch current market data
            try:
                market_data = await data_service.fetch_data(
                    ticker=ticker,
                    timeframe=timeframe,
                    lookback_bars=100
                )
            except Exception as e:
                raise TickerScanError(ticker, 'fetch_current', e) from e

            if not market_data.data:
                logger.warning(f"No data available for {ticker}")
                return (ticker, None)

            latest_close = market_data.data[-1].close
            latest_time = market_data.data[-1].timestamp

            # Normalize timestamp to naive
            if latest_time.tzinfo is not None:
                latest_time = latest_time.replace(tzinfo=None)

            # Stage 2: Detect A+ setups
            try:
                setups = await pattern_service.detect_a_plus_setups(
                    ticker=ticker,
                    timeframe=timeframe,
                    lookback_bars=500,
                    min_confidence=min_confidence
                )
            except Exception as e:
                raise TickerScanError(ticker, 'detect_setups', e) from e

            if not setups:
                return (ticker, None)

            # Stage 3: Filter to active setups
            active_setups = []
            for setup in setups:
                zone = setup.big_wick.sr_zone
                zone_lower, zone_upper = zone.price_range

                # Check if price is currently within zone bounds
                price_in_zone = zone_lower <= latest_close <= zone_upper

                # Check if setup is very recent (within last hour)
                setup_age_minutes = (latest_time - setup.detected_at).total_seconds() / 60
                is_recent = setup_age_minutes <= 60

                # Check if price is near zone (proportional to zone width)
                # Use 1.5x zone half-width as "near" threshold for tradeable setups
                zone_half_width = (zone_upper - zone_lower) / 2
                price_near_zone = abs(latest_close - zone.level) <= zone_half_width * 1.5

                # Include if price is at/near zone OR setup is very recent
                if price_in_zone or price_near_zone or is_recent:
                    active_setups.append(setup)

            if not active_setups:
                return (ticker, None)

            # Stage 4: Select best signal per ticker
            active_setups.sort(
                key=lambda s: (s.combined_confidence, s.detected_at),
                reverse=True
            )

            logger.info(f"Successfully scanned {ticker}: {len(active_setups)} active setup(s)")
            return (ticker, active_setups[0])

        except TickerScanError:
            # Re-raise TickerScanError to be caught by gather
            raise
        except Exception as e:
            # Wrap any other exceptions
            raise TickerScanError(ticker, 'unknown', e) from e


@router.get("/scan-all")
async def scan_all_tickers(
    timeframe: str = Query(default="1h", description="Chart timeframe"),
    min_confidence: float = Query(default=0.7, ge=0.5, le=1.0),
    summary: bool = Query(default=True, description="Return simplified summary only (reduces noise)"),
    current_user: Annotated[User | None, Depends(get_optional_user)] = None,
    pattern_service: Annotated[PatternDetectionService, Depends(get_pattern_service)] = None,
    data_service: Annotated[DataService, Depends(get_data_service)] = None
):
    """
    Scan all default tickers for ACTIVE A+ setups only.

    **Returns only 1 signal per ticker** where:
    - Price is currently at or near the SR zone (within 0.15%)
    - OR the setup is very recent (within 1 hour)
    - Signals are sorted by confidence (highest first)

    This filters out historical noise and only shows tradeable setups.

    - **timeframe**: Chart timeframe (1m, 5m, 15m, 30m, 1h, 4h, 1d) - **default: 1h**
    - **min_confidence**: Minimum confidence threshold (0.5-1.0) - **default: 0.7**
    - **summary**: If true, returns simplified data (default: True)

    **Example response:**
    ```json
    {
      "timeframe": "1h",
      "min_confidence": 0.7,
      "total_signals": 2,
      "signals": [
        {
          "ticker": "EURUSD=X",
          "direction": "buy",
          "entry": 1.0852,
          "confidence": 0.78,
          "zone_level": 1.0850
        }
      ]
    }
    ```
    """
    if pattern_service is None:
        pattern_service = get_pattern_service()

    from app.config.settings import get_settings
    from datetime import timedelta
    settings = get_settings()

    # Semaphore for concurrency control (max 3 concurrent tickers)
    MAX_CONCURRENT_TICKERS = 3
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_TICKERS)

    # Create concurrent tasks for all tickers
    logger.info(f"Starting concurrent scan of {len(settings.default_tickers)} tickers (max {MAX_CONCURRENT_TICKERS} concurrent)")

    tasks = [
        _process_single_ticker_scan(
            ticker=ticker,
            timeframe=timeframe,
            min_confidence=min_confidence,
            data_service=data_service,
            pattern_service=pattern_service,
            semaphore=semaphore
        )
        for ticker in settings.default_tickers
    ]

    # Execute all tasks concurrently with exception handling
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results and handle errors
    active_signals = {}
    failed_tickers = []

    for result in results:
        if isinstance(result, Exception):
            # Handle TickerScanError or other exceptions
            logger.error(f"Ticker scan failed: {result}")
            if isinstance(result, TickerScanError):
                failed_tickers.append(f"{result.ticker} ({result.stage})")
            continue

        ticker, setup = result
        if setup:
            active_signals[ticker] = setup

    # Log summary
    successful = len(active_signals)
    failed = len(failed_tickers)
    logger.info(
        f"Concurrent scan complete: {successful} successful, {failed} failed. "
        f"Failed tickers: {', '.join(failed_tickers) if failed_tickers else 'None'}"
    )

    # Build response
    if summary:
        all_summaries = []
        buy_count = 0
        sell_count = 0
        high_conf_count = 0

        for ticker, setup in active_signals.items():
            summary = ScanSummary(
                ticker=ticker,
                timeframe=timeframe,
                signal_type=setup.signal_type,
                direction="buy" if setup.is_buy else "sell",
                entry_price=setup.big_wick.entry_price,
                stop_loss=setup.big_wick.stop_loss,
                take_profit=setup.big_wick.take_profit,
                risk_reward=setup.big_wick.risk_reward,
                confidence=setup.combined_confidence,
                zone_level=setup.big_wick.sr_zone.level,
                zone_strength=setup.big_wick.sr_zone.strength,
                detected_at=setup.detected_at
            )
            all_summaries.append(summary)

            if setup.is_buy:
                buy_count += 1
            else:
                sell_count += 1

            if setup.combined_confidence > 0.75:
                high_conf_count += 1

        return ScanAllSummaryResponse(
            timeframe=timeframe,
            min_confidence=min_confidence,
            total_signals=len(all_summaries),
            buy_signals=buy_count,
            sell_signals=sell_count,
            high_confidence_count=high_conf_count,
            signals=all_summaries
        )

    # Full mode: return complete data
    results = {}
    total_setups = 0

    for ticker, setup in active_signals.items():
        results[ticker] = {
            "count": 1,
            "buy": 1 if setup.is_buy else 0,
            "sell": 1 if setup.is_sell else 0,
            "setups": [setup]
        }
        total_setups += 1

    return {
        "timeframe": timeframe,
        "min_confidence": min_confidence,
        "total_setups": total_setups,
        "results": results,
        "note": "Only showing 1 best active signal per ticker (price at/near zone or recent setup)"
    }
