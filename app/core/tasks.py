"""
Background task manager for periodic signal scanning.

Uses asyncio for background scanning and Discord alerts.
"""

import asyncio
from typing import Optional, Callable

from app.services.pattern_detection import PatternDetectionService
from app.services.discord_service import DiscordBotService
from app.config.settings import get_settings
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

        # Track sent alerts to avoid duplicates
        # Key: ticker + timeframe + timestamp + entry_price
        self._sent_alerts: set[str] = set()

        logger.info(
            f"BackgroundTaskManager initialized: "
            f"scan_interval={self.settings.scan_interval_minutes}min"
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

    def _is_alert_sent(self, setup) -> bool:
        """
        Check if an alert has already been sent for this setup.

        Args:
            setup: SignalResponse setup

        Returns:
            True if alert was already sent
        """
        key = self._get_setup_key(setup)
        return key in self._sent_alerts

    def _mark_alert_sent(self, setup):
        """
        Mark an alert as sent for this setup.

        Args:
            setup: SignalResponse setup
        """
        key = self._get_setup_key(setup)
        self._sent_alerts.add(key)

        # Keep set size manageable - remove old entries if too many
        # This prevents unbounded memory growth
        if len(self._sent_alerts) > 1000:
            # Remove oldest entries (first 100)
            keys_to_remove = list(self._sent_alerts)[:100]
            for key in keys_to_remove:
                self._sent_alerts.remove(key)
            logger.debug(f"Pruned sent alerts cache, now {len(self._sent_alerts)} entries")

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

                for ticker in self.settings.default_tickers:
                    if not self._running:
                        break

                    try:
                        setups = await self.pattern_service.detect_a_plus_setups(
                            ticker=ticker,
                            timeframe="15m",
                            min_confidence=0.75  # Higher threshold for auto-alerts
                        )

                        if setups:
                            logger.info(f"Found {len(setups)} A+ setup(s) for {ticker}")

                            # Filter out already-sent setups
                            new_setups = [s for s in setups if not self._is_alert_sent(s)]

                            if new_setups:
                                logger.info(f"Sending {len(new_setups)} new alert(s) for {ticker}")
                                total_setups += len(new_setups)

                                # Send Discord alerts only for new setups
                                for setup in new_setups:
                                    await self.discord_service.send_alert(setup)
                                    self._mark_alert_sent(setup)

                                    # Call callback if registered
                                    if self.on_setup_found:
                                        await self.on_setup_found(setup)
                            else:
                                logger.debug(f"No new setups for {ticker} (all already sent)")

                    except Exception as e:
                        logger.error(f"Error scanning {ticker}: {e}")

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

        for ticker in self.settings.default_tickers:
            try:
                setups = await self.pattern_service.detect_a_plus_setups(
                    ticker=ticker,
                    timeframe="15m",
                    min_confidence=0.7
                )

                if setups:
                    # Filter out already-sent setups
                    new_setups = [s for s in setups if not self._is_alert_sent(s)]
                    old_setups = [s for s in setups if self._is_alert_sent(s)]

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
                            await self.discord_service.send_alert(setup)
                            self._mark_alert_sent(setup)

                    logger.info(
                        f"{ticker}: {len(new_setups)} new, {len(old_setups)} already sent"
                    )

                else:
                    results[ticker] = {"count": 0, "new_count": 0}

            except Exception as e:
                logger.error(f"Error scanning {ticker}: {e}")
                results[ticker] = {"error": str(e)}

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

    def clear_sent_alerts(self):
        """
        Clear the sent alerts cache.

        This allows all setups to be sent again on the next scan.
        Useful for testing or after server restart.
        """
        count = len(self._sent_alerts)
        self._sent_alerts.clear()
        logger.info(f"Cleared {count} sent alerts from cache")

    def get_sent_alerts_count(self) -> int:
        """Get the number of alerts currently tracked in the cache."""
        return len(self._sent_alerts)
