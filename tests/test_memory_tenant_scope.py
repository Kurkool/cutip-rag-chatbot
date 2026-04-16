"""Task 2: Conversation memory must be tenant-scoped.

Previously doc key was `user_id` alone, so two tenants sharing a LINE userId
(or both hitting /api/chat without a user_id → DEFAULT_USER_ID="anonymous")
would read/write the same conversation document.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


class _FakeDoc:
    def __init__(self, store, key):
        self._store = store
        self._key = key

    @property
    def exists(self):
        return self._key in self._store

    def to_dict(self):
        return dict(self._store.get(self._key, {}))


class _FakeDocRef:
    def __init__(self, store, key):
        self._store = store
        self._key = key

    def set(self, data, merge=False):
        if merge and self._key in self._store:
            existing = self._store[self._key]
            for k, v in data.items():
                if hasattr(v, "values") and hasattr(v, "__class__") and v.__class__.__name__ == "ArrayUnion":
                    existing.setdefault(k, []).extend(v.values)
                else:
                    existing[k] = v
        else:
            resolved = {}
            for k, v in data.items():
                if hasattr(v, "values") and hasattr(v, "__class__") and v.__class__.__name__ == "ArrayUnion":
                    resolved[k] = list(v.values)
                else:
                    resolved[k] = v
            self._store[self._key] = resolved

    def get(self):
        return _FakeDoc(self._store, self._key)

    def update(self, data):
        self._store.setdefault(self._key, {}).update(data)

    def delete(self):
        self._store.pop(self._key, None)


class _FakeCollection:
    def __init__(self, store):
        self._store = store

    def document(self, key):
        return _FakeDocRef(self._store, key)


class _FakeDB:
    def __init__(self):
        self.store: dict[str, dict] = {}

    def collection(self, name):
        return _FakeCollection(self.store)


@pytest.fixture
def fake_db():
    return _FakeDB()


@pytest.fixture
def memory(fake_db):
    with patch("chat.services.memory.get_db", return_value=fake_db):
        from chat.services.memory import ConversationMemory
        yield ConversationMemory()


def test_add_turn_scopes_by_tenant(memory, fake_db):
    memory.add_turn("tenant_a", "user1", "q1", "a1")
    assert "tenant_a__user1" in fake_db.store
    assert "user1" not in fake_db.store


def test_get_history_isolated_between_tenants(memory, fake_db):
    memory.add_turn("tenant_a", "user1", "Thai tuition?", "21000")
    memory.add_turn("tenant_b", "user1", "Science fee?", "15000")

    hist_a = memory.get_history("tenant_a", "user1")
    hist_b = memory.get_history("tenant_b", "user1")

    if isinstance(hist_a, dict):
        turns_a = hist_a.get("turns", [])
        turns_b = hist_b.get("turns", [])
    else:
        turns_a, turns_b = hist_a, hist_b

    assert {t["query"] for t in turns_a} == {"Thai tuition?"}
    assert {t["query"] for t in turns_b} == {"Science fee?"}


def test_clear_only_affects_one_tenant(memory, fake_db):
    memory.add_turn("tenant_a", "user1", "q", "a")
    memory.add_turn("tenant_b", "user1", "q", "a")
    memory.clear("tenant_a", "user1")
    assert "tenant_a__user1" not in fake_db.store
    assert "tenant_b__user1" in fake_db.store


@pytest.mark.asyncio
async def test_async_wrapper_passes_tenant(fake_db):
    with patch("chat.services.memory.get_db", return_value=fake_db):
        from chat.services.memory import AsyncConversationMemory
        mem = AsyncConversationMemory()
        await mem.add_turn("tenant_a", "user1", "q", "a")
        assert "tenant_a__user1" in fake_db.store
        hist = await mem.get_history("tenant_a", "user1")
        if isinstance(hist, dict):
            assert hist["turns"][0]["query"] == "q"
        else:
            assert hist[0]["query"] == "q"
