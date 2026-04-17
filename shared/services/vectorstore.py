"""Pinecone vector store with per-namespace caching.

``langchain_pinecone`` / ``pinecone`` are imported lazily: helper functions
that only need metadata access (list/fetch/delete by ID) avoid pulling
``PineconeVectorStore`` (which itself pulls langchain_core embeddings shims).
"""

from functools import lru_cache
from threading import Lock
from typing import TYPE_CHECKING

from shared.config import settings

if TYPE_CHECKING:
    from langchain_pinecone import PineconeVectorStore

_lock = Lock()
_stores: dict[str, "PineconeVectorStore"] = {}


@lru_cache()
def _get_pinecone_index():
    from pinecone import Pinecone
    pc = Pinecone(api_key=settings.PINECONE_API_KEY)
    return pc.Index(settings.PINECONE_INDEX_NAME)


def get_vectorstore(namespace: str | None = None) -> "PineconeVectorStore":
    """Get a PineconeVectorStore scoped to the given namespace (thread-safe cache)."""
    from langchain_pinecone import PineconeVectorStore
    from shared.services.embedding import get_embedding_model

    key = namespace or "__default__"
    if key not in _stores:
        with _lock:
            if key not in _stores:  # double-check after acquiring lock
                _stores[key] = PineconeVectorStore(
                    index=_get_pinecone_index(),
                    embedding=get_embedding_model(),
                    namespace=namespace,
                )
    return _stores[key]


def get_raw_index():
    """Direct Pinecone Index for admin operations (delete, stats)."""
    return _get_pinecone_index()


# ──────────────────────────────────────
# Pinecone iteration helpers
# ──────────────────────────────────────

PINECONE_PAGE_SIZE = 100

# Metadata key under which langchain-pinecone stores page content. Exposed
# here so BM25 warm-up and any other consumer reads from one source of truth.
VECTORSTORE_TEXT_KEY = "text"


def _get_next_token(page) -> str | None:
    """Extract next pagination token, handling edge cases."""
    if not page or not page.pagination:
        return None
    token = getattr(page.pagination, "next", None)
    return token if token else None


def list_all_vector_ids(namespace: str) -> list[str]:
    """Paginate through all vector IDs in a namespace."""
    index = get_raw_index()
    all_ids: list[str] = []
    token = None

    while True:
        page = index.list_paginated(
            namespace=namespace, limit=PINECONE_PAGE_SIZE, pagination_token=token,
        )
        if not page.vectors:
            break
        all_ids.extend(v.id for v in page.vectors)
        token = _get_next_token(page)
        if not token:
            break

    return all_ids


def fetch_metadata_batch(ids: list[str], namespace: str) -> list[dict]:
    """Fetch metadata for a batch of vector IDs. Returns list of metadata dicts."""
    index = get_raw_index()
    results = []
    for i in range(0, len(ids), PINECONE_PAGE_SIZE):
        batch = ids[i:i + PINECONE_PAGE_SIZE]
        fetched = index.fetch(ids=batch, namespace=namespace)
        for vec in fetched.vectors.values():
            results.append(dict(vec.metadata) if vec.metadata else {})
    return results


def get_unique_filenames(namespace: str) -> set[str]:
    """Get all unique source_filenames in a namespace.

    Uses list_paginated + fetch instead of similarity_search to ensure
    exhaustive results regardless of vector content.
    """
    ids = list_all_vector_ids(namespace)
    if not ids:
        return set()
    metadata_list = fetch_metadata_batch(ids, namespace)
    return {m.get("source_filename", "") for m in metadata_list} - {""}


def delete_user_vectors(namespace: str, user_id: str) -> int:
    """Delete every vector in ``namespace`` whose metadata matches ``user_id``.

    Pinecone serverless does not support metadata-filter delete, so we
    list IDs + fetch metadata + delete by ID in batches. Today no ingestion
    path tags vectors with user_id, so this is typically a no-op — but it
    closes the PDPA right-to-erasure gap if user-linked vectors ever appear.
    """
    ids = list_all_vector_ids(namespace)
    if not ids:
        return 0

    index = get_raw_index()
    deleted = 0
    for i in range(0, len(ids), PINECONE_PAGE_SIZE):
        batch = ids[i:i + PINECONE_PAGE_SIZE]
        fetched = index.fetch(ids=batch, namespace=namespace)
        matching: list[str] = []
        for vid, vec in fetched.vectors.items():
            meta = vec.metadata or {}
            if meta.get("user_id") == user_id:
                matching.append(vid)
        if matching:
            index.delete(ids=matching, namespace=namespace)
            deleted += len(matching)
    return deleted


def get_document_list(namespace: str) -> list[dict]:
    """Get unique documents with category/type info for a namespace."""
    ids = list_all_vector_ids(namespace)
    if not ids:
        return []
    metadata_list = fetch_metadata_batch(ids, namespace)
    seen: set[str] = set()
    documents = []
    for meta in metadata_list:
        filename = meta.get("source_filename", "")
        if filename and filename not in seen:
            seen.add(filename)
            documents.append({
                "filename": filename,
                "category": meta.get("doc_category", ""),
                "source_type": meta.get("source_type", ""),
            })
    return documents
