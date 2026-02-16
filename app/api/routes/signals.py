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
    get_optional_user
)
from app.models.signals import BigWickSignal, ThreePulseSignal, SignalResponse
from app.db.models.user import User
from app.services.pattern_detection import PatternDetectionService
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
    timeframe: str = Query(default="15m", description="Chart timeframe"),
    min_confidence: float = Query(default=0.7, ge=0.5, le=1.0),
    current_user: Annotated[User | None, Depends(get_optional_user)] = None,
    pattern_service: Annotated[PatternDetectionService, Depends(get_pattern_service)] = None
):
    """
    Scan all default tickers for A+ setups.

    Returns a summary of A+ setups found across all configured tickers.
    """
    if pattern_service is None:
        pattern_service = get_pattern_service()

    from app.config.settings import get_settings
    settings = get_settings()

    results = {}
    total_setups = 0

    for ticker in settings.default_tickers:
        try:
            setups = await pattern_service.detect_a_plus_setups(
                ticker=ticker,
                timeframe=timeframe,
                lookback_bars=500,
                min_confidence=min_confidence
            )

            if setups:
                results[ticker] = {
                    "count": len(setups),
                    "buy": len([s for s in setups if s.is_buy]),
                    "sell": len([s for s in setups if s.is_sell]),
                    "setups": setups
                }
                total_setups += len(setups)

        except Exception as e:
            logger.error(f"Error scanning {ticker}: {e}")
            results[ticker] = {"error": str(e)}

    return {
        "timeframe": timeframe,
        "min_confidence": min_confidence,
        "total_setups": total_setups,
        "results": results
    }
