"""
Background task manager for periodic signal scanning.

Uses asyncio for background scanning and Discord alerts.
"""

import asyncio
from typing import Optional, Callable
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.pattern_detection import PatternDetectionService
from app.services.discord_service import DiscordBotService
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

        logger.info(
            f"BackgroundTaskManager initialized: "
            f"scan_interval={self.settings.scan_interval_minutes}min, "
            f"scan_timeframe={self.settings.scan_timeframe}, "
            f"scan_profile={self.settings.scan_sr_profile}"
        )

    def _get_setup_key(self, setup) -> str:
        """
        Generate a unique key for a setup to track sent alerts.

        Args:
            setup: SignalResponse setup

        Returns:
            Unique string key for this setup
        """
        return (
            f"{setup.big_wick.ticker}|"
            f"{setup.big_wick.timeframe}|"
            f"{setup.big_wick.timestamp.isoformat()}|"
            f"{setup.big_wick.entry_price:.5f}|"
            f"{'buy' if setup.is_buy else 'sell'}"
        )

    async def _is_alert_sent(self, db: AsyncSession, setup) -> bool:
        """
        Check if an alert has already been sent for this setup.

        Checks both the in-memory cache (fast path) and database (persistent).

        Args:
            db: Database session
            setup: SignalResponse setup

        Returns:
            True if alert was already sent
        """
        # Fast path: check in-memory cache first
        key = self._get_setup_key(setup)
        if key in self._recent_alerts_cache:
            return True

        # Slow path: check database
        components = SentAlert.create_key_components(setup)
        result = await db.execute(
            select(SentAlert).where(
                SentAlert.ticker == components['ticker'],
                SentAlert.timeframe == components['timeframe'],
                SentAlert.candle_timestamp == components['candle_timestamp'],
                SentAlert.entry_price == components['entry_price'],
                SentAlert.direction == components['direction']
            )
        )
        return result.first() is not None

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

                                # Filter out already-sent setups
                                new_setups = []
                                for setup in setups:
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
                        # Filter out already-sent setups
                        new_setups = []
                        old_setups = []
                        for setup in setups:
                            if await self._is_alert_sent(db, setup):
                                old_setups.append(setup)
                            else:
                                new_setups.append(setup)

                        results[ticker] = {
                            "count": len(setups),
                            "new_count": len(new_setups),
                            "buy_signals": len([s for s in setups if s.is_buy]),
                            "sell_signals": len([s for s in setups if s.is_sell]),
                            "setups": setups
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
