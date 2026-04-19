"""Router integration tests for thin-wrapper endpoints that delegate to ingest_v2.

Guards against regression where someone accidentally re-imports v1 dispatchers
(ingest_pdf, _ingest_by_type, etc.) — the router tests here assert that every
file-ingest endpoint actually calls ``ingestion_v2.ingest_v2`` under the hood.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import TENANT_A, faculty_admin_headers, fake_db


@pytest.fixture
def ingest_app():
    from ingest.main import app as fastapi_app
    return fastapi_app


@pytest.fixture
async def ingest_client(ingest_app):
    transport = ASGITransport(app=ingest_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _seed_tenant():
    fake_db.tenants.clear()
    fake_db.tenants["tenant_a"] = dict(TENANT_A)


# ──────────────────────────────────────
# /document — PDF/DOC/DOCX upload
# ──────────────────────────────────────

@pytest.mark.asyncio
async def test_document_endpoint_routes_through_v2(ingest_client):
    _seed_tenant()
    fake_v2 = AsyncMock(return_value=5)
    with patch("ingest.services.ingestion_v2.ingest_v2", fake_v2):
        files = {"file": ("test.pdf", b"%PDF-1.4\nfake\n%%EOF", "application/pdf")}
        r = await ingest_client.post(
            "/api/tenants/tenant_a/ingest/document",
            headers=faculty_admin_headers(),
            files=files,
            data={"doc_category": "form", "download_link": "https://drive/x"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chunks_processed"] == 5
    fake_v2.assert_called_once()
    kwargs = fake_v2.call_args.kwargs
    assert kwargs["filename"] == "test.pdf"
    assert kwargs["namespace"] == "ns-tenant-a"
    assert kwargs["tenant_id"] == "tenant_a"
    assert kwargs["doc_category"] == "form"
    assert kwargs["download_link"] == "https://drive/x"


# ──────────────────────────────────────
# /spreadsheet — XLSX/CSV upload
# ──────────────────────────────────────

@pytest.mark.asyncio
async def test_spreadsheet_endpoint_routes_through_v2(ingest_client):
    _seed_tenant()
    fake_v2 = AsyncMock(return_value=3)
    with patch("ingest.services.ingestion_v2.ingest_v2", fake_v2):
        files = {"file": ("data.xlsx", b"PK\x03\x04\x14\x00",
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        r = await ingest_client.post(
            "/api/tenants/tenant_a/ingest/spreadsheet",
            headers=faculty_admin_headers(),
            files=files,
            data={"doc_category": "general"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chunks_processed"] == 3
    assert body["sheets_processed"] == 0  # deprecated post-v2 cutover (sheet concept lost in PDF conversion)
    fake_v2.assert_called_once()
    assert fake_v2.call_args.kwargs["filename"] == "data.xlsx"


# ──────────────────────────────────────
# /gdrive/file — single-file Drive ingest
# ──────────────────────────────────────

@pytest.mark.asyncio
async def test_gdrive_file_endpoint_routes_through_v2(ingest_client):
    _seed_tenant()
    fake_v2 = AsyncMock(return_value=7)
    fake_list = MagicMock(return_value=[
        {"id": "fileid", "name": "doc.pdf", "mimeType": "application/pdf"},
    ])
    fake_download = MagicMock(return_value=b"%PDF-1.4\nfake\n%%EOF")
    with patch("ingest.services.ingestion_v2.ingest_v2", fake_v2), \
         patch("ingest.services.gdrive.list_files", fake_list), \
         patch("ingest.services.gdrive.download_file", fake_download):
        r = await ingest_client.post(
            "/api/tenants/tenant_a/ingest/gdrive/file",
            headers=faculty_admin_headers(),
            json={"folder_id": "folderid", "filename": "doc.pdf",
                  "doc_category": "general"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["chunks_processed"] == 7
    fake_v2.assert_called_once()
    kwargs = fake_v2.call_args.kwargs
    assert kwargs["filename"] == "doc.pdf"
    assert kwargs["namespace"] == "ns-tenant-a"


# ──────────────────────────────────────
# /gdrive — batch (force re-ingest all files)
# ──────────────────────────────────────

@pytest.mark.asyncio
async def test_gdrive_batch_routes_all_files_through_v2(ingest_client):
    _seed_tenant()
    fake_v2 = AsyncMock(return_value=2)
    fake_list = MagicMock(return_value=[
        {"id": "f1", "name": "a.pdf", "mimeType": "application/pdf"},
        {"id": "f2", "name": "b.docx",
         "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ])
    fake_download = MagicMock(return_value=b"%PDF-1.4")
    with patch("ingest.services.ingestion_v2.ingest_v2", fake_v2), \
         patch("ingest.services.gdrive.list_files", fake_list), \
         patch("ingest.services.gdrive.download_file", fake_download), \
         patch("ingest.routers.ingestion.asyncio.sleep", AsyncMock()):  # skip 3s pacing
        r = await ingest_client.post(
            "/api/tenants/tenant_a/ingest/gdrive",
            headers=faculty_admin_headers(),
            json={"folder_id": "folderid", "doc_category": "general"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_files"] == 2
    assert len(body["ingested"]) == 2
    assert fake_v2.call_count == 2  # every file goes through v2


# ──────────────────────────────────────
# /gdrive/scan — skip existing (Cloud Scheduler path)
# ──────────────────────────────────────

@pytest.mark.asyncio
async def test_gdrive_scan_skips_existing_and_routes_new_through_v2(ingest_client):
    _seed_tenant()
    fake_v2 = AsyncMock(return_value=1)
    fake_list = MagicMock(return_value=[
        {"id": "f1", "name": "already.pdf", "mimeType": "application/pdf"},
        {"id": "f2", "name": "new.pdf", "mimeType": "application/pdf"},
    ])
    fake_download = MagicMock(return_value=b"%PDF-1.4")
    fake_existing = MagicMock(return_value={"already.pdf"})
    with patch("ingest.services.ingestion_v2.ingest_v2", fake_v2), \
         patch("ingest.services.gdrive.list_files", fake_list), \
         patch("ingest.services.gdrive.download_file", fake_download), \
         patch("ingest.routers.ingestion._get_existing_filenames", fake_existing), \
         patch("ingest.routers.ingestion.asyncio.sleep", AsyncMock()):
        r = await ingest_client.post(
            "/api/tenants/tenant_a/ingest/gdrive/scan",
            headers=faculty_admin_headers(),
            json={"folder_id": "folderid", "doc_category": "general"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_files"] == 2
    assert len(body["ingested"]) == 1
    assert body["ingested"][0]["filename"] == "new.pdf"
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["filename"] == "already.pdf"
    # Crucial: v2 NOT invoked for the already-ingested file — skip is pure
    assert fake_v2.call_count == 1
    assert fake_v2.call_args.kwargs["filename"] == "new.pdf"
