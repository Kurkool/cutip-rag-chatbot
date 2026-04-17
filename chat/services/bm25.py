# services/bm25.py
"""BM25 keyword search index per namespace.

The index is warmed on first access by loading the full namespace from
Pinecone (list all IDs → fetch metadata+text → build BM25). Previously
the index was seeded from the vector-search top-K of the current query,
which meant BM25 only re-ranked vector results rather than providing
lexical recall across the full corpus. Warming from the whole namespace
makes the hybrid search truly hybrid.

Concurrent warm-up is guarded by a per-namespace lock with double-checked
locking so two parallel cold requests don't both fetch the entire
namespace.
"""

import logging
import re
import time
from threading import Lock

from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

_lock = Lock()
_cache: dict[str, "BM25Index"] = {}
# Per-namespace warm locks — created lazily under `_lock`. Ensures two
# concurrent cold readers for the same namespace run ONE full-namespace
# Pinecone fetch between them, not one per reader.
_warm_locks: dict[str, Lock] = {}


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer: split on whitespace and punctuation, lowercase."""
    return re.findall(r"[\w\d]+", text.lower())


_FILENAME_EXT_RE = re.compile(r"\.[a-zA-Z0-9]{2,4}$")


def _doc_tokens(doc: Document) -> list[str]:
    """Tokenize a document, prepending filename stem so lexical queries that
    name a file (e.g. English "slide presentation" asking about slide.pdf)
    can match even when the body is a different language from the query.
    Without this, a Thai-content chunk with an English filename was
    unreachable via BM25 for English queries.
    """
    filename = doc.metadata.get("source_filename", "") or ""
    stem = _FILENAME_EXT_RE.sub("", filename)
    return _tokenize(f"{stem} {doc.page_content}")


class BM25Index:
    """In-memory BM25 index over a list of Documents.

    ``warmed_ts`` records when the index was built (unix seconds). Callers
    compare this against ``tenants/{id}.bm25_invalidate_ts`` in Firestore:
    if the tenant's invalidate_ts is newer, the index is stale and must be
    re-warmed. This is how cross-process invalidation works between the
    ingest-worker (writes invalidate_ts) and chat-api (reads + re-warms).
    """

    def __init__(self, documents: list[Document]):
        self.documents = documents
        self.warmed_ts = time.time()
        corpus = [_doc_tokens(doc) for doc in documents]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def search(self, query: str, k: int = 10) -> list[Document]:
        if not self._bm25 or not self.documents:
            return []
        tokens = _tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        top_indices = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
        return [self.documents[i] for i in top_indices if scores[i] > 0]


def _load_namespace_documents(namespace: str) -> list[Document]:
    """Fetch every (content, metadata) in a Pinecone namespace as Documents.

    Lazy imports to avoid pulling langchain_pinecone at module load.
    """
    from shared.services.vectorstore import (
        PINECONE_PAGE_SIZE,
        VECTORSTORE_TEXT_KEY,
        get_raw_index,
        list_all_vector_ids,
    )

    ids = list_all_vector_ids(namespace)
    if not ids:
        return []

    index = get_raw_index()
    docs: list[Document] = []
    for i in range(0, len(ids), PINECONE_PAGE_SIZE):
        batch = ids[i:i + PINECONE_PAGE_SIZE]
        fetched = index.fetch(ids=batch, namespace=namespace)
        for vec in fetched.vectors.values():
            meta = dict(vec.metadata) if vec.metadata else {}
            content = meta.pop(VECTORSTORE_TEXT_KEY, "")
            if content:
                docs.append(Document(page_content=content, metadata=meta))
    return docs


def _get_warm_lock(namespace: str) -> Lock:
    """Return (creating if needed) the per-namespace warm lock."""
    with _lock:
        lock = _warm_locks.get(namespace)
        if lock is None:
            lock = Lock()
            _warm_locks[namespace] = lock
    return lock


def warm_bm25_for_namespace(namespace: str) -> BM25Index:
    """Build a BM25 index from the full namespace. Blocking — wrap in to_thread.

    Double-checked locking: two concurrent cold readers only fetch Pinecone
    once. The second reader waits on the lock, re-reads the cache, sees it
    populated, and returns the already-built index.
    """
    with _lock:
        cached = _cache.get(namespace)
    if cached is not None and cached.documents:
        return cached

    warm_lock = _get_warm_lock(namespace)
    with warm_lock:
        # Re-check after acquiring the lock: another thread may have warmed.
        with _lock:
            cached = _cache.get(namespace)
        if cached is not None and cached.documents:
            return cached

        try:
            docs = _load_namespace_documents(namespace)
        except Exception:
            logger.exception("BM25 warm-up failed for namespace '%s'", namespace)
            docs = []
        idx = BM25Index(docs)
        with _lock:
            _cache[namespace] = idx
        logger.info("BM25 warmed for namespace '%s': %d documents", namespace, len(docs))
        return idx


def get_bm25_index(namespace: str, documents: list[Document] | None = None) -> BM25Index:
    """Get or create BM25 index for a namespace. Pass documents to build/rebuild."""
    with _lock:
        if documents is not None:
            _cache[namespace] = BM25Index(documents)
        if namespace not in _cache:
            _cache[namespace] = BM25Index([])
        return _cache[namespace]


def invalidate_bm25_cache(namespace: str) -> None:
    """Invalidate cached BM25 index when new documents are ingested."""
    with _lock:
        _cache.pop(namespace, None)
