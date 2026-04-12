"""Analytics, chat logs, and vector management endpoints."""

from fastapi import APIRouter, Depends, Query

from schemas import AnalyticsResponse, ChatLogEntry
from services import firestore as firestore_service
from services.auth import get_accessible_tenant, require_super_admin
from services.vectorstore import get_raw_index, get_vectorstore

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

    stats = index.describe_index_stats()
    ns_stats = stats.get("namespaces", {}).get(namespace, {})
    vector_count = ns_stats.get("vector_count", 0)

    documents = []
    if vector_count > 0:
        vectorstore = get_vectorstore(namespace)
        results = vectorstore.similarity_search("document", k=min(vector_count, 100))
        seen: set[str] = set()
        for doc in results:
            filename = doc.metadata.get("source_filename", doc.metadata.get("source", ""))
            if filename and filename not in seen:
                seen.add(filename)
                documents.append({
                    "filename": filename,
                    "category": doc.metadata.get("doc_category", ""),
                    "source_type": doc.metadata.get("source_type", ""),
                })

    return {
        "tenant_id": tenant["tenant_id"],
        "namespace": namespace,
        "vector_count": vector_count,
        "documents": sorted(documents, key=lambda d: d["filename"]),
    }


@router.delete("/documents", status_code=204)
async def delete_all_documents(
    tenant: dict = Depends(get_accessible_tenant),
    _admin: dict = Depends(require_super_admin),
):
    """Delete all vectors in the tenant's Pinecone namespace. Super admin only."""
    get_raw_index().delete(delete_all=True, namespace=tenant["pinecone_namespace"])
