"""Firestore-backed conversation memory with TTL.

Persists across Cloud Run instances. Each user's history is stored
as a Firestore document with automatic expiry based on last activity.
"""

from datetime import datetime, timezone
from typing import Any

from config import settings
from services.firestore import _get_db

CONVERSATIONS_COLLECTION = "conversations"


class ConversationMemory:

    def get_history(self, user_id: str) -> list[dict[str, Any]]:
        doc = self._get_doc(user_id)
        if not doc:
            return []

        # Check TTL
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
        doc = doc_ref.get()

        turns = []
        if doc.exists:
            turns = doc.to_dict().get("turns", [])

        turns.append({"query": query, "answer": answer})
        # Keep only last N turns
        turns = turns[-settings.MAX_HISTORY_TURNS:]

        doc_ref.set({
            "turns": turns,
            "last_active": datetime.now(timezone.utc),
        })

    def clear(self, user_id: str):
        db = _get_db()
        db.collection(CONVERSATIONS_COLLECTION).document(user_id).delete()

    def _get_doc(self, user_id: str) -> dict[str, Any] | None:
        db = _get_db()
        doc = db.collection(CONVERSATIONS_COLLECTION).document(user_id).get()
        if not doc.exists:
            return None
        return doc.to_dict()


# Singleton
conversation_memory = ConversationMemory()
