"""
Pattern detection service for Three Pulse and Big Wick patterns.

Implements the core signal detection logic for the Naked Forex framework.
"""

from datetime import datetime, timedelta
from typing import Optional

from app.models.market import MarketData, OHLCV
from app.models.signals import (
    SRZone,
    BigWickSignal,
    ThreePulseSignal,
    SignalResponse,
    SignalType,
    ZoneType
)
from app.services.data_service import DataService
from app.services.sr_detection import SRDetectionService
from app.config.settings import get_settings
from app.config.constants import FOREX_PAIRS
from loguru import logger


class PatternDetectionService:
    """
    Service for detecting trading patterns.

    Detects:
    - Big Wick candlestick patterns
    - Three Pulse exhaustion patterns
    - A+ setups (combination of above + fresh S/R zone)
    """

    def __init__(
        self,
        wick_ratio: float | None = None,
        sr_service: SRDetectionService | None = None,
        sr_profile: str | None = None
    ):
        """
        Initialize pattern detection service.

        Args:
            wick_ratio: Minimum wick-to-body ratio for Big Wick
            sr_service: S/R detection service instance
            sr_profile: SR detection profile to use (conservative, balanced, aggressive)
        """
        settings = get_settings()
        self.wick_ratio = wick_ratio or settings.wick_ratio

        # Use provided SR service or create new one with profile
        if sr_service:
            self.sr_service = sr_service
        else:
            profile = sr_profile or settings.sr_detection_profile
            self.sr_service = SRDetectionService(profile=profile)

        self.data_service = DataService()

        logger.info(
            f"PatternDetectionService initialized: wick_ratio={self.wick_ratio}, "
            f"sr_profile={sr_profile or settings.sr_detection_profile}"
        )

    async def detect_big_wick(
        self,
        ticker: str,
        timeframe: str = "15m",
        lookback_bars: int = 500
    ) -> list[BigWickSignal]:
        """
        Detect Big Wick candlestick patterns at S/R zones.

        A valid Big Wick must:
        1. Have wick_ratio >= threshold (default 3.0)
        2. Occur at or near a known S/R zone
        3. Be larger than preceding candles

        Args:
            ticker: Ticker symbol
            timeframe: Chart timeframe
            lookback_bars: Number of bars to analyze

        Returns:
            List of BigWickSignal objects
        """
        logger.info(f"Detecting Big Wick patterns for {ticker} {timeframe}")

        # Fetch market data
        market_data = await self.data_service.fetch_data(
            ticker=ticker,
            timeframe=timeframe,
            lookback_bars=lookback_bars
        )

        # Detect S/R zones
        sr_zones = await self.sr_service.detect_zones(market_data)

        # Find Big Wick signals
        signals = []
        candles = market_data.data

        for i, candle in enumerate(candles):
            # Check if this is a Big Wick candle
            if not self._is_big_wick(candle, candles, i):
                continue

            # Check if it's near an S/R zone
            sr_zone = self._find_nearby_sr_zone(candle, sr_zones)
            if not sr_zone:
                continue

            # Determine signal type and calculate entry/SL/TP
            wick_to_body = candle.total_wick / candle.body_size if candle.body_size > 0 else 0

            if candle.is_bullish:
                signal_type = SignalType.BIG_WICK_BULLISH
                entry_price = candle.close
                stop_loss = candle.low  # Below the wick
                risk = abs(entry_price - stop_loss)
                take_profit = entry_price + risk  # 1:1 RR
            else:
                signal_type = SignalType.BIG_WICK_BEARISH
                entry_price = candle.close
                stop_loss = candle.high  # Above the wick
                risk = abs(entry_price - stop_loss)
                take_profit = entry_price - risk  # 1:1 RR

            # Calculate risk-reward
            rr = abs(take_profit - entry_price) / abs(entry_price - stop_loss)

            signal = BigWickSignal(
                ticker=ticker,
                timeframe=timeframe,
                timestamp=candle.timestamp,
                signal_type=signal_type,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                risk_reward=rr,
                wick_ratio=wick_to_body,
                sr_zone=sr_zone,
                confidence=self._calculate_big_wick_confidence(
                    candle, candles, i, sr_zone
                ),
                candle_open=candle.open,
                candle_high=candle.high,
                candle_low=candle.low,
                candle_close=candle.close,
                candle_volume=candle.volume
            )
            signals.append(signal)

        logger.info(f"Found {len(signals)} Big Wick signals for {ticker}")

        return signals

    async def detect_three_pulse(
        self,
        ticker: str,
        timeframe: str = "15m",
        lookback_bars: int = 500
    ) -> list[ThreePulseSignal]:
        """
        Detect Three Pulse exhaustion patterns.

        The Three Pulse pattern consists of:
        1. Range/consolidation period
        2. First pulse (breakout)
        3. Second pulse (FOMO continuation)
        4. Third pulse (exhaustion/stop hunt)

        Args:
            ticker: Ticker symbol
            timeframe: Chart timeframe
            lookback_bars: Number of bars to analyze

        Returns:
            List of ThreePulseSignal objects
        """
        logger.info(f"Detecting Three Pulse patterns for {ticker} {timeframe}")

        # Fetch market data
        market_data = await self.data_service.fetch_data(
            ticker=ticker,
            timeframe=timeframe,
            lookback_bars=lookback_bars
        )

        # Detect S/R zones
        sr_zones = await self.sr_service.detect_zones(market_data)

        # Find Three Pulse patterns
        signals = []
        pulse_patterns = self._find_three_pulse_sequences(market_data)

        for pattern in pulse_patterns:
            # Check if exhaustion point is near S/R zone
            sr_zone = self._find_nearby_sr_zone_by_price(
                pattern['exhaustion_price'],
                sr_zones
            )

            if not sr_zone:
                continue

            signal_type = (
                SignalType.THREE_PULSE_BULLISH
                if pattern['direction'] == 'bullish'
                else SignalType.THREE_PULSE_BEARISH
            )

            signal = ThreePulseSignal(
                ticker=ticker,
                timeframe=timeframe,
                start_time=pattern['start_time'],
                end_time=pattern['end_time'],
                signal_type=signal_type,
                pulse_count=len(pattern['pulses']),
                pulses=pattern['pulses'],
                exhaustion_point=pattern['exhaustion_price'],
                sr_zone=sr_zone,
                confidence=self._calculate_pulse_confidence(pattern, sr_zone),
                consolidation_start=pattern.get('consolidation_start'),
                breakout_time=pattern.get('breakout_time')
            )
            signals.append(signal)

        logger.info(f"Found {len(signals)} Three Pulse patterns for {ticker}")

        return signals

    async def detect_a_plus_setups(
        self,
        ticker: str,
        timeframe: str = "15m",
        lookback_bars: int = 500,
        min_confidence: float = 0.7
    ) -> list[SignalResponse]:
        """
        Detect A+ setups: Fresh S/R + Three Pulse + Big Wick.

        This is the complete Naked Forex setup according to Nick Shawn.

        Args:
            ticker: Ticker symbol
            timeframe: Chart timeframe
            lookback_bars: Number of bars to analyze
            min_confidence: Minimum combined confidence threshold

        Returns:
            List of SignalResponse objects representing A+ setups
        """
        logger.info(f"Detecting A+ setups for {ticker} {timeframe}")

        # Get both signal types
        big_wicks = await self.detect_big_wick(ticker, timeframe, lookback_bars)
        three_pulses = await self.detect_three_pulse(ticker, timeframe, lookback_bars)

        # Find matches where Big Wick occurs at Three Pulse exhaustion
        a_plus_setups = []

        for bw in big_wicks:
            for tp in three_pulses:
                # Check if Big Wick occurred near Three Pulse exhaustion
                time_diff = abs((bw.timestamp - tp.end_time).total_seconds())
                price_diff = abs(bw.entry_price - tp.exhaustion_point)

                # Must be near in time (within 2 hours) and price
                if time_diff < 7200 and price_diff < (bw.entry_price * 0.005):
                    # Calculate combined confidence
                    combined_confidence = (bw.confidence * 0.6) + (tp.confidence * 0.4)

                    # Filter by minimum confidence
                    if combined_confidence < min_confidence:
                        continue

                    # Determine signal type
                    signal_type = (
                        SignalType.A_PLUS_BUY if bw.is_bullish else SignalType.A_PLUS_SELL
                    )

                    setup = SignalResponse(
                        signal_type=signal_type,
                        big_wick=bw,
                        three_pulse=tp,
                        combined_confidence=combined_confidence,
                        detected_at=datetime.utcnow(),
                        notes=f"A+ Setup detected at {bw.timestamp}"
                    )
                    a_plus_setups.append(setup)

        logger.info(f"Found {len(a_plus_setups)} A+ setups for {ticker}")

        return a_plus_setups

    def _is_big_wick(
        self,
        candle: OHLCV,
        candles: list[OHLCV],
        index: int
    ) -> bool:
        """Check if candle meets Big Wick criteria."""
        # Wick must be larger than body
        if candle.body_size == 0:
            return False

        wick_to_body = candle.total_wick / candle.body_size
        if wick_to_body < self.wick_ratio:
            return False

        # Must be larger than preceding 3 candles (on average)
        if index >= 3:
            avg_preceding_wick = sum(
                c.total_wick for c in candles[index-3:index]
            ) / 3
            if candle.total_wick < avg_preceding_wick * 1.2:
                return False

        return True

    def _find_nearby_sr_zone(
        self,
        candle: OHLCV,
        sr_zones: list[SRZone],
        tolerance: float = 0.005
    ) -> Optional[SRZone]:
        """Find S/R zone near candle's wick."""
        for zone in sr_zones:
            zone_min, zone_max = zone.price_range
            # Check if candle's high or low is within zone
            if zone_min <= candle.high <= zone_max:
                return zone
            if zone_min <= candle.low <= zone_max:
                return zone
        return None

    def _find_nearby_sr_zone_by_price(
        self,
        price: float,
        sr_zones: list[SRZone]
    ) -> Optional[SRZone]:
        """Find S/R zone near a specific price."""
        for zone in sr_zones:
            if zone.contains_price(price):
                return zone
        return None

    def _find_three_pulse_sequences(
        self,
        data: MarketData
    ) -> list[dict]:
        """
        Find Three Pulse patterns in market data.

        Simplified implementation that detects swing sequences
        consistent with three pushes in one direction.

        Args:
            data: Market data

        Returns:
            List of pattern dictionaries
        """
        patterns = []
        candles = data.data

        if len(candles) < 30:
            return patterns

        # Look for three-swing sequences
        # This is a simplified version - full implementation would be more sophisticated
        i = 10  # Start with some lookback

        while i < len(candles) - 20:
            # Try to detect bullish three-pulse
            bullish_pattern = self._try_detect_three_pulse(candles, i, 'bullish')
            if bullish_pattern:
                patterns.append(bullish_pattern)
                i += 20  # Skip ahead
                continue

            # Try to detect bearish three-pulse
            bearish_pattern = self._try_detect_three_pulse(candles, i, 'bearish')
            if bearish_pattern:
                patterns.append(bearish_pattern)
                i += 20  # Skip ahead
                continue

            i += 1

        return patterns

    def _try_detect_three_pulse(
        self,
        candles: list[OHLCV],
        start_index: int,
        direction: str
    ) -> Optional[dict]:
        """
        Try to detect a three-pulse pattern starting at index.

        This is a simplified implementation focusing on the core concept:
        Three pushes in one direction followed by a reversal signal.
        """
        if start_index + 20 >= len(candles):
            return None

        # Look for three progressive highs (bullish) or lows (bearish)
        pulses = []
        pulse_points = []

        if direction == 'bullish':
            # Look for three higher highs
            for i in range(start_index, min(start_index + 20, len(candles))):
                # Find local high
                if i + 5 >= len(candles):
                    break
                local_high = max(c.high for c in candles[i:i+5])
                if candles[i].high == local_high:
                    pulse_points.append({
                        'index': i,
                        'price': local_high,
                        'time': candles[i].timestamp
                    })
                    if len(pulse_points) >= 3:
                        break
        else:
            # Look for three lower lows
            for i in range(start_index, min(start_index + 20, len(candles))):
                # Find local low
                if i + 5 >= len(candles):
                    break
                local_low = min(c.low for c in candles[i:i+5])
                if candles[i].low == local_low:
                    pulse_points.append({
                        'index': i,
                        'price': local_low,
                        'time': candles[i].timestamp
                    })
                    if len(pulse_points) >= 3:
                        break

        # Need at least 3 pulses
        if len(pulse_points) < 3:
            return None

        # Verify pulses are progressive
        for j in range(1, len(pulse_points)):
            if direction == 'bullish':
                if pulse_points[j]['price'] <= pulse_points[j-1]['price']:
                    return None  # Not making higher highs
            else:
                if pulse_points[j]['price'] >= pulse_points[j-1]['price']:
                    return None  # Not making lower lows

        # Found a valid pattern
        return {
            'direction': direction,
            'start_time': pulse_points[0]['time'],
            'end_time': pulse_points[-1]['time'],
            'pulses': [p['time'] for p in pulse_points],
            'exhaustion_price': pulse_points[-1]['price'],
            'pulse_count': len(pulse_points)
        }

    def _calculate_big_wick_confidence(
        self,
        candle: OHLCV,
        candles: list[OHLCV],
        index: int,
        sr_zone: SRZone
    ) -> float:
        """Calculate confidence score for Big Wick signal (0-1)."""
        confidence = 0.5  # Base confidence

        # Increase confidence for fresh zones
        if sr_zone.is_fresh:
            confidence += 0.2

        # Increase confidence for larger wick ratios
        if candle.body_size > 0:
            wick_ratio = candle.total_wick / candle.body_size
            if wick_ratio > 5.0:
                confidence += 0.15
            elif wick_ratio > 4.0:
                confidence += 0.1

        # Increase confidence for strong zones
        if sr_zone.strength > 0.7:
            confidence += 0.15

        return min(confidence, 1.0)

    def _calculate_pulse_confidence(
        self,
        pulse: dict,
        sr_zone: SRZone
    ) -> float:
        """Calculate confidence score for Three Pulse signal (0-1)."""
        confidence = 0.5  # Base confidence

        # Increase confidence for exactly 3 pulses
        if pulse['pulse_count'] == 3:
            confidence += 0.2

        # Increase confidence for fresh zones
        if sr_zone.is_fresh:
            confidence += 0.2

        # Increase confidence for strong zones
        if sr_zone.strength > 0.7:
            confidence += 0.1

        return min(confidence, 1.0)
