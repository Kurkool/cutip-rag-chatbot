"""Tests for POST /api/ingest/scan-all — cross-tenant scheduler endpoint."""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import super_admin_headers, faculty_admin_headers, fake_db


@pytest.fixture
def ingest_app():
    from ingest.main import app as fastapi_app
    return fastapi_app


@pytest.fixture
async def ingest_client(ingest_app):
    transport = ASGITransport(app=ingest_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _seed_tenant_with_folder(tid: str, folder_id: str, active: bool = True):
    from datetime import datetime, timezone
    fake_db.tenants[tid] = {
        "tenant_id": tid,
        "faculty_name": f"Faculty {tid}",
        "line_destination": f"U_{tid}",
        "line_channel_access_token": "t",
        "line_channel_secret": "s",
        "pinecone_namespace": f"ns-{tid}",
        "persona": "",
        "drive_folder_id": folder_id,
        "is_active": active,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }


@pytest.mark.asyncio
async def test_scan_all_requires_super_admin(ingest_client):
    r = await ingest_client.post("/api/ingest/scan-all")
    assert r.status_code == 401

    r = await ingest_client.post(
        "/api/ingest/scan-all", headers=faculty_admin_headers(),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_scan_all_skips_tenants_without_folder(ingest_client):
    fake_db.tenants.clear()
    _seed_tenant_with_folder("t_a", folder_id="folder_a")
    _seed_tenant_with_folder("t_b", folder_id="")  # opt-out
    _seed_tenant_with_folder("t_c", folder_id="folder_c", active=False)

    from shared.schemas import GDriveIngestResult

    async def fake_process(tenant, folder_id, doc_category, skip_existing):
        return GDriveIngestResult(total_files=2, ingested=[{"f": 1}], skipped=[], errors=[])

    with patch("ingest.routers.ingestion._process_gdrive_folder", side_effect=fake_process):
        r = await ingest_client.post(
            "/api/ingest/scan-all", headers=super_admin_headers(),
        )

    assert r.status_code == 200
    data = r.json()
    assert data["total_tenants"] == 3
    processed_ids = {p["tenant_id"] for p in data["processed"]}
    assert processed_ids == {"t_a"}
    skipped = {s["tenant_id"]: s["reason"] for s in data["skipped_tenants"]}
    assert skipped == {"t_b": "no drive_folder_id", "t_c": "inactive"}


@pytest.mark.asyncio
async def test_scan_all_isolates_per_tenant_errors(ingest_client):
    fake_db.tenants.clear()
    _seed_tenant_with_folder("t_ok", folder_id="folder_ok")
    _seed_tenant_with_folder("t_bad", folder_id="folder_bad")

    from shared.schemas import GDriveIngestResult

    async def fake_process(tenant, folder_id, doc_category, skip_existing):
        if folder_id == "folder_bad":
            raise RuntimeError("drive api blew up")
        return GDriveIngestResult(total_files=1, ingested=[{"f": 1}], skipped=[], errors=[])

    with patch("ingest.routers.ingestion._process_gdrive_folder", side_effect=fake_process):
        r = await ingest_client.post(
            "/api/ingest/scan-all", headers=super_admin_headers(),
        )

    assert r.status_code == 200
    data = r.json()
    assert {p["tenant_id"] for p in data["processed"]} == {"t_ok"}
    assert {e["tenant_id"] for e in data["errored_tenants"]} == {"t_bad"}
    assert data["errored_tenants"][0]["error"] == "RuntimeError"
    # Message body included so scheduler-alert readers know the cause
    assert "drive api blew up" in data["errored_tenants"][0]["message"]
