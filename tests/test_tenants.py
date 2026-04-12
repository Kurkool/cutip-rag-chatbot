"""Integration tests for tenant CRUD endpoints."""

import pytest
from tests.conftest import super_admin_headers, faculty_admin_headers


class TestListTenants:
    async def test_list(self, client):
        res = await client.get("/api/tenants", headers=super_admin_headers())
        assert res.status_code == 200
        assert isinstance(res.json(), list)
        assert len(res.json()) == 2


class TestCreateTenant:
    async def test_create_success(self, client):
        res = await client.post(
            "/api/tenants",
            headers=super_admin_headers(),
            json={
                "tenant_id": "new_tenant",
                "faculty_name": "New Faculty",
                "line_destination": "U999",
                "line_channel_access_token": "tok",
                "line_channel_secret": "sec",
                "pinecone_namespace": "ns-new",
            },
        )
        assert res.status_code == 201
        data = res.json()
        assert data["tenant_id"] == "new_tenant"
        assert data["faculty_name"] == "New Faculty"

    async def test_create_duplicate(self, client):
        res = await client.post(
            "/api/tenants",
            headers=super_admin_headers(),
            json={
                "tenant_id": "tenant_a",
                "faculty_name": "Dup",
                "line_destination": "U123",
                "line_channel_access_token": "tok",
                "line_channel_secret": "sec",
                "pinecone_namespace": "ns-dup",
            },
        )
        assert res.status_code == 409

    async def test_create_invalid_id(self, client):
        res = await client.post(
            "/api/tenants",
            headers=super_admin_headers(),
            json={
                "tenant_id": "INVALID ID!",
                "faculty_name": "Bad",
                "line_destination": "U123",
                "line_channel_access_token": "tok",
                "line_channel_secret": "sec",
                "pinecone_namespace": "ns-bad",
            },
        )
        assert res.status_code == 422


class TestGetTenant:
    async def test_get_existing(self, client):
        res = await client.get(
            "/api/tenants/tenant_a",
            headers=super_admin_headers(),
        )
        assert res.status_code == 200
        assert res.json()["tenant_id"] == "tenant_a"

    async def test_get_nonexistent(self, client):
        res = await client.get(
            "/api/tenants/nonexistent",
            headers=super_admin_headers(),
        )
        assert res.status_code == 404


class TestUpdateTenant:
    async def test_update_success(self, client):
        res = await client.put(
            "/api/tenants/tenant_a",
            headers=super_admin_headers(),
            json={"faculty_name": "Updated Faculty"},
        )
        assert res.status_code == 200
        assert res.json()["faculty_name"] == "Updated Faculty"

    async def test_update_empty_body(self, client):
        res = await client.put(
            "/api/tenants/tenant_a",
            headers=super_admin_headers(),
            json={},
        )
        assert res.status_code == 400

    async def test_update_nonexistent(self, client):
        res = await client.put(
            "/api/tenants/nonexistent",
            headers=super_admin_headers(),
            json={"faculty_name": "X"},
        )
        assert res.status_code == 404

    async def test_faculty_admin_can_update_assigned(self, client):
        res = await client.put(
            "/api/tenants/tenant_a",
            headers=faculty_admin_headers(),
            json={"persona": "new persona"},
        )
        assert res.status_code == 200


class TestDeleteTenant:
    async def test_delete_success(self, client):
        res = await client.delete(
            "/api/tenants/tenant_b",
            headers=super_admin_headers(),
        )
        assert res.status_code == 204

    async def test_delete_nonexistent(self, client):
        res = await client.delete(
            "/api/tenants/nonexistent",
            headers=super_admin_headers(),
        )
        assert res.status_code == 404
