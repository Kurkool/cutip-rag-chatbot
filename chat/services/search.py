"""Search orchestrator: query rewrite → decomposition → multi-query → hybrid search → RRF → confidence rerank → MMR diversify."""

import asyncio
import json
import logging
import re
from langchain_core.documents import Document

from shared.config import settings
from shared.services.dependencies import format_history
from shared.services.llm import get_haiku
from chat.services.bm25 import get_bm25_index, warm_bm25_for_namespace
from chat.services.reranker import _fmt_page, rerank_with_scores, format_with_confidence
from shared.services.vectorstore import get_vectorstore

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    stripped = _JSON_FENCE_RE.sub("", stripped)
    return stripped.strip()


# Dedup key: first N chars of chunk content used to identify unique documents
_DEDUP_PREFIX_LEN = 200

_REWRITE_PROMPT = (
    "Given the conversation history and the user's latest message, rewrite the "
    "latest message as a standalone search query that captures what they really "
    "want to find.\n\n"
    "- If the latest message already stands alone, return it unchanged.\n"
    "- Preserve the original language (Thai → Thai, English → English).\n"
    "- Do not answer the question. Just rewrite it.\n\n"
    "History:\n{history}\n\n"
    "Latest message: {query}\n\n"
    "Rewritten query (no quotes, no explanation):"
)

_DECOMPOSE_PROMPT = (
    "Analyze this question. If it asks about multiple topics or requires comparison, "
    "decompose into separate search queries (max 3). If it's a single-topic question, return it as-is.\n\n"
    "Question: {query}\n\n"
    'Return JSON only: {{"type": "simple", "query": "..."}} or {{"type": "complex", "sub_queries": ["...", "..."]}}'
)

_MULTI_QUERY_PROMPT = (
    "Generate 2 alternative search queries for this question. "
    "One should translate key terms to English, one should use Thai synonyms or rephrase.\n\n"
    "Question: {query}\n\n"
    'Return JSON array only: ["english translation query", "thai synonym query"]'
)


_get_haiku = get_haiku  # Cached Claude Haiku for multi-query + decomposition + rewrite


async def search(query: str, namespace: str, category: str | None = None) -> str:
    """Full search pipeline returning formatted text."""
    result, _ = await search_with_sources(query, namespace, category)
    return result


async def search_with_sources(
    query: str,
    namespace: str,
    category: str | None = None,
    history: list | dict | None = None,
    user_id: str | None = None,
    invalidate_ts: float = 0.0,
) -> tuple[str, list[dict]]:
    """Full search pipeline returning (formatted_text, structured_sources).

    Pipeline: rewrite-with-history → decompose → multi-query variants →
    hybrid search (vector + BM25 + RRF) per variant → dedup → rerank with
    confidence scores → MMR diversify → format + structured sources.

    ``user_id`` is optional; when provided, its first 8 chars are included in
    telemetry log lines for correlating zero-result / low-score incidents
    back to a specific user session.
    """
    uid_tag = (user_id[:8] if user_id else "")
    # Step 0: Rewrite ambiguous follow-up queries with chat context
    search_query = await _rewrite_query_with_history(query, history)

    # Step 1: Decompose complex queries into sub-queries
    sub_queries = await _decompose_query(search_query)
    is_complex = len(sub_queries) > 1

    # Step 1b: Adaptive top_k — multi-topic queries need more context to
    # cover every sub-topic; single-topic queries want tighter precision.
    final_top_k = settings.TOP_K_COMPLEX if is_complex else settings.TOP_K
    # Rerank candidate pool = 2× final so MMR has room to trade relevance
    # for diversity; floor at 10 for tiny result sets.
    rerank_top_k = max(final_top_k * 2, 10)

    # Step 2a: Generate variants for all sub-queries in parallel (Haiku fan-out)
    variant_lists = await asyncio.gather(
        *[_generate_query_variants(sq) for sq in sub_queries]
    )

    # Step 2b: Flatten + dedup variants (same text may repeat across sub_queries)
    unique_variants: list[str] = []
    seen_variants: set[str] = set()
    for variants in variant_lists:
        for v in variants:
            if v not in seen_variants:
                seen_variants.add(v)
                unique_variants.append(v)

    # Step 2c: Fan out hybrid search across all variants in parallel
    search_results = await asyncio.gather(
        *[
            _hybrid_search(v, namespace, category=category, k=10, invalidate_ts=invalidate_ts)
            for v in unique_variants
        ]
    )

    # Step 2d: Merge + dedup returned docs (preserving first-seen order)
    all_docs: list[Document] = []
    seen: set[str] = set()
    for results in search_results:
        for doc in results:
            key = doc.page_content[:_DEDUP_PREFIX_LEN]
            if key not in seen:
                seen.add(key)
                all_docs.append(doc)

    if not all_docs:
        logger.info(
            "search_quality: zero_results namespace=%s user=%s query=%r rewritten=%r",
            namespace, uid_tag, query[:80], search_query[:80],
        )
        return (
            "NO_RESULTS: Search returned zero documents for this query. "
            "Tell the user honestly you couldn't find this information in the "
            "knowledge base, and suggest contacting faculty staff. Do NOT "
            "fabricate an answer."
        ), []

    # Step 3: Rerank with confidence scores against the REWRITTEN query
    scored = await rerank_with_scores(search_query, all_docs, top_k=rerank_top_k)

    # Step 4: MMR diversify — prevent top-K collapsing into near-duplicates
    diversified = _mmr_diversify(scored, top_k=final_top_k)

    logger.debug(
        "search: complex=%s sub_queries=%d rerank_top_k=%d final_top_k=%d selected=%d",
        is_complex, len(sub_queries), rerank_top_k, final_top_k, len(diversified),
    )

    # Telemetry: flag low-confidence top-1 queries (tune-later signal)
    if diversified and diversified[0][1] < settings.TELEMETRY_LOW_TOP1_SCORE:
        logger.info(
            "search_quality: low_top1_score=%.3f namespace=%s user=%s query=%r",
            diversified[0][1], namespace, uid_tag, search_query[:80],
        )

    # Step 5: Format and extract sources
    formatted = format_with_confidence(diversified)
    sources = []
    for doc, score in diversified:
        if score >= settings.RERANKER_MIN_CONFIDENCE:
            # Normalize page: Pinecone round-trips ints as floats (1 → 1.0).
            # Emit as clean string ("1") for display-ready JSON; empty when
            # the source has no page dimension (XLSX, flat text).
            page_display = _fmt_page(doc.metadata.get("page")) or None
            sources.append({
                "filename": doc.metadata.get("source_filename", "unknown"),
                "page": page_display,
                "category": doc.metadata.get("doc_category", ""),
                "download_link": doc.metadata.get("download_link", ""),
                "relevance_score": round(score, 3),
                "confidence": "HIGH" if score > 0.6 else "MEDIUM",
            })

    return formatted, sources


async def _rewrite_query_with_history(
    query: str, history: list | dict | None,
) -> str:
    """Rewrite a follow-up query into a standalone search query using history."""
    if not history:
        return query
    history_text = format_history(history)
    if not history_text or history_text == "ไม่มีประวัติสนทนา":
        return query
    try:
        llm = _get_haiku()
        result = await llm.ainvoke(
            _REWRITE_PROMPT.format(history=history_text, query=query)
        )
        rewritten = (result.content or "").strip().strip('"').strip("'")
        # Guardrails: empty or suspiciously long → fall back to original
        if not rewritten or len(rewritten) > max(len(query) * 5, 500):
            return query
        if rewritten != query:
            logger.debug("query rewrite: %r → %r", query, rewritten)
        return rewritten
    except Exception as exc:
        logger.info("Query rewriting failed (%s), using original", exc)
        return query


async def _decompose_query(query: str) -> list[str]:
    """Decompose complex query into sub-queries using Haiku."""
    try:
        llm = _get_haiku()
        result = await llm.ainvoke(_DECOMPOSE_PROMPT.format(query=query))
        parsed = json.loads(_strip_json_fence(result.content))
        if parsed.get("type") == "complex" and parsed.get("sub_queries"):
            return parsed["sub_queries"][:3]
        return [parsed.get("query", query)]
    except Exception as exc:
        logger.info("Query decomposition failed (%s), using original query", exc)
        return [query]


async def _generate_query_variants(query: str) -> list[str]:
    """Generate alternative queries using Haiku."""
    variants = [query]
    try:
        llm = _get_haiku()
        result = await llm.ainvoke(_MULTI_QUERY_PROMPT.format(query=query))
        parsed = json.loads(_strip_json_fence(result.content))
        if isinstance(parsed, list):
            variants.extend(parsed[:2])
    except Exception as exc:
        logger.info("Multi-query generation failed (%s), using original only", exc)
    return variants


def _vector_search_sync(query: str, namespace: str, k: int, filter_dict) -> list[Document]:
    try:
        return get_vectorstore(namespace).similarity_search(query, k=k, filter=filter_dict)
    except Exception:
        logger.warning("Vector search failed")
        return []


async def _hybrid_search(
    query: str,
    namespace: str,
    category: str | None = None,
    k: int = 10,
    invalidate_ts: float = 0.0,
) -> list[Document]:
    """Combine vector search + BM25 keyword search via RRF.

    BM25 is warmed from the full Pinecone namespace on first query per process,
    and re-warmed when ``invalidate_ts`` (from the tenant's Firestore doc,
    written by the ingest-worker) is newer than the cached index's warmed_ts.
    This is the cross-process invalidation path — without it, the chat
    container serves stale search results for hours/days after an ingest.
    """
    filter_dict = {"doc_category": category} if category else None
    vector_results = await asyncio.to_thread(
        _vector_search_sync, query, namespace, k, filter_dict,
    )

    bm25_idx = get_bm25_index(namespace)
    stale = invalidate_ts > 0 and getattr(bm25_idx, "warmed_ts", 0) < invalidate_ts
    if not bm25_idx.documents or stale:
        if stale:
            logger.info(
                "BM25 stale for namespace '%s' (cached=%.1f, invalidated=%.1f) — re-warming",
                namespace, getattr(bm25_idx, "warmed_ts", 0), invalidate_ts,
            )
        bm25_idx = await asyncio.to_thread(warm_bm25_for_namespace, namespace)

    if bm25_idx.documents:
        bm25_results = await asyncio.to_thread(bm25_idx.search, query, k)
    else:
        bm25_results = []

    if category and bm25_results:
        bm25_results = [d for d in bm25_results if d.metadata.get("doc_category") == category]

    if not vector_results:
        return bm25_results[:k]
    if not bm25_results:
        return vector_results[:k]

    return reciprocal_rank_fusion(vector_results, bm25_results, k=settings.RRF_K)[:k]


def reciprocal_rank_fusion(
    vector_results: list[Document],
    bm25_results: list[Document],
    k: int = 60,
) -> list[Document]:
    """Merge two ranked lists using Reciprocal Rank Fusion."""
    doc_scores: dict[str, tuple[Document, float]] = {}

    for rank, doc in enumerate(vector_results):
        key = doc.page_content[:_DEDUP_PREFIX_LEN]
        score = 1 / (k + rank + 1)
        if key in doc_scores:
            doc_scores[key] = (doc, doc_scores[key][1] + score)
        else:
            doc_scores[key] = (doc, score)

    for rank, doc in enumerate(bm25_results):
        key = doc.page_content[:_DEDUP_PREFIX_LEN]
        score = 1 / (k + rank + 1)
        if key in doc_scores:
            doc_scores[key] = (doc, doc_scores[key][1] + score)
        else:
            doc_scores[key] = (doc, score)

    sorted_items = sorted(doc_scores.values(), key=lambda x: -x[1])
    return [doc for doc, _ in sorted_items]


def _mmr_diversify(
    scored_docs: list[tuple[Document, float]],
    top_k: int,
    lambda_: float | None = None,
) -> list[tuple[Document, float]]:
    """Maximal Marginal Relevance: pick top_k with relevance-vs-diversity trade-off.

    Uses token-overlap Jaccard on first 500 chars as a cheap similarity proxy
    (no extra embedding calls). For each candidate, combined score is
    ``λ * rerank_score - (1 - λ) * max_similarity_to_already_selected``.

    Complexity O(N * top_k) where N = len(scored_docs); fine for N ≤ ~50.
    Tokens are indexed positionally against the original ``scored_docs`` list
    (not ``id(doc)``) so GC can't invalidate cache keys while the loop runs.
    """
    if not scored_docs:
        return []
    if len(scored_docs) <= top_k:
        return scored_docs

    lam = settings.MMR_LAMBDA if lambda_ is None else lambda_

    def _tokens(doc: Document) -> frozenset[str]:
        return frozenset(re.findall(r"[\w\d]+", doc.page_content[:500].lower()))

    # Positional cache — stable regardless of object identity/lifetime.
    token_cache: list[frozenset[str]] = [_tokens(doc) for doc, _ in scored_docs]

    def _jaccard(a: frozenset, b: frozenset) -> float:
        if not a or not b:
            return 0.0
        inter = len(a & b)
        union = len(a | b)
        return inter / union if union else 0.0

    remaining_indices = list(range(len(scored_docs)))
    selected_indices: list[int] = [remaining_indices.pop(0)]  # top-1 always stays

    while remaining_indices and len(selected_indices) < top_k:
        best_local_idx = 0
        best_combined = -float("inf")
        for local_idx, cand_idx in enumerate(remaining_indices):
            cand_tokens = token_cache[cand_idx]
            score = scored_docs[cand_idx][1]
            max_sim = max(
                _jaccard(cand_tokens, token_cache[sel_idx])
                for sel_idx in selected_indices
            )
            combined = lam * score - (1 - lam) * max_sim
            if combined > best_combined:
                best_combined = combined
                best_local_idx = local_idx
        selected_indices.append(remaining_indices.pop(best_local_idx))

    return [scored_docs[i] for i in selected_indices]
