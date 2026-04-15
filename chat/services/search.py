"""Search orchestrator: decomposition → multi-query → hybrid search → RRF → confidence rerank."""

import json
import logging
from functools import lru_cache

from langchain_anthropic import ChatAnthropic
from langchain_core.documents import Document

from shared.config import settings
from chat.services.bm25 import get_bm25_index
from chat.services.reranker import rerank_with_scores, format_with_confidence
from shared.services.vectorstore import get_vectorstore

logger = logging.getLogger(__name__)

# Dedup key: first N chars of chunk content used to identify unique documents
_DEDUP_PREFIX_LEN = 200

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


@lru_cache()
def _get_haiku():
    return ChatAnthropic(
        model=settings.VISION_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        temperature=0.3,
        max_tokens=150,
        max_retries=2,
    )


async def search(query: str, namespace: str, category: str | None = None) -> str:
    """Full search pipeline returning formatted text."""
    result, _ = await search_with_sources(query, namespace, category)
    return result


async def search_with_sources(
    query: str, namespace: str, category: str | None = None
) -> tuple[str, list[dict]]:
    """Full search pipeline returning (formatted_text, structured_sources)."""
    # Step 1: Decompose complex queries
    sub_queries = await _decompose_query(query)

    # Step 2: For each sub-query, generate variants and search
    all_docs: list[Document] = []
    seen: set[str] = set()
    for sq in sub_queries:
        variants = await _generate_query_variants(sq)
        for v in variants:
            results = _hybrid_search(v, namespace, category=category, k=10)
            for doc in results:
                key = doc.page_content[:_DEDUP_PREFIX_LEN]
                if key not in seen:
                    seen.add(key)
                    all_docs.append(doc)

    if not all_docs:
        return "No relevant documents found for this query.", []

    # Step 3: Rerank with confidence scores
    scored = rerank_with_scores(query, all_docs, top_k=settings.TOP_K)

    # Step 4: Format and extract sources
    formatted = format_with_confidence(scored)
    sources = []
    for doc, score in scored:
        if score >= 0.3:
            sources.append({
                "filename": doc.metadata.get("source_filename", "unknown"),
                "page": doc.metadata.get("page"),
                "category": doc.metadata.get("doc_category", ""),
                "download_link": doc.metadata.get("download_link", ""),
                "relevance_score": round(score, 3),
                "confidence": "HIGH" if score > 0.6 else "MEDIUM",
            })

    return formatted, sources


async def _decompose_query(query: str) -> list[str]:
    """Decompose complex query into sub-queries using Haiku."""
    try:
        llm = _get_haiku()
        result = await llm.ainvoke(_DECOMPOSE_PROMPT.format(query=query))
        parsed = json.loads(result.content.strip())
        if parsed.get("type") == "complex" and parsed.get("sub_queries"):
            return parsed["sub_queries"][:3]
        return [parsed.get("query", query)]
    except Exception:
        logger.debug("Query decomposition failed, using original query")
        return [query]


async def _generate_query_variants(query: str) -> list[str]:
    """Generate alternative queries using Haiku."""
    variants = [query]
    try:
        llm = _get_haiku()
        result = await llm.ainvoke(_MULTI_QUERY_PROMPT.format(query=query))
        parsed = json.loads(result.content.strip())
        if isinstance(parsed, list):
            variants.extend(parsed[:2])
    except Exception:
        logger.debug("Multi-query generation failed, using original only")
    return variants


def _hybrid_search(
    query: str, namespace: str, category: str | None = None, k: int = 10
) -> list[Document]:
    """Combine vector search + BM25 keyword search via RRF."""
    vectorstore = get_vectorstore(namespace)

    # Vector search
    filter_dict = {"doc_category": category} if category else None
    try:
        vector_results = vectorstore.similarity_search(query, k=k, filter=filter_dict)
    except Exception:
        logger.warning("Vector search failed")
        vector_results = []

    # BM25 search — index is built during ingestion (_upsert)
    # If empty (cold start), seed from vector results so BM25 can contribute
    bm25_idx = get_bm25_index(namespace)
    if not bm25_idx.documents and vector_results:
        bm25_idx = get_bm25_index(namespace, vector_results)
    bm25_results = bm25_idx.search(query, k=k) if bm25_idx.documents else []

    # Category filter for BM25 results
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
