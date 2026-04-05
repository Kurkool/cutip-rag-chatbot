"""Pinecone vector store with per-namespace caching."""

from functools import lru_cache
from threading import Lock

from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone

from config import settings
from services.embedding import get_embedding_model

_lock = Lock()
_stores: dict[str, PineconeVectorStore] = {}


@lru_cache()
def _get_pinecone_index():
    pc = Pinecone(api_key=settings.PINECONE_API_KEY)
    return pc.Index(settings.PINECONE_INDEX_NAME)


def get_vectorstore(namespace: str | None = None) -> PineconeVectorStore:
    """Get a PineconeVectorStore scoped to the given namespace (thread-safe cache)."""
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
