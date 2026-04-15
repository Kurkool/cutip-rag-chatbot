# services/bm25.py
"""BM25 keyword search index per namespace."""

import logging
import re
from threading import Lock

from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

_lock = Lock()
_cache: dict[str, "BM25Index"] = {}


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer: split on whitespace and punctuation, lowercase."""
    return re.findall(r"[\w\d]+", text.lower())


class BM25Index:
    """In-memory BM25 index over a list of Documents."""

    def __init__(self, documents: list[Document]):
        self.documents = documents
        corpus = [_tokenize(doc.page_content) for doc in documents]
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
