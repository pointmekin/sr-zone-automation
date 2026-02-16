"""
Support/Resistance zone detection service.

Uses pivot point detection and clustering algorithms to identify
key horizontal price levels.
"""

from datetime import datetime, timedelta
from typing import Optional

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from app.models.market import MarketData
from app.models.signals import SRZone, ZoneType
from app.config.settings import get_settings
from loguru import logger


class SRDetectionService:
    """
    Service for detecting Support and Resistance zones.

    Uses a two-step process:
    1. Find pivot highs and lows using local neighborhood search
    2. Cluster pivot points into zones using hierarchical clustering
    """

    def __init__(
        self,
        sensitivity: float | None = None,
        min_touches: int = 2,
        lookback_pivots: int = 5
    ):
        """
        Initialize S/R detection service.

        Args:
            sensitivity: Price difference threshold for clustering (0.01-0.2)
            min_touches: Minimum touches to qualify as a zone
            lookback_pivots: Lookback period for pivot detection
        """
        settings = get_settings()
        self.sensitivity = sensitivity or settings.sr_sensitivity
        self.min_touches = min_touches
        self.lookback_pivots = lookback_pivots
        self.fresh_zone_threshold = settings.fresh_zone_threshold

        logger.info(
            f"SRDetectionService initialized: sensitivity={self.sensitivity}, "
            f"min_touches={min_touches}"
        )

    async def detect_zones(
        self,
        data: MarketData,
        min_strength: float = 0.0,
        sensitivity: float | None = None
    ) -> list[SRZone]:
        """
        Detect support and resistance zones.

        Args:
            data: Market data with OHLCV candles
            min_strength: Minimum strength threshold (0-1)
            sensitivity: Override sensitivity for clustering (uses instance sensitivity if None)

        Returns:
            List of SRZone objects sorted by strength (descending)
        """
        if not data.data:
            logger.warning("No data available for S/R detection")
            return []

        # Use provided sensitivity or fall back to instance sensitivity
        cluster_sensitivity = sensitivity if sensitivity is not None else self.sensitivity

        # Find pivot highs and lows
        pivot_highs = self._find_pivot_highs(data, self.lookback_pivots)
        pivot_lows = self._find_pivot_lows(data, self.lookback_pivots)

        logger.info(
            f"Found {len(pivot_highs)} pivot highs and {len(pivot_lows)} pivot lows"
        )

        # Cluster pivot points into zones
        resistance_zones = self._cluster_pivots_to_zones(
            pivot_highs,
            ZoneType.RESISTANCE,
            data,
            cluster_sensitivity
        )
        support_zones = self._cluster_pivots_to_zones(
            pivot_lows,
            ZoneType.SUPPORT,
            data,
            cluster_sensitivity
        )

        # Combine and filter by strength
        all_zones = resistance_zones + support_zones
        filtered_zones = [z for z in all_zones if z.strength >= min_strength]

        # Sort by strength (descending)
        filtered_zones.sort(key=lambda z: z.strength, reverse=True)

        logger.info(f"Detected {len(filtered_zones)} S/R zones (min_strength={min_strength})")

        return filtered_zones

    def _find_pivot_highs(
        self,
        data: MarketData,
        lookback: int
    ) -> list[dict]:
        """
        Find pivot high points.

        A pivot high is a candle whose high is the highest in its neighborhood.

        Args:
            data: Market data
            lookback: Number of candles on each side to check

        Returns:
            List of pivot high dictionaries with price, timestamp, index
        """
        pivots = []
        candles = data.data

        for i in range(lookback, len(candles) - lookback):
            current = candles[i]
            is_pivot = True

            # Check if current high is highest in neighborhood
            for j in range(i - lookback, i + lookback + 1):
                if candles[j].high > current.high:
                    is_pivot = False
                    break

            if is_pivot:
                pivots.append({
                    'price': current.high,
                    'timestamp': current.timestamp,
                    'index': i
                })

        return pivots

    def _find_pivot_lows(
        self,
        data: MarketData,
        lookback: int
    ) -> list[dict]:
        """
        Find pivot low points.

        A pivot low is a candle whose low is the lowest in its neighborhood.

        Args:
            data: Market data
            lookback: Number of candles on each side to check

        Returns:
            List of pivot low dictionaries with price, timestamp, index
        """
        pivots = []
        candles = data.data

        for i in range(lookback, len(candles) - lookback):
            current = candles[i]
            is_pivot = True

            # Check if current low is lowest in neighborhood
            for j in range(i - lookback, i + lookback + 1):
                if candles[j].low < current.low:
                    is_pivot = False
                    break

            if is_pivot:
                pivots.append({
                    'price': current.low,
                    'timestamp': current.timestamp,
                    'index': i
                })

        return pivots

    def _cluster_pivots_to_zones(
        self,
        pivots: list[dict],
        zone_type: ZoneType,
        data: MarketData,
        sensitivity: float | None = None
    ) -> list[SRZone]:
        """
        Cluster pivot points into zones.

        Uses hierarchical clustering to group nearby pivot points.

        Args:
            pivots: List of pivot dictionaries
            zone_type: SUPPORT or RESISTANCE
            data: Market data
            sensitivity: Sensitivity for clustering (uses instance sensitivity if None)

        Returns:
            List of SRZone objects
        """
        if not pivots:
            return []

        # Use provided sensitivity or fall back to instance sensitivity
        cluster_sensitivity = sensitivity if sensitivity is not None else self.sensitivity

        # Extract prices for clustering
        prices = np.array([[p['price']] for p in pivots])

        # Calculate distance threshold based on sensitivity and average price
        avg_price = np.mean(prices)
        distance_threshold = avg_price * cluster_sensitivity

        # Perform clustering
        n_clusters = min(len(pivots), max(2, len(pivots) // 2))
        clustering = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=distance_threshold,
            linkage='average'
        )

        try:
            labels = clustering.fit_predict(prices)
        except Exception as e:
            logger.warning(f"Clustering failed: {e}, using each pivot as a zone")
            labels = list(range(len(pivots)))

        # Group pivots by cluster
        clusters = {}
        for idx, label in enumerate(labels):
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(pivots[idx])

        # Create zones from clusters
        zones = []
        for cluster_pivots in clusters.values():
            if len(cluster_pivots) < self.min_touches:
                continue

            # Calculate zone level (average price)
            avg_level = np.mean([p['price'] for p in cluster_pivots])

            # Find most recent touch
            most_recent = max(cluster_pivots, key=lambda p: p['index'])

            # Calculate strength based on touch count and recency
            strength = self._calculate_strength(cluster_pivots, data)

            # Check if zone is fresh
            is_fresh = self._is_fresh_zone(most_recent['index'], len(data.data))

            zone = SRZone(
                level=float(avg_level),
                zone_type=zone_type,
                strength=strength,
                is_fresh=is_fresh,
                touches=len(cluster_pivots),
                last_touch_date=most_recent['timestamp']
            )
            zones.append(zone)

        return zones

    def _calculate_strength(
        self,
        cluster: list[dict],
        data: MarketData
    ) -> float:
        """
        Calculate zone strength (0-1).

        Based on:
        - Number of touches (more = stronger)
        - Recency of touches
        - Cleanliness of rejections (could add later)

        Args:
            cluster: List of pivot points in the cluster
            data: Market data

        Returns:
            Strength score between 0 and 1
        """
        # Base strength from touch count
        touch_strength = min(len(cluster) / 5.0, 1.0)  # 5+ touches = 1.0

        # Adjust for recency (more recent touches = stronger)
        most_recent_index = max(p['index'] for p in cluster)
        total_candles = len(data.data)
        recency_factor = 1.0 - (most_recent_index / total_candles) * 0.3

        return min(touch_strength * recency_factor, 1.0)

    def _is_fresh_zone(
        self,
        last_touch_index: int,
        total_candles: int
    ) -> bool:
        """
        Determine if zone is fresh (not recently tested).

        A zone is fresh if it hasn't been touched in the last N bars.

        Args:
            last_touch_index: Index of most recent touch
            total_candles: Total number of candles

        Returns:
            True if zone is fresh
        """
        current_index = total_candles - 1
        bars_since_touch = current_index - last_touch_index

        return bars_since_touch >= self.fresh_zone_threshold

    def find_nearby_zone(
        self,
        price: float,
        zones: list[SRZone],
        tolerance: float | None = None
    ) -> Optional[SRZone]:
        """
        Find S/R zone near a given price.

        Args:
            price: Price to check
            zones: List of S/R zones
            tolerance: Price tolerance (default: from sensitivity)

        Returns:
            Nearby SRZone or None
        """
        if not zones:
            return None

        if tolerance is None:
            # Use average zone sensitivity
            tolerance = self.sensitivity

        for zone in zones:
            if zone.contains_price(price):
                return zone

        return None
