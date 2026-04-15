"""Shared test fixtures: mock Firebase, mock Firestore, test client."""

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

# ──────────────────────────────────────
# Mock data
# ──────────────────────────────────────

SUPER_ADMIN = {
    "uid": "super-uid-001",
    "email": "admin@test.com",
    "display_name": "Test Admin",
    "role": "super_admin",
    "tenant_ids": [],
    "is_active": True,
    "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
}

FACULTY_ADMIN = {
    "uid": "faculty-uid-001",
    "email": "faculty@test.com",
    "display_name": "Faculty Admin",
    "role": "faculty_admin",
    "tenant_ids": ["tenant_a"],
    "is_active": True,
    "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
}

TENANT_A = {
    "tenant_id": "tenant_a",
    "faculty_name": "Faculty of Engineering",
    "line_destination": "U1234567890",
    "line_channel_access_token": "token_a",
    "line_channel_secret": "secret_a",
    "pinecone_namespace": "ns-tenant-a",
    "persona": "",
    "is_active": True,
    "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
}

TENANT_B = {
    "tenant_id": "tenant_b",
    "faculty_name": "Faculty of Science",
    "line_destination": "U0987654321",
    "line_channel_access_token": "token_b",
    "line_channel_secret": "secret_b",
    "pinecone_namespace": "ns-tenant-b",
    "persona": "",
    "is_active": True,
    "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
}


# ──────────────────────────────────────
# In-memory Firestore mock
# ──────────────────────────────────────

class FakeFirestore:
    """In-memory Firestore replacement for tests."""

    def __init__(self):
        self.tenants: dict[str, dict] = {}
        self.admin_users: dict[str, dict] = {}
        self.chat_logs: list[dict] = []
        self.conversations: dict[str, dict] = {}
        self.consents: list[dict] = []
        self.pending_registrations: dict[str, dict] = {}

    def reset(self):
        self.tenants.clear()
        self.admin_users.clear()
        self.chat_logs.clear()
        self.conversations.clear()
        self.consents.clear()
        self.pending_registrations.clear()

    def seed(self):
        """Seed with test data."""
        self.tenants = {
            "tenant_a": {**TENANT_A},
            "tenant_b": {**TENANT_B},
        }
        self.admin_users = {
            "super-uid-001": {**SUPER_ADMIN},
            "faculty-uid-001": {**FACULTY_ADMIN},
        }
        # Seed chat logs for privacy tests
        self.chat_logs = [
            {
                "tenant_id": "tenant_a", "user_id": "LINE_USER_001",
                "query": "What courses?", "answer": "CS101",
                "sources": [], "created_at": datetime(2026, 1, 10, tzinfo=timezone.utc),
            },
            {
                "tenant_id": "tenant_a", "user_id": "LINE_USER_001",
                "query": "Tuition fee?", "answer": "50000 THB",
                "sources": [], "created_at": datetime(2026, 1, 15, tzinfo=timezone.utc),
            },
            {
                "tenant_id": "tenant_a", "user_id": "LINE_USER_002",
                "query": "Schedule?", "answer": "Mon-Fri",
                "sources": [], "created_at": datetime(2026, 1, 12, tzinfo=timezone.utc),
            },
            {   # Old log for retention test (200 days ago)
                "tenant_id": "tenant_a", "user_id": "LINE_USER_003",
                "query": "Old question", "answer": "Old answer",
                "sources": [], "created_at": datetime(2025, 9, 1, tzinfo=timezone.utc),
            },
        ]
        # Seed conversations
        self.conversations = {
            "LINE_USER_001": {
                "turns": [{"query": "Hi", "answer": "Hello!"}],
                "last_active": datetime(2026, 1, 15, tzinfo=timezone.utc),
            },
        }


fake_db = FakeFirestore()


async def mock_get_tenant(tenant_id: str) -> dict | None:
    return fake_db.tenants.get(tenant_id)


async def mock_list_tenants() -> list[dict]:
    return [{"tenant_id": k, **v} for k, v in fake_db.tenants.items()]


async def mock_create_tenant(data: dict) -> dict:
    tid = data.pop("tenant_id")
    now = datetime.now(timezone.utc)
    doc = {**data, "tenant_id": tid, "created_at": now, "updated_at": now}
    fake_db.tenants[tid] = doc
    return doc


async def mock_update_tenant(tenant_id: str, data: dict) -> dict | None:
    if tenant_id not in fake_db.tenants:
        return None
    fake_db.tenants[tenant_id].update(data)
    return fake_db.tenants[tenant_id]


async def mock_delete_tenant(tenant_id: str) -> bool:
    if tenant_id not in fake_db.tenants:
        return False
    del fake_db.tenants[tenant_id]
    return True


async def mock_get_admin_user(uid: str) -> dict | None:
    return fake_db.admin_users.get(uid)


async def mock_list_admin_users() -> list[dict]:
    return list(fake_db.admin_users.values())


async def mock_create_admin_user(uid: str, data: dict) -> dict:
    now = datetime.now(timezone.utc)
    doc = {"uid": uid, **data, "created_at": now, "updated_at": now}
    fake_db.admin_users[uid] = doc
    return doc


async def mock_update_admin_user(uid: str, data: dict) -> dict | None:
    if uid not in fake_db.admin_users:
        return None
    fake_db.admin_users[uid].update(data)
    return fake_db.admin_users[uid]


async def mock_delete_admin_user(uid: str) -> bool:
    if uid not in fake_db.admin_users:
        return False
    del fake_db.admin_users[uid]
    return True


async def mock_count_admin_users() -> int:
    return len(fake_db.admin_users)


async def mock_log_chat(tenant_id, user_id, query, answer, sources) -> str:
    fake_db.chat_logs.append({
        "tenant_id": tenant_id, "user_id": user_id,
        "query": query, "answer": answer, "sources": sources,
    })
    return "log-001"


async def mock_get_chat_logs(tenant_id, limit=50, offset=0) -> list[dict]:
    logs = [l for l in fake_db.chat_logs if l["tenant_id"] == tenant_id]
    return [{"id": f"log-{i}", **l} for i, l in enumerate(logs[offset:offset + limit])]


async def mock_get_analytics(tenant_id) -> dict:
    logs = [l for l in fake_db.chat_logs if l["tenant_id"] == tenant_id]
    return {
        "tenant_id": tenant_id,
        "total_chats": len(logs),
        "unique_users": len({l["user_id"] for l in logs}),
    }


async def mock_export_user_data(tenant_id: str, user_id: str) -> dict:
    logs = [
        {"id": f"log-{i}", **l}
        for i, l in enumerate(fake_db.chat_logs)
        if l["tenant_id"] == tenant_id and l["user_id"] == user_id
    ]
    conversation = fake_db.conversations.get(user_id)
    consents = [
        c for c in fake_db.consents
        if c["tenant_id"] == tenant_id and c["user_id"] == user_id
    ]
    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "chat_logs": logs,
        "conversation_memory": conversation,
        "consents": consents,
    }


async def mock_delete_user_data(tenant_id: str, user_id: str) -> dict:
    before = len(fake_db.chat_logs)
    fake_db.chat_logs = [
        l for l in fake_db.chat_logs
        if not (l["tenant_id"] == tenant_id and l["user_id"] == user_id)
    ]
    deleted_logs = before - len(fake_db.chat_logs)
    deleted_conv = 0
    if user_id in fake_db.conversations:
        del fake_db.conversations[user_id]
        deleted_conv = 1
    before_consents = len(fake_db.consents)
    fake_db.consents = [
        c for c in fake_db.consents
        if not (c["tenant_id"] == tenant_id and c["user_id"] == user_id)
    ]
    deleted_consents = before_consents - len(fake_db.consents)
    return {
        "deleted_chat_logs": deleted_logs,
        "deleted_conversations": deleted_conv,
        "deleted_consents": deleted_consents,
    }


async def mock_anonymize_user_data(tenant_id: str, user_id: str) -> dict:
    import hashlib
    anon_id = f"anon_{hashlib.sha256(user_id.encode()).hexdigest()[:12]}"
    count = 0
    for log in fake_db.chat_logs:
        if log["tenant_id"] == tenant_id and log["user_id"] == user_id:
            log["user_id"] = anon_id
            count += 1
    if user_id in fake_db.conversations:
        fake_db.conversations[anon_id] = fake_db.conversations.pop(user_id)
    for consent in fake_db.consents:
        if consent["tenant_id"] == tenant_id and consent["user_id"] == user_id:
            consent["user_id"] = anon_id
    return {"anonymized_records": count, "anonymous_id": anon_id}


async def mock_cleanup_expired_data(retention_days: int) -> dict:
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    before = len(fake_db.chat_logs)
    fake_db.chat_logs = [l for l in fake_db.chat_logs if l["created_at"] >= cutoff]
    return {"deleted_chat_logs": before - len(fake_db.chat_logs)}


async def mock_record_consent(tenant_id: str, user_id: str, consent_type: str, version: str) -> dict:
    now = datetime.now(timezone.utc)
    consent = {
        "tenant_id": tenant_id, "user_id": user_id,
        "consent_type": consent_type, "version": version,
        "granted_at": now,
    }
    fake_db.consents.append(consent)
    return {"id": f"consent-{len(fake_db.consents)}", **consent}


async def mock_get_user_consents(tenant_id: str, user_id: str) -> list:
    return [
        c for c in fake_db.consents
        if c["tenant_id"] == tenant_id and c["user_id"] == user_id
    ]


async def mock_revoke_consent(tenant_id: str, user_id: str, consent_type: str) -> bool:
    before = len(fake_db.consents)
    fake_db.consents = [
        c for c in fake_db.consents
        if not (c["tenant_id"] == tenant_id and c["user_id"] == user_id and c["consent_type"] == consent_type)
    ]
    return len(fake_db.consents) < before


# Registration mocks

async def mock_create_registration(data: dict) -> dict:
    now = datetime.now(timezone.utc)
    reg_id = f"reg-{len(fake_db.pending_registrations) + 1:03d}"
    doc = {
        "id": reg_id, **data,
        "status": "pending",
        "created_at": now,
    }
    fake_db.pending_registrations[reg_id] = doc
    return doc


async def mock_list_registrations(status: str = "pending") -> list:
    return [
        r for r in fake_db.pending_registrations.values()
        if r["status"] == status
    ]


async def mock_get_registration(reg_id: str) -> dict | None:
    return fake_db.pending_registrations.get(reg_id)


async def mock_update_registration(reg_id: str, data: dict) -> dict | None:
    if reg_id not in fake_db.pending_registrations:
        return None
    fake_db.pending_registrations[reg_id].update(data)
    return fake_db.pending_registrations[reg_id]


async def mock_get_onboarding_status(tenant_id: str) -> list:
    tenant = fake_db.tenants.get(tenant_id)
    if not tenant:
        return []
    return tenant.get("onboarding_completed", [])


async def mock_update_onboarding_status(tenant_id: str, steps: list) -> dict | None:
    if tenant_id not in fake_db.tenants:
        return None
    fake_db.tenants[tenant_id]["onboarding_completed"] = steps
    return fake_db.tenants[tenant_id]


# ──────────────────────────────────────
# Fixtures
# ──────────────────────────────────────

_FIRESTORE_PATCHES = {
    "shared.services.firestore.get_tenant": mock_get_tenant,
    "shared.services.firestore.list_tenants": mock_list_tenants,
    "shared.services.firestore.create_tenant": mock_create_tenant,
    "shared.services.firestore.update_tenant": mock_update_tenant,
    "shared.services.firestore.delete_tenant": mock_delete_tenant,
    "shared.services.firestore.get_admin_user": mock_get_admin_user,
    "shared.services.firestore.list_admin_users": mock_list_admin_users,
    "shared.services.firestore.create_admin_user": mock_create_admin_user,
    "shared.services.firestore.update_admin_user": mock_update_admin_user,
    "shared.services.firestore.delete_admin_user": mock_delete_admin_user,
    "shared.services.firestore.count_admin_users": mock_count_admin_users,
    "shared.services.firestore.log_chat": mock_log_chat,
    "shared.services.firestore.get_chat_logs": mock_get_chat_logs,
    "shared.services.firestore.get_analytics": mock_get_analytics,
    "shared.services.firestore.export_user_data": mock_export_user_data,
    "shared.services.firestore.delete_user_data": mock_delete_user_data,
    "shared.services.firestore.anonymize_user_data": mock_anonymize_user_data,
    "shared.services.firestore.cleanup_expired_data": mock_cleanup_expired_data,
    "shared.services.firestore.record_consent": mock_record_consent,
    "shared.services.firestore.get_user_consents": mock_get_user_consents,
    "shared.services.firestore.revoke_consent": mock_revoke_consent,
    "shared.services.firestore.create_registration": mock_create_registration,
    "shared.services.firestore.list_registrations": mock_list_registrations,
    "shared.services.firestore.get_registration": mock_get_registration,
    "shared.services.firestore.update_registration": mock_update_registration,
    "shared.services.firestore.get_onboarding_status": mock_get_onboarding_status,
    "shared.services.firestore.update_onboarding_status": mock_update_onboarding_status,
}


@pytest.fixture(autouse=True)
def _patch_firestore():
    """Replace all Firestore calls with in-memory fakes."""
    fake_db.reset()
    fake_db.seed()

    patchers = [patch(target, side_effect=fn) for target, fn in _FIRESTORE_PATCHES.items()]
    for p in patchers:
        p.start()
    yield
    for p in patchers:
        p.stop()


@pytest.fixture(autouse=True)
def _patch_firebase_auth():
    """Mock Firebase token verification."""
    def fake_verify(token: str) -> dict:
        # Token format: "test-token-{uid}"
        if token.startswith("test-token-"):
            uid = token.replace("test-token-", "")
            return {"uid": uid}
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid token")

    with (
        patch("shared.services.auth._init_firebase"),
        patch("shared.services.auth._verify_id_token", side_effect=fake_verify),
    ):
        yield


@pytest.fixture(autouse=True)
def _patch_startup():
    """Skip heavy startup (embedding, vectorstore, reranker)."""
    with (
        patch("shared.services.embedding.get_embedding_model"),
        patch("shared.services.vectorstore.get_vectorstore"),
        patch("shared.services.vectorstore.get_raw_index"),
        patch("chat.services.reranker.get_reranker"),
    ):
        yield


@pytest.fixture
def app():
    from admin.main import app as fastapi_app
    return fastapi_app


@pytest.fixture
async def client(app):
    """Async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def super_admin_headers() -> dict:
    """Auth headers for super admin."""
    return {"Authorization": "Bearer test-token-super-uid-001"}


def faculty_admin_headers() -> dict:
    """Auth headers for faculty admin."""
    return {"Authorization": "Bearer test-token-faculty-uid-001"}


def api_key_headers() -> dict:
    """Auth headers using API key."""
    return {"X-API-Key": ""}  # Empty = skip auth per config default
