"""
Visualization routes.

Provides endpoints for generating interactive charts
and watchlist dashboards.
"""

from typing import Annotated, List

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from app.api.deps import (
    get_current_user,
    get_optional_user,
    get_viz_service
)
from app.db.models.user import User
from app.services.visualization_service import VisualizationService
from loguru import logger


router = APIRouter(prefix="/charts", tags=["visualization"])


@router.post("/generate", response_class=HTMLResponse)
async def generate_chart(
    ticker: str = Query(..., description="Ticker symbol (e.g., EURUSD=X)"),
    timeframe: str = Query(default="15m", description="Chart timeframe"),
    lookback_bars: int = Query(default=200, ge=50, le=1000, description="Lookback bars"),
    show_sr_zones: bool = Query(default=True, description="Show S/R zones"),
    show_signals: bool = Query(default=False, description="Show trade signals"),
    current_user: Annotated[User | None, Depends(get_optional_user)] = None,
    viz_service: Annotated[VisualizationService, Depends(get_viz_service)] = None
):
    """
    Generate an interactive Plotly chart with S/R zones and signals.

    Returns an HTML page with an interactive candlestick chart featuring:
    - OHLCV candlestick data
    - Volume bars
    - Support/Resistance zones (shaded rectangles)
    - Trade signals (optional)

    The chart uses Plotly's dark theme and supports zooming, panning,
    and hover tooltips.
    """
    if viz_service is None:
        viz_service = get_viz_service()

    logger.info(f"Generating chart for {ticker} {timeframe}")

    chart_html = await viz_service.generate_chart(
        ticker=ticker,
        timeframe=timeframe,
        lookback_bars=lookback_bars,
        show_sr_zones=show_sr_zones,
        show_signals=show_signals
    )

    return chart_html


@router.get("/watchlist", response_class=HTMLResponse)
async def generate_watchlist_charts(
    tickers: str | None = Query(None, description="Comma-separated ticker list"),
    timeframe: str = Query(default="15m", description="Chart timeframe"),
    current_user: Annotated[User | None, Depends(get_optional_user)] = None,
    viz_service: Annotated[VisualizationService, Depends(get_viz_service)] = None
):
    """
    Generate a watchlist dashboard with multiple charts.

    Creates a grid of charts for all specified tickers or the default
    watchlist. Uses a 2-column responsive layout.

    Default tickers include:
    - EURUSD=X (EUR/USD)
    - GBPUSD=X (GBP/USD)
    - USDJPY=X (USD/JPY)
    - AUDUSD=X (AUD/USD)
    - USDCAD=X (USD/CAD)
    - XAUUSD=X (Gold)

    Returns a complete HTML dashboard page.
    """
    if viz_service is None:
        viz_service = get_viz_service()

    # Parse tickers from query string
    ticker_list = None
    if tickers:
        ticker_list = [t.strip() for t in tickers.split(",")]

    logger.info(f"Generating watchlist: {ticker_list or 'default tickers'}")

    dashboard_html = await viz_service.generate_watchlist(
        tickers=ticker_list,
        timeframe=timeframe
    )

    return dashboard_html


@router.get("/chart-embed/{ticker}")
async def get_chart_embed(
    ticker: str,
    timeframe: str = "15m",
    current_user: Annotated[User | None, Depends(get_optional_user)] = None,
    viz_service: Annotated[VisualizationService, Depends(get_viz_service)] = None
):
    """
    Get chart embed code for a ticker.

    Returns HTML/JavaScript code that can be embedded in
    external websites or applications.
    """
    if viz_service is None:
        viz_service = get_viz_service()

    # Generate the chart URL
    chart_url = f"/api/v1/charts/generate?ticker={ticker}&timeframe={timeframe}"

    embed_code = f'''
<!-- Naked Forex Chart Embed -->
<iframe
    src="{chart_url}"
    width="100%"
    height="800"
    frameborder="0"
    style="border: 1px solid #333; border-radius: 8px;">
</iframe>
'''

    return {
        "ticker": ticker,
        "timeframe": timeframe,
        "embed_code": embed_code.strip(),
        "chart_url": chart_url
    }
