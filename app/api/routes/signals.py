"""
Signal detection routes.

Provides endpoints for detecting trading signals including
Big Wick, Three Pulse, and A+ setups.
"""

from typing import Annotated, List

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

    # Get current price for each ticker and filter to active signals only
    active_signals = {}

    for ticker in settings.default_tickers:
        try:
            # Fetch current market data to get latest price
            market_data = await data_service.fetch_data(
                ticker=ticker,
                timeframe=timeframe,
                lookback_bars=100  # Only need recent data
            )

            if not market_data.data:
                logger.warning(f"No data available for {ticker}")
                continue

            latest_close = market_data.data[-1].close
            latest_time = market_data.data[-1].timestamp

            # Detect all setups
            setups = await pattern_service.detect_a_plus_setups(
                ticker=ticker,
                timeframe=timeframe,
                lookback_bars=500,
                min_confidence=min_confidence
            )

            if not setups:
                continue

            # Filter to active setups only (price near zone OR very recent)
            active_setups = []
            for setup in setups:
                zone = setup.big_wick.sr_zone
                zone_lower, zone_upper = zone.price_range

                # Check if price is currently within zone bounds
                price_in_zone = zone_lower <= latest_close <= zone_upper

                # Check if setup is very recent (within last 2 bars)
                setup_age_minutes = (latest_time - setup.detected_at).total_seconds() / 60
                is_recent = setup_age_minutes <= 60  # Within last hour for 1h timeframe

                # Check if price is near zone (within 0.15%)
                price_near_zone = abs(latest_close - zone.level) / zone.level <= 0.0015

                # Include if price is at/near zone OR setup is very recent
                if price_in_zone or price_near_zone or is_recent:
                    active_setups.append(setup)

            if not active_setups:
                continue

            # Select only 1 signal per ticker: highest confidence, most recent
            # Sort by confidence (desc), then by detected_at (desc)
            active_setups.sort(
                key=lambda s: (s.combined_confidence, s.detected_at),
                reverse=True
            )

            # Keep only the best signal per ticker
            active_signals[ticker] = active_setups[0]

        except Exception as e:
            logger.error(f"Error scanning {ticker}: {e}")

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
