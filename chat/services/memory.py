"""Firestore-backed conversation memory with TTL and summarization.

Persists across Cloud Run instances. Uses Firestore array operations
to avoid race conditions on concurrent writes. Blocking Firestore + LLM
calls are wrapped with asyncio.to_thread() to avoid blocking the event loop.

Documents are keyed by (tenant_id, user_id) via composite doc ID
f"{tenant_id}__{user_id}" to guarantee multi-tenant isolation. A LINE user
or "anonymous" caller on tenant A cannot read/write tenant B's conversation.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore as fs

from shared.config import settings
from shared.services.llm import get_haiku_precise
from shared.services.firestore import get_db, CONVERSATIONS_COLLECTION

logger = logging.getLogger(__name__)

_SUMMARIZE_PROMPT = (
    "Summarize this conversation between a student and university assistant in 1-2 sentences. "
    "Preserve key topics, specific details (course codes, names, amounts), and any unresolved questions.\n\n"
    "{conversation}"
)


def _doc_key(tenant_id: str, user_id: str) -> str:
    """Composite Firestore doc ID for (tenant, user) conversation isolation."""
    return f"{tenant_id}__{user_id}"


class ConversationMemory:
    """Sync implementation — all methods block. Use AsyncConversationMemory for FastAPI."""

    def get_history(self, tenant_id: str, user_id: str) -> list[dict[str, Any]] | dict[str, Any]:
        doc = self._get_doc(tenant_id, user_id)
        if not doc:
            return []

        last_active = doc.get("last_active")
        if last_active:
            elapsed = (datetime.now(timezone.utc) - last_active).total_seconds()
            if elapsed > settings.MEMORY_TTL:
                self.clear(tenant_id, user_id)
                return []

        turns = doc.get("turns", [])
        summary = doc.get("summary", "")

        if summary:
            return {"summary": summary, "turns": turns}

        return turns[-settings.MAX_HISTORY_TURNS:]

    def add_turn(self, tenant_id: str, user_id: str, query: str, answer: str) -> None:
        db = get_db()
        key = _doc_key(tenant_id, user_id)
        doc_ref = db.collection(CONVERSATIONS_COLLECTION).document(key)
        turn = {"query": query, "answer": answer}

        doc_ref.set(
            {
                "turns": fs.ArrayUnion([turn]),
                "last_active": datetime.now(timezone.utc),
                "tenant_id": tenant_id,
                "user_id": user_id,
            },
            merge=True,
        )

        doc = doc_ref.get()
        if doc.exists:
            doc_data = doc.to_dict()
            turns = doc_data.get("turns", [])
            if len(turns) > settings.MAX_HISTORY_TURNS:
                existing_summary = doc_data.get("summary", "")
                new_summary = self._summarize(turns, existing_summary)
                doc_ref.update({"turns": [], "summary": new_summary})

    def clear(self, tenant_id: str, user_id: str) -> None:
        get_db().collection(CONVERSATIONS_COLLECTION).document(
            _doc_key(tenant_id, user_id)
        ).delete()

    def _summarize(self, turns: list[dict[str, Any]], existing_summary: str = "") -> str:
        """Summarize conversation turns using Haiku. Blocking — call via to_thread."""
        lines = []
        if existing_summary:
            lines.append(f"Previous context: {existing_summary}")
            lines.append("")
        for turn in turns:
            lines.append(f"Student: {turn['query']}")
            lines.append(f"Assistant: {turn['answer']}")
        conversation_text = "\n".join(lines)

        prompt = _SUMMARIZE_PROMPT.format(conversation=conversation_text)
        try:
            llm = get_haiku_precise()
            response = llm.invoke(prompt)
            return response.content
        except Exception as exc:
            logger.warning("Summarization failed, keeping existing summary: %s", exc)
            return existing_summary

    def _get_doc(self, tenant_id: str, user_id: str) -> dict[str, Any] | None:
        doc = (
            get_db()
            .collection(CONVERSATIONS_COLLECTION)
            .document(_doc_key(tenant_id, user_id))
            .get()
        )
        if not doc.exists:
            return None
        return doc.to_dict()


_memory = ConversationMemory()


class AsyncConversationMemory:
    """Non-blocking wrapper — runs all blocking calls in thread pool."""

    async def get_history(
        self, tenant_id: str, user_id: str,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        return await asyncio.to_thread(_memory.get_history, tenant_id, user_id)

    async def add_turn(
        self, tenant_id: str, user_id: str, query: str, answer: str,
    ) -> None:
        await asyncio.to_thread(_memory.add_turn, tenant_id, user_id, query, answer)

    async def clear(self, tenant_id: str, user_id: str) -> None:
        await asyncio.to_thread(_memory.clear, tenant_id, user_id)


conversation_memory = AsyncConversationMemory()
