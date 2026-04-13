"""Analytics, chat logs, and vector management endpoints."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger(__name__)

from schemas import AnalyticsResponse, ChatLogEntry
from services import firestore as firestore_service
from services import usage as usage_service
from services.auth import get_accessible_tenant, get_current_user, require_super_admin
from services.vectorstore import get_document_list, get_raw_index

router = APIRouter(prefix="/api/tenants/{tenant_id}", tags=["Analytics"])


@router.get("/analytics", response_model=AnalyticsResponse)
async def get_analytics(tenant: dict = Depends(get_accessible_tenant)):
    """Usage stats: total chats, unique users."""
    return AnalyticsResponse(**await firestore_service.get_analytics(tenant["tenant_id"]))


@router.get("/chat-logs", response_model=list[ChatLogEntry])
async def get_chat_logs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    tenant: dict = Depends(get_accessible_tenant),
):
    """Paginated chat history for a tenant."""
    return await firestore_service.get_chat_logs(tenant["tenant_id"], limit=limit, offset=offset)


@router.get("/documents")
async def list_documents(tenant: dict = Depends(get_accessible_tenant)):
    """Vector count + list of unique ingested documents in the tenant's namespace."""
    namespace = tenant["pinecone_namespace"]
    index = get_raw_index()

    try:
        stats = index.describe_index_stats()
    except Exception:
        logger.exception("Failed to get Pinecone index stats")
        raise HTTPException(status_code=503, detail="Vector store temporarily unavailable")

    ns_stats = stats.get("namespaces", {}).get(namespace, {})
    vector_count = ns_stats.get("vector_count", 0)

    documents = await asyncio.to_thread(get_document_list, namespace) if vector_count > 0 else []

    return {
        "tenant_id": tenant["tenant_id"],
        "namespace": namespace,
        "vector_count": vector_count,
        "documents": sorted(documents, key=lambda d: d["filename"]),
    }


@router.get("/usage")
async def get_usage(
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    tenant: dict = Depends(get_accessible_tenant),
):
    """API usage stats for a tenant (current month by default)."""
    return await usage_service.get_usage(tenant["tenant_id"], month)


@router.delete("/documents", status_code=204)
async def delete_all_documents(
    tenant: dict = Depends(get_accessible_tenant),
    _admin: dict = Depends(require_super_admin),
):
    """Delete all vectors in the tenant's Pinecone namespace. Super admin only."""
    get_raw_index().delete(delete_all=True, namespace=tenant["pinecone_namespace"])


# ──────────────────────────────────────
# Global usage overview (Super Admin)
# ──────────────────────────────────────

global_router = APIRouter(prefix="/api/usage", tags=["Usage"])


@global_router.get("")
async def get_all_usage(
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    _admin: dict = Depends(require_super_admin),
):
    """Usage overview for all tenants (super admin only)."""
    return await usage_service.get_all_usage(month)
