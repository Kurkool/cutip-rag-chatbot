"""Cohere embed-v4.0 embedding model."""

from functools import lru_cache

from langchain_cohere import CohereEmbeddings

from config import settings


@lru_cache()
def get_embedding_model() -> CohereEmbeddings:
    return CohereEmbeddings(
        model=settings.EMBEDDING_MODEL,
        cohere_api_key=settings.COHERE_API_KEY,
    )
