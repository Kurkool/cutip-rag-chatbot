"""Cohere Rerank v3.5 for precision document reranking.

Cohere's Python SDK is synchronous. We expose async wrappers that run the
network call in a thread pool so they do not stall the asyncio event loop.
"""

import asyncio
from functools import lru_cache

import cohere
from langchain_core.documents import Document

from shared.config import settings


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


async def rerank_documents(
    query: str, documents: list[Document], top_k: int
) -> list[Document]:
    """Re-score documents by relevance using Cohere cross-encoder."""
    if not documents:
        return documents
    response = await asyncio.to_thread(_rerank_sync, query, documents, top_k)
    return [documents[r.index] for r in response.results]


async def rerank_with_scores(
    query: str, documents: list[Document], top_k: int
) -> list[tuple[Document, float]]:
    """Re-score and return (document, relevance_score) tuples."""
    if not documents:
        return []
    response = await asyncio.to_thread(_rerank_sync, query, documents, top_k)
    return [(documents[r.index], r.relevance_score) for r in response.results]


_MAX_RESULT_CHARS = 2000


def format_with_confidence(scored_docs: list[tuple[Document, float]]) -> str:
    """Format with confidence tiers. Filter out score < 0.3."""
    results = []
    for i, (doc, score) in enumerate(scored_docs, 1):
        if score < 0.3:
            continue
        confidence = (
            "[HIGH CONFIDENCE]"
            if score > 0.6
            else "[MEDIUM - may not be exact match]"
        )
        source = doc.metadata.get("source_filename", "unknown")
        page = doc.metadata.get("page", "")
        category = doc.metadata.get("doc_category", "")
        download_link = doc.metadata.get("download_link", "")
        header = f"{confidence} [{i}] Source: {source}"
        if page and page != "N/A":
            header += f" (page {page})"
        if category:
            header += f" [{category}]"
        if download_link:
            header += f"\n    Download: {download_link}"
        content = doc.page_content[:_MAX_RESULT_CHARS]
        results.append(f"{header}\n{content}")
    if not results:
        return "No relevant documents found with sufficient confidence."
    return "\n\n---\n\n".join(results)
