"""Cohere embed-v4.0 embedding model.

``langchain_cohere`` transitively loads ~6000 Python modules (accelerate,
torch, transformers, docling) — ~5s cold. To keep non-embedding callers
lightweight (test suite, admin service, LINE webhook warmup) we defer the
import until the model is actually requested.
"""

from functools import lru_cache
from typing import TYPE_CHECKING

from shared.config import settings

if TYPE_CHECKING:
    from langchain_cohere import CohereEmbeddings


@lru_cache()
def get_embedding_model() -> "CohereEmbeddings":
    from langchain_cohere import CohereEmbeddings
    return CohereEmbeddings(
        model=settings.EMBEDDING_MODEL,
        cohere_api_key=settings.COHERE_API_KEY,
    )
