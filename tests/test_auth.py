"""Integration tests for authentication + RBAC."""

import pytest
from tests.conftest import super_admin_headers, faculty_admin_headers


class TestHealthCheck:
    async def test_health_no_auth(self, client):
        res = await client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestAuthRequired:
    async def test_no_auth_returns_401(self, client):
        res = await client.get("/api/tenants")
        assert res.status_code == 401

    async def test_invalid_token_returns_401(self, client):
        res = await client.get(
            "/api/tenants",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert res.status_code == 401

    async def test_valid_super_admin_token(self, client):
        res = await client.get("/api/tenants", headers=super_admin_headers())
        assert res.status_code == 200

    async def test_valid_faculty_admin_token(self, client):
        res = await client.get("/api/tenants", headers=faculty_admin_headers())
        assert res.status_code == 200


class TestGetMe:
    async def test_super_admin_me(self, client):
        res = await client.get("/api/users/me", headers=super_admin_headers())
        assert res.status_code == 200
        data = res.json()
        assert data["role"] == "super_admin"
        assert data["email"] == "admin@test.com"

    async def test_faculty_admin_me(self, client):
        res = await client.get("/api/users/me", headers=faculty_admin_headers())
        assert res.status_code == 200
        data = res.json()
        assert data["role"] == "faculty_admin"
        assert "tenant_a" in data["tenant_ids"]


class TestRBACTenantScoping:
    async def test_super_admin_sees_all_tenants(self, client):
        res = await client.get("/api/tenants", headers=super_admin_headers())
        assert res.status_code == 200
        ids = [t["tenant_id"] for t in res.json()]
        assert "tenant_a" in ids
        assert "tenant_b" in ids

    async def test_faculty_admin_sees_only_assigned(self, client):
        res = await client.get("/api/tenants", headers=faculty_admin_headers())
        assert res.status_code == 200
        ids = [t["tenant_id"] for t in res.json()]
        assert "tenant_a" in ids
        assert "tenant_b" not in ids

    async def test_faculty_admin_cannot_access_unassigned_tenant(self, client):
        res = await client.get(
            "/api/tenants/tenant_b",
            headers=faculty_admin_headers(),
        )
        assert res.status_code == 403

    async def test_faculty_admin_can_access_assigned_tenant(self, client):
        res = await client.get(
            "/api/tenants/tenant_a",
            headers=faculty_admin_headers(),
        )
        assert res.status_code == 200
        assert res.json()["tenant_id"] == "tenant_a"


class TestRBACSuperAdminOnly:
    async def test_faculty_cannot_create_tenant(self, client):
        res = await client.post(
            "/api/tenants",
            headers=faculty_admin_headers(),
            json={
                "tenant_id": "new_tenant",
                "faculty_name": "New",
                "line_destination": "U999",
                "line_channel_access_token": "tok",
                "line_channel_secret": "sec",
                "pinecone_namespace": "ns-new",
            },
        )
        assert res.status_code == 403

    async def test_faculty_cannot_delete_tenant(self, client):
        res = await client.delete(
            "/api/tenants/tenant_a",
            headers=faculty_admin_headers(),
        )
        assert res.status_code == 403

    async def test_faculty_cannot_list_users(self, client):
        res = await client.get("/api/users", headers=faculty_admin_headers())
        assert res.status_code == 403

    async def test_super_admin_can_list_users(self, client):
        res = await client.get("/api/users", headers=super_admin_headers())
        assert res.status_code == 200
        assert len(res.json()) >= 2
