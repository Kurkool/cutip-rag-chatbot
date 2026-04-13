"""Per-tenant API usage tracking.

Logs each LLM/embedding/reranker call with estimated costs.
Stored in Firestore 'usage_logs' collection, aggregated per tenant per month.
"""

import asyncio
import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from google.cloud import firestore

from config import settings

logger = logging.getLogger(__name__)

USAGE_COLLECTION = "usage_logs"

# Estimated costs per call (USD) — update as pricing changes
COST_ESTIMATES = {
    "llm_call": 0.06,         # Claude Opus ~60 tokens avg
    "embedding_call": 0.001,  # Cohere embed per batch
    "reranker_call": 0.002,   # Cohere rerank per query
    "vision_call": 0.01,      # Claude Haiku Vision per page
}


@lru_cache()
def _get_db() -> firestore.Client:
    return firestore.Client(project=settings.GOOGLE_CLOUD_PROJECT)


# ──────────────────────────────────────
# Logging (sync, called via to_thread)
# ──────────────────────────────────────

def _get_month_key() -> str:
    """Current month as 'YYYY-MM' for aggregation."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _increment_usage_sync(tenant_id: str, call_type: str, count: int = 1) -> None:
    """Increment usage counter for a tenant in the current month."""
    db = _get_db()
    month = _get_month_key()
    doc_id = f"{tenant_id}_{month}"
    doc_ref = db.collection(USAGE_COLLECTION).document(doc_id)

    doc_ref.set(
        {
            "tenant_id": tenant_id,
            "month": month,
            f"{call_type}_count": firestore.Increment(count),
            f"{call_type}_cost": firestore.Increment(
                count * COST_ESTIMATES.get(call_type, 0)
            ),
            "total_cost": firestore.Increment(
                count * COST_ESTIMATES.get(call_type, 0)
            ),
            "updated_at": datetime.now(timezone.utc),
        },
        merge=True,
    )


def _get_usage_sync(tenant_id: str, month: str | None = None) -> dict[str, Any]:
    """Get usage for a tenant in a given month (default: current)."""
    db = _get_db()
    month = month or _get_month_key()
    doc_id = f"{tenant_id}_{month}"
    doc = db.collection(USAGE_COLLECTION).document(doc_id).get()
    if not doc.exists:
        return {
            "tenant_id": tenant_id,
            "month": month,
            "llm_call_count": 0,
            "embedding_call_count": 0,
            "reranker_call_count": 0,
            "vision_call_count": 0,
            "total_cost": 0.0,
        }
    return {"tenant_id": tenant_id, **doc.to_dict()}


def _get_all_usage_sync(month: str | None = None) -> list[dict[str, Any]]:
    """Get usage for all tenants in a given month."""
    db = _get_db()
    month = month or _get_month_key()
    docs = (
        db.collection(USAGE_COLLECTION)
        .where("month", "==", month)
        .get()
    )
    results = []
    for doc in docs:
        data = doc.to_dict()
        results.append(data)
    return results


# ──────────────────────────────────────
# Async wrappers
# ──────────────────────────────────────

async def track(tenant_id: str, call_type: str, count: int = 1) -> None:
    """Track an API call for a tenant. Fire-and-forget safe."""
    try:
        await asyncio.to_thread(_increment_usage_sync, tenant_id, call_type, count)
    except Exception:
        logger.warning("Failed to track usage for %s", tenant_id, exc_info=True)


async def get_usage(tenant_id: str, month: str | None = None) -> dict[str, Any]:
    """Get usage summary for a tenant."""
    return await asyncio.to_thread(_get_usage_sync, tenant_id, month)


async def get_all_usage(month: str | None = None) -> list[dict[str, Any]]:
    """Get usage summary for all tenants."""
    return await asyncio.to_thread(_get_all_usage_sync, month)
