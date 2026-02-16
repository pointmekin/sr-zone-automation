"""
Visualization service for generating interactive charts.

Uses Plotly to create candlestick charts with S/R zones and signals.
"""

from typing import Optional

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.models.market import MarketData
from app.models.signals import SRZone, BigWickSignal, SignalType
from app.services.data_service import DataService
from app.services.sr_detection import SRDetectionService
from app.config.settings import get_settings
from loguru import logger


class VisualizationService:
    """
    Service for generating interactive trading charts.

    Creates Plotly charts with:
    - Candlestick OHLCV data
    - S/R zones as shaded rectangles
    - Trade signals as annotations
    """

    def __init__(self):
        """Initialize visualization service."""
        self.data_service = DataService()
        self.sr_service = SRDetectionService()
        self.settings = get_settings()

        logger.info("VisualizationService initialized")

    async def generate_chart(
        self,
        ticker: str,
        timeframe: str = "15m",
        lookback_bars: int = 200,
        show_sr_zones: bool = True,
        show_signals: bool = True
    ) -> str:
        """
        Generate interactive Plotly chart with S/R zones and signals.

        Args:
            ticker: Ticker symbol
            timeframe: Chart timeframe
            lookback_bars: Number of bars to display
            show_sr_zones: Show support/resistance zones
            show_signals: Show trade signals

        Returns:
            HTML string with interactive chart
        """
        logger.info(f"Generating chart for {ticker} {timeframe}")

        # Fetch market data
        market_data = await self.data_service.fetch_data(
            ticker=ticker,
            timeframe=timeframe,
            lookback_bars=lookback_bars
        )

        if not market_data.data:
            return self._empty_chart(ticker, timeframe)

        # Detect S/R zones
        sr_zones = []
        if show_sr_zones:
            sr_zones = await self.sr_service.detect_zones(market_data)

        # Create figure
        fig = go.Figure()

        # Add candlestick chart
        timestamps = [c.timestamp for c in market_data.data]
        opens = [c.open for c in market_data.data]
        highs = [c.high for c in market_data.data]
        lows = [c.low for c in market_data.data]
        closes = [c.close for c in market_data.data]
        volumes = [c.volume for c in market_data.data]

        fig.add_trace(go.Candlestick(
            x=timestamps,
            open=opens,
            high=highs,
            low=lows,
            close=closes,
            name=f"{ticker} OHLCV",
            increasing_line_color='#00FF00',
            decreasing_line_color='#FF0000'
        ))

        # Add volume bars
        fig.add_trace(go.Bar(
            x=timestamps,
            y=volumes,
            name="Volume",
            marker_color='rgba(128, 128, 128, 0.3)',
            yaxis='y2'
        ))

        # Add S/R zones
        if show_sr_zones and sr_zones:
            for zone in sr_zones[:5]:  # Top 5 zones only
                zone_min, zone_max = zone.price_range

                color = 'rgba(255, 0, 0, 0.2)' if zone.zone_type.value == 'resistance' else 'rgba(0, 255, 0, 0.2)'

                fig.add_hrect(
                    y0=zone_min,
                    y1=zone_max,
                    fillcolor=color,
                    layer="below",
                    line_width=0,
                    annotation_text=(
                        f"{zone.zone_type.value.upper()}"
                        if zone.strength > 0.7 else None
                    ),
                    annotation_font_size=10,
                    annotation_font_color="white"
                )

        # Add signals (placeholder - would fetch from pattern detection)
        if show_signals:
            # TODO: Integrate with pattern detection service
            pass

        # Update layout
        fig.update_layout(
            title=f"Naked Forex Analysis: {ticker} ({timeframe})",
            xaxis_title="Time",
            yaxis_title="Price",
            xaxis_rangeslider_visible=False,
            height=800,
            template="plotly_dark",
            hovermode="x unified",
            yaxis2=dict(
                overlaying='y',
                side='right',
                showgrid=False,
                title="Volume"
            ),
            legend=dict(
                yanchor="top",
                y=0.99,
                xanchor="left",
                x=0.01
            )
        )

        # Return HTML
        return fig.to_html(include_plotlyjs='cdn')

    async def generate_watchlist(
        self,
        tickers: list[str] | None = None,
        timeframe: str = "15m"
    ) -> str:
        """
        Generate watchlist dashboard with multiple charts.

        Args:
            tickers: List of ticker symbols (default: from settings)
            timeframe: Chart timeframe

        Returns:
            HTML string with dashboard
        """
        if tickers is None:
            tickers = self.settings.default_tickers

        logger.info(f"Generating watchlist for {len(tickers)} tickers")

        # Generate individual charts
        charts = []
        for ticker in tickers:
            chart_html = await self.generate_chart(
                ticker=ticker,
                timeframe=timeframe,
                lookback_bars=200,
                show_sr_zones=True,
                show_signals=False  # Too cluttered for watchlist
            )
            charts.append((ticker, chart_html))

        # Combine into dashboard
        dashboard_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Naked Forex Watchlist</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    background-color: #1e1e1e;
                    color: #ffffff;
                    margin: 0;
                    padding: 20px;
                }}
                .dashboard {{
                    display: grid;
                    grid-template-columns: repeat(2, 1fr);
                    gap: 20px;
                }}
                .chart-container {{
                    background-color: #2d2d2d;
                    border-radius: 8px;
                    padding: 15px;
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
                }}
                h1 {{
                    text-align: center;
                    margin-bottom: 30px;
                }}
                @media (max-width: 1200px) {{
                    .dashboard {{
                        grid-template-columns: 1fr;
                    }}
                }}
            </style>
        </head>
        <body>
            <h1>📈 Naked Forex Watchlist - {timeframe} Timeframe</h1>
            <div class="dashboard">
                {''.join([f'<div class="chart-container"><h3>{ticker}</h3>{chart}</div>' for ticker, chart in charts])}
            </div>
        </body>
        </html>
        """

        return dashboard_html

    def _empty_chart(self, ticker: str, timeframe: str) -> str:
        """Generate empty chart when no data available."""
        fig = go.Figure()
        fig.update_layout(
            title=f"No data available for {ticker} ({timeframe})",
            height=400,
            template="plotly_dark"
        )
        return fig.to_html(include_plotlyjs='cdn')

    def add_signal_annotations(
        self,
        fig: go.Figure,
        signals: list[BigWickSignal]
    ) -> go.Figure:
        """
        Add signal annotations to chart.

        Args:
            fig: Plotly figure
            signals: List of BigWickSignal objects

        Returns:
            Updated figure
        """
        for signal in signals:
            color = 'green' if signal.is_bullish else 'red'
            symbol = 'triangle-up' if signal.is_bullish else 'triangle-down'

            # Add marker at signal location
            fig.add_scatter(
                x=[signal.timestamp],
                y=[signal.entry_price],
                mode='markers',
                marker=dict(
                    symbol=symbol,
                    size=15,
                    color=color,
                    line=dict(width=2, color='white')
                ),
                name=f"{signal.signal_type.value}",
                hovertemplate=(
                    f"<b>{signal.ticker}</b><br>"
                    f"Type: {signal.signal_type.value}<br>"
                    f"Entry: {signal.entry_price:.5f}<br>"
                    f"SL: {signal.stop_loss:.5f}<br>"
                    f"TP: {signal.take_profit:.5f}<br>"
                    f"Confidence: {signal.confidence:.0%}"
                )
            )

        return fig

    def add_fibonacci_levels(
        self,
        fig: go.Figure,
        swing_high: float,
        swing_low: float,
        start_time,
        end_time
    ) -> go.Figure:
        """
        Add Fibonacci retracement levels to chart.

        Args:
            fig: Plotly figure
            swing_high: Swing high price
            swing_low: Swing low price
            start_time: Start time for fib lines
            end_time: End time for fib lines

        Returns:
            Updated figure
        """
        diff = swing_high - swing_low

        fib_levels = {
            '0%': swing_high,
            '23.6%': swing_high - (diff * 0.236),
            '38.2%': swing_high - (diff * 0.382),
            '50%': swing_high - (diff * 0.5),
            '61.8%': swing_high - (diff * 0.618),
            '100%': swing_low
        }

        for level_name, level_price in fib_levels.items():
            fig.add_hline(
                y=level_price,
                line_dash="dash",
                line_color="yellow",
                opacity=0.5,
                annotation_text=level_name,
                annotation_font_size=10,
                annotation_bgcolor="rgba(0,0,0,0.5)"
            )

        return fig
