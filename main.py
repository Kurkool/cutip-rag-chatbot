"""Multi-Tenant University RAG SaaS - FastAPI application."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.security import APIKeyHeader

from config import settings
from routers import analytics_router, ingestion_router, tenants_router, webhook_router
from services.embedding import get_embedding_model
from services.rag_chain import get_query_condenser
from services.reranker import get_reranker
from services.vectorstore import get_vectorstore

# ──────────────────────────────────────
# API Key Authentication
# ──────────────────────────────────────

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(_api_key_header)):
    if not settings.ADMIN_API_KEY:
        return  # No key configured = skip auth (dev mode)
    if api_key != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")


# ──────────────────────────────────────
# Lifespan
# ──────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    get_embedding_model()
    get_vectorstore()
    get_query_condenser()
    get_reranker()
    yield


# ──────────────────────────────────────
# App
# ──────────────────────────────────────

app = FastAPI(
    title="Multi-Tenant University RAG SaaS",
    description="RAG Chatbot platform: LINE OA, multi-format ingestion, per-tenant isolation",
    version="3.0.0",
    lifespan=lifespan,
)

# Public
app.include_router(webhook_router)

# Protected (requires X-API-Key)
app.include_router(tenants_router, dependencies=[Depends(verify_api_key)])
app.include_router(ingestion_router, dependencies=[Depends(verify_api_key)])
app.include_router(analytics_router, dependencies=[Depends(verify_api_key)])


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "version": "3.0.0"}
