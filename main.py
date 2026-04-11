"""Multi-Tenant University RAG SaaS - FastAPI application."""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

from config import settings
from routers import analytics_router, ingestion_router, tenants_router, webhook_router
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
# API Key Authentication
# ──────────────────────────────────────

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(_api_key_header)):
    if not settings.ADMIN_API_KEY:
        return
    if api_key != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")


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
    version="3.0.0",
    lifespan=lifespan,
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

# Protected (requires X-API-Key)
app.include_router(tenants_router, dependencies=[Depends(verify_api_key)])
app.include_router(ingestion_router, dependencies=[Depends(verify_api_key)])
app.include_router(analytics_router, dependencies=[Depends(verify_api_key)])


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "version": "3.0.0"}
