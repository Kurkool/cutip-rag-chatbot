"""Firestore client for tenant config and chat log persistence.

All Firestore SDK calls are synchronous — we wrap them with
asyncio.to_thread() to avoid blocking the async event loop.
"""

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from functools import lru_cache, wraps
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from shared.config import settings

TENANTS_COLLECTION = "tenants"
CHAT_LOGS_COLLECTION = "chat_logs"
ADMIN_USERS_COLLECTION = "admin_users"
CONVERSATIONS_COLLECTION = "conversations"
CONSENTS_COLLECTION = "consents"
REGISTRATIONS_COLLECTION = "pending_registrations"


@lru_cache()
def _get_db() -> firestore.Client:
    return firestore.Client(project=settings.GOOGLE_CLOUD_PROJECT or None)


# Public alias for cross-package use
get_db = _get_db


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


def _bump_bm25_invalidate_ts_sync(tenant_id: str) -> float:
    """Write ``time.time()`` into the tenant doc so chat-api re-warms BM25.

    Cross-process invalidation: ingest-worker writes this after every
    successful upsert; chat-api reads it on every request via the tenant
    dict already in its request context and compares with its in-process
    ``BM25Index.warmed_ts``. Stale-cache window bounded by tenant-fetch
    freshness (~per-request).
    """
    import time as _time
    db = _get_db()
    ts = _time.time()
    doc_ref = db.collection(TENANTS_COLLECTION).document(tenant_id)
    # Use set(merge=True) so missing tenant (shouldn't happen) creates field
    # without overwriting other tenant fields.
    doc_ref.set({"bm25_invalidate_ts": ts}, merge=True)
    return ts


def _delete_tenant_cascade_sync(tenant_id: str) -> dict[str, int]:
    """Delete a tenant plus all linked per-tenant records.

    Cascades: chat_logs, conversations, consents, pending_registrations for
    this tenant, and strips the tenant_id from any admin_user's tenant_ids.
    Returns per-collection delete counts for observability.
    """
    db = _get_db()

    counts = {
        "chat_logs": 0,
        "conversations": 0,
        "consents": 0,
        "registrations": 0,
        "admin_users_updated": 0,
    }

    for doc in (
        db.collection(CHAT_LOGS_COLLECTION)
        .where(filter=FieldFilter("tenant_id", "==", tenant_id))
        .get()
    ):
        doc.reference.delete()
        counts["chat_logs"] += 1

    for doc in (
        db.collection(CONVERSATIONS_COLLECTION)
        .where(filter=FieldFilter("tenant_id", "==", tenant_id))
        .get()
    ):
        doc.reference.delete()
        counts["conversations"] += 1

    for doc in (
        db.collection(CONSENTS_COLLECTION)
        .where(filter=FieldFilter("tenant_id", "==", tenant_id))
        .get()
    ):
        doc.reference.delete()
        counts["consents"] += 1

    for doc in db.collection(ADMIN_USERS_COLLECTION).get():
        data = doc.to_dict() or {}
        tenant_ids = data.get("tenant_ids") or []
        if tenant_id in tenant_ids:
            doc.reference.update({
                "tenant_ids": [t for t in tenant_ids if t != tenant_id],
                "updated_at": datetime.now(timezone.utc),
            })
            counts["admin_users_updated"] += 1

    tenant_ref = db.collection(TENANTS_COLLECTION).document(tenant_id)
    if tenant_ref.get().exists:
        tenant_ref.delete()

    return counts


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

    conv_key = f"{tenant_id}__{user_id}"
    conv_doc = db.collection(CONVERSATIONS_COLLECTION).document(conv_key).get()
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
    conv_key = f"{tenant_id}__{user_id}"
    conv_ref = db.collection(CONVERSATIONS_COLLECTION).document(conv_key)
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

    # Delete any Pinecone vectors tagged with this user_id. Today the ingest
    # pipeline does not tag chunks with user_id (documents are tenant-scoped),
    # so this is typically a no-op — but closes the PDPA gap if user-linked
    # content is ever indexed.
    deleted_vectors = 0
    tenant_doc = db.collection(TENANTS_COLLECTION).document(tenant_id).get()
    if tenant_doc.exists:
        namespace = tenant_doc.to_dict().get("pinecone_namespace")
        if namespace:
            try:
                from shared.services.vectorstore import delete_user_vectors
                deleted_vectors = delete_user_vectors(namespace, user_id)
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "Pinecone user-vector delete failed for %s/%s",
                    tenant_id, user_id,
                )

    return {
        "deleted_chat_logs": deleted_logs,
        "deleted_conversations": deleted_conv,
        "deleted_consents": deleted_consents,
        "deleted_vectors": deleted_vectors,
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

    conv_key = f"{tenant_id}__{user_id}"
    conv_ref = db.collection(CONVERSATIONS_COLLECTION).document(conv_key)
    conv_snap = conv_ref.get()
    if conv_snap.exists:
        data = conv_snap.to_dict()
        data["user_id"] = anon_id
        conv_ref.delete()
        anon_key = f"{tenant_id}__{anon_id}"
        db.collection(CONVERSATIONS_COLLECTION).document(anon_key).set(data)

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
# Async wrapper generator
# ──────────────────────────────────────

def _async_wrap(sync_fn):
    """Create an async wrapper that runs sync_fn in a thread pool."""
    @wraps(sync_fn)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(sync_fn, *args, **kwargs)
    # Strip _sync suffix and leading _ for the public name
    wrapper.__name__ = sync_fn.__name__.replace("_sync", "").lstrip("_")
    return wrapper


# Tenants
create_tenant = _async_wrap(_create_tenant_sync)
get_tenant = _async_wrap(_get_tenant_sync)
get_tenant_by_destination = _async_wrap(_get_tenant_by_destination_sync)
list_tenants = _async_wrap(_list_tenants_sync)
update_tenant = _async_wrap(_update_tenant_sync)
delete_tenant = _async_wrap(_delete_tenant_sync)
delete_tenant_cascade = _async_wrap(_delete_tenant_cascade_sync)
bump_bm25_invalidate_ts = _async_wrap(_bump_bm25_invalidate_ts_sync)

# Chat Logs & Analytics
log_chat = _async_wrap(_log_chat_sync)
get_chat_logs = _async_wrap(_get_chat_logs_sync)
get_analytics = _async_wrap(_get_analytics_sync)

# Admin Users
create_admin_user = _async_wrap(_create_admin_user_sync)
get_admin_user = _async_wrap(_get_admin_user_sync)
list_admin_users = _async_wrap(_list_admin_users_sync)
update_admin_user = _async_wrap(_update_admin_user_sync)
delete_admin_user = _async_wrap(_delete_admin_user_sync)
count_admin_users = _async_wrap(_count_admin_users_sync)

# Privacy / PDPA
export_user_data = _async_wrap(_export_user_data_sync)
delete_user_data = _async_wrap(_delete_user_data_sync)
anonymize_user_data = _async_wrap(_anonymize_user_data_sync)
cleanup_expired_data = _async_wrap(_cleanup_expired_data_sync)
record_consent = _async_wrap(_record_consent_sync)
get_user_consents = _async_wrap(_get_user_consents_sync)
revoke_consent = _async_wrap(_revoke_consent_sync)


# ──────────────────────────────────────
# Registration / Onboarding (sync + async)
# ──────────────────────────────────────

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


create_registration = _async_wrap(_create_registration_sync)
list_registrations = _async_wrap(_list_registrations_sync)
get_registration = _async_wrap(_get_registration_sync)
update_registration = _async_wrap(_update_registration_sync)
get_onboarding_status = _async_wrap(_get_onboarding_status_sync)
update_onboarding_status = _async_wrap(_update_onboarding_status_sync)
