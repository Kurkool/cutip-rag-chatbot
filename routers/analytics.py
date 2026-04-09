"""Analytics, chat logs, and vector management endpoints."""

from fastapi import APIRouter, Query

from schemas import AnalyticsResponse, ChatLogEntry
from services import firestore as firestore_service
from services.dependencies import get_tenant_or_404
from services.vectorstore import get_raw_index, get_vectorstore

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
    """Vector count + list of unique ingested documents in the tenant's namespace."""
    tenant = await get_tenant_or_404(tenant_id)
    namespace = tenant["pinecone_namespace"]
    index = get_raw_index()

    stats = index.describe_index_stats()
    ns_stats = stats.get("namespaces", {}).get(namespace, {})
    vector_count = ns_stats.get("vector_count", 0)

    # Fetch a sample of vectors to extract unique source filenames
    documents = []
    if vector_count > 0:
        from services.embedding import get_embedding_model
        vectorstore = get_vectorstore(namespace)
        # Dummy search to get vectors with metadata
        results = vectorstore.similarity_search("document", k=min(vector_count, 100))
        seen = set()
        for doc in results:
            filename = doc.metadata.get("source_filename", doc.metadata.get("source", ""))
            category = doc.metadata.get("doc_category", "")
            source_type = doc.metadata.get("source_type", "")
            key = filename
            if key and key not in seen:
                seen.add(key)
                documents.append({
                    "filename": filename,
                    "category": category,
                    "source_type": source_type,
                })

    return {
        "tenant_id": tenant_id,
        "namespace": namespace,
        "vector_count": vector_count,
        "documents": sorted(documents, key=lambda d: d["filename"]),
    }


@router.delete("/documents", status_code=204)
async def delete_all_documents(tenant_id: str):
    """Delete all vectors in the tenant's Pinecone namespace."""
    tenant = await get_tenant_or_404(tenant_id)
    get_raw_index().delete(delete_all=True, namespace=tenant["pinecone_namespace"])
