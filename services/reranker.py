"""Cohere Rerank v3.5 for precision document reranking."""

from functools import lru_cache

import cohere
from langchain_core.documents import Document

from config import settings


@lru_cache()
def _get_client() -> cohere.Client:
    return cohere.Client(api_key=settings.COHERE_API_KEY)


def get_reranker():
    """Warm up Cohere client on startup."""
    _get_client()


def rerank_documents(
    query: str, documents: list[Document], top_k: int
) -> list[Document]:
    """Re-score documents by relevance using Cohere cross-encoder."""
    if not documents:
        return documents

    response = _get_client().rerank(
        model=settings.RERANKER_MODEL,
        query=query,
        documents=[doc.page_content for doc in documents],
        top_n=top_k,
    )
    return [documents[r.index] for r in response.results]
