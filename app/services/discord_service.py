"""
Discord bot service for real-time trading alerts.

Sends alerts when A+ setups are detected and provides commands
 for manual scanning and statistics.
"""

import asyncio
from typing import Optional

import discord
from discord.ext import commands

from app.models.signals import SignalResponse, SRZone
from app.services.pattern_detection import PatternDetectionService
from app.config.settings import get_settings
from app.config.constants import DISCORD_COLORS
from loguru import logger


class DiscordBot(commands.Bot):
    """
    Discord bot for trading alerts.

    Provides commands for:
    - Manual signal scanning
    - Displaying statistics
    - Managing watchlists
    """

    def __init__(self, pattern_service: PatternDetectionService):
        """
        Initialize the Discord bot.

        Args:
            pattern_service: Pattern detection service for scanning
        """
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents
        )

        self.pattern_service = pattern_service
        self.settings = get_settings()
        self._channel_id = self.settings.discord_channel_id

    async def setup_hook(self):
        """Set up bot hooks when ready."""
        await self.add_cog(TradingCommands(self))
        logger.info("Discord bot commands loaded")

    async def send_a_plus_alert(
        self,
        setup: SignalResponse,
        channel_id: int | None = None
    ):
        """
        Send an A+ setup alert as a Discord embed.

        Args:
            setup: A+ setup to alert about
            channel_id: Channel to send to (default: from settings)
        """
        channel_id = channel_id or self._channel_id

        if not channel_id:
            logger.warning("No Discord channel ID configured, skipping alert")
            return

        try:
            channel = self.get_channel(channel_id)
            if not channel:
                logger.error(f"Could not find Discord channel {channel_id}")
                return

            # Create embed
            color = DISCORD_COLORS["buy"] if setup.is_buy else DISCORD_COLORS["sell"]
            direction = "📈 BUY" if setup.is_buy else "📉 SELL"

            embed = discord.Embed(
                title=f"🎯 A+ Setup Detected: {setup.big_wick.ticker}",
                description=f"{direction} Signal - {setup.big_wick.timeframe} Timeframe",
                color=color,
                timestamp=setup.detected_at
            )

            # Entry details
            embed.add_field(
                name="💰 Entry Details",
                value=(
                    f"**Entry Price:** {setup.big_wick.entry_price:.5f}\n"
                    f"**Stop Loss:** {setup.big_wick.stop_loss:.5f}\n"
                    f"**Take Profit:** {setup.big_wick.take_profit:.5f}\n"
                    f"**Risk-Reward:** 1:{setup.big_wick.risk_reward:.1f}"
                ),
                inline=False
            )

            # Signal quality
            embed.add_field(
                name="📊 Signal Quality",
                value=(
                    f"**Big Wick Ratio:** {setup.big_wick.wick_ratio:.2f}\n"
                    f"**S/R Zone:** {setup.big_wick.sr_zone.zone_type.value.upper()}\n"
                    f"**Zone Level:** {setup.big_wick.sr_zone.level:.5f}\n"
                    f"**Fresh Zone:** {'✅' if setup.big_wick.sr_zone.is_fresh else '❌'}"
                ),
                inline=False
            )

            # Confidence
            confidence_percent = setup.combined_confidence * 100
            embed.add_field(
                name="🎲 Confidence",
                value=f"{confidence_percent:.0f}%",
                inline=False
            )

            # Footer with timestamp
            embed.set_footer(
                text=f"Signal Time: {setup.big_wick.timestamp.strftime('%Y-%m-%d %H:%M')}"
            )

            await channel.send(embed=embed)
            logger.info(f"Sent Discord alert for A+ setup: {setup.big_wick.ticker}")

        except Exception as e:
            logger.error(f"Failed to send Discord alert: {e}")

    async def send_message(
        self,
        message: str,
        channel_id: int | None = None
    ):
        """
        Send a simple text message to Discord.

        Args:
            message: Message to send
            channel_id: Channel to send to
        """
        channel_id = channel_id or self._channel_id

        if not channel_id:
            return

        try:
            channel = self.get_channel(channel_id)
            if channel:
                await channel.send(message)
                logger.info(f"Sent Discord message: {message[:50]}...")
        except Exception as e:
            logger.error(f"Failed to send Discord message: {e}")


class TradingCommands(commands.Cog):
    """Discord bot commands for trading."""

    def __init__(self, bot: DiscordBot):
        self.bot = bot
        self.pattern_service = bot.pattern_service

    @commands.command(name="scan")
    async def scan_signals(self, ctx: commands.Context, ticker: str = None):
        """
        Manually trigger scan for A+ setups.

        Usage: !scan [ticker]
        If ticker not provided, scans all default tickers.
        """
        await ctx.trigger_typing()

        if ticker:
            await ctx.send(f"🔍 Scanning {ticker} for A+ setups...")
            try:
                setups = await self.pattern_service.detect_a_plus_setups(
                    ticker=ticker,
                    timeframe="15m",
                    min_confidence=0.7
                )

                if setups:
                    await ctx.send(f"✅ Found {len(setups)} A+ setup(s) for {ticker}!")
                    for setup in setups[:3]:  # Max 3 to avoid spam
                        await self.bot.send_a_plus_alert(setup, ctx.channel.id)
                else:
                    await ctx.send(f"❌ No A+ setups found for {ticker}")

            except Exception as e:
                await ctx.send(f"❌ Error scanning {ticker}: {e}")
        else:
            await ctx.send("🔍 Scanning all tickers for A+ setups...")
            settings = get_settings()
            total_found = 0

            for t in settings.default_tickers[:3]:  # Limit to 3 for manual scan
                try:
                    setups = await self.pattern_service.detect_a_plus_setups(
                        ticker=t,
                        timeframe="15m",
                        min_confidence=0.7
                    )

                    if setups:
                        await ctx.send(f"✅ {t}: Found {len(setups)} A+ setup(s)")
                        total_found += len(setups)
                        for setup in setups[:1]:  # Show first setup
                            await self.bot.send_a_plus_alert(setup, ctx.channel.id)

                except Exception as e:
                    await ctx.send(f"❌ Error scanning {t}: {e}")

            if total_found == 0:
                await ctx.send("No A+ setups found across all tickers.")
            else:
                await ctx.send(f"✅ Scan complete: {total_found} A+ setup(s) found")

    @commands.command(name="stats")
    async def show_statistics(self, ctx: commands.Context):
        """Display current trading statistics."""
        # This would require database access - placeholder for now
        await ctx.send(
            "📊 **Trading Statistics**\n"
            "```\n"
            "Total Trades: 0\n"
            "Win Rate: N/A\n"
            "Total R Profit: 0R\n"
            "Expectancy: N/A\n"
            "```\n"
            "*Connect to database to see real statistics*"
        )

    @commands.command(name="status")
    async def show_status(self, ctx: commands.Context):
        """Show bot status and configuration."""
        settings = get_settings()

        embed = discord.Embed(
            title="🤖 Bot Status",
            color=DISCORD_COLORS["info"]
        )

        embed.add_field(name="Default Timeframe", value=settings.default_timeframe, inline=True)
        wick_ratio_val = f"{settings.wick_ratio:.1f}"
        embed.add_field(name="Wick Ratio", value=wick_ratio_val, inline=True)
        rr_target_val = f"1:{settings.rr_target:.1f}"
        embed.add_field(name="RR Target", value=rr_target_val, inline=True)
        scan_interval_val = f"{settings.scan_interval_minutes} min"
        embed.add_field(name="Scan Interval", value=scan_interval_val, inline=True)

        tickers = ", ".join(settings.default_tickers[:3]) + "..."
        embed.add_field(name="Watchlist", value=tickers, inline=False)

        await ctx.send(embed=embed)

    @commands.command(name="help")
    async def show_help(self, ctx: commands.Context):
        """Show available commands."""
        embed = discord.Embed(
            title="📖 Available Commands",
            color=DISCORD_COLORS["info"],
            description="Commands for the Naked Forex trading bot"
        )

        embed.add_field(
            name="!scan [ticker]",
            value="Scan for A+ setups (optional: specific ticker)",
            inline=False
        )
        embed.add_field(
            name="!stats",
            value="Display trading statistics",
            inline=False
        )
        embed.add_field(
            name="!status",
            value="Show bot status and settings",
            inline=False
        )
        embed.add_field(
            name="!help",
            value="Show this help message",
            inline=False
        )

        await ctx.send(embed=embed)


class DiscordBotService:
    """
    Service wrapper for Discord bot functionality.

    Provides a cleaner interface for the main application to interact
    with the Discord bot.
    """

    def __init__(self, pattern_service: PatternDetectionService):
        """
        Initialize the Discord bot service.

        Args:
            pattern_service: Pattern detection service
        """
        self.pattern_service = pattern_service
        self.settings = get_settings()
        self.bot: DiscordBot | None = None
        self._running = False

    async def start(self):
        """Start the Discord bot."""
        if not self.settings.discord_token.get_secret_value():
            logger.warning("No Discord token configured, bot not started")
            return

        self.bot = DiscordBot(self.pattern_service)
        self._running = True

        # Run bot in background
        asyncio.create_task(self.bot.start(self.settings.discord_token.get_secret_value()))

        logger.info("Discord bot started")

    async def stop(self):
        """Stop the Discord bot."""
        if self.bot:
            await self.bot.close()
            self._running = False
            logger.info("Discord bot stopped")

    async def send_alert(self, setup: SignalResponse):
        """Send an A+ setup alert."""
        if self.bot and self._running:
            await self.bot.send_a_plus_alert(setup)

    def is_running(self) -> bool:
        """Check if bot is running."""
        return self._running
