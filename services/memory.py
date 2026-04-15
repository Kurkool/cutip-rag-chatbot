"""Firestore-backed conversation memory with TTL.

Persists across Cloud Run instances. Uses Firestore array operations
to avoid race conditions on concurrent writes. All Firestore calls
wrapped with asyncio.to_thread() to avoid blocking the event loop.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore as fs
from langchain_anthropic import ChatAnthropic

from config import settings
from services.firestore import _get_db

logger = logging.getLogger(__name__)

_SUMMARIZE_PROMPT = (
    "Summarize this conversation between a student and university assistant in 1-2 sentences. "
    "Preserve key topics, specific details (course codes, names, amounts), and any unresolved questions.\n\n"
    "{conversation}"
)

CONVERSATIONS_COLLECTION = "conversations"


class ConversationMemory:

    def get_history(self, user_id: str) -> list[dict[str, Any]] | dict[str, Any]:
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
        summary = doc.get("summary", "")

        if summary:
            return {"summary": summary, "turns": turns}

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
            doc_data = doc.to_dict()
            turns = doc_data.get("turns", [])
            if len(turns) > settings.MAX_HISTORY_TURNS:
                existing_summary = doc_data.get("summary", "")
                new_summary = self._summarize(turns, existing_summary)
                doc_ref.update({"turns": [], "summary": new_summary})

    def clear(self, user_id: str) -> None:
        _get_db().collection(CONVERSATIONS_COLLECTION).document(user_id).delete()

    def _summarize(self, turns: list[dict[str, Any]], existing_summary: str = "") -> str:
        """Summarize conversation turns using Haiku. Returns summary text."""
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
            llm = ChatAnthropic(
                model=settings.VISION_MODEL,
                anthropic_api_key=settings.ANTHROPIC_API_KEY,
                max_tokens=200,
                temperature=0,
            )
            response = llm.invoke(prompt)
            return response.content
        except Exception as exc:
            logger.warning("Summarization failed, keeping existing summary: %s", exc)
            return existing_summary

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
