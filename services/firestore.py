"""Firestore client for tenant config and chat log persistence.

All Firestore SDK calls are synchronous — we wrap them with
asyncio.to_thread() to avoid blocking the async event loop.
"""

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from config import settings

TENANTS_COLLECTION = "tenants"
CHAT_LOGS_COLLECTION = "chat_logs"
ADMIN_USERS_COLLECTION = "admin_users"
CONVERSATIONS_COLLECTION = "conversations"
CONSENTS_COLLECTION = "consents"
REGISTRATIONS_COLLECTION = "pending_registrations"


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
# Privacy / PDPA (sync)
# ──────────────────────────────────────

def _export_user_data_sync(tenant_id: str, user_id: str) -> dict[str, Any]:
    db = _get_db()
    logs = (
        db.collection(CHAT_LOGS_COLLECTION)
        .where(filter=FieldFilter("tenant_id", "==", tenant_id))
        .where(filter=FieldFilter("user_id", "==", user_id))
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .get()
    )
    chat_logs = [{"id": doc.id, **doc.to_dict()} for doc in logs]

    conv_doc = db.collection(CONVERSATIONS_COLLECTION).document(user_id).get()
    conversation = conv_doc.to_dict() if conv_doc.exists else None

    consent_docs = (
        db.collection(CONSENTS_COLLECTION)
        .where(filter=FieldFilter("tenant_id", "==", tenant_id))
        .where(filter=FieldFilter("user_id", "==", user_id))
        .get()
    )
    consents = [doc.to_dict() for doc in consent_docs]

    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "chat_logs": chat_logs,
        "conversation_memory": conversation,
        "consents": consents,
    }


def _delete_user_data_sync(tenant_id: str, user_id: str) -> dict[str, Any]:
    """Delete all personal data for a user within a tenant (PDPA right to erasure)."""
    db = _get_db()
    logs = (
        db.collection(CHAT_LOGS_COLLECTION)
        .where(filter=FieldFilter("tenant_id", "==", tenant_id))
        .where(filter=FieldFilter("user_id", "==", user_id))
        .get()
    )
    deleted_logs = 0
    for doc in logs:
        doc.reference.delete()
        deleted_logs += 1

    deleted_conv = 0
    conv_ref = db.collection(CONVERSATIONS_COLLECTION).document(user_id)
    if conv_ref.get().exists:
        conv_ref.delete()
        deleted_conv = 1

    # Delete consent records (also contain user_id = personal data)
    consent_docs = (
        db.collection(CONSENTS_COLLECTION)
        .where(filter=FieldFilter("tenant_id", "==", tenant_id))
        .where(filter=FieldFilter("user_id", "==", user_id))
        .get()
    )
    deleted_consents = 0
    for doc in consent_docs:
        doc.reference.delete()
        deleted_consents += 1

    return {
        "deleted_chat_logs": deleted_logs,
        "deleted_conversations": deleted_conv,
        "deleted_consents": deleted_consents,
    }


def _anonymize_user_data_sync(tenant_id: str, user_id: str) -> dict[str, Any]:
    """Replace user_id with SHA256 hash in chat_logs, conversations, and consents."""
    db = _get_db()
    anon_id = f"anon_{hashlib.sha256(user_id.encode()).hexdigest()[:12]}"

    logs = (
        db.collection(CHAT_LOGS_COLLECTION)
        .where(filter=FieldFilter("tenant_id", "==", tenant_id))
        .where(filter=FieldFilter("user_id", "==", user_id))
        .get()
    )
    count = 0
    for doc in logs:
        doc.reference.update({"user_id": anon_id})
        count += 1

    conv_ref = db.collection(CONVERSATIONS_COLLECTION).document(user_id)
    conv_snap = conv_ref.get()
    if conv_snap.exists:
        data = conv_snap.to_dict()
        conv_ref.delete()
        db.collection(CONVERSATIONS_COLLECTION).document(anon_id).set(data)

    # Anonymize consent records
    consent_docs = (
        db.collection(CONSENTS_COLLECTION)
        .where(filter=FieldFilter("tenant_id", "==", tenant_id))
        .where(filter=FieldFilter("user_id", "==", user_id))
        .get()
    )
    for doc in consent_docs:
        doc.reference.update({"user_id": anon_id})

    return {"anonymized_records": count, "anonymous_id": anon_id}


def _cleanup_expired_data_sync(retention_days: int) -> dict[str, Any]:
    """Delete chat_logs older than retention_days across ALL tenants."""
    db = _get_db()
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    old_logs = (
        db.collection(CHAT_LOGS_COLLECTION)
        .where(filter=FieldFilter("created_at", "<", cutoff))
        .get()
    )
    deleted = 0
    for doc in old_logs:
        doc.reference.delete()
        deleted += 1

    return {"deleted_chat_logs": deleted}


def _record_consent_sync(
    tenant_id: str, user_id: str, consent_type: str, version: str,
) -> dict[str, Any]:
    db = _get_db()
    now = datetime.now(timezone.utc)
    doc_ref = db.collection(CONSENTS_COLLECTION).document()
    data = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "consent_type": consent_type,
        "version": version,
        "granted_at": now,
    }
    doc_ref.set(data)
    return {"id": doc_ref.id, **data}


def _get_user_consents_sync(tenant_id: str, user_id: str) -> list[dict[str, Any]]:
    docs = (
        _get_db()
        .collection(CONSENTS_COLLECTION)
        .where(filter=FieldFilter("tenant_id", "==", tenant_id))
        .where(filter=FieldFilter("user_id", "==", user_id))
        .get()
    )
    return [{"id": doc.id, **doc.to_dict()} for doc in docs]


def _revoke_consent_sync(tenant_id: str, user_id: str, consent_type: str) -> bool:
    docs = (
        _get_db()
        .collection(CONSENTS_COLLECTION)
        .where(filter=FieldFilter("tenant_id", "==", tenant_id))
        .where(filter=FieldFilter("user_id", "==", user_id))
        .where(filter=FieldFilter("consent_type", "==", consent_type))
        .get()
    )
    found = False
    for doc in docs:
        doc.reference.delete()
        found = True
    return found


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


# Privacy / PDPA

async def export_user_data(tenant_id: str, user_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_export_user_data_sync, tenant_id, user_id)

async def delete_user_data(tenant_id: str, user_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_delete_user_data_sync, tenant_id, user_id)

async def anonymize_user_data(tenant_id: str, user_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_anonymize_user_data_sync, tenant_id, user_id)

async def cleanup_expired_data(retention_days: int) -> dict[str, Any]:
    return await asyncio.to_thread(_cleanup_expired_data_sync, retention_days)

async def record_consent(tenant_id: str, user_id: str, consent_type: str, version: str) -> dict[str, Any]:
    return await asyncio.to_thread(_record_consent_sync, tenant_id, user_id, consent_type, version)

async def get_user_consents(tenant_id: str, user_id: str) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_get_user_consents_sync, tenant_id, user_id)

async def revoke_consent(tenant_id: str, user_id: str, consent_type: str) -> bool:
    return await asyncio.to_thread(_revoke_consent_sync, tenant_id, user_id, consent_type)


# Registration / Onboarding

def _create_registration_sync(data: dict[str, Any]) -> dict[str, Any]:
    db = _get_db()
    now = datetime.now(timezone.utc)
    doc_ref = db.collection(REGISTRATIONS_COLLECTION).document()
    doc_data = {**data, "status": "pending", "created_at": now}
    doc_ref.set(doc_data)
    return {"id": doc_ref.id, **doc_data}


def _list_registrations_sync(status: str = "pending") -> list[dict[str, Any]]:
    docs = (
        _get_db()
        .collection(REGISTRATIONS_COLLECTION)
        .where(filter=FieldFilter("status", "==", status))
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .get()
    )
    return [{"id": doc.id, **doc.to_dict()} for doc in docs]


def _get_registration_sync(reg_id: str) -> dict[str, Any] | None:
    doc = _get_db().collection(REGISTRATIONS_COLLECTION).document(reg_id).get()
    if not doc.exists:
        return None
    return {"id": doc.id, **doc.to_dict()}


def _update_registration_sync(reg_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    db = _get_db()
    doc_ref = db.collection(REGISTRATIONS_COLLECTION).document(reg_id)
    if not doc_ref.get().exists:
        return None
    data["updated_at"] = datetime.now(timezone.utc)
    doc_ref.update(data)
    doc = doc_ref.get()
    return {"id": doc.id, **doc.to_dict()}


def _get_onboarding_status_sync(tenant_id: str) -> list[int]:
    doc = _get_db().collection(TENANTS_COLLECTION).document(tenant_id).get()
    if not doc.exists:
        return []
    return doc.to_dict().get("onboarding_completed", [])


def _update_onboarding_status_sync(tenant_id: str, steps: list[int]) -> dict[str, Any] | None:
    db = _get_db()
    doc_ref = db.collection(TENANTS_COLLECTION).document(tenant_id)
    if not doc_ref.get().exists:
        return None
    doc_ref.update({"onboarding_completed": steps, "updated_at": datetime.now(timezone.utc)})
    return {"tenant_id": tenant_id, **doc_ref.get().to_dict()}


async def create_registration(data: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_create_registration_sync, data)

async def list_registrations(status: str = "pending") -> list[dict[str, Any]]:
    return await asyncio.to_thread(_list_registrations_sync, status)

async def get_registration(reg_id: str) -> dict[str, Any] | None:
    return await asyncio.to_thread(_get_registration_sync, reg_id)

async def update_registration(reg_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    return await asyncio.to_thread(_update_registration_sync, reg_id, data)

async def get_onboarding_status(tenant_id: str) -> list[int]:
    return await asyncio.to_thread(_get_onboarding_status_sync, tenant_id)

async def update_onboarding_status(tenant_id: str, steps: list[int]) -> dict[str, Any] | None:
    return await asyncio.to_thread(_update_onboarding_status_sync, tenant_id, steps)
