"""Centralized LLM client factory — single source of truth for all model configurations."""

from functools import lru_cache

from langchain_anthropic import ChatAnthropic

from shared.config import settings


@lru_cache()
def get_opus() -> ChatAnthropic:
    """Claude Opus — main agentic reasoning (chat)."""
    return ChatAnthropic(
        model=settings.LLM_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=8192,
        max_retries=3,
    )


@lru_cache()
def get_haiku() -> ChatAnthropic:
    """Claude Haiku — multi-query generation, query decomposition (search)."""
    return ChatAnthropic(
        model=settings.VISION_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        temperature=0.3,
        max_tokens=150,
        max_retries=2,
    )


@lru_cache()
def get_haiku_precise() -> ChatAnthropic:
    """Claude Haiku — deterministic tasks: summarization, enrichment (temp=0)."""
    return ChatAnthropic(
        model=settings.VISION_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        temperature=0,
        max_tokens=200,
        max_retries=3,
    )


@lru_cache()
def get_haiku_vision() -> ChatAnthropic:
    """Claude Haiku — Vision: PDF pages, spreadsheet interpretation (high token limit)."""
    return ChatAnthropic(
        model=settings.VISION_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        temperature=0,
        max_tokens=4096,
        max_retries=3,
    )
