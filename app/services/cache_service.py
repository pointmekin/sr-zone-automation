"""
Caching services for expensive operations.

Provides LRU cache with TTL-based expiration for S/R zones and
pattern detection results to eliminate redundant calculations.
"""

import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Any

from app.models.signals import SRZone
from loguru import logger


class CacheEntry:
    """Generic cache entry with metadata."""

    def __init__(self, data: Any, ttl_seconds: int, metadata: dict = None):
        self.data = data
        self.created_at = datetime.utcnow()
        self.ttl_seconds = ttl_seconds
        self.metadata = metadata or {}

    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        age = (datetime.utcnow() - self.created_at).total_seconds()
        return age > self.ttl_seconds

    def age_seconds(self) -> float:
        """Get age of cache entry in seconds."""
        return (datetime.utcnow() - self.created_at).total_seconds()


class SRZoneCache:
    """
    Dedicated cache for S/R zones with smart invalidation.

    Caches SR zones by (ticker, timeframe, profile) with:
    - TTL-based expiration
    - Data version invalidation
    - Size limits with LRU eviction
    """

    def __init__(self, max_size: int = 100, default_ttl_seconds: int = 3600):
        """
        Initialize SR zone cache.

        Args:
            max_size: Maximum number of cached zone sets
            default_ttl_seconds: Default TTL in seconds (1 hour)
        """
        self._cache: dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._default_ttl = default_ttl_seconds
        self._access_times: dict[str, datetime] = {}

        # Track data versions for invalidation
        self._data_versions: dict[str, str] = {}  # key → version hash

        logger.info(
            f"SRZoneCache initialized: max_size={max_size}, "
            f"default_ttl={default_ttl_seconds}s"
        )

    def _generate_key(
        self,
        ticker: str,
        timeframe: str,
        profile: str
    ) -> str:
        """Generate cache key for SR zones."""
        return f"sr_zones:{ticker}:{timeframe}:{profile}"

    def _generate_data_version(
        self,
        ticker: str,
        timeframe: str,
        data_fingerprint: str
    ) -> str:
        """Generate version hash for market data."""
        # Combine ticker, timeframe, and data fingerprint
        version_str = f"{ticker}:{timeframe}:{data_fingerprint}"
        return hashlib.sha256(version_str.encode()).hexdigest()[:16]

    def get(
        self,
        ticker: str,
        timeframe: str,
        profile: str,
        data_version: Optional[str] = None
    ) -> Optional[List[SRZone]]:
        """
        Get cached SR zones.

        Args:
            ticker: Ticker symbol
            timeframe: Chart timeframe
            profile: SR detection profile
            data_version: Current data version (for invalidation)

        Returns:
            Cached zones or None if cache miss/invalid
        """
        key = self._generate_key(ticker, timeframe, profile)

        # Check if entry exists
        if key not in self._cache:
            logger.debug(f"SR zone cache miss: {key}")
            return None

        entry = self._cache[key]

        # Check expiration
        if entry.is_expired():
            logger.debug(f"SR zone cache expired: {key} (age: {entry.age_seconds():.1f}s)")
            self._remove(key)
            return None

        # Check data version (invalidate if underlying data changed)
        if data_version and self._data_versions.get(key) != data_version:
            logger.debug(f"SR zone cache invalidated (data version changed): {key}")
            self._remove(key)
            return None

        # Update access time for LRU
        self._access_times[key] = datetime.utcnow()

        logger.info(
            f"SR zone cache hit: {key} (age: {entry.age_seconds():.1f}s, "
            f"{len(entry.data)} zones)"
        )
        return entry.data

    def set(
        self,
        ticker: str,
        timeframe: str,
        profile: str,
        zones: List[SRZone],
        ttl_seconds: Optional[int] = None,
        data_version: Optional[str] = None
    ) -> None:
        """
        Cache SR zones.

        Args:
            ticker: Ticker symbol
            timeframe: Chart timeframe
            profile: SR detection profile
            zones: SR zones to cache
            ttl_seconds: Custom TTL (uses default if None)
            data_version: Version hash of source data
        """
        key = self._generate_key(ticker, timeframe, profile)
        ttl = ttl_seconds or self._default_ttl

        # Evict if at capacity
        if len(self._cache) >= self._max_size and key not in self._cache:
            self._evict_lru()

        # Store cache entry
        entry = CacheEntry(
            data=zones,
            ttl_seconds=ttl,
            metadata={
                "ticker": ticker,
                "timeframe": timeframe,
                "profile": profile,
                "zone_count": len(zones)
            }
        )
        self._cache[key] = entry
        self._access_times[key] = datetime.utcnow()

        # Store data version if provided
        if data_version:
            self._data_versions[key] = data_version

        logger.info(
            f"SR zone cached: {key} ({len(zones)} zones, TTL: {ttl}s)"
        )

    def invalidate(
        self,
        ticker: Optional[str] = None,
        timeframe: Optional[str] = None,
        profile: Optional[str] = None
    ) -> int:
        """
        Invalidate cache entries matching criteria.

        Args:
            ticker: Filter by ticker (None = all)
            timeframe: Filter by timeframe (None = all)
            profile: Filter by profile (None = all)

        Returns:
            Number of entries invalidated
        """
        keys_to_remove = []

        for key in self._cache.keys():
            parts = key.split(":")
            if len(parts) >= 4:
                _, k_ticker, k_timeframe, k_profile = parts[:4]

                if ticker and k_ticker != ticker:
                    continue
                if timeframe and k_timeframe != timeframe:
                    continue
                if profile and k_profile != profile:
                    continue

                keys_to_remove.append(key)

        for key in keys_to_remove:
            self._remove(key)

        logger.info(f"Invalidated {len(keys_to_remove)} SR zone cache entries")
        return len(keys_to_remove)

    def _remove(self, key: str) -> None:
        """Remove cache entry."""
        self._cache.pop(key, None)
        self._access_times.pop(key, None)
        self._data_versions.pop(key, None)

    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if not self._access_times:
            return

        lru_key = min(self._access_times.items(), key=lambda x: x[1])[0]
        logger.debug(f"Evicting LRU cache entry: {lru_key}")
        self._remove(lru_key)

    def clear(self) -> None:
        """Clear all cached entries."""
        count = len(self._cache)
        self._cache.clear()
        self._access_times.clear()
        self._data_versions.clear()
        logger.info(f"Cleared {count} SR zone cache entries")

    def get_stats(self) -> dict:
        """Get cache statistics."""
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "entries": [
                {
                    "key": key,
                    "age_seconds": entry.age_seconds(),
                    "ttl_remaining": max(0, entry.ttl_seconds - entry.age_seconds()),
                    "metadata": entry.metadata
                }
                for key, entry in self._cache.items()
            ]
        }
