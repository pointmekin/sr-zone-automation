"""
Background task manager for periodic signal scanning.

Uses asyncio for background scanning and Discord alerts.
"""

import asyncio
from datetime import timedelta
from typing import Optional, Callable
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.pattern_detection import PatternDetectionService
from app.services.discord_service import DiscordBotService
from app.services.data_service import DataService
from app.config.settings import get_settings
from app.db.session import get_db
from app.db.models.sent_alert import SentAlert
from loguru import logger


class BackgroundTaskManager:
    """
    Manager for background scanning tasks.

    Runs periodic scans for A+ setups and sends Discord alerts
    when high-confidence setups are found.
    """

    def __init__(
        self,
        pattern_service: PatternDetectionService,
        discord_service: DiscordBotService
    ):
        """
        Initialize the task manager.

        Args:
            pattern_service: Pattern detection service
            discord_service: Discord bot service
        """
        self.pattern_service = pattern_service
        self.discord_service = discord_service
        self.settings = get_settings()

        self._scan_task: asyncio.Task | None = None
        self._running = False
        self._scan_interval = self.settings.scan_interval_minutes * 60  # Convert to seconds

        # Callback for when A+ setups are found
        self.on_setup_found: Callable | None = None

        # In-memory cache for recently sent alerts (reduces DB queries)
        self._recent_alerts_cache: set[str] = set()
        self._cache_max_size = 1000

        # Create pattern service with scan profile for periodic scans
        from app.services.pattern_detection import PatternDetectionService
        self.scan_pattern_service = PatternDetectionService(
            sr_profile=self.settings.scan_sr_profile  # Use configured profile for scans
        )

        # Data service for fetching current price
        self.data_service = DataService()

        logger.info(
            f"BackgroundTaskManager initialized: "
            f"scan_interval={self.settings.scan_interval_minutes}min, "
            f"scan_timeframe={self.settings.scan_timeframe}, "
            f"scan_profile={self.settings.scan_sr_profile}"
        )

    def _get_setup_key(self, setup) -> str:
        """
        Generate a unique key for a setup to track sent alerts.

        Uses zone level (rounded) instead of candle timestamp to allow
        re-alerts when price returns to test the same zone.

        Args:
            setup: SignalResponse setup

        Returns:
            Unique string key for this setup (zone-based)
        """
        # Round zone level to 5 decimal places for grouping (~1 pip for EURUSD)
        zone_level_rounded = round(setup.big_wick.sr_zone.level, 5)
        return (
            f"{setup.big_wick.ticker}|"
            f"{setup.big_wick.timeframe}|"
            f"{zone_level_rounded}|"
            f"{'buy' if setup.is_buy else 'sell'}"
        )

    async def _is_alert_sent(self, db: AsyncSession, setup) -> bool:
        """
        Check if an alert has already been sent for this setup recently.

        Checks both the in-memory cache (fast path) and database (persistent).
        Alerts expire after 4 hours to allow re-alerts on zone re-tests.

        Args:
            db: Database session
            setup: SignalResponse setup

        Returns:
            True if alert was already sent (within last 4 hours)
        """
        # Fast path: check in-memory cache first
        key = self._get_setup_key(setup)
        if key in self._recent_alerts_cache:
            return True

        # Slow path: check database (with 4-hour expiry)
        # Since we now use zone-based keys, we need to query by zone level
        zone_level_rounded = round(setup.big_wick.sr_zone.level, 5)

        four_hours_ago = datetime.utcnow().replace(tzinfo=None) - timedelta(hours=4)

        # Query for recent alerts at this zone level
        result = await db.execute(
            select(SentAlert).where(
                SentAlert.ticker == setup.big_wick.ticker,
                SentAlert.timeframe == setup.big_wick.timeframe,
                SentAlert.direction == ('buy' if setup.is_buy else 'sell'),
                SentAlert.created_at >= four_hours_ago
            ).order_by(SentAlert.created_at.desc())
        )
        recent_alerts = result.all()

        # Check if any recent alert is near the same zone level (within 0.0005)
        for alert in recent_alerts:
            # Parse entry_price to get zone level approximation
            try:
                alert_entry_price = float(alert.entry_price)
                if abs(alert_entry_price - zone_level_rounded) <= 0.0005:
                    return True
            except (ValueError, TypeError):
                continue

        return False

    async def _mark_alert_sent(self, db: AsyncSession, setup):
        """
        Mark an alert as sent for this setup by storing in database.

        Args:
            db: Database session
            setup: SignalResponse setup
        """
        key = self._get_setup_key(setup)
        components = SentAlert.create_key_components(setup)

        # Add to database
        sent_alert = SentAlert(
            ticker=components['ticker'],
            timeframe=components['timeframe'],
            candle_timestamp=components['candle_timestamp'],
            entry_price=components['entry_price'],
            direction=components['direction'],
            confidence=components.get('confidence'),
            sent_successfully=True
        )
        db.add(sent_alert)
        await db.flush()  # Get the ID without committing

        # Add to in-memory cache
        self._recent_alerts_cache.add(key)

        # Prune cache if too large
        if len(self._recent_alerts_cache) > self._cache_max_size:
            # Remove oldest entries (convert set to list and slice)
            keys_to_remove = list(self._recent_alerts_cache)[:100]
            for k in keys_to_remove:
                self._recent_alerts_cache.remove(k)
            logger.debug(f"Pruned alerts cache, now {len(self._recent_alerts_cache)} entries")

    async def start_scanning(self):
        """Start the background scanning task."""
        if self._running:
            logger.warning("Background scanning already running")
            return

        self._running = True
        self._scan_task = asyncio.create_task(self._scan_loop())

        logger.info("Background scanning started")

    async def stop_scanning(self):
        """Stop the background scanning task."""
        if not self._running:
            return

        self._running = False

        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass

        logger.info("Background scanning stopped")

    async def _scan_loop(self):
        """Main scanning loop."""
        while self._running:
            try:
                logger.info("Starting periodic scan for A+ setups")

                total_setups = 0

                # Get database session for this scan
                async for db in get_db():
                    for ticker in self.settings.default_tickers:
                        if not self._running:
                            break

                        try:
                            setups = await self.scan_pattern_service.detect_a_plus_setups(
                                ticker=ticker,
                                timeframe=self.settings.scan_timeframe,  # Use configured timeframe (default: 1h)
                                min_confidence=self.settings.scan_min_confidence  # Use configured threshold (default: 0.75)
                            )

                            if setups:
                                logger.info(f"Found {len(setups)} A+ setup(s) for {ticker}")

                                # Filter by current price proximity (only alert if price is tradeable)
                                market_data = await self.data_service.fetch_data(
                                    ticker=ticker,
                                    timeframe=self.settings.scan_timeframe,
                                    lookback_bars=100
                                )

                                if not market_data.data:
                                    logger.warning(f"No current data available for {ticker}")
                                    continue

                                latest_close = market_data.data[-1].close

                                # Filter to setups where price is currently at/near zone
                                price_filtered_setups = []
                                for setup in setups:
                                    zone = setup.big_wick.sr_zone
                                    zone_lower, zone_upper = zone.price_range
                                    zone_half_width = (zone_upper - zone_lower) / 2

                                    # Check if price is in zone or near zone (1.5x half-width)
                                    price_in_zone = zone_lower <= latest_close <= zone_upper
                                    price_near = abs(latest_close - zone.level) <= zone_half_width * 1.5

                                    if price_in_zone or price_near:
                                        price_filtered_setups.append(setup)
                                    else:
                                        distance_pips = abs(latest_close - zone.level) * 10000
                                        logger.debug(
                                            f"Setup for {ticker} filtered out: price {latest_close:.5f} "
                                            f"is {distance_pips:.1f} pips from zone {zone.level:.5f}"
                                        )

                                logger.info(
                                    f"Price-filtered to {len(price_filtered_setups)} tradeable setup(s) for {ticker}"
                                )

                                # Filter out already-sent setups
                                new_setups = []
                                for setup in price_filtered_setups:
                                    if not await self._is_alert_sent(db, setup):
                                        new_setups.append(setup)

                                if new_setups:
                                    logger.info(f"Sending {len(new_setups)} new alert(s) for {ticker}")
                                    total_setups += len(new_setups)

                                    # Send Discord alerts only for new setups
                                    for setup in new_setups:
                                        await self.discord_service.send_alert(setup)
                                        await self._mark_alert_sent(db, setup)

                                        # Call callback if registered
                                        if self.on_setup_found:
                                            await self.on_setup_found(setup)
                                else:
                                    logger.debug(f"No new setups for {ticker} (all already sent)")

                        except Exception as e:
                            logger.error(f"Error scanning {ticker}: {e}")

                    # Commit all database changes at the end of the scan
                    await db.commit()

                    if total_setups > 0:
                        logger.info(f"Periodic scan complete: {total_setups} A+ setup(s) found")
                    else:
                        logger.info("Periodic scan complete: No A+ setups found")

                    # Wait for next scan
                    await asyncio.sleep(self._scan_interval)

            except asyncio.CancelledError:
                logger.info("Scan loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in scan loop: {e}")
                # Wait before retrying
                await asyncio.sleep(60)

    async def scan_once(self) -> dict:
        """
        Perform a one-time scan of all tickers.

        Only returns setups where price is currently at or near the SR zone.

        Returns:
            Dictionary with scan results
        """
        logger.info("Starting one-time scan")

        results = {}
        total_setups = 0

        # Get database session for this scan
        async for db in get_db():
            for ticker in self.settings.default_tickers:
                try:
                    setups = await self.pattern_service.detect_a_plus_setups(
                        ticker=ticker,
                        timeframe=self.settings.scan_timeframe,  # Use configured timeframe (default: 1h)
                        min_confidence=self.settings.scan_min_confidence  # Use configured threshold
                    )

                    if setups:
                        # Filter by current price proximity
                        market_data = await self.data_service.fetch_data(
                            ticker=ticker,
                            timeframe=self.settings.scan_timeframe,
                            lookback_bars=100
                        )

                        price_filtered_setups = []
                        if market_data.data:
                            latest_close = market_data.data[-1].close
                            for setup in setups:
                                zone = setup.big_wick.sr_zone
                                zone_lower, zone_upper = zone.price_range
                                zone_half_width = (zone_upper - zone_lower) / 2

                                price_in_zone = zone_lower <= latest_close <= zone_upper
                                price_near = abs(latest_close - zone.level) <= zone_half_width * 1.5

                                if price_in_zone or price_near:
                                    price_filtered_setups.append(setup)

                            logger.debug(
                                f"{ticker}: {len(setups)} total setups, "
                                f"{len(price_filtered_setups)} with price at/near zone"
                            )
                        else:
                            logger.warning(f"No current data for {ticker}")
                            price_filtered_setups = []

                        # Filter out already-sent setups
                        new_setups = []
                        old_setups = []
                        for setup in price_filtered_setups:
                            if await self._is_alert_sent(db, setup):
                                old_setups.append(setup)
                            else:
                                new_setups.append(setup)

                        results[ticker] = {
                            "count": len(price_filtered_setups),
                            "new_count": len(new_setups),
                            "buy_signals": len([s for s in price_filtered_setups if s.is_buy]),
                            "sell_signals": len([s for s in price_filtered_setups if s.is_sell]),
                            "setups": price_filtered_setups
                        }
                        total_setups += len(new_setups)

                        # Send alerts only for new high-confidence setups
                        for setup in new_setups:
                            if setup.combined_confidence >= 0.75:
                                try:
                                    await self.discord_service.send_alert(setup)
                                    await self._mark_alert_sent(db, setup)
                                except Exception as e:
                                    # Handle duplicate key errors or other DB errors
                                    logger.warning(f"Failed to mark alert as sent for {ticker}: {e}")
                                    await db.rollback()
                                    # Add to in-memory cache anyway to prevent retries
                                    self._recent_alerts_cache.add(self._get_setup_key(setup))

                        logger.info(
                            f"{ticker}: {len(new_setups)} new, {len(old_setups)} already sent"
                        )

                    else:
                        results[ticker] = {"count": 0, "new_count": 0}

                except Exception as e:
                    logger.error(f"Error scanning {ticker}: {e}")
                    results[ticker] = {"error": str(e)}

            # Commit all changes
            await db.commit()

        logger.info(f"One-time scan complete: {total_setups} A+ setup(s) found")

        return {
            "total_setups": total_setups,
            "results": results
        }

    def set_scan_interval(self, minutes: int):
        """
        Update the scan interval.

        Args:
            minutes: New interval in minutes
        """
        self._scan_interval = minutes * 60
        logger.info(f"Scan interval updated to {minutes} minutes")

    def is_running(self) -> bool:
        """Check if scanning is active."""
        return self._running

    def get_scan_interval_minutes(self) -> int:
        """Get current scan interval in minutes."""
        return self._scan_interval // 60

    async def clear_sent_alerts(self):
        """
        Clear the sent alerts cache (both memory and database).

        This allows all setups to be sent again on the next scan.
        Useful for testing or after server restart.
        """
        # Clear in-memory cache
        cache_count = len(self._recent_alerts_cache)
        self._recent_alerts_cache.clear()

        # Clear database
        async for db in get_db():
            from sqlalchemy import delete
            await db.execute(delete(SentAlert))
            await db.commit()

            # Get count of deleted rows
            result = await db.execute(select(SentAlert))
            db_count = len(result.all())

        logger.info(f"Cleared {cache_count} from cache, {db_count} from database")

    async def get_sent_alerts_count(self) -> int:
        """Get the number of alerts currently tracked in the database."""
        async for db in get_db():
            result = await db.execute(select(SentAlert))
            return len(result.all())
        return 0

    def get_cache_size(self) -> int:
        """Get the number of alerts currently in the in-memory cache."""
        return len(self._recent_alerts_cache)
