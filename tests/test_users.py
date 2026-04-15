"""Integration tests for user management endpoints."""

import pytest
from unittest.mock import patch, MagicMock
from tests.conftest import super_admin_headers, faculty_admin_headers


class TestListUsers:
    async def test_super_admin_can_list(self, client):
        res = await client.get("/api/users", headers=super_admin_headers())
        assert res.status_code == 200
        users = res.json()
        assert len(users) >= 2
        emails = [u["email"] for u in users]
        assert "admin@test.com" in emails

    async def test_faculty_admin_cannot_list(self, client):
        res = await client.get("/api/users", headers=faculty_admin_headers())
        assert res.status_code == 403


class TestGetUser:
    async def test_get_existing_user(self, client):
        res = await client.get(
            "/api/users/super-uid-001",
            headers=super_admin_headers(),
        )
        assert res.status_code == 200
        assert res.json()["email"] == "admin@test.com"

    async def test_get_nonexistent_user(self, client):
        res = await client.get(
            "/api/users/nonexistent",
            headers=super_admin_headers(),
        )
        assert res.status_code == 404


class TestCreateUser:
    async def test_create_success(self, client):
        mock_fb_user = MagicMock()
        mock_fb_user.uid = "new-uid-001"

        with (
            patch("admin.routers.users._init_firebase"),
            patch("admin.routers.users.firebase_auth.create_user", return_value=mock_fb_user),
        ):
            res = await client.post(
                "/api/users",
                headers=super_admin_headers(),
                json={
                    "email": "new@test.com",
                    "password": "securepass",
                    "display_name": "New User",
                    "role": "faculty_admin",
                    "tenant_ids": ["tenant_a"],
                },
            )
        assert res.status_code == 201
        data = res.json()
        assert data["email"] == "new@test.com"
        assert data["role"] == "faculty_admin"

    async def test_create_with_invalid_tenant(self, client):
        res = await client.post(
            "/api/users",
            headers=super_admin_headers(),
            json={
                "email": "x@test.com",
                "password": "securepass",
                "display_name": "X",
                "role": "faculty_admin",
                "tenant_ids": ["nonexistent_tenant"],
            },
        )
        assert res.status_code == 404

    async def test_faculty_cannot_create(self, client):
        res = await client.post(
            "/api/users",
            headers=faculty_admin_headers(),
            json={
                "email": "x@test.com",
                "password": "securepass",
                "display_name": "X",
                "role": "faculty_admin",
                "tenant_ids": [],
            },
        )
        assert res.status_code == 403


class TestUpdateUser:
    async def test_update_role(self, client):
        res = await client.put(
            "/api/users/faculty-uid-001",
            headers=super_admin_headers(),
            json={"role": "super_admin"},
        )
        assert res.status_code == 200
        assert res.json()["role"] == "super_admin"

    async def test_update_empty(self, client):
        res = await client.put(
            "/api/users/faculty-uid-001",
            headers=super_admin_headers(),
            json={},
        )
        assert res.status_code == 400


class TestDeleteUser:
    async def test_delete_success(self, client):
        with (
            patch("admin.routers.users._init_firebase"),
            patch("admin.routers.users.firebase_auth.delete_user"),
        ):
            res = await client.delete(
                "/api/users/faculty-uid-001",
                headers=super_admin_headers(),
            )
        assert res.status_code == 204

    async def test_cannot_delete_self(self, client):
        res = await client.delete(
            "/api/users/super-uid-001",
            headers=super_admin_headers(),
        )
        assert res.status_code == 400
        assert "yourself" in res.json()["detail"].lower()

    async def test_delete_nonexistent(self, client):
        res = await client.delete(
            "/api/users/nonexistent",
            headers=super_admin_headers(),
        )
        assert res.status_code == 404
