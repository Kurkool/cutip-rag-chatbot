"""Analytics, chat logs, and vector management endpoints."""

from fastapi import APIRouter, Query

from schemas import AnalyticsResponse, ChatLogEntry
from services import firestore as firestore_service
from services.dependencies import get_tenant_or_404
from services.vectorstore import get_raw_index

router = APIRouter(prefix="/api/tenants/{tenant_id}", tags=["Analytics"])


@router.get("/analytics", response_model=AnalyticsResponse)
async def get_analytics(tenant_id: str):
    """Usage stats: total chats, unique users."""
    await get_tenant_or_404(tenant_id)
    return AnalyticsResponse(**await firestore_service.get_analytics(tenant_id))


@router.get("/chat-logs", response_model=list[ChatLogEntry])
async def get_chat_logs(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Paginated chat history for a tenant."""
    await get_tenant_or_404(tenant_id)
    return await firestore_service.get_chat_logs(tenant_id, limit=limit, offset=offset)


@router.get("/documents")
async def list_documents(tenant_id: str):
    """Vector count in the tenant's Pinecone namespace."""
    tenant = await get_tenant_or_404(tenant_id)
    namespace = tenant["pinecone_namespace"]
    stats = get_raw_index().describe_index_stats()
    ns_stats = stats.get("namespaces", {}).get(namespace, {})
    return {
        "tenant_id": tenant_id,
        "namespace": namespace,
        "vector_count": ns_stats.get("vector_count", 0),
    }


@router.delete("/documents", status_code=204)
async def delete_all_documents(tenant_id: str):
    """Delete all vectors in the tenant's Pinecone namespace."""
    tenant = await get_tenant_or_404(tenant_id)
    get_raw_index().delete(delete_all=True, namespace=tenant["pinecone_namespace"])
