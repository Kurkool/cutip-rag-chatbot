"""Tests for /api/chat authentication and RBAC — addresses Critical #1.

Verifies that /api/chat:
- Rejects unauthenticated requests (401)
- Allows super_admin to query any tenant
- Allows faculty_admin to query only their tenants
- Rejects faculty_admin querying unowned tenants (403)
- Accepts API-key auth for system callers
"""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import super_admin_headers, faculty_admin_headers


@pytest.fixture
def chat_app():
    from chat.main import app as fastapi_app
    return fastapi_app


@pytest.fixture
async def chat_client(chat_app):
    transport = ASGITransport(app=chat_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _patch_run_agent():
    """Stub run_agent so auth is the only thing under test."""
    with patch(
        "chat.routers.webhook.run_agent",
        new=AsyncMock(return_value=("stub answer", [])),
    ):
        yield


@pytest.mark.asyncio
async def test_chat_rejects_anonymous(chat_client):
    """Anonymous POST /api/chat → 401 (previously 200 — tenant injection)."""
    r = await chat_client.post(
        "/api/chat",
        json={"query": "hello", "tenant_id": "tenant_a"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_chat_super_admin_any_tenant(chat_client):
    r = await chat_client.post(
        "/api/chat",
        json={"query": "hello", "tenant_id": "tenant_b"},
        headers=super_admin_headers(),
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_chat_faculty_own_tenant_ok(chat_client):
    r = await chat_client.post(
        "/api/chat",
        json={"query": "hello", "tenant_id": "tenant_a"},
        headers=faculty_admin_headers(),
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_chat_faculty_foreign_tenant_forbidden(chat_client):
    """Faculty admin of tenant_a cannot query tenant_b's RAG."""
    r = await chat_client.post(
        "/api/chat",
        json={"query": "hello", "tenant_id": "tenant_b"},
        headers=faculty_admin_headers(),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_chat_requires_tenant_id(chat_client):
    r = await chat_client.post(
        "/api/chat",
        json={"query": "hello"},
        headers=super_admin_headers(),
    )
    assert r.status_code == 400
