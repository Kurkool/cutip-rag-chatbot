"""Multi-Tenant University RAG SaaS - FastAPI application."""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from config import APP_VERSION, settings
from services.rate_limit import limiter
from routers import (
    analytics_router,
    ingestion_router,
    tenants_router,
    users_router,
    webhook_router,
)
from services.embedding import get_embedding_model
from services.reranker import get_reranker
from services.vectorstore import get_vectorstore

# ──────────────────────────────────────
# Logging
# ──────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────
# Lifespan
# ──────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up — warming API clients...")
    get_embedding_model()
    get_vectorstore()
    get_reranker()
    logger.info("Startup complete")
    yield
    logger.info("Shutting down")


# ──────────────────────────────────────
# App
# ──────────────────────────────────────

app = FastAPI(
    title="Multi-Tenant University RAG SaaS",
    description="RAG Chatbot platform: LINE OA, multi-format ingestion, per-tenant isolation",
    version=APP_VERSION,
    lifespan=lifespan,
)

# Rate limiting
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


# ──────────────────────────────────────
# Middleware: request logging + global error handler
# ──────────────────────────────────────

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


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check logs for details."},
    )


# ──────────────────────────────────────
# Routes
# ──────────────────────────────────────

# Public
app.include_router(webhook_router)

# Auth is handled per-endpoint inside each router via Depends(get_current_user)
app.include_router(users_router)
app.include_router(tenants_router)
app.include_router(ingestion_router)
app.include_router(analytics_router)


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "version": APP_VERSION}
