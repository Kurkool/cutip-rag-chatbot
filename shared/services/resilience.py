"""Shared async resilience helper: semaphore + exponential-backoff retry.

Used by ingestion paths that fan out Haiku calls — enrichment, DOCX image
Vision, XLSX batch interpretation. Without backoff, a ~50-image DOCX
serialized 50 Haiku calls and silently dropped results after the rate
limit kicked in. With this helper, calls are bounded and retried on 429.
"""

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Fallback substring markers, used only when structured exception checks
# don't match (non-anthropic errors, wrapped exceptions from langchain).
# Kept narrow: "rate limit", "overload", "too many requests", explicit "429".
# Previously included bare "rate" which false-matched "generation rate exceeded"
# (a quota error, non-retryable).
_RATE_LIMIT_MARKERS = ("429", "rate limit", "rate_limit", "overload", "too many requests")


def _is_rate_limited(exc: Exception) -> bool:
    """Detect rate-limit errors. Prefer structured exception class, fall back to substring."""
    # Structured check — most reliable for direct Anthropic SDK calls.
    try:
        import anthropic  # lazy import
        if isinstance(exc, anthropic.RateLimitError):
            return True
    except ImportError:
        pass
    # Generic HTTP-status check — catches httpx/requests wrappers.
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status == 429:
        return True
    # Substring fallback — matches wrapped langchain exceptions whose typing
    # is lost by the time we catch them.
    msg = str(exc).lower()
    return any(marker in msg for marker in _RATE_LIMIT_MARKERS)


async def call_with_backoff(
    coro_factory: Callable[[], Awaitable[T]],
    semaphore: asyncio.Semaphore,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    label: str = "call",
) -> T | None:
    """Run an async call under ``semaphore`` with exponential backoff on rate errors.

    ``coro_factory`` is a zero-arg callable that returns a *fresh* coroutine
    each attempt (required because awaiting a coroutine exhausts it). On
    non-rate-limit errors we log and return None immediately — we only retry
    when ``_is_rate_limited(exc)`` is True.

    Returns the awaited result, or None if the call ultimately fails.
    """
    async with semaphore:
        delay = initial_delay
        for attempt in range(max_retries):
            try:
                return await coro_factory()
            except Exception as exc:
                is_last = attempt == max_retries - 1
                is_rate = _is_rate_limited(exc)
                if is_last or not is_rate:
                    logger.warning(
                        "%s failed (attempt %d/%d, rate=%s): %s",
                        label, attempt + 1, max_retries, is_rate, exc,
                    )
                    return None
                await asyncio.sleep(delay)
                delay *= 2
    return None
