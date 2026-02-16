"""
Trade journal service for Series of 10 tracking.

Implements the "Series of 10" evaluation system from "The Mission".
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trades import (
    TradeEntry,
    TradeResponse,
    SeriesOfTen,
    CreateSeriesRequest,
    UpdateTradeRequest,
    TradingStatistics
)
from app.config.constants import TradeOutcome, TradeStatus
from app.db.models.trade import Trade, TradeSeries as DBTradeSeries
from app.db.models.user import User
from loguru import logger


class TradeJournalService:
    """
    Service for managing trade journal and Series of 10.

    Provides CRUD operations for trades and series,
    plus performance statistics calculations.
    """

    def __init__(self, db_session: AsyncSession):
        """
        Initialize trade journal service.

        Args:
            db_session: Database session for persistence
        """
        self.db = db_session
        logger.info("TradeJournalService initialized")

    async def create_series(
        self,
        user_id: int,
        request: CreateSeriesRequest
    ) -> SeriesOfTen:
        """
        Create a new Series of 10.

        Args:
            user_id: User ID creating the series
            request: Series creation request

        Returns:
            Created SeriesOfTen object
        """
        db_series = DBTradeSeries(
            user_id=user_id,
            start_date=datetime.utcnow(),
            starting_balance=request.starting_balance,
            target_r_profit=request.target_r_profit,
            notes=request.notes
        )

        self.db.add(db_series)
        await self.db.commit()
        await self.db.refresh(db_series)

        logger.info(f"Created new Series of 10: id={db_series.id}")

        return SeriesOfTen(
            id=db_series.id,
            user_id=db_series.user_id,
            start_date=db_series.start_date,
            end_date=db_series.end_date,
            trades=[],
            starting_balance=db_series.starting_balance,
            target_r_profit=db_series.target_r_profit
        )

    async def get_series(self, series_id: int, user_id: int) -> Optional[SeriesOfTen]:
        """
        Get a complete Series of 10 with all trades.

        Args:
            series_id: Series ID
            user_id: User ID (for ownership check)

        Returns:
            SeriesOfTen object or None
        """
        # Fetch series
        result = await self.db.execute(
            select(DBTradeSeries).where(
                and_(
                    DBTradeSeries.id == series_id,
                    DBTradeSeries.user_id == user_id
                )
            )
        )
        db_series = result.scalar_one_or_none()

        if not db_series:
            return None

        # Fetch trades
        result = await self.db.execute(
            select(Trade)
            .where(Trade.series_id == series_id)
            .order_by(Trade.entry_time)
        )
        db_trades = result.scalars().all()

        # Convert to Pydantic models
        trades = [self._db_to_pydantic(t) for t in db_trades]

        return SeriesOfTen(
            id=db_series.id,
            user_id=db_series.user_id,
            start_date=db_series.start_date,
            end_date=db_series.end_date,
            trades=trades,
            starting_balance=db_series.starting_balance,
            target_r_profit=db_series.target_r_profit
        )

    async def list_series(
        self,
        user_id: int,
        limit: int = 50,
        offset: int = 0
    ) -> list[SeriesOfTen]:
        """
        List all series for a user.

        Args:
            user_id: User ID
            limit: Maximum number of series to return
            offset: Number of series to skip

        Returns:
            List of SeriesOfTen objects
        """
        result = await self.db.execute(
            select(DBTradeSeries)
            .where(DBTradeSeries.user_id == user_id)
            .order_by(DBTradeSeries.start_date.desc())
            .limit(limit)
            .offset(offset)
        )
        db_series_list = result.scalars().all()

        series_list = []
        for db_series in db_series_list:
            # Get trade count only
            result = await self.db.execute(
                select(Trade.id).where(Trade.series_id == db_series.id)
            )
            trade_count = len(result.all())

            series_list.append(
                SeriesOfTen(
                    id=db_series.id,
                    user_id=db_series.user_id,
                    start_date=db_series.start_date,
                    end_date=db_series.end_date,
                    trades=[],
                    starting_balance=db_series.starting_balance,
                    target_r_profit=db_series.target_r_profit
                )
            )

        return series_list

    async def get_active_series(self, user_id: int) -> Optional[SeriesOfTen]:
        """
        Get the currently active (incomplete) series for a user.

        Args:
            user_id: User ID

        Returns:
            Active SeriesOfTen or None
        """
        result = await self.db.execute(
            select(DBTradeSeries)
            .where(
                and_(
                    DBTradeSeries.user_id == user_id,
                    DBTradeSeries.is_complete == False
                )
            )
            .order_by(DBTradeSeries.start_date.desc())
        )
        db_series = result.scalar_one_or_none()

        if db_series:
            return await self.get_series(db_series.id, user_id)

        return None

    async def log_trade(
        self,
        user_id: int,
        trade: TradeEntry
    ) -> TradeResponse:
        """
        Log a trade entry.

        Args:
            user_id: User ID logging the trade
            trade: Trade entry details

        Returns:
            Created trade record with ID
        """
        # Verify series exists and belongs to user
        series_result = await self.db.execute(
            select(DBTradeSeries).where(
                and_(
                    DBTradeSeries.id == trade.series_id,
                    DBTradeSeries.user_id == user_id
                )
            )
        )
        db_series = series_result.scalar_one_or_none()

        if not db_series:
            raise ValueError(f"Series {trade.series_id} not found")

        # Check if series is complete
        if db_series.is_complete:
            raise ValueError("Cannot add trades to a completed series")

        # Create trade record
        db_trade = Trade(
            series_id=trade.series_id,
            ticker=trade.ticker,
            direction=trade.direction,
            entry_price=trade.entry_price,
            entry_time=trade.entry_time,
            stop_loss=trade.stop_loss,
            take_profit=trade.take_profit,
            position_size=trade.position_size,
            risk_amount=trade.risk_amount,
            risk_reward=trade.risk_reward,
            status=trade.status,
            was_fresh_zone=trade.was_fresh_zone,
            had_three_pulse=trade.had_three_pulse,
            wick_ratio=trade.wick_ratio,
            confidence=trade.confidence,
            notes=trade.notes
        )

        self.db.add(db_trade)
        await self.db.commit()
        await self.db.refresh(db_trade)

        logger.info(f"Logged trade: id={db_trade.id}, ticker={trade.ticker}")

        # Check if series is now complete
        await self._check_series_completion(trade.series_id)

        return self._db_to_pydantic(db_trade)

    async def update_trade(
        self,
        trade_id: int,
        user_id: int,
        update: UpdateTradeRequest
    ) -> Optional[TradeResponse]:
        """
        Update a trade (typically to set exit price and outcome).

        Args:
            trade_id: Trade ID
            user_id: User ID (for ownership check)
            update: Update request

        Returns:
            Updated trade or None
        """
        # Fetch trade with ownership check
        result = await self.db.execute(
            select(Trade)
            .join(DBTradeSeries)
            .where(
                and_(
                    Trade.id == trade_id,
                    DBTradeSeries.user_id == user_id
                )
            )
        )
        db_trade = result.scalar_one_or_none()

        if not db_trade:
            return None

        # Update fields
        if update.exit_price is not None:
            db_trade.exit_price = update.exit_price

        if update.exit_time is not None:
            db_trade.exit_time = update.exit_time

        if update.outcome is not None:
            db_trade.outcome = update.outcome
            # Calculate R profit and P&L
            db_trade.r_profit = self._calculate_r_profit(db_trade)
            db_trade.profit_loss = self._calculate_profit_loss(db_trade)

        if update.status is not None:
            db_trade.status = update.status

        if update.notes is not None:
            db_trade.notes = update.notes

        await self.db.commit()
        await self.db.refresh(db_trade)

        logger.info(f"Updated trade: id={trade_id}")

        return self._db_to_pydantic(db_trade)

    async def get_statistics(self, user_id: int) -> TradingStatistics:
        """
        Get overall trading statistics for a user.

        Args:
            user_id: User ID

        Returns:
            TradingStatistics object
        """
        # Get all trades for user
        result = await self.db.execute(
            select(Trade)
            .join(DBTradeSeries)
            .where(DBTradeSeries.user_id == user_id)
        )
        all_trades = result.scalars().all()

        if not all_trades:
            return TradingStatistics(
                total_trades=0,
                total_series=0,
                completed_series=0,
                overall_win_rate=0.0,
                total_r_profit=0.0,
                overall_expectancy=0.0,
                max_drawdown=0.0
            )

        # Count completed trades
        completed_trades = [t for t in all_trades if t.outcome is not None]

        # Basic stats
        total_trades = len(completed_trades)
        wins = len([t for t in completed_trades if t.outcome == TradeOutcome.WIN])
        win_rate = wins / total_trades if total_trades > 0 else 0.0

        # R profit
        total_r = sum([t.r_profit for t in completed_trades if t.r_profit is not None])
        expectancy = total_r / total_trades if total_trades > 0 else 0.0

        # Series stats
        series_result = await self.db.execute(
            select(DBTradeSeries).where(DBTradeSeries.user_id == user_id)
        )
        all_series = series_result.scalars().all()
        completed_series_count = len([s for s in all_series if s.is_complete])

        # A+ setup stats
        a_plus_trades = [t for t in completed_trades if t.is_a_plus_setup]
        a_plus_wins = len([t for t in a_plus_trades if t.outcome == TradeOutcome.WIN])
        a_plus_win_rate = a_plus_wins / len(a_plus_trades) if a_plus_trades else 0.0

        # Max drawdown
        max_dd = self._calculate_max_drawdown(completed_trades)

        return TradingStatistics(
            total_trades=total_trades,
            total_series=len(all_series),
            completed_series=completed_series_count,
            overall_win_rate=win_rate,
            total_r_profit=total_r,
            overall_expectancy=expectancy,
            max_drawdown=abs(max_dd),
            a_plus_setup_count=len(a_plus_trades),
            a_plus_win_rate=a_plus_win_rate
        )

    async def _check_series_completion(self, series_id: int) -> None:
        """Check if series is complete and update if so."""
        result = await self.db.execute(
            select(Trade.id).where(Trade.series_id == series_id)
        )
        trade_count = len(result.all())

        if trade_count >= 10:
            # Mark series as complete
            update_result = await self.db.execute(
                select(DBTradeSeries).where(DBTradeSeries.id == series_id)
            )
            db_series = update_result.scalar_one_or_none()

            if db_series:
                db_series.is_complete = True
                db_series.end_date = datetime.utcnow()
                await self.db.commit()

                logger.info(f"Series {series_id} completed with 10 trades")

    def _calculate_r_profit(self, db_trade: Trade) -> Optional[float]:
        """Calculate R profit for a trade."""
        if not db_trade.exit_price:
            return None

        if db_trade.direction == TradeDirection.LONG:
            price_change = db_trade.exit_price - db_trade.entry_price
        else:
            price_change = db_trade.entry_price - db_trade.exit_price

        risk_per_unit = abs(db_trade.entry_price - db_trade.stop_loss)
        if risk_per_unit == 0:
            return None

        return price_change / risk_per_unit

    def _calculate_profit_loss(self, db_trade: Trade) -> Optional[float]:
        """Calculate profit/loss in account currency."""
        if not db_trade.exit_price:
            return None

        if db_trade.direction == TradeDirection.LONG:
            price_change = db_trade.exit_price - db_trade.entry_price
        else:
            price_change = db_trade.entry_price - db_trade.exit_price

        return price_change * db_trade.position_size

    def _calculate_max_drawdown(self, trades: list[Trade]) -> float:
        """Calculate maximum drawdown in R."""
        if not trades:
            return 0.0

        # Sort by entry time
        sorted_trades = sorted(trades, key=lambda t: t.entry_time)

        peak = 0.0
        max_dd = 0.0
        cumulative_r = 0.0

        for trade in sorted_trades:
            if trade.r_profit:
                cumulative_r += trade.r_profit
                peak = max(peak, cumulative_r)
                drawdown = peak - cumulative_r
                max_dd = max(max_dd, drawdown)

        return max_dd

    def _db_to_pydantic(self, db_trade: Trade) -> TradeResponse:
        """Convert ORM model to Pydantic model."""
        return TradeResponse(
            id=db_trade.id,
            series_id=db_trade.series_id,
            ticker=db_trade.ticker,
            direction=db_trade.direction,
            entry_price=db_trade.entry_price,
            stop_loss=db_trade.stop_loss,
            take_profit=db_trade.take_profit,
            position_size=db_trade.position_size,
            risk_amount=db_trade.risk_amount,
            risk_reward=db_trade.risk_reward,
            entry_time=db_trade.entry_time,
            exit_price=db_trade.exit_price,
            exit_time=db_trade.exit_time,
            outcome=db_trade.outcome,
            status=db_trade.status,
            was_fresh_zone=db_trade.was_fresh_zone,
            had_three_pulse=db_trade.had_three_pulse,
            wick_ratio=db_trade.wick_ratio,
            confidence=db_trade.confidence,
            notes=db_trade.notes,
            created_at=db_trade.created_at,
            updated_at=db_trade.updated_at
        )
