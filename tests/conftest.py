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

    def reset(self):
        self.tenants.clear()
        self.admin_users.clear()
        self.chat_logs.clear()

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


# ──────────────────────────────────────
# Fixtures
# ──────────────────────────────────────

@pytest.fixture(autouse=True)
def _patch_firestore():
    """Replace all Firestore calls with in-memory fakes."""
    fake_db.reset()
    fake_db.seed()

    with (
        patch("services.firestore.get_tenant", side_effect=mock_get_tenant),
        patch("services.firestore.list_tenants", side_effect=mock_list_tenants),
        patch("services.firestore.create_tenant", side_effect=mock_create_tenant),
        patch("services.firestore.update_tenant", side_effect=mock_update_tenant),
        patch("services.firestore.delete_tenant", side_effect=mock_delete_tenant),
        patch("services.firestore.get_admin_user", side_effect=mock_get_admin_user),
        patch("services.firestore.list_admin_users", side_effect=mock_list_admin_users),
        patch("services.firestore.create_admin_user", side_effect=mock_create_admin_user),
        patch("services.firestore.update_admin_user", side_effect=mock_update_admin_user),
        patch("services.firestore.delete_admin_user", side_effect=mock_delete_admin_user),
        patch("services.firestore.count_admin_users", side_effect=mock_count_admin_users),
        patch("services.firestore.log_chat", side_effect=mock_log_chat),
        patch("services.firestore.get_chat_logs", side_effect=mock_get_chat_logs),
        patch("services.firestore.get_analytics", side_effect=mock_get_analytics),
    ):
        yield


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
        patch("services.auth._init_firebase"),
        patch("services.auth._verify_id_token", side_effect=fake_verify),
    ):
        yield


@pytest.fixture(autouse=True)
def _patch_startup():
    """Skip heavy startup (embedding, vectorstore, reranker)."""
    with (
        patch("services.embedding.get_embedding_model"),
        patch("services.vectorstore.get_vectorstore"),
        patch("services.vectorstore.get_raw_index"),
        patch("services.reranker.get_reranker"),
    ):
        yield


@pytest.fixture
def app():
    from main import app as fastapi_app
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
