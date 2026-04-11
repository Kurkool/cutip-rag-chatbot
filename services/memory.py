"""Firestore-backed conversation memory with TTL.

Persists across Cloud Run instances. Uses Firestore array operations
to avoid race conditions on concurrent writes.
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

    def add_turn(self, user_id: str, query: str, answer: str):
        db = _get_db()
        doc_ref = db.collection(CONVERSATIONS_COLLECTION).document(user_id)
        turn = {"query": query, "answer": answer}

        # Atomic operation: append to array + update timestamp
        doc_ref.set(
            {
                "turns": fs.ArrayUnion([turn]),
                "last_active": datetime.now(timezone.utc),
            },
            merge=True,
        )

        # Trim to max turns (separate operation, acceptable if slightly stale)
        doc = doc_ref.get()
        if doc.exists:
            turns = doc.to_dict().get("turns", [])
            if len(turns) > settings.MAX_HISTORY_TURNS:
                doc_ref.update({"turns": turns[-settings.MAX_HISTORY_TURNS:]})

    def clear(self, user_id: str):
        db = _get_db()
        db.collection(CONVERSATIONS_COLLECTION).document(user_id).delete()

    def _get_doc(self, user_id: str) -> dict[str, Any] | None:
        doc = _get_db().collection(CONVERSATIONS_COLLECTION).document(user_id).get()
        if not doc.exists:
            return None
        return doc.to_dict()


conversation_memory = ConversationMemory()
