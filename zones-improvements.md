 I'll analyze this support and resistance detection algorithm for flaws and provide concrete improvements. Let me first search for best practices and common issues in SR detection algorithms to ensure my recommendations are grounded in current research.  
 Based on my analysis of your algorithm and research into best practices, I've identified several critical flaws in your current implementation. The issues you mentioned (zones too large, unclear boundaries, missing new zones) stem from fundamental architectural decisions in the clustering and pivot detection phases.

Here is a comprehensive code implementation guide to address these issues:

---

## Critical Flaws & Solutions

### 1. **Fixed Percentage Threshold Problem**
Your current algorithm uses `avg_price × sensitivity` (e.g., 5% of average price). This creates zones that are too wide for high-priced assets and too narrow for low-priced assets.

**Solution: Implement ATR-based dynamic thresholds**

```python
import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering
from dataclasses import dataclass
from typing import List, Tuple, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

@dataclass
class SRZone:
    level: float
    zone_type: str  # 'SUPPORT' or 'RESISTANCE'
    strength: float
    touches: int
    first_touch_date: datetime
    last_touch_date: datetime
    price_range: Tuple[float, float]
    pivot_indices: List[int]  # Track which candles formed this zone
    is_fresh: bool
    volume_at_zone: float  # NEW: Volume confirmation metric
    
    @property
    def is_strong(self) -> bool:
        return self.strength > 0.7
    
    def contains_price(self, price: float) -> bool:
        return self.price_range[0] <= price <= self.price_range[1]
    
    def distance_to_price(self, price: float) -> float:
        return price - self.level


class ImprovedSRDetectionService:
    def __init__(
        self,
        sensitivity_atr_multiplier: float = 0.5,  # NEW: ATR-based instead of fixed %
        min_touches: int = 2,
        lookback_pivots: int = 5,
        min_strength: float = 0.3,  # Raised default to filter noise
        zone_width_atr_multiplier: float = 0.25,  # NEW: Dynamic width
        recency_weight: float = 0.4,  # Increased from 0.3
        touch_weight: float = 0.6,   # Explicit weighting
        min_pivot_distance_bars: int = 10,  # NEW: Prevent overlapping pivots
        max_zone_age_bars: int = 500,  # NEW: Expire old zones
        use_volume_confirmation: bool = True,  # NEW: Volume filter
        round_number_proximity: float = 0.001  # NEW: Psychological levels
    ):
        self.sensitivity_atr = sensitivity_atr_multiplier
        self.min_touches = min_touches
        self.lookback = lookback_pivots
        self.min_strength = min_strength
        self.zone_width_atr = zone_width_atr_multiplier
        self.recency_weight = recency_weight
        self.touch_weight = touch_weight
        self.min_pivot_distance = min_pivot_distance_bars
        self.max_zone_age = max_zone_age_bars
        self.use_volume = use_volume_confirmation
        self.round_number_proximity = round_number_proximity
        
    def calculate_atr(self, candles: pd.DataFrame, period: int = 14) -> float:
        """Calculate Average True Range for dynamic thresholding"""
        highs = candles['high']
        lows = candles['low']
        closes = candles['close']
        
        tr1 = highs - lows
        tr2 = abs(highs - closes.shift())
        tr3 = abs(lows - closes.shift())
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean().iloc[-1]
        
        return atr if not np.isnan(atr) else (highs - lows).mean()
    
    def detect_pivots_improved(self, candles: pd.DataFrame) -> Tuple[List[dict], List[dict]]:
        """
        IMPROVED: Multi-timeframe pivot detection with volume confirmation
        and minimum distance enforcement to prevent cluster crowding
        """
        pivot_highs = []
        pivot_lows = []
        
        highs = candles['high'].values
        lows = candles['low'].values
        volumes = candles.get('volume', pd.Series([1]*len(candles))).values
        timestamps = candles.index
        
        # Calculate average volume for confirmation
        avg_volume = np.mean(volumes) if self.use_volume else 0
        
        last_pivot_high_idx = -self.min_pivot_distance
        last_pivot_low_idx = -self.min_pivot_distance
        
        for i in range(self.lookback, len(candles) - self.lookback):
            # Pivot High Detection with volume confirmation
            current_high = highs[i]
            neighborhood_highs = highs[i - self.lookback:i + self.lookback + 1]
            
            is_pivot_high = current_high == np.max(neighborhood_highs)
            
            # Ensure minimum distance from previous pivot
            if is_pivot_high and (i - last_pivot_high_idx) >= self.min_pivot_distance:
                # Volume confirmation: pivot should have above-average volume
                volume_confirmed = (not self.use_volume) or (volumes[i] > avg_volume * 0.8)
                
                if volume_confirmed:
                    pivot_highs.append({
                        'price': float(current_high),
                        'timestamp': timestamps[i],
                        'index': i,
                        'volume': volumes[i],
                        'candle': candles.iloc[i]
                    })
                    last_pivot_high_idx = i
            
            # Pivot Low Detection with volume confirmation
            current_low = lows[i]
            neighborhood_lows = lows[i - self.lookback:i + self.lookback + 1]
            
            is_pivot_low = current_low == np.min(neighborhood_lows)
            
            if is_pivot_low and (i - last_pivot_low_idx) >= self.min_pivot_distance:
                volume_confirmed = (not self.use_volume) or (volumes[i] > avg_volume * 0.8)
                
                if volume_confirmed:
                    pivot_lows.append({
                        'price': float(current_low),
                        'timestamp': timestamps[i],
                        'index': i,
                        'volume': volumes[i],
                        'candle': candles.iloc[i]
                    })
                    last_pivot_low_idx = i
        
        return pivot_highs, pivot_lows
    
    def calculate_dynamic_threshold(self, candles: pd.DataFrame, pivots: List[dict]) -> float:
        """
        IMPROVED: Use ATR instead of fixed percentage for dynamic clustering threshold
        """
        if not pivots:
            return 0.0
        
        atr = self.calculate_atr(candles)
        current_price = candles['close'].iloc[-1]
        
        # Dynamic threshold based on volatility
        threshold = atr * self.sensitivity_atr
        
        # Ensure minimum threshold based on price level (for very low volatility)
        min_threshold = current_price * 0.001  # 0.1% minimum
        threshold = max(threshold, min_threshold)
        
        return threshold
    
    def cluster_pivots_optimized(self, pivots: List[dict], candles: pd.DataFrame) -> List[dict]:
        """
        IMPROVED: Hierarchical clustering with dynamic threshold and 
        post-processing merge for cleaner zones
        """
        if len(pivots) < self.min_touches:
            return []
        
        prices = np.array([p['price'] for p in pivots]).reshape(-1, 1)
        threshold = self.calculate_dynamic_threshold(candles, pivots)
        
        # If threshold is too small, fall back to distance-based grouping
        if threshold <= 0:
            return self._fallback_clustering(pivots)
        
        try:
            clustering = AgglomerativeClustering(
                n_clusters=None,
                distance_threshold=threshold,
                linkage='average',
                metric='euclidean'
            )
            
            labels = clustering.fit_predict(prices)
            
            # Group pivots by cluster
            clusters = {}
            for idx, label in enumerate(labels):
                if label not in clusters:
                    clusters[label] = []
                clusters[label].append(pivots[idx])
            
            # Post-process: merge clusters that are too close (within 0.5 * threshold)
            merged_clusters = self._merge_nearby_clusters(clusters, threshold * 0.5)
            
            return list(merged_clusters.values())
            
        except Exception as e:
            logger.warning(f"Clustering failed: {e}, using fallback")
            return self._fallback_clustering(pivots)
    
    def _merge_nearby_clusters(self, clusters: dict, merge_threshold: float) -> dict:
        """
        NEW: Post-processing to merge clusters that are statistically similar
        but split due to clustering artifacts
        """
        if not clusters:
            return clusters
        
        cluster_centers = {
            label: np.mean([p['price'] for p in pivots])
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
    
    def _fallback_clustering(self, pivots: List[dict]) -> List[dict]:
        """Fallback: group by proximity within 0.1% of price"""
        if not pivots:
            return []
        
        sorted_pivots = sorted(pivots, key=lambda x: x['price'])
        clusters = []
        current_cluster = [sorted_pivots[0]]
        
        for pivot in sorted_pivots[1:]:
            avg_price = np.mean([p['price'] for p in current_cluster])
            if abs(pivot['price'] - avg_price) / avg_price < 0.001:
                current_cluster.append(pivot)
            else:
                clusters.append(current_cluster)
                current_cluster = [pivot]
        
        if current_cluster:
            clusters.append(current_cluster)
        
        return clusters
    
    def calculate_zone_strength_improved(self, cluster_pivots: List[dict], 
                                        total_candles: int,
                                        candles: pd.DataFrame) -> dict:
        """
        IMPROVED: Multi-factor strength calculation with time decay and
        reaction intensity (how price reacted at the level)
        """
        if not cluster_pivots:
            return {'strength': 0, 'is_fresh': False}
        
        touches = len(cluster_pivots)
        indices = sorted([p['index'] for p in cluster_pivots])
        
        # Factor 1: Touch count (capped at 5 for max score)
        touch_score = min(touches / 5.0, 1.0)
        
        # Factor 2: Recency with exponential decay (more recent = stronger)
        last_idx = indices[-1]
        bars_ago = total_candles - last_idx
        
        # Exponential decay: recent touches matter more
        recency_score = np.exp(-bars_ago / 100)  # Decay over ~100 bars
        
        # Factor 3: Time span (zones that hold over time are stronger)
        first_idx = indices[0]
        time_span = (last_idx - first_idx) / total_candles  # 0 to 1
        persistence_score = min(time_span * 2, 1.0)  # Bonus for long-lived zones
        
        # Factor 4: Volume confirmation (if available)
        volume_score = 1.0
        if self.use_volume:
            avg_volume = np.mean([p['volume'] for p in cluster_pivots])
            total_avg = candles['volume'].mean() if 'volume' in candles else avg_volume
            volume_score = min(avg_volume / total_avg, 1.5) / 1.5  # Normalize
        
        # Combined weighted score
        strength = (
            touch_score * self.touch_weight +
            recency_score * self.recency_weight +
            persistence_score * 0.2 +
            volume_score * 0.1
        )
        
        # Cap at 1.0
        strength = min(strength, 1.0)
        
        # Freshness: zone tested recently but not too recently
        is_fresh = 10 < bars_ago < self.max_zone_age
        
        return {
            'strength': strength,
            'is_fresh': is_fresh,
            'last_touch_bars_ago': bars_ago,
            'touch_score': touch_score,
            'recency_score': recency_score
        }
    
    def calculate_zone_width(self, level: float, candles: pd.DataFrame, 
                           zone_type: str) -> Tuple[float, float]:
        """
        IMPROVED: ATR-based zone width for consistent visual representation
        across different price levels and volatilities
        """
        atr = self.calculate_atr(candles)
        half_width = atr * self.zone_width_atr
        
        if zone_type == 'SUPPORT':
            # Support extends more below (buyers defend)
            lower = level - half_width
            upper = level + half_width * 0.5
        else:  # RESISTANCE
            # Resistance extends more above (sellers defend)
            lower = level - half_width * 0.5
            upper = level + half_width
        
        return (lower, upper)
    
    def detect_zones(self, candles: pd.DataFrame) -> List[SRZone]:
        """
        Main detection pipeline with all improvements integrated
        """
        if len(candles) < self.lookback * 2:
            logger.warning("Insufficient data for pivot detection")
            return []
        
        # Step 1: Detect pivots with volume and distance filtering
        pivot_highs, pivot_lows = self.detect_pivots_improved(candles)
        
        zones = []
        
        # Step 2 & 3: Cluster and create zones for highs (resistance)
        resistance_clusters = self.cluster_pivots_optimized(pivot_highs, candles)
        for cluster in resistance_clusters:
            if len(cluster) >= self.min_touches:
                zone = self._create_zone_from_cluster(cluster, 'RESISTANCE', candles)
                if zone and zone.strength >= self.min_strength:
                    zones.append(zone)
        
        # Step 2 & 3: Cluster and create zones for lows (support)
        support_clusters = self.cluster_pivots_optimized(pivot_lows, candles)
        for cluster in support_clusters:
            if len(cluster) >= self.min_touches:
                zone = self._create_zone_from_cluster(cluster, 'SUPPORT', candles)
                if zone and zone.strength >= self.min_strength:
                    zones.append(zone)
        
        # Step 4: Post-processing - remove overlapping zones
        zones = self._remove_overlapping_zones(zones)
        
        # Step 5: Sort by strength
        zones.sort(key=lambda x: x.strength, reverse=True)
        
        return zones
    
    def _create_zone_from_cluster(self, cluster: List[dict], zone_type: str, 
                                  candles: pd.DataFrame) -> Optional[SRZone]:
        """Create SRZone object from cluster of pivots"""
        prices = [p['price'] for p in cluster]
        level = float(np.mean(prices))
        
        # Check for round number proximity (psychological levels)
        round_number_factor = self._check_round_number_proximity(level)
        
        # Calculate strength
        strength_data = self.calculate_zone_strength_improved(
            cluster, len(candles), candles
        )
        
        # Boost strength slightly for psychological levels
        adjusted_strength = min(strength_data['strength'] * (1 + round_number_factor * 0.1), 1.0)
        
        # Calculate price range
        price_range = self.calculate_zone_width(level, candles, zone_type)
        
        return SRZone(
            level=level,
            zone_type=zone_type,
            strength=adjusted_strength,
            touches=len(cluster),
            first_touch_date=cluster[0]['timestamp'],
            last_touch_date=cluster[-1]['timestamp'],
            price_range=price_range,
            pivot_indices=[p['index'] for p in cluster],
            is_fresh=strength_data['is_fresh'],
            volume_at_zone=np.mean([p.get('volume', 0) for p in cluster])
        )
    
    def _check_round_number_proximity(self, price: float) -> float:
        """
        NEW: Check if price is near psychological round numbers (00, 50, 000)
        Returns 0-1 factor indicating proximity to round number
        """
        # Convert to string to check decimal places
        price_str = f"{price:.10f}".rstrip('0')
        
        # Check various round number patterns
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
                return 0.8 * (1.0 - (abs(decimal_part - target) / self.round_number_proximity))
        
        return 0.0
    
    def _remove_overlapping_zones(self, zones: List[SRZone], 
                                   overlap_threshold: float = 0.7) -> List[SRZone]:
        """
        NEW: Remove or merge zones that overlap significantly
        Keep the stronger zone when overlap occurs
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
                    if overlap_size / min_size > overlap_threshold:
                        overlap_found = True
                        break
            
            if not overlap_found:
                filtered.append(zone)
        
        return filtered
    
    def find_nearby_zone(self, price: float, zones: List[SRZone], 
                        tolerance: Optional[float] = None) -> Optional[SRZone]:
        """Find zone near given price with tolerance"""
        if tolerance is None:
            tolerance = self.calculate_atr(pd.DataFrame()) * self.sensitivity_atr
        
        nearby = [z for z in zones if abs(z.level - price) <= tolerance]
        return min(nearby, key=lambda x: abs(x.level - price)) if nearby else None


# Usage Example
async def main():
    # Load your OHLCV data into a pandas DataFrame
    # columns: ['open', 'high', 'low', 'close', 'volume']
    candles = pd.read_csv('market_data.csv', index_col='timestamp', parse_dates=True)
    
    # Initialize with improved parameters
    service = ImprovedSRDetectionService(
        sensitivity_atr_multiplier=0.5,  # 0.5 ATR units
        min_touches=2,
        lookback_pivots=5,
        min_strength=0.4,  # Filter weak zones
        zone_width_atr_multiplier=0.25,  # Tighter zones
        min_pivot_distance_bars=10,  # Prevent pivot crowding
        use_volume_confirmation=True
    )
    
    zones = service.detect_zones(candles)
    
    print(f"Found {len(zones)} zones:")
    for zone in zones:
        print(f"{zone.zone_type}: {zone.level:.4f} "
              f"(strength: {zone.strength:.2f}, touches: {zone.touches}) "
              f"Range: {zone.price_range[0]:.4f} - {zone.price_range[1]:.4f}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

---

## Key Improvements Explained

### 1. **ATR-Based Dynamic Thresholds** (Fixes "zones too large")
- **Problem**: Fixed 5% of average price creates massive zones for high-priced assets (e.g., $50,000 Bitcoin → $2,500 zone width)
- **Solution**: Use Average True Range (ATR) which adapts to current volatility. A 0.5 ATR threshold means zones are proportionally consistent across assets and time periods.

### 2. **Minimum Pivot Distance** (Fixes "unclear zones")
- **Problem**: Multiple pivots in consecutive candles create messy, overlapping clusters
- **Solution**: Enforce minimum 10-bar distance between pivots to ensure each touch is meaningfully distinct

### 3. **Post-Processing Merge** (Fixes clustering artifacts)
- **Problem**: Hierarchical clustering sometimes splits what should be one zone into two due to chain effects
- **Solution**: After initial clustering, merge clusters whose centers are within 50% of the threshold distance

### 4. **Volume Confirmation** (Fixes false zones)
- **Problem**: Low-volume pivots create unreliable zones
- **Solution**: Require pivots to have at least 80% of average volume to be considered valid

### 5. **Overlap Removal** (Fixes zone clarity)
- **Problem**: Support and resistance zones often overlap, creating confusion
- **Solution**: Post-detection filtering that keeps the stronger zone when overlaps exceed 70%

### 6. **Psychological Levels Boost** (Fixes missing key levels)
- **Problem**: Algorithm misses obvious round numbers (1.0000, 1.5000, etc.) that traders actually watch
- **Solution**: Detect proximity to round numbers and boost strength score, ensuring these critical levels are retained

### 7. **Exponential Recency Decay** (Fixes stale zones)
- **Problem**: Linear recency weighting doesn't distinguish between "touched 10 bars ago" vs "touched 200 bars ago"
- **Solution**: Exponential decay ensures truly recent zones get much higher scores

---

## Configuration Guidelines

| Market Type | `sensitivity_atr` | `zone_width_atr` | `lookback` | `min_pivot_distance` |
|-------------|------------------|------------------|------------|---------------------|
| Forex (M15) | 0.3 - 0.5 | 0.15 - 0.25 | 5 | 10 |
| Crypto (H1) | 0.8 - 1.2 | 0.4 - 0.6 | 5 | 12 |
| Stocks (D1) | 0.5 - 0.8 | 0.25 - 0.4 | 3 | 5 |
| Scalping (M1) | 0.2 - 0.3 | 0.1 - 0.15 | 3 | 5 |

These changes should resolve the issues of zones being too large, unclear boundaries, and missing new zones by making the algorithm adaptive to market conditions rather than using fixed percentages.