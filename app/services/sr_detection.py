"""
Improved Support/Resistance zone detection service.

Uses pivot point detection and clustering algorithms with ATR-based thresholds,
volume confirmation, psychological level detection, and advanced filtering.
"""

import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde
from scipy.signal import find_peaks

from app.models.market import MarketData, OHLCV
from app.models.signals import SRZone, ZoneType
from app.config.settings import get_settings
from loguru import logger


# Type hint for optional cache service
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.services.cache_service import SRZoneCache


class SRDetectionService:
    """
    Improved Service for detecting Support and Resistance zones.

    Uses a two-step process with multiple enhancements:
    1. Find pivot highs and lows using local neighborhood search
    2. Cluster pivot points into zones using ATR-based hierarchical clustering

    Improvements over basic implementation:
    - ATR-based dynamic thresholds instead of fixed percentage
    - Minimum pivot distance to prevent crowding
    - Volume confirmation for pivots
    - Post-processing cluster merging
    - Zone overlap removal
    - Psychological level detection
    - Exponential recency decay in strength calculation
    """

    def __init__(
        self,
        sensitivity: Optional[float] = None,
        min_touches: int = 2,
        lookback_pivots: int = 5,
        use_atr: bool = True,
        sensitivity_atr_multiplier: Optional[float] = None,
        zone_width_atr_multiplier: Optional[float] = None,
        profile: Optional[str] = None,
        cache_service: Optional['SRZoneCache'] = None,
        enable_cache: bool = True,
    ):
        """
        Initialize improved S/R detection service.

        Args:
            sensitivity: Legacy fixed percentage threshold (use ATR instead)
            min_touches: Minimum touches to qualify as a zone
            lookback_pivots: Lookback period for pivot detection
            use_atr: Use ATR-based dynamic thresholds
            sensitivity_atr_multiplier: ATR multiplier for clustering
            zone_width_atr_multiplier: ATR multiplier for zone width
            profile: Preset profile name (conservative, balanced, aggressive)
        """
        settings = get_settings()

        # Load preset profile if specified
        from app.config.constants import SR_DETECTION_PRESETS
        selected_profile = profile or settings.sr_detection_profile
        preset = SR_DETECTION_PRESETS.get(selected_profile, SR_DETECTION_PRESETS["balanced"])

        # Legacy support (use preset if not explicitly provided)
        self.sensitivity = sensitivity or settings.sr_sensitivity
        self.min_touches = min_touches if min_touches != 2 else preset.get("min_zone_touches", 2)
        self.lookback_pivots = lookback_pivots if lookback_pivots != 5 else preset.get("min_pivot_lookback", 5)
        self.fresh_zone_threshold = preset.get("fresh_zone_threshold", 100)

        # New improved parameters - use preset if not explicitly provided
        self.use_atr = use_atr or preset.get("use_atr_thresholds", True)
        self.sensitivity_atr = sensitivity_atr_multiplier or preset.get("sensitivity_atr_multiplier", 0.3)
        self.zone_width_atr = zone_width_atr_multiplier or preset.get("zone_width_atr_multiplier", 0.5)
        self.atr_period = preset.get("atr_period", 14)
        self.min_pivot_distance = preset.get("min_pivot_distance_bars", 5)
        self.use_volume = preset.get("use_volume_confirmation", False)
        self.volume_threshold = settings.volume_confirmation_threshold
        self.max_zone_age = preset.get("max_zone_age_bars", 500)
        self.recency_weight = preset.get("recency_weight", 0.4)
        self.touch_weight = preset.get("touch_weight", 0.6)
        self.round_number_proximity = preset.get("round_number_proximity", 0.001)
        self.overlap_threshold = preset.get("overlap_removal_threshold", 0.7)
        self.min_strength = preset.get("min_zone_strength", 0.0)

        # Cache support
        self.enable_cache = enable_cache
        if cache_service is not None:
            self.cache = cache_service
        elif enable_cache:
            # Import here to avoid circular dependency
            from app.services.cache_service import SRZoneCache
            self.cache = SRZoneCache(
                max_size=settings.cache_max_size_sr_zones if hasattr(settings, 'cache_max_size_sr_zones') else 100,
                default_ttl_seconds=3600
            )
        else:
            self.cache = None

        logger.info(
            f"SRDetectionService initialized: profile={selected_profile}, "
            f"ATR={self.use_atr}, "
            f"sensitivity_atr={self.sensitivity_atr}, "
            f"zone_width_atr={self.zone_width_atr}, "
            f"min_touches={self.min_touches}"
        )

    async def detect_zones(
        self,
        data: MarketData,
        min_strength: float = 0.0,
        sensitivity: Optional[float] = None
    ) -> list[SRZone]:
        """
        Detect support and resistance zones with improved algorithm.

        Args:
            data: Market data with OHLCV candles
            min_strength: Minimum strength threshold (0-1)
            sensitivity: Override sensitivity for clustering

        Returns:
            List of SRZone objects sorted by strength (descending)
        """
        if not data.data:
            logger.warning("No data available for S/R detection")
            return []

        # Try cache first
        if self.enable_cache and self.cache:
            settings = get_settings()
            profile_name = settings.sr_detection_profile
            data_version = self._generate_data_fingerprint(data)
            cached_zones = self.cache.get(
                ticker=data.ticker,
                timeframe=str(data.timeframe),
                profile=profile_name,
                data_version=data_version
            )
            if cached_zones is not None:
                logger.info(
                    f"Using cached SR zones for {data.ticker} "
                    f"({len(cached_zones)} zones)"
                )
                # Filter by min_strength
                strength_threshold = min_strength if min_strength > 0 else self.min_strength
                return [z for z in cached_zones if z.strength >= strength_threshold]

        # Use provided min_strength or instance default
        strength_threshold = min_strength if min_strength > 0 else self.min_strength

        # Convert to pandas DataFrame for easier manipulation
        df = self._to_dataframe(data)

        # Calculate ATR if using ATR-based thresholds
        atr = self.calculate_atr(df) if self.use_atr else 0.0

        logger.info(f"ATR: {atr:.6f}, using ATR-based: {self.use_atr}")

        # Find pivot highs and lows with volume and distance filtering
        pivot_highs, pivot_lows = self._detect_pivots_improved(df)

        logger.info(
            f"Found {len(pivot_highs)} pivot highs and {len(pivot_lows)} pivot lows"
        )

        # Cluster pivot points into zones
        resistance_zones = self._cluster_pivots_to_zones(
            pivot_highs,
            ZoneType.RESISTANCE,
            data,
            df,
            atr,
            sensitivity
        )
        support_zones = self._cluster_pivots_to_zones(
            pivot_lows,
            ZoneType.SUPPORT,
            data,
            df,
            atr,
            sensitivity
        )

        # Combine and filter by strength
        all_zones = resistance_zones + support_zones
        filtered_zones = [z for z in all_zones if z.strength >= strength_threshold]

        # Remove overlapping zones (keep stronger ones)
        filtered_zones = self._remove_overlapping_zones(filtered_zones)

        # Sort by strength (descending)
        filtered_zones.sort(key=lambda z: z.strength, reverse=True)

        logger.info(
            f"Detected {len(filtered_zones)} S/R zones "
            f"(min_strength={strength_threshold:.2f})"
        )

        # Cache the results
        if self.enable_cache and self.cache:
            settings = get_settings()
            profile_name = settings.sr_detection_profile
            data_version = self._generate_data_fingerprint(data)
            ttl_seconds = self._calculate_ttl(str(data.timeframe))

            self.cache.set(
                ticker=data.ticker,
                timeframe=str(data.timeframe),
                profile=profile_name,
                zones=filtered_zones,
                ttl_seconds=ttl_seconds,
                data_version=data_version
            )
            logger.info(
                f"Cached {len(filtered_zones)} SR zones for {data.ticker} "
                f"(TTL: {ttl_seconds}s)"
            )

        return filtered_zones

    def _to_dataframe(self, data: MarketData) -> pd.DataFrame:
        """Convert MarketData to pandas DataFrame."""
        records = []
        for candle in data.data:
            records.append({
                'timestamp': candle.timestamp,
                'open': candle.open,
                'high': candle.high,
                'low': candle.low,
                'close': candle.close,
                'volume': getattr(candle, 'volume', 1.0)
            })

        df = pd.DataFrame(records)
        if not df.empty:
            df.set_index('timestamp', inplace=True)
        return df

    def calculate_atr(self, df: pd.DataFrame, period: Optional[int] = None) -> float:
        """
        Calculate Average True Range for dynamic thresholding.

        Args:
            df: DataFrame with OHLCV data
            period: ATR period (default: from settings)

        Returns:
            ATR value or 0 if calculation fails
        """
        if df.empty:
            return 0.0

        period = period or self.atr_period

        try:
            highs = df['high']
            lows = df['low']
            closes = df['close']

            tr1 = highs - lows
            tr2 = abs(highs - closes.shift())
            tr3 = abs(lows - closes.shift())

            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(window=period).mean().iloc[-1]

            return float(atr) if not np.isnan(atr) else float((highs - lows).mean())
        except Exception as e:
            logger.warning(f"ATR calculation failed: {e}")
            return float((df['high'] - df['low']).mean())

    def _detect_pivots_improved(
        self, df: pd.DataFrame
    ) -> Tuple[List[dict], List[dict]]:
        """
        Improved pivot detection with volume confirmation and minimum distance.

        Args:
            df: DataFrame with OHLCV data

        Returns:
            Tuple of (pivot_highs, pivot_lows) lists
        """
        pivot_highs = []
        pivot_lows = []

        if df.empty or len(df) < self.lookback_pivots * 2:
            return pivot_highs, pivot_lows

        highs = df['high'].values
        lows = df['low'].values
        volumes = df.get('volume', pd.Series([1.0] * len(df))).values
        timestamps = df.index

        # Calculate average volume for confirmation
        avg_volume = float(np.mean(volumes)) if self.use_volume else 0.0

        last_pivot_high_idx = -self.min_pivot_distance
        last_pivot_low_idx = -self.min_pivot_distance

        for i in range(self.lookback_pivots, len(df) - self.lookback_pivots):
            # Pivot High Detection
            current_high = highs[i]
            neighborhood_highs = highs[i - self.lookback_pivots:i + self.lookback_pivots + 1]

            is_pivot_high = current_high == np.max(neighborhood_highs)

            # Ensure minimum distance from previous pivot
            if is_pivot_high and (i - last_pivot_high_idx) >= self.min_pivot_distance:
                # Volume confirmation
                volume_confirmed = (
                    not self.use_volume or
                    volumes[i] > avg_volume * self.volume_threshold
                )

                if volume_confirmed:
                    pivot_highs.append({
                        'price': float(current_high),
                        'timestamp': timestamps[i],
                        'index': i,
                        'volume': float(volumes[i]),
                    })
                    last_pivot_high_idx = i

            # Pivot Low Detection
            current_low = lows[i]
            neighborhood_lows = lows[i - self.lookback_pivots:i + self.lookback_pivots + 1]

            is_pivot_low = current_low == np.min(neighborhood_lows)

            if is_pivot_low and (i - last_pivot_low_idx) >= self.min_pivot_distance:
                volume_confirmed = (
                    not self.use_volume or
                    volumes[i] > avg_volume * self.volume_threshold
                )

                if volume_confirmed:
                    pivot_lows.append({
                        'price': float(current_low),
                        'timestamp': timestamps[i],
                        'index': i,
                        'volume': float(volumes[i]),
                    })
                    last_pivot_low_idx = i

        return pivot_highs, pivot_lows

    def _calculate_dynamic_threshold(
        self,
        df: pd.DataFrame,
        pivots: List[dict],
        atr: float,
        sensitivity: Optional[float] = None
    ) -> float:
        """
        Calculate dynamic clustering threshold using ATR or fixed percentage.

        Args:
            df: DataFrame with market data
            pivots: List of pivot points
            atr: Calculated ATR value
            sensitivity: Override sensitivity value

        Returns:
            Distance threshold for clustering
        """
        if not pivots:
            return 0.0

        if self.use_atr and atr > 0:
            # ATR-based threshold
            threshold = atr * self.sensitivity_atr
            # Ensure minimum threshold based on price level
            current_price = float(df['close'].iloc[-1])
            min_threshold = current_price * 0.001  # 0.1% minimum
            return max(threshold, min_threshold)
        else:
            # Fixed percentage threshold (legacy)
            cluster_sensitivity = sensitivity or self.sensitivity
            prices = np.array([p['price'] for p in pivots])
            avg_price = float(np.mean(prices))
            return avg_price * cluster_sensitivity

    def _cluster_pivots_to_zones(
        self,
        pivots: List[dict],
        zone_type: ZoneType,
        data: MarketData,
        df: pd.DataFrame,
        atr: float,
        sensitivity: Optional[float] = None
    ) -> List[SRZone]:
        """
        Cluster pivot points into zones using Time-Weighted Kernel Density Estimation (KDE).
        """
        if not pivots or len(pivots) < self.min_touches:
            return []

        prices_arr = np.array([p['price'] for p in pivots])
        indices_arr = np.array([p['index'] for p in pivots])
        current_price = float(df['close'].iloc[-1])
        total_candles = len(df)

        # 1. Time-Decay Weighting
        decay_factor = 0.98
        weights = np.array([decay_factor ** (total_candles - idx - 1) for idx in indices_arr])
        
        # Ensure weights don't vanish entirely to prevent NaNs
        weights = np.clip(weights, 1e-10, 1.0)

        try:
            # 2. Kernel Density Estimation
            kde = gaussian_kde(prices_arr, weights=weights, bw_method='scott')

            price_min, price_max = np.min(prices_arr), np.max(prices_arr)
            padding = atr * 2 if atr > 0 else current_price * 0.01
            price_grid = np.linspace(price_min - padding, price_max + padding, 1000)
            density = kde(price_grid)

            # Convert ATR threshold to grid indices to ensure peaks don't overlap
            grid_step = (price_max - price_min + padding * 2) / 1000
            min_distance_idx = max(int((atr * self.sensitivity_atr) / grid_step), 10) if atr > 0 else 10

            peaks, _ = find_peaks(density, distance=min_distance_idx)

            zones = []
            for peak_idx in peaks:
                peak_price = float(price_grid[peak_idx])

                # Proximity Filtering
                distance_to_current = abs(current_price - peak_price)
                if atr > 0 and distance_to_current > (atr * 3):
                    continue
                
                # Fetch pivots near this peak to construct the zone attributes
                local_mask = np.abs(prices_arr - peak_price) < (atr if atr > 0 else peak_price * 0.005)
                local_pivots = [pivots[i] for i in range(len(pivots)) if local_mask[i]]

                if len(local_pivots) < self.min_touches:
                    continue

                zone = self._create_zone_from_kde(
                    peak_price=peak_price,
                    cluster_pivots=local_pivots,
                    zone_type=zone_type,
                    data=data,
                    atr=atr,
                    distance_to_current=distance_to_current
                )

                if zone and zone.strength >= self.min_strength:
                    zones.append(zone)

            return zones

        except Exception as e:
            logger.warning(f"KDE Clustering failed: {e}, using fallback")
            return self._fallback_clustering(pivots, zone_type, data, df)

    def _merge_nearby_clusters(
        self,
        clusters: dict,
        merge_threshold: float
    ) -> dict:
        """
        Post-process to merge clusters that are statistically similar.

        Args:
            clusters: Dictionary of cluster label to pivots
            merge_threshold: Distance threshold for merging

        Returns:
            Merged clusters dictionary
        """
        if not clusters:
            return clusters

        # Calculate cluster centers
        cluster_centers = {
            label: float(np.mean([p['price'] for p in pivots]))
            for label, pivots in clusters.items()
        }

        # Sort by price level
        sorted_labels = sorted(cluster_centers.keys(), key=lambda x: cluster_centers[x])

        merged = {}
        current_group = [sorted_labels[0]]
        current_center = cluster_centers[sorted_labels[0]]

        for label in sorted_labels[1:]:
            if abs(cluster_centers[label] - current_center) <= merge_threshold:
                current_group.append(label)
            else:
                # Save current group
                merged_pivots = []
                for l in current_group:
                    merged_pivots.extend(clusters[l])
                merged[len(merged)] = merged_pivots

                # Start new group
                current_group = [label]
                current_center = cluster_centers[label]

        # Don't forget last group
        merged_pivots = []
        for l in current_group:
            merged_pivots.extend(clusters[l])
        merged[len(merged)] = merged_pivots

        return merged

    def _fallback_clustering(
        self,
        pivots: List[dict],
        zone_type: ZoneType,
        data: MarketData,
        df: pd.DataFrame
    ) -> List[SRZone]:
        """
        Fallback clustering using simple proximity grouping.

        Args:
            pivots: List of pivot points
            zone_type: Zone type
            data: Market data
            df: DataFrame

        Returns:
            List of SRZone objects
        """
        if not pivots:
            return []

        sorted_pivots = sorted(pivots, key=lambda x: x['price'])
        clusters = []
        current_cluster = [sorted_pivots[0]]

        for pivot in sorted_pivots[1:]:
            avg_price = float(np.mean([p['price'] for p in current_cluster]))
            # Use 0.1% proximity threshold
            if abs(pivot['price'] - avg_price) / avg_price < 0.001:
                current_cluster.append(pivot)
            else:
                clusters.append(current_cluster)
                current_cluster = [pivot]

        if current_cluster:
            clusters.append(current_cluster)

        # Create zones
        zones = []
        for cluster in clusters:
            if len(cluster) >= self.min_touches:
                zone = self._create_zone_from_cluster(cluster, zone_type, data, df)
                if zone:
                    zones.append(zone)

        return zones

    def _calculate_strength_improved(
        self,
        cluster_pivots: List[dict],
        total_candles: int
    ) -> dict:
        """
        Improved zone strength calculation with multiple factors.

        Args:
            cluster_pivots: List of pivots in the cluster
            total_candles: Total number of candles in dataset

        Returns:
            Dictionary with strength components
        """
        if not cluster_pivots:
            return {
                'strength': 0.0,
                'is_fresh': False,
                'last_touch_bars_ago': 0,
                'touch_score': 0.0,
                'recency_score': 0.0,
                'time_span_bars': 0
            }

        touches = len(cluster_pivots)
        indices = sorted([p['index'] for p in cluster_pivots])

        # Factor 1: Touch count (capped at 5 for max score)
        touch_score = min(touches / 5.0, 1.0)

        # Factor 2: Recency with exponential decay
        last_idx = indices[-1]
        bars_ago = total_candles - last_idx
        recency_score = np.exp(-bars_ago / 100)  # Decay over ~100 bars

        # Factor 3: Time span (zones that hold over time are stronger)
        first_idx = indices[0]
        time_span = last_idx - first_idx
        time_span_normalized = min(time_span / total_candles * 2, 1.0)

        # Combined weighted score
        strength = (
            touch_score * self.touch_weight +
            recency_score * self.recency_weight +
            time_span_normalized * 0.2
        )

        strength = min(strength, 1.0)

        # Freshness: zone tested recently but not too recently
        is_fresh = 10 < bars_ago < self.max_zone_age

        return {
            'strength': strength,
            'is_fresh': is_fresh,
            'last_touch_bars_ago': bars_ago,
            'touch_score': touch_score,
            'recency_score': recency_score,
            'time_span_bars': time_span
        }

    def _check_round_number_proximity(self, price: float) -> float:
        """
        Check if price is near psychological round numbers.

        Args:
            price: Price level to check

        Returns:
            Factor from 0-1 indicating proximity to round number
        """
        whole = int(price)
        decimal_part = price - whole

        # Check whole numbers (1.0000, 2.0000)
        if decimal_part < self.round_number_proximity:
            return 1.0 - (decimal_part / self.round_number_proximity)

        # Check .50 levels (1.5000, 2.5000)
        if abs(decimal_part - 0.5) < self.round_number_proximity:
            return 1.0 - (abs(decimal_part - 0.5) / self.round_number_proximity)

        # Check .00, .25, .50, .75 for forex
        for target in [0.0, 0.25, 0.50, 0.75]:
            if abs(decimal_part - target) < self.round_number_proximity:
                proximity = 1.0 - (abs(decimal_part - target) / self.round_number_proximity)
                return 0.8 * proximity

        return 0.0

    def _create_zone_from_kde(
        self,
        peak_price: float,
        cluster_pivots: List[dict],
        zone_type: ZoneType,
        data: MarketData,
        atr: float,
        distance_to_current: float
    ) -> Optional[SRZone]:
        """
        Create SRZone object strictly from KDE peak and proximity data.
        """
        if not cluster_pivots:
            return None

        # Base attributes
        level = peak_price
        prices = [p['price'] for p in cluster_pivots]
        
        # Dynamic Width via localized Standard Deviation
        if len(prices) > 1:
            std_dev = np.std(prices)
            zone_half_width = max(std_dev * 1.5, atr * 0.1) if atr > 0 else max(std_dev * 1.5, level * 0.001)
        else:
            zone_half_width = atr * 0.5 if atr > 0 else level * 0.005

        if zone_type == ZoneType.SUPPORT:
            lower = level - zone_half_width
            upper = level + zone_half_width * 0.5
        else:
            lower = level - zone_half_width * 0.5
            upper = level + zone_half_width

        price_range = (float(lower), float(upper))
        
        # Proximity weight
        relevance_score = 1.0 / (1.0 + (distance_to_current / atr)) if atr > 0 else 1.0

        # Optional factors
        round_number_factor = self._check_round_number_proximity(level)
        strength_data = self._calculate_strength_improved(cluster_pivots, len(data.data))
        
        # Scale strength with proximity relevance
        base_strength = strength_data['strength']
        adjusted_strength = min(base_strength * relevance_score * (1 + round_number_factor * 0.1), 1.0)
        
        pivot_indices = [p['index'] for p in cluster_pivots]
        volume_at_zone = float(np.mean([p.get('volume', 0) for p in cluster_pivots]))
        
        sorted_pivots = sorted(cluster_pivots, key=lambda x: x['index'])
        first_touch_date = sorted_pivots[0]['timestamp']
        last_touch_date = sorted_pivots[-1]['timestamp']

        return SRZone(
            level=float(level),
            zone_type=zone_type,
            strength=float(adjusted_strength),
            is_fresh=strength_data['is_fresh'],
            touches=len(cluster_pivots),
            last_touch_date=last_touch_date,
            first_touch_date=first_touch_date,
            pivot_indices=pivot_indices,
            volume_at_zone=volume_at_zone,
            round_number_factor=round_number_factor,
            time_span_bars=strength_data['time_span_bars'],
            last_touch_bars_ago=strength_data['last_touch_bars_ago'],
            touch_score=strength_data['touch_score'],
            recency_score=strength_data['recency_score'],
            price_range=price_range,
            distance_to_current=float(distance_to_current)
        )

    def _calculate_zone_width(
        self,
        level: float,
        df: pd.DataFrame,
        zone_type: ZoneType
    ) -> Tuple[float, float]:
        """
        Calculate zone width using ATR or fixed percentage.

        Args:
            level: Central price level
            df: DataFrame with market data
            zone_type: SUPPORT or RESISTANCE

        Returns:
            Tuple of (lower_bound, upper_bound)
        """
        if self.use_atr:
            atr = self.calculate_atr(df)
            half_width = atr * self.zone_width_atr
        else:
            half_width = level * 0.005  # 0.5% default

        if zone_type == ZoneType.SUPPORT:
            # Support extends more below (buyers defend)
            lower = level - half_width
            upper = level + half_width * 0.5
        else:  # RESISTANCE
            # Resistance extends more above (sellers defend)
            lower = level - half_width * 0.5
            upper = level + half_width

        return (lower, upper)

    def _remove_overlapping_zones(
        self,
        zones: List[SRZone]
    ) -> List[SRZone]:
        """
        Remove or merge zones that overlap significantly.

        Args:
            zones: List of zones to filter

        Returns:
            Filtered list of zones
        """
        if not zones:
            return zones

        # Sort by strength (descending) to keep strongest zones
        sorted_zones = sorted(zones, key=lambda x: x.strength, reverse=True)
        filtered = []

        for zone in sorted_zones:
            overlap_found = False
            for kept_zone in filtered:
                # Calculate overlap
                overlap_start = max(zone.price_range[0], kept_zone.price_range[0])
                overlap_end = min(zone.price_range[1], kept_zone.price_range[1])

                if overlap_start < overlap_end:
                    overlap_size = overlap_end - overlap_start
                    zone_size = zone.price_range[1] - zone.price_range[0]
                    kept_size = kept_zone.price_range[1] - kept_zone.price_range[0]

                    # Check if overlap is significant (>70% of smaller zone)
                    min_size = min(zone_size, kept_size)
                    if overlap_size / min_size > self.overlap_threshold:
                        overlap_found = True
                        break

            if not overlap_found:
                filtered.append(zone)

        return filtered

    def find_nearby_zone(
        self,
        price: float,
        zones: List[SRZone],
        tolerance: Optional[float] = None
    ) -> Optional[SRZone]:
        """
        Find S/R zone near a given price.

        Args:
            price: Price to check
            zones: List of S/R zones
            tolerance: Price tolerance (optional)

        Returns:
            Nearby SRZone or None
        """
        if not zones:
            return None

        for zone in zones:
            if zone.contains_price(price):
                return zone

        return None

    def _generate_data_fingerprint(self, data: MarketData) -> str:
        """
        Generate fingerprint of market data for cache invalidation.

        Uses last candle timestamp and close price to detect new data.
        """
        if not data.data:
            return "empty"

        last_candle = data.data[-1]
        fingerprint = f"{last_candle.timestamp.isoformat()}_{last_candle.close:.6f}_{last_candle.volume:.2f}"
        return hashlib.sha256(fingerprint.encode()).hexdigest()[:16]

    def _calculate_ttl(self, timeframe: str) -> int:
        """
        Calculate cache TTL based on timeframe.

        Longer timeframes = longer TTL (data changes less frequently).
        """
        ttl_map = {
            "1m": 300,      # 5 minutes
            "5m": 900,      # 15 minutes
            "15m": 1800,    # 30 minutes
            "30m": 3600,    # 1 hour
            "1h": 7200,     # 2 hours
            "4h": 14400,    # 4 hours
            "1d": 86400,    # 1 day
        }
        return ttl_map.get(timeframe, 3600)  # Default 1 hour

