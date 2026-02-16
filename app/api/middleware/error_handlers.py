"""
Global exception handlers for FastAPI.

Provides standardized error responses across all endpoints.
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from pydantic import ValidationError

from loguru import logger


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError
) -> JSONResponse:
    """
    Handle Pydantic validation errors.

    Args:
        request: Request that caused the error
        exc: Validation error

    Returns:
        JSON response with validation error details
    """
    errors = exc.errors()
    formatted_errors = []

    for error in errors:
        formatted_errors.append({
            "field": ".".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type": error["type"]
        })

    logger.warning(f"Validation error on {request.url}: {formatted_errors}")

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Validation error",
            "errors": formatted_errors
        }
    )


async def http_exception_handler(
    request: Request,
    exc: Exception
) -> JSONResponse:
    """
    Handle general HTTP exceptions.

    Args:
        request: Request that caused the error
        exc: Exception

    Returns:
        JSON response with error details
    """
    # Check if it's a FastAPI HTTPException
    if hasattr(exc, "status_code") and hasattr(exc, "detail"):
        status_code = exc.status_code
        detail = exc.detail
    else:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        detail = "Internal server error"

    logger.error(f"HTTP error on {request.url}: {detail}")

    return JSONResponse(
        status_code=status_code,
        content={"detail": detail}
    )


async def database_exception_handler(
    request: Request,
    exc: SQLAlchemyError
) -> JSONResponse:
    """
    Handle database errors.

    Args:
        request: Request that caused the error
        exc: Database error

    Returns:
        JSON response with error details
    """
    logger.error(f"Database error on {request.url}: {exc}")

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Database error occurred",
            "error": str(exc) if logger.level == "DEBUG" else "See logs for details"
        }
    )


async def general_exception_handler(
    request: Request,
    exc: Exception
) -> JSONResponse:
    """
    Handle all unhandled exceptions.

    Args:
        request: Request that caused the error
        exc: Exception

    Returns:
        JSON response with error details
    """
    logger.exception(f"Unhandled exception on {request.url}: {exc}")

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An unexpected error occurred",
            "error": str(exc) if logger.level == "DEBUG" else "See logs for details"
        }
    )
