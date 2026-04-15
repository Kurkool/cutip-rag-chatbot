"""Reusable middleware setup for all microservices.

Extracts CORS, request logging, and global error handling from main.py
into a single setup_middleware(app) function.
"""

import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from shared.config import settings
from shared.services.rate_limit import limiter

logger = logging.getLogger(__name__)


def setup_middleware(app: FastAPI) -> None:
    """Attach CORS, rate-limit error handler, request logging, and global error handler to app."""

    # Rate limiting — attach limiter to app.state (required by slowapi)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # CORS — explicit origins only (no wildcard with credentials)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    )

    # Request logging
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        elapsed = time.time() - start
        logger.info(
            "%s %s → %d (%.2fs)",
            request.method, request.url.path, response.status_code, elapsed,
        )
        return response

    # Global unhandled exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)

        # Fire-and-forget Slack alert
        try:
            from shared.services.notifications import alert_error
            await alert_error(
                "Unhandled Server Error",
                f"`{type(exc).__name__}`: {str(exc)[:200]}",
                Endpoint=f"{request.method} {request.url.path}",
            )
        except Exception:
            logger.warning("Failed to send Slack alert", exc_info=True)

        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error. Check logs for details."},
        )
