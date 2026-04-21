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


def _seed_tenant(drive_folder_id: str = ""):
    fake_db.tenants.clear()
    data = dict(TENANT_A)
    data["drive_folder_id"] = drive_folder_id
    fake_db.tenants["tenant_a"] = data


# ──────────────────────────────────────
# /stage — admin-portal upload → Drive → ingest with citation
# ──────────────────────────────────────

@pytest.mark.asyncio
async def test_stage_upload_routes_via_drive_then_ingest_v2(ingest_client):
    _seed_tenant(drive_folder_id="folderABC")
    fake_upload = MagicMock(return_value={
        "id": "driveFile123",
        "name": "test.pdf",
        "webViewLink": "https://drive.google.com/file/d/driveFile123/view",
    })
    fake_v2 = AsyncMock(return_value=8)
    with patch("shared.services.gdrive.upload_file", fake_upload), \
         patch("ingest.services.ingestion_v2.ingest_v2", fake_v2):
        files = {"file": ("test.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")}
        r = await ingest_client.post(
            "/api/tenants/tenant_a/ingest/stage",
            headers=faculty_admin_headers(),
            files=files,
            data={"doc_category": "announcement"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["chunks_processed"] == 8

    # Drive upload happened with correct folder
    fake_upload.assert_called_once()
    up_args = fake_upload.call_args.args
    assert up_args[1] == "test.pdf"        # filename
    assert up_args[2] == "folderABC"       # folder_id

    # ingest_v2 called with the Drive webViewLink as download_link → citation works
    # + drive_file_id stored so admin delete survives Drive rename later
    fake_v2.assert_called_once()
    kwargs = fake_v2.call_args.kwargs
    assert kwargs["download_link"] == "https://drive.google.com/file/d/driveFile123/view"
    assert kwargs["drive_file_id"] == "driveFile123"
    assert kwargs["doc_category"] == "announcement"
    assert kwargs["namespace"] == "ns-tenant-a"


@pytest.mark.asyncio
async def test_stage_upload_requires_connected_drive_folder(ingest_client):
    _seed_tenant(drive_folder_id="")  # not connected
    with patch("shared.services.gdrive.upload_file") as fake_upload, \
         patch("ingest.services.ingestion_v2.ingest_v2") as fake_v2:
        files = {"file": ("test.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")}
        r = await ingest_client.post(
            "/api/tenants/tenant_a/ingest/stage",
            headers=faculty_admin_headers(),
            files=files,
        )
    assert r.status_code == 400
    assert "connected Drive folder" in r.json()["detail"]
    fake_upload.assert_not_called()
    fake_v2.assert_not_called()


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
         patch("shared.services.gdrive.list_files", fake_list), \
         patch("shared.services.gdrive.download_file", fake_download):
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
         patch("shared.services.gdrive.list_files", fake_list), \
         patch("shared.services.gdrive.download_file", fake_download), \
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
async def test_gdrive_scan_detects_rename(ingest_client):
    """Rename in Drive: same drive_file_id, different name → delete old vectors + re-ingest new name."""
    _seed_tenant()
    fake_v2 = AsyncMock(return_value=2)
    fake_delete = MagicMock(return_value=5)
    # Drive now has the file under a new name (same id)
    fake_list = MagicMock(return_value=[
        {"id": "file_rename", "name": "new_name.pdf",
         "mimeType": "application/pdf",
         "modifiedTime": "2026-04-20T10:00:00.000Z"},
    ])
    fake_download = MagicMock(return_value=b"%PDF-1.4")
    # Pinecone has chunks for old_name.pdf with same drive_file_id
    fake_state = MagicMock(return_value={
        "file_rename": {"filename": "old_name.pdf", "ingest_ts": 1.0},
    })
    fake_existing = MagicMock(return_value={"old_name.pdf"})
    with patch("ingest.services.ingestion_v2.ingest_v2", fake_v2), \
         patch("shared.services.gdrive.list_files", fake_list), \
         patch("shared.services.gdrive.download_file", fake_download), \
         patch("shared.services.vectorstore.get_existing_drive_state", fake_state), \
         patch("shared.services.vectorstore.delete_vectors_by_filename", fake_delete), \
         patch("ingest.routers.ingestion._get_existing_filenames", fake_existing), \
         patch("ingest.routers.ingestion.asyncio.sleep", AsyncMock()):
        r = await ingest_client.post(
            "/api/tenants/tenant_a/ingest/gdrive/scan",
            headers=faculty_admin_headers(),
            json={"folder_id": "folderid", "doc_category": "general"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    # Old filename's chunks deleted
    fake_delete.assert_called_once_with("ns-tenant-a", "old_name.pdf")
    # New filename ingested
    assert fake_v2.call_count == 1
    assert fake_v2.call_args.kwargs["filename"] == "new_name.pdf"
    assert fake_v2.call_args.kwargs["drive_file_id"] == "file_rename"
    assert len(body["ingested"]) == 1


@pytest.mark.asyncio
async def test_gdrive_scan_skips_unmodified_file(ingest_client):
    """Drive file modifiedTime ≤ Pinecone ingest_ts → skip (no-op)."""
    _seed_tenant()
    fake_v2 = AsyncMock(return_value=0)
    fake_list = MagicMock(return_value=[
        {"id": "file_stable", "name": "stable.pdf",
         "mimeType": "application/pdf",
         "modifiedTime": "2026-04-19T00:00:00.000Z"},  # older than ingest_ts
    ])
    # ingest_ts = 2026-04-20 (unix ~1776614400) — NEWER than Drive modifiedTime
    import datetime
    future_ts = datetime.datetime(2026, 4, 20, tzinfo=datetime.timezone.utc).timestamp()
    fake_state = MagicMock(return_value={
        "file_stable": {"filename": "stable.pdf", "ingest_ts": future_ts},
    })
    fake_existing = MagicMock(return_value={"stable.pdf"})
    with patch("ingest.services.ingestion_v2.ingest_v2", fake_v2), \
         patch("shared.services.gdrive.list_files", fake_list), \
         patch("shared.services.gdrive.download_file") as fake_dl, \
         patch("shared.services.vectorstore.get_existing_drive_state", fake_state), \
         patch("ingest.routers.ingestion._get_existing_filenames", fake_existing):
        r = await ingest_client.post(
            "/api/tenants/tenant_a/ingest/gdrive/scan",
            headers=faculty_admin_headers(),
            json={"folder_id": "folderid", "doc_category": "general"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    fake_v2.assert_not_called()
    fake_dl.assert_not_called()
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["reason"] == "up to date"


@pytest.mark.asyncio
async def test_gdrive_scan_detects_overwrite(ingest_client):
    """Drive file modifiedTime > Pinecone ingest_ts, same name → re-ingest."""
    _seed_tenant()
    fake_v2 = AsyncMock(return_value=3)
    fake_list = MagicMock(return_value=[
        {"id": "file_updated", "name": "doc.pdf",
         "mimeType": "application/pdf",
         "modifiedTime": "2026-04-20T12:00:00.000Z"},
    ])
    fake_state = MagicMock(return_value={
        "file_updated": {"filename": "doc.pdf", "ingest_ts": 1.0},  # very old ts
    })
    fake_existing = MagicMock(return_value={"doc.pdf"})
    fake_download = MagicMock(return_value=b"%PDF-1.4")
    with patch("ingest.services.ingestion_v2.ingest_v2", fake_v2), \
         patch("shared.services.gdrive.list_files", fake_list), \
         patch("shared.services.gdrive.download_file", fake_download), \
         patch("shared.services.vectorstore.get_existing_drive_state", fake_state), \
         patch("ingest.routers.ingestion._get_existing_filenames", fake_existing), \
         patch("ingest.routers.ingestion.asyncio.sleep", AsyncMock()):
        r = await ingest_client.post(
            "/api/tenants/tenant_a/ingest/gdrive/scan",
            headers=faculty_admin_headers(),
            json={"folder_id": "folderid", "doc_category": "general"},
        )
    assert r.status_code == 200, r.text
    # OVERWRITE triggered re-ingest (no delete call — _upsert handles dedup)
    fake_v2.assert_called_once()
    assert fake_v2.call_args.kwargs["filename"] == "doc.pdf"


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
         patch("shared.services.gdrive.list_files", fake_list), \
         patch("shared.services.gdrive.download_file", fake_download), \
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


# ──────────────────────────────────────
# _process_gdrive_folder — FAIL_COOLDOWN branch (Task 12)
# ──────────────────────────────────────

@pytest.mark.asyncio
async def test_scan_fail_cooldown_blocks_at_threshold(monkeypatch):
    """fail_count >= MAX + drive_modified <= last_drive_modified → skip without calling ingest_v2."""
    from ingest.routers import ingestion as router_mod
    from shared.services import ingest_failures as ifs

    monkeypatch.setattr(router_mod, "_get_existing_filenames", lambda ns: set())

    async def fake_list_failures(tenant_id):
        return {
            "drive_file_abc": {
                "fail_count": 3,
                "last_drive_modified": 2000.0,
            }
        }
    monkeypatch.setattr(ifs, "list_failures", fake_list_failures)

    def fake_get_state(ns):
        return {}  # no prior Pinecone entry
    monkeypatch.setattr("shared.services.vectorstore.get_existing_drive_state", fake_get_state)

    def fake_list_files(folder_id):
        return [{"id": "drive_file_abc", "name": "broken.pdf", "modifiedTime": "1970-01-01T00:33:20.000Z"}]
    monkeypatch.setattr("shared.services.gdrive.list_files", fake_list_files)

    ingest_called = {"n": 0}

    async def fake_ingest_v2(**kw):
        ingest_called["n"] += 1
        return 5
    monkeypatch.setattr("ingest.services.ingestion_v2.ingest_v2", fake_ingest_v2)

    tenant = {"tenant_id": "t", "pinecone_namespace": "ns-t"}
    result = await router_mod._process_gdrive_folder(
        tenant, folder_id="F", doc_category="general", skip_existing=True,
    )

    assert ingest_called["n"] == 0
    assert any("cooldown" in s["reason"].lower() for s in result.skipped)


@pytest.mark.asyncio
async def test_scan_fail_cooldown_unblocks_on_drive_modified_advance(monkeypatch):
    """drive_modified > last_drive_modified → cooldown lifts → ingest_v2 runs."""
    from ingest.routers import ingestion as router_mod
    from shared.services import ingest_failures as ifs

    monkeypatch.setattr(router_mod, "_get_existing_filenames", lambda ns: set())

    async def fake_list_failures(tenant_id):
        return {
            "drive_file_abc": {
                "fail_count": 3,
                "last_drive_modified": 1000.0,
            }
        }
    monkeypatch.setattr(ifs, "list_failures", fake_list_failures)
    monkeypatch.setattr("shared.services.vectorstore.get_existing_drive_state", lambda ns: {})
    monkeypatch.setattr(
        "shared.services.gdrive.list_files",
        lambda fid: [{"id": "drive_file_abc", "name": "fixed.pdf", "modifiedTime": "2020-01-01T00:00:00.000Z"}],
    )
    monkeypatch.setattr("shared.services.gdrive.download_file", lambda fid: b"%PDF-1.4\n%%EOF")

    ingest_called = {"n": 0}
    async def fake_ingest_v2(**kw):
        ingest_called["n"] += 1
        return 5
    monkeypatch.setattr("ingest.services.ingestion_v2.ingest_v2", fake_ingest_v2)

    async def noop(*a, **kw): return None
    monkeypatch.setattr(ifs, "record_failure", noop)
    monkeypatch.setattr(ifs, "clear_failure", noop)

    tenant = {"tenant_id": "t", "pinecone_namespace": "ns-t"}
    await router_mod._process_gdrive_folder(
        tenant, folder_id="F", doc_category="general", skip_existing=True,
    )

    assert ingest_called["n"] == 1


@pytest.mark.asyncio
async def test_scan_fail_count_below_threshold_ingests(monkeypatch):
    """fail_count < MAX → ingest attempted."""
    from ingest.routers import ingestion as router_mod
    from shared.services import ingest_failures as ifs

    monkeypatch.setattr(router_mod, "_get_existing_filenames", lambda ns: set())

    async def fake_list_failures(tenant_id):
        return {"drive_file_abc": {"fail_count": 2, "last_drive_modified": 9999.0}}
    monkeypatch.setattr(ifs, "list_failures", fake_list_failures)
    monkeypatch.setattr("shared.services.vectorstore.get_existing_drive_state", lambda ns: {})
    monkeypatch.setattr(
        "shared.services.gdrive.list_files",
        lambda fid: [{"id": "drive_file_abc", "name": "f.pdf", "modifiedTime": "1970-01-01T00:00:00.000Z"}],
    )
    monkeypatch.setattr("shared.services.gdrive.download_file", lambda fid: b"%PDF-1.4\n%%EOF")

    ingest_called = {"n": 0}
    async def fake_ingest_v2(**kw):
        ingest_called["n"] += 1
        return 7
    monkeypatch.setattr("ingest.services.ingestion_v2.ingest_v2", fake_ingest_v2)
    async def noop(*a, **kw): return None
    monkeypatch.setattr(ifs, "record_failure", noop)
    monkeypatch.setattr(ifs, "clear_failure", noop)

    tenant = {"tenant_id": "t", "pinecone_namespace": "ns-t"}
    await router_mod._process_gdrive_folder(
        tenant, folder_id="F", doc_category="general", skip_existing=True,
    )

    assert ingest_called["n"] == 1


# ──────────────────────────────────────
# _process_gdrive_folder — failure bookkeeping (Task 13)
# ──────────────────────────────────────

@pytest.mark.asyncio
async def test_scan_records_failure_on_zero_chunks(monkeypatch):
    from ingest.routers import ingestion as router_mod
    from shared.services import ingest_failures as ifs

    monkeypatch.setattr(router_mod, "_get_existing_filenames", lambda ns: set())
    async def empty_failures(tid): return {}
    monkeypatch.setattr(ifs, "list_failures", empty_failures)
    monkeypatch.setattr("shared.services.vectorstore.get_existing_drive_state", lambda ns: {})
    monkeypatch.setattr(
        "shared.services.gdrive.list_files",
        lambda fid: [{"id": "d", "name": "f.pdf", "modifiedTime": "2020-01-01T00:00:00.000Z"}],
    )
    monkeypatch.setattr("shared.services.gdrive.download_file", lambda fid: b"%PDF-1.4\n%%EOF")
    async def zero(**kw): return 0
    monkeypatch.setattr("ingest.services.ingestion_v2.ingest_v2", zero)

    record_calls: list = []
    async def capture(**kw): record_calls.append(kw)
    monkeypatch.setattr(ifs, "record_failure", capture)
    async def noop(*a, **kw): return None
    monkeypatch.setattr(ifs, "clear_failure", noop)

    tenant = {"tenant_id": "t", "pinecone_namespace": "ns-t"}
    result = await router_mod._process_gdrive_folder(
        tenant, folder_id="F", doc_category="general", skip_existing=True,
    )

    assert len(record_calls) == 1
    assert record_calls[0]["drive_file_id"] == "d"
    assert any(s["reason"] == "0 chunks produced" for s in result.skipped)


@pytest.mark.asyncio
async def test_scan_records_failure_on_exception(monkeypatch):
    from ingest.routers import ingestion as router_mod
    from shared.services import ingest_failures as ifs

    monkeypatch.setattr(router_mod, "_get_existing_filenames", lambda ns: set())
    async def empty_failures(tid): return {}
    monkeypatch.setattr(ifs, "list_failures", empty_failures)
    monkeypatch.setattr("shared.services.vectorstore.get_existing_drive_state", lambda ns: {})
    monkeypatch.setattr(
        "shared.services.gdrive.list_files",
        lambda fid: [{"id": "d", "name": "f.pdf", "modifiedTime": "2020-01-01T00:00:00.000Z"}],
    )
    monkeypatch.setattr("shared.services.gdrive.download_file", lambda fid: b"%PDF-1.4\n%%EOF")
    async def boom(**kw): raise RuntimeError("opus exploded")
    monkeypatch.setattr("ingest.services.ingestion_v2.ingest_v2", boom)

    record_calls: list = []
    async def capture(**kw): record_calls.append(kw)
    monkeypatch.setattr(ifs, "record_failure", capture)
    async def noop(*a, **kw): return None
    monkeypatch.setattr(ifs, "clear_failure", noop)

    tenant = {"tenant_id": "t", "pinecone_namespace": "ns-t"}
    result = await router_mod._process_gdrive_folder(
        tenant, folder_id="F", doc_category="general", skip_existing=True,
    )

    assert len(record_calls) == 1
    assert isinstance(record_calls[0]["error"], RuntimeError)
    assert len(result.errors) == 1


@pytest.mark.asyncio
async def test_scan_clears_failure_on_successful_ingest(monkeypatch):
    from ingest.routers import ingestion as router_mod
    from shared.services import ingest_failures as ifs

    monkeypatch.setattr(router_mod, "_get_existing_filenames", lambda ns: set())
    async def empty_failures(tid): return {}
    monkeypatch.setattr(ifs, "list_failures", empty_failures)
    monkeypatch.setattr("shared.services.vectorstore.get_existing_drive_state", lambda ns: {})
    monkeypatch.setattr(
        "shared.services.gdrive.list_files",
        lambda fid: [{"id": "d", "name": "f.pdf", "modifiedTime": "2020-01-01T00:00:00.000Z"}],
    )
    monkeypatch.setattr("shared.services.gdrive.download_file", lambda fid: b"%PDF-1.4\n%%EOF")
    async def good(**kw): return 7
    monkeypatch.setattr("ingest.services.ingestion_v2.ingest_v2", good)

    clear_calls: list = []
    async def capture(*a, **kw): clear_calls.append((a, kw))
    monkeypatch.setattr(ifs, "clear_failure", capture)
    async def noop(*a, **kw): return None
    monkeypatch.setattr(ifs, "record_failure", noop)

    tenant = {"tenant_id": "t", "pinecone_namespace": "ns-t"}
    await router_mod._process_gdrive_folder(
        tenant, folder_id="F", doc_category="general", skip_existing=True,
    )

    # One clear call after successful ingest
    assert len(clear_calls) == 1


@pytest.mark.asyncio
async def test_scan_skip_up_to_date_also_clears_failure(monkeypatch):
    """A stale failure doc is cleared opportunistically when we SKIP (file is fine)."""
    from ingest.routers import ingestion as router_mod
    from shared.services import ingest_failures as ifs

    monkeypatch.setattr(router_mod, "_get_existing_filenames", lambda ns: set())
    # A failure doc exists even though Pinecone says the file is fine.
    async def fake_failures(tid):
        return {"d": {"fail_count": 3, "last_drive_modified": 1.0}}
    monkeypatch.setattr(ifs, "list_failures", fake_failures)

    # Pinecone says the file is ingested and current.
    def fake_state(ns):
        return {"d": {"filename": "f.pdf", "ingest_ts": 9999999999.0}}
    monkeypatch.setattr("shared.services.vectorstore.get_existing_drive_state", fake_state)
    monkeypatch.setattr(
        "shared.services.gdrive.list_files",
        lambda fid: [{"id": "d", "name": "f.pdf", "modifiedTime": "2020-01-01T00:00:00.000Z"}],
    )

    clear_calls: list = []
    async def capture(*a, **kw): clear_calls.append((a, kw))
    monkeypatch.setattr(ifs, "clear_failure", capture)
    async def noop(*a, **kw): return None
    monkeypatch.setattr(ifs, "record_failure", noop)

    ingest_called = {"n": 0}
    async def should_not_run(**kw):
        ingest_called["n"] += 1
        return 5
    monkeypatch.setattr("ingest.services.ingestion_v2.ingest_v2", should_not_run)

    tenant = {"tenant_id": "t", "pinecone_namespace": "ns-t"}
    result = await router_mod._process_gdrive_folder(
        tenant, folder_id="F", doc_category="general", skip_existing=True,
    )

    assert ingest_called["n"] == 0  # SKIP up-to-date wins
    assert len(clear_calls) == 1  # stale doc got cleared
    assert any(s["reason"] == "up to date" for s in result.skipped)


@pytest.mark.asyncio
async def test_scan_valueerror_skips_without_recording(monkeypatch):
    """Unsupported format (ValueError) goes to skipped, NOT to ingest_failures."""
    from ingest.routers import ingestion as router_mod
    from shared.services import ingest_failures as ifs

    monkeypatch.setattr(router_mod, "_get_existing_filenames", lambda ns: set())
    async def empty_failures(tid): return {}
    monkeypatch.setattr(ifs, "list_failures", empty_failures)
    monkeypatch.setattr("shared.services.vectorstore.get_existing_drive_state", lambda ns: {})
    monkeypatch.setattr(
        "shared.services.gdrive.list_files",
        lambda fid: [{"id": "d", "name": "f.rtf", "modifiedTime": "2020-01-01T00:00:00.000Z"}],
    )
    monkeypatch.setattr("shared.services.gdrive.download_file", lambda fid: b"junk")
    async def bad_format(**kw): raise ValueError("unsupported extension '.rtf'")
    monkeypatch.setattr("ingest.services.ingestion_v2.ingest_v2", bad_format)

    record_calls: list = []
    async def capture(**kw): record_calls.append(kw)
    monkeypatch.setattr(ifs, "record_failure", capture)
    async def noop(*a, **kw): return None
    monkeypatch.setattr(ifs, "clear_failure", noop)

    tenant = {"tenant_id": "t", "pinecone_namespace": "ns-t"}
    result = await router_mod._process_gdrive_folder(
        tenant, folder_id="F", doc_category="general", skip_existing=True,
    )

    # KEY assertion: ValueError → skip, NOT record_failure
    assert len(record_calls) == 0
    assert len(result.errors) == 0
    assert any("unsupported extension" in s["reason"] for s in result.skipped)
