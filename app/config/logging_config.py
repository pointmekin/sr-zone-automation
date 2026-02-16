"""
Logging configuration using Loguru.

Provides structured logging with console and file handlers.
"""

import sys
from pathlib import Path
from loguru import logger
from typing import Literal


def setup_logging(
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO",
    log_file: str = "logs/app.log",
    console_format: str | None = None,
    file_format: str | None = None
) -> None:
    """
    Configure application logging with Loguru.

    Args:
        log_level: Minimum log level to capture
        log_file: Path to log file
        console_format: Custom format for console logs (optional)
        file_format: Custom format for file logs (optional)

    Example:
        >>> setup_logging("INFO", "logs/app.log")
        >>> logger.info("Application started")
    """
    # Remove default handler
    logger.remove()

    # Default console format with colors
    if console_format is None:
        console_format = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        )

    # Default file format without colors
    if file_format is None:
        file_format = (
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{name}:{function}:{line} | "
            "{message}"
        )

    # Add console handler with colors
    logger.add(
        sys.stdout,
        level=log_level,
        format=console_format,
        colorize=True,
        backtrace=True,
        diagnose=True
    )

    # Ensure log directory exists
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Add file handler with rotation
    logger.add(
        log_file,
        level=log_level,
        format=file_format,
        rotation="10 MB",
        retention="30 days",
        compression="zip",
        backtrace=True,
        diagnose=True,
        encoding="utf-8"
    )

    logger.info(f"Logging configured: level={log_level}, file={log_file}")


class InterceptHandler:
    """
    Intercept standard logging messages and redirect to Loguru.

    This allows compatibility with libraries that use Python's standard logging module.
    """

    def __init__(self, level: str | int = "INFO") -> None:
        """Initialize the intercept handler with a log level."""
        self.level = level

    def emit(self, record) -> None:  # pragma: no cover
        """Emit a log record to Loguru."""
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_standard_logging_intercept() -> None:
    """
    Intercept standard library logging and redirect to Loguru.

    This ensures all third-party library logs are captured by Loguru.
    """
    import logging

    # Configure standard logging to use intercept handler
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # Disable other loggers
    for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
        logging_logger = logging.getLogger(logger_name)
        logging_logger.handlers = [InterceptHandler()]
        logging_logger.propagate = False

    logger.debug("Standard logging intercepted by Loguru")
