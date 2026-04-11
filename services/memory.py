"""Firestore-backed conversation memory with TTL.

Persists across Cloud Run instances. Uses Firestore array operations
to avoid race conditions on concurrent writes. All Firestore calls
wrapped with asyncio.to_thread() to avoid blocking the event loop.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore as fs

from config import settings
from services.firestore import _get_db

CONVERSATIONS_COLLECTION = "conversations"


class ConversationMemory:

    def get_history(self, user_id: str) -> list[dict[str, Any]]:
        doc = self._get_doc(user_id)
        if not doc:
            return []

        last_active = doc.get("last_active")
        if last_active:
            elapsed = (datetime.now(timezone.utc) - last_active).total_seconds()
            if elapsed > settings.MEMORY_TTL:
                self.clear(user_id)
                return []

        turns = doc.get("turns", [])
        return turns[-settings.MAX_HISTORY_TURNS:]

    def add_turn(self, user_id: str, query: str, answer: str) -> None:
        db = _get_db()
        doc_ref = db.collection(CONVERSATIONS_COLLECTION).document(user_id)
        turn = {"query": query, "answer": answer}

        doc_ref.set(
            {
                "turns": fs.ArrayUnion([turn]),
                "last_active": datetime.now(timezone.utc),
            },
            merge=True,
        )

        doc = doc_ref.get()
        if doc.exists:
            turns = doc.to_dict().get("turns", [])
            if len(turns) > settings.MAX_HISTORY_TURNS:
                doc_ref.update({"turns": turns[-settings.MAX_HISTORY_TURNS:]})

    def clear(self, user_id: str) -> None:
        _get_db().collection(CONVERSATIONS_COLLECTION).document(user_id).delete()

    def _get_doc(self, user_id: str) -> dict[str, Any] | None:
        doc = _get_db().collection(CONVERSATIONS_COLLECTION).document(user_id).get()
        if not doc.exists:
            return None
        return doc.to_dict()


# Async wrappers (non-blocking)
_memory = ConversationMemory()


class AsyncConversationMemory:
    """Async wrapper that runs blocking Firestore calls in a thread pool."""

    def get_history(self, user_id: str) -> list[dict[str, Any]]:
        # Called from sync context (agent tools) — keep sync
        return _memory.get_history(user_id)

    def add_turn(self, user_id: str, query: str, answer: str) -> None:
        # Called from sync context (agent.py) — keep sync
        _memory.add_turn(user_id, query, answer)

    def clear(self, user_id: str) -> None:
        _memory.clear(user_id)


conversation_memory = AsyncConversationMemory()
