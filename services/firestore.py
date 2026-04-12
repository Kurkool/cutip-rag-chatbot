"""Firestore client for tenant config and chat log persistence.

All Firestore SDK calls are synchronous — we wrap them with
asyncio.to_thread() to avoid blocking the async event loop.
"""

import asyncio
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from config import settings

TENANTS_COLLECTION = "tenants"
CHAT_LOGS_COLLECTION = "chat_logs"
ADMIN_USERS_COLLECTION = "admin_users"


@lru_cache()
def _get_db() -> firestore.Client:
    return firestore.Client(project=settings.GOOGLE_CLOUD_PROJECT or None)


# ──────────────────────────────────────
# Sync helpers (run in thread pool)
# ──────────────────────────────────────

def _create_tenant_sync(data: dict[str, Any]) -> dict[str, Any]:
    db = _get_db()
    tenant_id = data.pop("tenant_id")
    now = datetime.now(timezone.utc)
    doc_data = {**data, "created_at": now, "updated_at": now}
    db.collection(TENANTS_COLLECTION).document(tenant_id).set(doc_data)
    return {"tenant_id": tenant_id, **doc_data}


def _get_tenant_sync(tenant_id: str) -> dict[str, Any] | None:
    doc = _get_db().collection(TENANTS_COLLECTION).document(tenant_id).get()
    if not doc.exists:
        return None
    return {"tenant_id": doc.id, **doc.to_dict()}


def _get_tenant_by_destination_sync(line_destination: str) -> dict[str, Any] | None:
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


def _list_tenants_sync() -> list[dict[str, Any]]:
    docs = _get_db().collection(TENANTS_COLLECTION).get()
    return [{"tenant_id": doc.id, **doc.to_dict()} for doc in docs]


def _update_tenant_sync(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    db = _get_db()
    doc_ref = db.collection(TENANTS_COLLECTION).document(tenant_id)
    if not doc_ref.get().exists:
        return None
    data["updated_at"] = datetime.now(timezone.utc)
    doc_ref.update(data)
    return _get_tenant_sync(tenant_id)


def _delete_tenant_sync(tenant_id: str) -> bool:
    db = _get_db()
    doc_ref = db.collection(TENANTS_COLLECTION).document(tenant_id)
    if not doc_ref.get().exists:
        return False
    doc_ref.delete()
    return True


def _log_chat_sync(
    tenant_id: str, user_id: str, query: str, answer: str,
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


def _get_chat_logs_sync(
    tenant_id: str, limit: int = 50, offset: int = 0,
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


def _get_analytics_sync(tenant_id: str) -> dict[str, Any]:
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


# ──────────────────────────────────────
# Admin Users (sync)
# ──────────────────────────────────────

def _create_admin_user_sync(uid: str, data: dict[str, Any]) -> dict[str, Any]:
    db = _get_db()
    now = datetime.now(timezone.utc)
    doc_data = {**data, "created_at": now, "updated_at": now}
    db.collection(ADMIN_USERS_COLLECTION).document(uid).set(doc_data)
    return {"uid": uid, **doc_data}


def _get_admin_user_sync(uid: str) -> dict[str, Any] | None:
    doc = _get_db().collection(ADMIN_USERS_COLLECTION).document(uid).get()
    if not doc.exists:
        return None
    return {"uid": doc.id, **doc.to_dict()}


def _list_admin_users_sync() -> list[dict[str, Any]]:
    docs = _get_db().collection(ADMIN_USERS_COLLECTION).get()
    return [{"uid": doc.id, **doc.to_dict()} for doc in docs]


def _update_admin_user_sync(uid: str, data: dict[str, Any]) -> dict[str, Any] | None:
    db = _get_db()
    doc_ref = db.collection(ADMIN_USERS_COLLECTION).document(uid)
    if not doc_ref.get().exists:
        return None
    data["updated_at"] = datetime.now(timezone.utc)
    doc_ref.update(data)
    return _get_admin_user_sync(uid)


def _delete_admin_user_sync(uid: str) -> bool:
    db = _get_db()
    doc_ref = db.collection(ADMIN_USERS_COLLECTION).document(uid)
    if not doc_ref.get().exists:
        return False
    doc_ref.delete()
    return True


def _count_admin_users_sync() -> int:
    return len(_get_db().collection(ADMIN_USERS_COLLECTION).get())


# ──────────────────────────────────────
# Async wrappers (non-blocking)
# ──────────────────────────────────────

async def create_tenant(data: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_create_tenant_sync, data)

async def get_tenant(tenant_id: str) -> dict[str, Any] | None:
    return await asyncio.to_thread(_get_tenant_sync, tenant_id)

async def get_tenant_by_destination(line_destination: str) -> dict[str, Any] | None:
    return await asyncio.to_thread(_get_tenant_by_destination_sync, line_destination)

async def list_tenants() -> list[dict[str, Any]]:
    return await asyncio.to_thread(_list_tenants_sync)

async def update_tenant(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    return await asyncio.to_thread(_update_tenant_sync, tenant_id, data)

async def delete_tenant(tenant_id: str) -> bool:
    return await asyncio.to_thread(_delete_tenant_sync, tenant_id)

async def log_chat(
    tenant_id: str, user_id: str, query: str, answer: str,
    sources: list[dict[str, Any]],
) -> str:
    return await asyncio.to_thread(_log_chat_sync, tenant_id, user_id, query, answer, sources)

async def get_chat_logs(
    tenant_id: str, limit: int = 50, offset: int = 0,
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_get_chat_logs_sync, tenant_id, limit, offset)

async def get_analytics(tenant_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_get_analytics_sync, tenant_id)


# Admin Users

async def create_admin_user(uid: str, data: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_create_admin_user_sync, uid, data)

async def get_admin_user(uid: str) -> dict[str, Any] | None:
    return await asyncio.to_thread(_get_admin_user_sync, uid)

async def list_admin_users() -> list[dict[str, Any]]:
    return await asyncio.to_thread(_list_admin_users_sync)

async def update_admin_user(uid: str, data: dict[str, Any]) -> dict[str, Any] | None:
    return await asyncio.to_thread(_update_admin_user_sync, uid, data)

async def delete_admin_user(uid: str) -> bool:
    return await asyncio.to_thread(_delete_admin_user_sync, uid)

async def count_admin_users() -> int:
    return await asyncio.to_thread(_count_admin_users_sync)
