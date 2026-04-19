"""Integration tests for tenant CRUD endpoints."""

import pytest
from tests.conftest import fake_db, super_admin_headers, faculty_admin_headers


@pytest.fixture
def seed_tenant_a_with_drive():
    """Add drive_folder_id to the pre-seeded tenant_a so Drive-delete code paths activate."""
    if "tenant_a" in fake_db.tenants:
        fake_db.tenants["tenant_a"]["drive_folder_id"] = "folder_xyz"
    yield
    if "tenant_a" in fake_db.tenants:
        fake_db.tenants["tenant_a"]["drive_folder_id"] = ""


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


class TestConnectGDrive:
    async def test_connect_persists_folder(self, client):
        res = await client.post(
            "/api/tenants/tenant_a/gdrive/connect",
            headers=super_admin_headers(),
            json={
                "folder_id": "abc123xyz",
                "folder_name": "Faculty A - Documents",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["drive_folder_id"] == "abc123xyz"
        assert data["drive_folder_name"] == "Faculty A - Documents"

    async def test_connect_rejects_empty_folder_id(self, client):
        res = await client.post(
            "/api/tenants/tenant_a/gdrive/connect",
            headers=super_admin_headers(),
            json={"folder_id": "", "folder_name": "Name"},
        )
        assert res.status_code == 422  # Pydantic min_length=1

    async def test_faculty_admin_can_connect_assigned_tenant(self, client):
        res = await client.post(
            "/api/tenants/tenant_a/gdrive/connect",
            headers=faculty_admin_headers(),
            json={"folder_id": "folderId", "folder_name": "Shared"},
        )
        assert res.status_code == 200


class TestDeleteSingleDocument:
    async def test_delete_uses_stored_drive_file_id(self, client, seed_tenant_a_with_drive):
        """Rename-safe delete: Pinecone stores drive_file_id → delete by ID directly,
        no name-based Drive lookup (which would fail after rename).
        """
        from unittest.mock import patch
        with patch(
            "admin.routers.analytics.get_drive_file_id_for",
            return_value="file_abc",
        ) as mock_lookup, patch(
            "admin.routers.analytics.delete_vectors_by_filename",
            return_value=7,
        ) as mock_vectors, patch(
            "shared.services.gdrive.find_file_id_by_name",
        ) as mock_find_by_name, patch(
            "shared.services.gdrive.delete_file",
            return_value=True,
        ) as mock_drive_del:
            res = await client.delete(
                "/api/tenants/tenant_a/documents/example.pdf",
                headers=super_admin_headers(),
            )
        assert res.status_code == 200
        body = res.json()
        assert body["vectors_deleted"] == 7
        assert body["drive_removed"] is True
        mock_vectors.assert_called_once_with("ns-tenant-a", "example.pdf")
        mock_drive_del.assert_called_once_with("file_abc")
        # Name fallback MUST NOT be called when ID is available
        mock_find_by_name.assert_not_called()

    async def test_delete_falls_back_to_name_for_legacy_chunks(self, client, seed_tenant_a_with_drive):
        """Legacy chunks (no drive_file_id in metadata) → fall back to name-based Drive lookup."""
        from unittest.mock import patch
        with patch(
            "admin.routers.analytics.get_drive_file_id_for",
            return_value=None,  # legacy: no drive_file_id stored
        ), patch(
            "admin.routers.analytics.delete_vectors_by_filename",
            return_value=5,
        ), patch(
            "shared.services.gdrive.find_file_id_by_name",
            return_value="file_legacy",
        ) as mock_find, patch(
            "shared.services.gdrive.delete_file",
            return_value=True,
        ) as mock_drive_del:
            res = await client.delete(
                "/api/tenants/tenant_a/documents/legacy.pdf",
                headers=super_admin_headers(),
            )
        assert res.status_code == 200
        assert res.json()["drive_removed"] is True
        mock_find.assert_called_once_with("folder_xyz", "legacy.pdf")
        mock_drive_del.assert_called_once_with("file_legacy")

    async def test_delete_handles_renamed_file_gracefully(self, client, seed_tenant_a_with_drive):
        """User renamed file in Drive after ingest, then deletes via admin portal.
        With drive_file_id stored, ID-based delete succeeds despite stale name.
        """
        from unittest.mock import patch
        # Pinecone metadata has drive_file_id (rename-safe path)
        with patch(
            "admin.routers.analytics.get_drive_file_id_for",
            return_value="file_renamed",
        ), patch(
            "admin.routers.analytics.delete_vectors_by_filename",
            return_value=4,
        ), patch(
            "shared.services.gdrive.find_file_id_by_name",
        ) as mock_find_by_name, patch(
            "shared.services.gdrive.delete_file",
            return_value=True,
        ) as mock_drive_del:
            res = await client.delete(
                "/api/tenants/tenant_a/documents/original_name.pdf",
                headers=super_admin_headers(),
            )
        assert res.status_code == 200
        # ID-based delete fired; name-based fallback NOT invoked (the original name
        # wouldn't match the renamed file in Drive anyway)
        mock_drive_del.assert_called_once_with("file_renamed")
        mock_find_by_name.assert_not_called()

    async def test_delete_faculty_admin_allowed(self, client, seed_tenant_a_with_drive):
        from unittest.mock import patch
        with patch(
            "admin.routers.analytics.get_drive_file_id_for",
            return_value=None,
        ), patch(
            "admin.routers.analytics.delete_vectors_by_filename",
            return_value=0,
        ), patch(
            "shared.services.gdrive.find_file_id_by_name",
            return_value=None,
        ):
            res = await client.delete(
                "/api/tenants/tenant_a/documents/nothing.pdf",
                headers=faculty_admin_headers(),
            )
        assert res.status_code == 200
        assert res.json()["drive_removed"] is False

    async def test_delete_no_drive_folder_skips_drive(self, client):
        """Tenant without drive_folder_id and no drive_file_id: Pinecone-only."""
        from unittest.mock import patch
        with patch(
            "admin.routers.analytics.get_drive_file_id_for",
            return_value=None,
        ), patch(
            "admin.routers.analytics.delete_vectors_by_filename",
            return_value=2,
        ), patch(
            "shared.services.gdrive.find_file_id_by_name",
        ) as mock_find, patch(
            "shared.services.gdrive.delete_file",
        ) as mock_del:
            res = await client.delete(
                "/api/tenants/tenant_a/documents/orphan.pdf",
                headers=super_admin_headers(),
            )
        assert res.status_code == 200
        assert res.json()["drive_removed"] is False
        mock_find.assert_not_called()
        mock_del.assert_not_called()

    async def test_delete_handles_thai_filename(self, client, seed_tenant_a_with_drive):
        from unittest.mock import patch
        from urllib.parse import quote
        with patch(
            "admin.routers.analytics.get_drive_file_id_for",
            return_value="file_thai",
        ), patch(
            "admin.routers.analytics.delete_vectors_by_filename",
            return_value=3,
        ) as mock_vectors, patch(
            "shared.services.gdrive.delete_file",
            return_value=True,
        ):
            res = await client.delete(
                f"/api/tenants/tenant_a/documents/{quote('ตารางเรียน.xlsx')}",
                headers=super_admin_headers(),
            )
        assert res.status_code == 200
        mock_vectors.assert_called_once_with("ns-tenant-a", "ตารางเรียน.xlsx")


class TestDeleteAllDocuments:
    async def test_delete_all_wipes_drive_and_pinecone(self, client, seed_tenant_a_with_drive):
        from unittest.mock import patch, MagicMock
        fake_index = MagicMock()
        with patch("admin.routers.analytics.get_raw_index", return_value=fake_index), \
             patch(
                "shared.services.gdrive.list_files",
                return_value=[
                    {"id": "f1", "name": "a.pdf", "mimeType": "application/pdf"},
                    {"id": "f2", "name": "b.xlsx", "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
                ],
             ), patch(
                "shared.services.gdrive.delete_file",
                return_value=True,
             ) as mock_drive_del:
            res = await client.delete(
                "/api/tenants/tenant_a/documents",
                headers=super_admin_headers(),
            )
        assert res.status_code == 200
        body = res.json()
        assert body["drive_deleted"] == 2
        assert body["drive_errors"] == []
        fake_index.delete.assert_called_once_with(delete_all=True, namespace="ns-tenant-a")
        assert mock_drive_del.call_count == 2




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
