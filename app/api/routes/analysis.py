"""
Market analysis routes.

Provides endpoints for detecting support/resistance zones
and fetching market data.
"""

from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from app.api.deps import (
    get_current_user,
    get_data_service,
    get_sr_service,
    get_optional_user
)
from app.models.market import AnalysisRequest, AnalysisResponse, TimeFrame
from app.models.signals import SRZone
from app.db.models.user import User
from app.services.data_service import DataService
from app.services.sr_detection import SRDetectionService
from loguru import logger


router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("/zones", response_model=List[SRZone])
async def detect_support_resistance(
    request: AnalysisRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    data_service: Annotated[DataService, Depends(get_data_service)],
    sr_service: Annotated[SRDetectionService, Depends(get_sr_service)]
):
    """
    Detect support and resistance zones for a given ticker.

    - **ticker**: Forex pair or commodity (e.g., EURUSD=X, XAUUSD=X)
    - **timeframe**: Chart timeframe (1m, 5m, 15m, 30m, 1h, 4h, 1d)
    - **lookback_bars**: Number of bars to analyze (default: 500)

    Returns a list of S/R zones sorted by strength.
    """
    logger.info(
        f"Detecting S/R zones for {request.ticker} "
        f"{request.timeframe} ({request.lookback_bars} bars)"
    )

    # Fetch market data
    market_data = await data_service.fetch_data(
        ticker=request.ticker,
        timeframe=request.timeframe,
        lookback_bars=request.lookback_bars
    )

    if not market_data.data:
        raise HTTPException(
            status_code=404,
            detail=f"No data available for {request.ticker}"
        )

    # Detect S/R zones with custom sensitivity
    zones = await sr_service.detect_zones(
        market_data,
        sensitivity=request.sr_sensitivity
    )

    logger.info(f"Found {len(zones)} S/R zones for {request.ticker}")

    return zones


@router.get("/ohlcv")
async def fetch_ohlcv_data(
    ticker: str,
    timeframe: TimeFrame = TimeFrame.M15,
    lookback_bars: int = 200,
    current_user: Annotated[User | None, Depends(get_optional_user)] = None,
    data_service: Annotated[DataService, Depends(get_data_service)] = None
):
    """
    Fetch OHLCV market data.

    - **ticker**: Forex pair or commodity
    - **timeframe**: Chart timeframe
    - **lookback_bars**: Number of bars to fetch
    """
    if data_service is None:
        data_service = get_data_service()

    market_data = await data_service.fetch_data(
        ticker=ticker,
        timeframe=timeframe.value,
        lookback_bars=lookback_bars
    )

    if not market_data.data:
        raise HTTPException(
            status_code=404,
            detail=f"No data available for {ticker}"
        )

    return {
        "ticker": market_data.ticker,
        "timeframe": market_data.timeframe.value,
        "candle_count": market_data.candle_count,
        "date_range": market_data.date_range,
        "high_price": market_data.high_price,
        "low_price": market_data.low_price,
        "data": [
            {
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume
            }
            for c in market_data.data
        ]
    }
