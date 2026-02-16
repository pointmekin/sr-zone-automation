# Naked Forex API

> A professional FastAPI application implementing the Nick Shawn "Naked Forex" trading framework with automated pattern detection, trade journaling, and real-time Discord alerts.

## Features

- **Pattern Detection**: Algorithmic detection of Three Pulse exhaustion patterns and Big Wick candlestick setups
- **Support/Resistance Zones**: Automated identification using pivot point analysis and hierarchical clustering
- **Trade Journaling**: "Series of 10" tracking system with performance statistics and expectancy calculations
- **Interactive Charts**: Plotly-based visualizations with S/R zones and signal annotations
- **Discord Bot**: Real-time alerts for A+ setups with manual scanning commands
- **JWT Authentication**: Secure user authentication with role-based access control
- **REST API**: Professional OpenAPI/Swagger documentation

## Trading Strategy

Based on the Nick Shawn "Naked Forex" methodology:

- **50/50 Market Theory**: Markets are probabilistic, not predictive
- **Price Action**: Pure OHLCV analysis without lagging indicators
- **Three Pulse Cycle**: Identifies momentum exhaustion after 3 pushes
- **Big Wick Trigger**: Entry signals with wick-to-body ratio ≥ 3:1
- **1:1 Risk-Reward**: Conservative RR targets for consistent profitability
- **Series of 10**: Performance evaluation in blocks of 10 trades

## Quick Start

### Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) package manager

### Installation

```bash
# Install dependencies
uv sync

# Create .env from template
cp .env.example .env

# Update .env with your settings
# - Generate a secure SECRET_KEY
# - Add Discord token (optional)
# - Configure trading parameters

# Initialize database
python scripts/init_db.py

# Start the API server
uv run uvicorn app.main:app --reload
```

The API will be available at [http://localhost:8000](http://localhost:8000)

Interactive documentation: [http://localhost:8000/docs](http://localhost:8000/docs)

## API Endpoints

### Authentication

```bash
# Register a new user
POST /api/v1/auth/register
{
  "email": "user@example.com",
  "password": "securepassword123",
  "full_name": "John Doe"
}

# Login
POST /api/v1/auth/login/json
{
  "email": "user@example.com",
  "password": "securepassword123"
}
```

### Market Analysis

```bash
# Detect Support/Resistance zones
POST /api/v1/analysis/zones
Authorization: Bearer <token>
{
  "ticker": "EURUSD=X",
  "timeframe": "15m",
  "lookback_bars": 500
}

# Fetch OHLCV data
GET /api/v1/analysis/ohlcv?ticker=EURUSD=X&timeframe=15m&lookback_bars=200
```

### Signal Detection

```bash
# Detect Big Wick patterns
POST /api/v1/signals/big-wick
Authorization: Bearer <token>
?ticker=EURUSD=X&timeframe=15m&lookback_bars=500

# Detect Three Pulse patterns
POST /api/v1/signals/three-pulse
Authorization: Bearer <token>
?ticker=EURUSD=X&timeframe=15m&lookback_bars=500

# Detect A+ Setups (complete signals)
POST /api/v1/signals/a-setups
Authorization: Bearer <token>
{
  "ticker": "EURUSD=X",
  "timeframe": "15m",
  "min_confidence": 0.7
}
```

### Trade Journaling

```bash
# Create a new Series of 10
POST /api/v1/trades/series
Authorization: Bearer <token>
{
  "starting_balance": 10000,
  "target_r_profit": 2.0
}

# Get active series
GET /api/v1/trades/series/active
Authorization: Bearer <token>

# Log a trade
POST /api/v1/trades
Authorization: Bearer <token>
{
  "series_id": 1,
  "ticker": "EURUSD=X",
  "direction": "long",
  "entry_price": 1.0850,
  "stop_loss": 1.0800,
  "take_profit": 1.0900,
  "position_size": 100000,
  "risk_amount": 100,
  "risk_reward": 1.0,
  "was_fresh_zone": true,
  "had_three_pulse": true,
  "wick_ratio": 3.5
}

# Update trade outcome
PUT /api/v1/trades/{trade_id}
Authorization: Bearer <token>
{
  "exit_price": 1.0880,
  "exit_time": "2025-01-15T14:30:00Z",
  "outcome": "win"
}

# Get trading statistics
GET /api/v1/trades/statistics/overview
Authorization: Bearer <token>
```

### Visualization

```bash
# Generate interactive chart
POST /api/v1/charts/generate
{
  "ticker": "EURUSD=X",
  "timeframe": "15m",
  "lookback_bars": 200,
  "show_sr_zones": true
}

# Generate watchlist dashboard
GET /api/v1/charts/watchlist?timeframe=15m
```

## Discord Bot

### Setup

1. Create a Discord application at [Discord Developer Portal](https://discord.com/developers/applications)
2. Enable bot functionality and get the token
3. Invite the bot to your server
4. Add the token to `.env`:
   ```
   DISCORD_TOKEN=your_bot_token_here
   DISCORD_CHANNEL_ID=your_channel_id_here
   ```

### Commands

- `!scan [ticker]` - Manually trigger scan for A+ setups
- `!stats` - Display trading statistics
- `!status` - Show bot status and configuration
- `!help` - Show available commands

### Automatic Alerts

The bot automatically scans for A+ setups every 15 minutes (configurable) and sends alerts when high-confidence setups are detected.

## Configuration

Key environment variables in `.env`:

```bash
# Trading Parameters
DEFAULT_TIMEFRAME=15m           # Default chart timeframe
LOOKBACK_BARS=500              # Bars to analyze
SR_SENSITIVITY=0.05            # S/R zone sensitivity (5%)
WICK_RATIO=3.0                 # Minimum wick-to-body ratio
RR_TARGET=1.0                  # Default risk-reward ratio

# Risk Management
MAX_RISK_PER_TRADE=0.02        # 2% risk per trade

# Pattern Detection
FRESH_ZONE_THRESHOLD=100       # Bars since touch for "fresh" zone
MANUAL_EXIT_BARS=5             # Bars before suggesting manual exit

# Discord (optional)
DISCORD_TOKEN=your_token
SCAN_INTERVAL_MINUTES=15        # Background scan interval
```

## Project Structure

```
finance-automation/
├── app/
│   ├── main.py                  # FastAPI application
│   ├── config/                  # Configuration
│   │   ├── settings.py          # Pydantic Settings
│   │   ├── logging_config.py    # Loguru setup
│   │   └── constants.py         # Trading constants
│   ├── api/                     # API layer
│   │   ├── routes/              # API endpoints
│   │   ├── deps.py              # Dependency injection
│   │   └── middleware/          # Error handlers
│   ├── core/                    # Core functionality
│   │   ├── security.py          # JWT authentication
│   │   └── tasks.py             # Background tasks
│   ├── models/                  # Pydantic models
│   │   ├── market.py            # OHLCV models
│   │   ├── signals.py           # Signal models
│   │   └── trades.py            # Trade journal models
│   ├── services/                # Business logic
│   │   ├── data_service.py      # yfinance integration
│   │   ├── sr_detection.py      # S/R zone detection
│   │   ├── pattern_detection.py # Pattern recognition
│   │   ├── risk_manager.py      # Risk calculations
│   │   ├── trade_journal.py     # Series of 10 tracking
│   │   ├── visualization_service.py  # Plotly charts
│   │   └── discord_service.py   # Discord bot
│   └── db/                      # Database
│       ├── session.py           # DB session
│       └── models/              # SQLAlchemy ORM
├── scripts/
│   └── init_db.py               # Database initialization
├── tests/                       # Test suite
├── .env.example                 # Environment template
├── pyproject.toml               # Project configuration
└── README.md
```

## Development

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=app --cov-report=html

# Run specific test
uv run pytest tests/test_api/test_signals.py
```

### Code Quality

```bash
# Format code
uv run black app/

# Lint code
uv run ruff check app/

# Type checking
uv run mypy app/
```

## Architecture Decisions

- **Async/Await**: All services use async for concurrent data fetching
- **Pydantic v2**: Using latest Pydantic with `computed_field` for derived properties
- **SQLite**: Simple file-based database (easily upgradable to PostgreSQL)
- **yfinance**: Free market data (no API keys required)
- **Discord.py**: Async Discord library for real-time alerts
- **Plotly**: Interactive charts with dark theme

## Trading Parameters (Default)

From the Nick Shawn framework:

| Parameter | Value | Description |
|-----------|-------|-------------|
| S/R Sensitivity | 0.05 (5%) | Price difference to cluster into zones |
| Wick Ratio | 3.0 | Minimum wick-to-body ratio for Big Wick |
| Risk-Reward | 1:1 | Default RR target |
| Max Risk | 2% | Maximum risk per trade |
| Fresh Zone | 100 bars | Bars since last touch for "fresh" zone |
| Manual Exit | 5 bars | Consolidation before suggesting exit |

## API Documentation

- Interactive Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- OpenAPI JSON: [http://localhost:8000/api/v1/openapi.json](http://localhost:8000/api/v1/openapi.json)

## License

MIT

## References

- [Nick Shawn Trading Framework](https://www.youtube.com/watch?v=9WV9Md5VSo0)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Pydantic v2 Documentation](https://docs.pydantic.dev/latest/)
