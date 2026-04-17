"""Centralized LLM client factory — single source of truth for all model configurations.

``langchain_anthropic`` transitively loads ``transformers`` → ``torch``
(~3s cold). We defer the import until a model is actually requested so the
admin service, tests, and webhook startup don't pay the cost.
"""

from functools import lru_cache
from typing import TYPE_CHECKING

from shared.config import settings

if TYPE_CHECKING:
    from langchain_anthropic import ChatAnthropic


@lru_cache()
def get_opus() -> "ChatAnthropic":
    """Claude Opus 4.7 — main agentic reasoning (chat).

    Opus 4.7 removes ``temperature``/``top_p``/``top_k`` (sending them 400s).
    It also removes fixed ``budget_tokens`` thinking in favour of adaptive
    thinking — enabled here since agentic RAG qualifies as "remotely
    complicated" per the claude-api guidance.
    """
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model=settings.LLM_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        max_tokens=8192,
        max_retries=3,
        thinking={"type": "adaptive"},
    )


@lru_cache()
def get_haiku() -> "ChatAnthropic":
    """Claude Haiku — multi-query generation, query decomposition (search)."""
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model=settings.VISION_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        temperature=0.3,
        max_tokens=150,
        max_retries=2,
    )


@lru_cache()
def get_haiku_precise() -> "ChatAnthropic":
    """Claude Haiku — deterministic tasks: summarization, enrichment (temp=0)."""
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model=settings.VISION_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        temperature=0,
        max_tokens=200,
        max_retries=3,
    )


@lru_cache()
def get_haiku_vision() -> "ChatAnthropic":
    """Claude Haiku — Vision-lite: spreadsheet layout interpretation (no OCR).

    Kept on Haiku because ``interpret_spreadsheet`` works from already-
    extracted tabular text, not images — it's a layout/formatting task where
    Haiku is both cheap and adequate.
    """
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model=settings.VISION_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        temperature=0,
        max_tokens=4096,
        max_retries=3,
    )


@lru_cache()
def get_ocr_llm() -> "ChatAnthropic":
    """Claude Opus 4.7 — Vision OCR for PDF pages with Thai text.

    Upgraded from Haiku 4.5 on 2026-04-17 after auditing an announcement PDF
    with 23 Thai person names: Haiku dropped the whole list (OCR'd garbage
    into names, emitted refusal strings like "Could you please re-upload")
    while the fix-A text-layer path was still being built. Opus 4.7 Thai OCR
    is dramatically more accurate; the cost hit is modest because Vision
    only runs when the PyMuPDF text layer is truly empty (scanned pages).
    """
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model=settings.OCR_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        max_tokens=4096,
        max_retries=3,
        thinking={"type": "adaptive"},
    )
