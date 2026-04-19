"""Tier-3 reliability tests: Cohere rerank retry, Vision MIME autodetect,
per-tenant LINE webhook rate limit.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document

from tests.conftest import fake_db


# ──────────────────────────────────────
# Cohere rerank retry + fallback
# ──────────────────────────────────────

@pytest.mark.asyncio
async def test_rerank_retries_on_rate_limit_then_succeeds():
    """A transient 429 from Cohere must be retried, not swallowed."""
    from chat.services.reranker import rerank_with_scores

    calls = {"n": 0}

    def flaky_client(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("429 rate limit exceeded")
        resp = MagicMock()
        resp.results = [MagicMock(index=0, relevance_score=0.9)]
        return resp

    with (
        patch("chat.services.reranker._get_client") as mock_client,
        patch("shared.services.resilience.asyncio.sleep", new=AsyncMock()),
    ):
        mock_client.return_value.rerank.side_effect = flaky_client
        docs = [Document(page_content="test", metadata={})]
        results = await rerank_with_scores("q", docs, top_k=1)

    assert calls["n"] == 2, "expected retry after first 429"
    assert len(results) == 1 and results[0][1] == 0.9


@pytest.mark.asyncio
async def test_rerank_falls_back_to_neutral_score_on_persistent_failure():
    """When rerank gives up, return docs with neutral 0.5 confidence — not empty."""
    from chat.services.reranker import rerank_with_scores

    with (
        patch("chat.services.reranker._get_client") as mock_client,
        patch("shared.services.resilience.asyncio.sleep", new=AsyncMock()),
    ):
        mock_client.return_value.rerank.side_effect = RuntimeError("429 too many")
        docs = [
            Document(page_content="a", metadata={}),
            Document(page_content="b", metadata={}),
            Document(page_content="c", metadata={}),
        ]
        results = await rerank_with_scores("q", docs, top_k=2)

    # Graceful fallback: top-K docs with 0.5 (MEDIUM) score, not empty
    assert len(results) == 2
    assert all(score == 0.5 for _, score in results)


@pytest.mark.asyncio
async def test_rerank_retries_on_structured_429_error():
    """Regression guard for Cohere SDK: TooManyRequestsError(ApiError) has
    status_code=429 but its .message doesn't always contain '429' or 'rate'.
    Must still retry via the structured `status_code == 429` branch of
    _is_rate_limited, not the substring fallback.
    """
    from chat.services.reranker import rerank_with_scores

    class FakeApiError(Exception):
        """Mimics cohere.core.api_error.ApiError shape."""
        status_code = 429

        def __str__(self):
            return "service temporarily unavailable"  # no 'rate' substring!

    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            raise FakeApiError()
        resp = MagicMock()
        resp.results = [MagicMock(index=0, relevance_score=0.77)]
        return resp

    with (
        patch("chat.services.reranker._get_client") as mock_client,
        patch("shared.services.resilience.asyncio.sleep", new=AsyncMock()),
    ):
        mock_client.return_value.rerank.side_effect = flaky
        docs = [Document(page_content="x", metadata={})]
        results = await rerank_with_scores("q", docs, top_k=1)

    assert calls["n"] == 2, "structured 429 via status_code must trigger retry"
    assert results[0][1] == 0.77


@pytest.mark.asyncio
async def test_rerank_does_not_retry_on_non_rate_errors():
    """Bad-request-style errors (schema mismatch etc.) should not retry."""
    from chat.services.reranker import rerank_with_scores

    calls = {"n": 0}

    def bad_request(*args, **kwargs):
        calls["n"] += 1
        raise ValueError("malformed document list")

    with patch("chat.services.reranker._get_client") as mock_client:
        mock_client.return_value.rerank.side_effect = bad_request
        docs = [Document(page_content="x", metadata={})]
        results = await rerank_with_scores("q", docs, top_k=1)

    assert calls["n"] == 1, "must not retry non-rate errors"
    # Still gracefully degrade — neutral fallback
    assert len(results) == 1 and results[0][1] == 0.5


# ──────────────────────────────────────
# Per-tenant LINE webhook rate limit
# ──────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_tenant_rate_buckets():
    import chat.routers.webhook as w
    with w._tenant_rate_lock:
        w._tenant_rate_buckets.clear()
    yield
    with w._tenant_rate_lock:
        w._tenant_rate_buckets.clear()


def test_tenant_rate_check_within_limit_passes():
    from chat.routers.webhook import _tenant_rate_check, _TENANT_WEBHOOK_LIMIT_PER_WINDOW
    for _ in range(_TENANT_WEBHOOK_LIMIT_PER_WINDOW - 1):
        assert _tenant_rate_check("tenant_a") is True


def test_tenant_rate_check_rejects_over_limit():
    from chat.routers.webhook import _tenant_rate_check, _TENANT_WEBHOOK_LIMIT_PER_WINDOW
    # Exhaust the window
    for _ in range(_TENANT_WEBHOOK_LIMIT_PER_WINDOW):
        _tenant_rate_check("tenant_a")
    # Next call must be rejected
    assert _tenant_rate_check("tenant_a") is False


def test_tenant_rate_check_isolates_tenants():
    """One tenant exceeding the limit must NOT affect other tenants."""
    from chat.routers.webhook import _tenant_rate_check, _TENANT_WEBHOOK_LIMIT_PER_WINDOW
    # tenant_a exhausts its quota
    for _ in range(_TENANT_WEBHOOK_LIMIT_PER_WINDOW):
        _tenant_rate_check("tenant_a")
    assert _tenant_rate_check("tenant_a") is False
    # tenant_b untouched
    assert _tenant_rate_check("tenant_b") is True
    assert _tenant_rate_check("tenant_c") is True


def test_tenant_rate_check_empty_tenant_passes():
    """Defensive: missing tenant_id should not block — caller shouldn't get here anyway."""
    from chat.routers.webhook import _tenant_rate_check
    assert _tenant_rate_check("") is True


def test_tenant_rate_check_sliding_window_evicts_old(monkeypatch):
    """After window expires, old timestamps should be evicted — quota refreshes."""
    import chat.routers.webhook as w
    from chat.routers.webhook import _tenant_rate_check, _TENANT_WEBHOOK_LIMIT_PER_WINDOW

    fake_time = [1000.0]

    def fake_time_fn():
        return fake_time[0]

    monkeypatch.setattr(w.time, "time", fake_time_fn)

    # Exhaust at t=1000
    for _ in range(_TENANT_WEBHOOK_LIMIT_PER_WINDOW):
        _tenant_rate_check("tenant_a")
    assert _tenant_rate_check("tenant_a") is False

    # Advance past window
    fake_time[0] = 1000.0 + w._TENANT_WEBHOOK_WINDOW_SECONDS + 1
    # Old entries should evict → quota refreshed
    assert _tenant_rate_check("tenant_a") is True
