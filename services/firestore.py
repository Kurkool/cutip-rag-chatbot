"""Firestore client for tenant config and chat log persistence."""

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from config import settings

TENANTS_COLLECTION = "tenants"
CHAT_LOGS_COLLECTION = "chat_logs"


@lru_cache()
def _get_db() -> firestore.Client:
    return firestore.Client(project=settings.GOOGLE_CLOUD_PROJECT or None)


# ──────────────────────────────────────
# Tenants
# ──────────────────────────────────────

async def create_tenant(data: dict[str, Any]) -> dict[str, Any]:
    db = _get_db()
    tenant_id = data.pop("tenant_id")
    now = datetime.now(timezone.utc)
    doc_data = {**data, "created_at": now, "updated_at": now}
    db.collection(TENANTS_COLLECTION).document(tenant_id).set(doc_data)
    return {"tenant_id": tenant_id, **doc_data}


async def get_tenant(tenant_id: str) -> dict[str, Any] | None:
    doc = _get_db().collection(TENANTS_COLLECTION).document(tenant_id).get()
    if not doc.exists:
        return None
    return {"tenant_id": doc.id, **doc.to_dict()}


async def get_tenant_by_destination(line_destination: str) -> dict[str, Any] | None:
    docs = (
        _get_db()
        .collection(TENANTS_COLLECTION)
        .where(filter=FieldFilter("line_destination", "==", line_destination))
        .where(filter=FieldFilter("is_active", "==", True))
        .limit(1)
        .get()
    )
    for doc in docs:
        return {"tenant_id": doc.id, **doc.to_dict()}
    return None


async def list_tenants() -> list[dict[str, Any]]:
    docs = _get_db().collection(TENANTS_COLLECTION).get()
    return [{"tenant_id": doc.id, **doc.to_dict()} for doc in docs]


async def update_tenant(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    db = _get_db()
    doc_ref = db.collection(TENANTS_COLLECTION).document(tenant_id)
    if not doc_ref.get().exists:
        return None
    data["updated_at"] = datetime.now(timezone.utc)
    doc_ref.update(data)
    return await get_tenant(tenant_id)


async def delete_tenant(tenant_id: str) -> bool:
    db = _get_db()
    doc_ref = db.collection(TENANTS_COLLECTION).document(tenant_id)
    if not doc_ref.get().exists:
        return False
    doc_ref.delete()
    return True


# ──────────────────────────────────────
# Chat Logs
# ──────────────────────────────────────

async def log_chat(
    tenant_id: str,
    user_id: str,
    query: str,
    answer: str,
    sources: list[dict[str, Any]],
) -> str:
    doc_ref = _get_db().collection(CHAT_LOGS_COLLECTION).document()
    doc_ref.set({
        "tenant_id": tenant_id,
        "user_id": user_id,
        "query": query,
        "answer": answer,
        "sources": sources,
        "created_at": datetime.now(timezone.utc),
    })
    return doc_ref.id


async def get_chat_logs(
    tenant_id: str, limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    query = (
        _get_db()
        .collection(CHAT_LOGS_COLLECTION)
        .where(filter=FieldFilter("tenant_id", "==", tenant_id))
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .offset(offset)
    )
    return [{"id": doc.id, **doc.to_dict()} for doc in query.get()]


async def get_analytics(tenant_id: str) -> dict[str, Any]:
    docs = (
        _get_db()
        .collection(CHAT_LOGS_COLLECTION)
        .where(filter=FieldFilter("tenant_id", "==", tenant_id))
        .get()
    )
    user_ids: set[str] = set()
    total = 0
    for doc in docs:
        total += 1
        user_ids.add(doc.to_dict().get("user_id", ""))
    return {
        "tenant_id": tenant_id,
        "total_chats": total,
        "unique_users": len(user_ids),
    }
