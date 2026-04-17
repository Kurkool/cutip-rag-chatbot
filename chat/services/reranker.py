"""Cohere Rerank v3.5 for precision document reranking.

Cohere's Python SDK is synchronous. We expose async wrappers that run the
network call in a thread pool so they do not stall the asyncio event loop.

Rate-limit protection: the network call is wrapped in ``call_with_backoff``
so a transient 429 triggers exponential retry instead of silently returning
an empty result. If all retries fail, we fall back to the original document
order (better than empty — user gets raw hybrid-search results without
rerank weighting, instead of "no results found").
"""

import asyncio
from functools import lru_cache

import cohere
from langchain_core.documents import Document

from shared.config import settings
from shared.services.resilience import call_with_backoff

# Cohere Trial: 100 reqs/min. Dedicated per-request semaphore so rerank
# doesn't monopolize the ingest semaphore and vice versa.
_RERANK_CONCURRENCY = 5


@lru_cache()
def _get_client() -> cohere.Client:
    return cohere.Client(api_key=settings.COHERE_API_KEY)


def get_reranker():
    """Warm up Cohere client on startup."""
    _get_client()


def _rerank_sync(query: str, docs: list[Document], top_k: int):
    return _get_client().rerank(
        model=settings.RERANKER_MODEL,
        query=query,
        documents=[doc.page_content for doc in docs],
        top_n=top_k,
    )


_rerank_sem = asyncio.Semaphore(_RERANK_CONCURRENCY)


async def _rerank_with_retry(query: str, documents: list[Document], top_k: int):
    """Wrap _rerank_sync with retry + semaphore. Returns None on sustained failure."""
    async def _call():
        return await asyncio.to_thread(_rerank_sync, query, documents, top_k)

    return await call_with_backoff(
        _call,
        semaphore=_rerank_sem,
        max_retries=3,
        label="cohere_rerank",
    )


async def rerank_documents(
    query: str, documents: list[Document], top_k: int
) -> list[Document]:
    """Re-score documents by relevance using Cohere cross-encoder.

    On rerank failure (after retries), falls back to the top-K documents
    in original (post-RRF) order. Better than empty results.
    """
    if not documents:
        return documents
    response = await _rerank_with_retry(query, documents, top_k)
    if response is None:
        return documents[:top_k]
    return [documents[r.index] for r in response.results]


async def rerank_with_scores(
    query: str, documents: list[Document], top_k: int
) -> list[tuple[Document, float]]:
    """Re-score and return (document, relevance_score) tuples.

    Fallback on rerank failure: return top-K docs with a neutral confidence
    score (0.5) so the downstream format_with_confidence treats them as
    MEDIUM confidence rather than dropping them. Rerank being unreachable
    should degrade, not fail, the user's query.
    """
    if not documents:
        return []
    response = await _rerank_with_retry(query, documents, top_k)
    if response is None:
        # Neutral MEDIUM-confidence fallback — downstream 0.3 filter keeps them
        return [(doc, 0.5) for doc in documents[:top_k]]
    return [(documents[r.index], r.relevance_score) for r in response.results]


_MAX_RESULT_CHARS = 2000


import math


def _fmt_page(page: float | int | str | None) -> str:
    """Normalize a Pinecone-round-tripped page number for display.

    Pinecone stores metadata numerics as double-precision floats, so an int
    ``1`` ingested comes back as float ``1.0`` — and ``str(1.0)`` is ``"1.0"``,
    which leaks to users as ``(p.1.0)`` in LINE Flex messages and as
    ``(page 1.0)`` in LLM context. Convert whole-number floats back to the
    integer display they were meant to be.

    Hardening against metadata drift (ingest bug could theoretically write a
    bool, NaN, or an unreasonably-large page):
    - ``bool`` values are rejected (``True``/``False`` are ``int`` subclasses
      and would otherwise render as "1"/"0" → "page 0" looks like a real page)
    - NaN/±Inf and numbers outside ``[1, 10000]`` collapse to ``""``
    - Non-numeric strings pass through untouched (e.g., "cover")
    """
    if page is None or page == "" or page == "N/A":
        return ""
    if isinstance(page, bool):
        return ""
    try:
        f = float(page)
    except (TypeError, ValueError):
        return str(page)
    if not math.isfinite(f):
        return ""
    if f < 1 or f > 10000:
        return ""
    return str(int(f)) if f.is_integer() else str(page)


def format_with_confidence(scored_docs: list[tuple[Document, float]]) -> str:
    """Format search results for the agent with confidence tiers.

    Filters chunks with ``score < settings.RERANKER_MIN_CONFIDENCE``. The
    returned string is consumed by the LLM as tool output, not shown to the
    user directly — it must teach the LLM both the facts AND the expected
    citation style (inline markdown links).

    Each retained chunk renders as:
        [HIGH|MEDIUM] [1] filename (page N) [category] INLINE_LINK: [name](url)
        <page content…>

    The ``INLINE_LINK:`` hint shows the LLM the exact markdown shape to use
    when embedding download links in its final answer. See the system
    prompt's "Inline download links" section for the user-facing rule.
    """
    results = []
    for i, (doc, score) in enumerate(scored_docs, 1):
        if score < settings.RERANKER_MIN_CONFIDENCE:
            continue
        confidence = (
            "[HIGH CONFIDENCE]"
            if score > 0.6
            else "[MEDIUM - may not be exact match]"
        )
        # Fall back when the field exists but is empty-string so INLINE_LINK
        # never renders as a zero-width [](url) in the final answer.
        source = doc.metadata.get("source_filename") or "unknown"
        page = _fmt_page(doc.metadata.get("page", ""))
        category = doc.metadata.get("doc_category", "")
        download_link = doc.metadata.get("download_link", "")
        header = f"{confidence} [{i}] {source}"
        if page:
            header += f" (page {page})"
        if category:
            header += f" [{category}]"
        if download_link:
            # Model the exact markdown format we want the LLM to emit.
            header += f" INLINE_LINK: [{source}]({download_link})"
        content = doc.page_content[:_MAX_RESULT_CHARS]
        results.append(f"{header}\n{content}")
    if not results:
        # Actionable marker — clearer than "No relevant documents…" for the
        # LLM to recognize. Paired with system-prompt rules on honest refusal.
        return (
            "NO_RESULTS: Search returned no chunks above the confidence "
            "threshold for this query. Tell the user honestly you couldn't "
            "find this information in the knowledge base, and suggest "
            "contacting faculty staff. Do NOT fabricate an answer."
        )
    return "\n\n---\n\n".join(results)
