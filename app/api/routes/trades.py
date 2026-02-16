"""
Trade journaling routes.

Provides endpoints for logging trades, managing Series of 10,
and tracking trading statistics.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    get_current_user,
    get_trade_journal
)
from app.models.trades import (
    TradeEntry,
    TradeResponse,
    SeriesOfTen,
    TradingStatistics,
    CreateSeriesRequest,
    UpdateTradeRequest
)
from app.db.models.user import User
from app.services.trade_journal import TradeJournalService
from loguru import logger


router = APIRouter(prefix="/trades", tags=["trades"])


# Series Management
@router.post("/series", response_model=SeriesOfTen, status_code=status.HTTP_201_CREATED)
async def create_new_series(
    request: CreateSeriesRequest,
    current_user: User = Depends(get_current_user),
    journal: TradeJournalService = Depends(get_trade_journal)
):
    """
    Create a new Series of 10.

    - **starting_balance**: Account balance at series start
    - **target_r_profit**: Target R profit for the series
    - **notes**: Optional notes about the series
    """
    series = await journal.create_series(current_user.id, request)

    logger.info(f"User {current_user.id} created new Series of 10: {series.id}")

    return series


@router.get("/series/active", response_model=SeriesOfTen)
async def get_active_series(
    current_user: User = Depends(get_current_user),
    journal: TradeJournalService = Depends(get_trade_journal)
):
    """
    Get the currently active (incomplete) Series of 10.

    Returns the most recent series that has not yet reached 10 trades.
    """
    series = await journal.get_active_series(current_user.id)

    if not series:
        raise HTTPException(
            status_code=404,
            detail="No active series found. Create a new series to start tracking."
        )

    return series


@router.get("/series", response_model=List[SeriesOfTen])
async def list_series(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    journal: TradeJournalService = Depends(get_trade_journal)
):
    """
    List all Series of 10 for the current user.

    - **limit**: Maximum number of series to return
    - **offset**: Number of series to skip
    """
    series_list = await journal.list_series(current_user.id, limit, offset)

    return series_list


@router.get("/series/{series_id}", response_model=SeriesOfTen)
async def get_series(
    series_id: int,
    current_user: User = Depends(get_current_user),
    journal: TradeJournalService = Depends(get_trade_journal)
):
    """
    Get a specific Series of 10 with all trades and statistics.

    Returns complete series including:
    - All trades in the series
    - Win rate
    - Total R profit
    - Expectancy
    """
    series = await journal.get_series(series_id, current_user.id)

    if not series:
        raise HTTPException(
            status_code=404,
            detail=f"Series {series_id} not found"
        )

    return series


# Trade Management
@router.post("/", response_model=TradeResponse, status_code=status.HTTP_201_CREATED)
async def log_trade(
    trade: TradeEntry,
    current_user: User = Depends(get_current_user),
    journal: TradeJournalService = Depends(get_trade_journal)
):
    """
    Log a trade entry for Series of 10 tracking.

    Records trade details including:
    - Entry price and time
    - Stop loss and take profit levels
    - Position size and risk amount
    - Setup quality metrics (fresh zone, three pulse, wick ratio)

    Note: Outcome is set to None when logging. Use update endpoint
    to set the outcome when the trade is closed.
    """
    try:
        trade_record = await journal.log_trade(current_user.id, trade)

        logger.info(
            f"User {current_user.id} logged trade: {trade.ticker} "
            f"{trade.direction.value} @ {trade.entry_price}"
        )

        return trade_record

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error logging trade: {e}")
        raise HTTPException(status_code=500, detail="Failed to log trade")


@router.put("/{trade_id}", response_model=TradeResponse)
async def update_trade(
    trade_id: int,
    update: UpdateTradeRequest,
    current_user: User = Depends(get_current_user),
    journal: TradeJournalService = Depends(get_trade_journal)
):
    """
    Update a trade (typically to set exit price and outcome).

    Use this endpoint when a trade is closed to set:
    - **exit_price**: Final exit price
    - **exit_time**: When the trade was closed
    - **outcome**: win, loss, or breakeven
    """
    trade = await journal.update_trade(trade_id, current_user.id, update)

    if not trade:
        raise HTTPException(
            status_code=404,
            detail=f"Trade {trade_id} not found"
        )

    logger.info(f"User {current_user.id} updated trade {trade_id}: outcome={update.outcome}")

    return trade


@router.get("/{trade_id}", response_model=TradeResponse)
async def get_trade(
    trade_id: int,
    current_user: User = Depends(get_current_user),
    journal: TradeJournalService = Depends(get_trade_journal)
):
    """
    Get details of a specific trade.
    """
    series = await journal.get_series_by_trade(trade_id, current_user.id)

    if not series:
        raise HTTPException(
            status_code=404,
            detail=f"Trade {trade_id} not found"
        )

    # Find the trade in the series
    for trade in series.trades:
        if trade.id == trade_id:
            return trade

    raise HTTPException(
        status_code=404,
        detail=f"Trade {trade_id} not found"
    )


# Statistics
@router.get("/statistics/overview", response_model=TradingStatistics)
async def get_trading_statistics(
    current_user: User = Depends(get_current_user),
    journal: TradeJournalService = Depends(get_trade_journal)
):
    """
    Get overall trading statistics across all series.

    Returns:
    - Total trades and series
    - Overall win rate
    - Total R profit
    - Expectancy
    - Maximum drawdown
    - A+ setup statistics
    """
    stats = await journal.get_statistics(current_user.id)

    return stats


# Fix: Add missing method to TradeJournalService
async def get_series_by_trade(
    self: TradeJournalService,
    trade_id: int,
    user_id: int
) -> SeriesOfTen | None:
    """Get series containing a specific trade."""
    from sqlalchemy import select, and_
    from app.db.models.trade import Trade, TradeSeries as DBTradeSeries

    # Get trade's series_id
    result = await self.db.execute(
        select(Trade.series_id).where(
            and_(
                Trade.id == trade_id,
                Trade.series_id == DBTradeSeries.id,
                DBTradeSeries.user_id == user_id
            )
        )
    )
    series_id = result.scalar_one_or_none()

    if not series_id:
        return None

    return await self.get_series(series_id, user_id)


# Monkey patch the method onto the class
TradeJournalService.get_series_by_trade = get_series_by_trade
