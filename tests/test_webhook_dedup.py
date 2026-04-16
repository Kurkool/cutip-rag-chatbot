"""LINE webhook event deduplication — replay protection.

Tests the in-memory dedup cache that drops duplicate webhookEventId retries.
"""
import time

import pytest


@pytest.fixture(autouse=True)
def _reset_dedup():
    import chat.routers.webhook as w
    with w._dedup_lock:
        w._dedup_cache.clear()
    yield
    with w._dedup_lock:
        w._dedup_cache.clear()


def test_first_event_is_not_duplicate():
    from chat.routers.webhook import _is_duplicate_event
    assert _is_duplicate_event("evt-1") is False


def test_replayed_event_is_duplicate():
    from chat.routers.webhook import _is_duplicate_event
    _is_duplicate_event("evt-1")
    assert _is_duplicate_event("evt-1") is True


def test_distinct_events_not_confused():
    from chat.routers.webhook import _is_duplicate_event
    _is_duplicate_event("evt-1")
    assert _is_duplicate_event("evt-2") is False


def test_empty_event_id_never_deduped():
    from chat.routers.webhook import _is_duplicate_event
    assert _is_duplicate_event("") is False
    assert _is_duplicate_event("") is False


def test_expired_entry_evicted(monkeypatch):
    import chat.routers.webhook as w
    with w._dedup_lock:
        w._dedup_cache.clear()
    # Stale entry older than TTL
    w._dedup_cache["old"] = time.time() - (w._DEDUP_TTL_SECONDS + 1)
    # New call evicts expired prefix entries before checking
    assert w._is_duplicate_event("fresh") is False
    assert "old" not in w._dedup_cache
