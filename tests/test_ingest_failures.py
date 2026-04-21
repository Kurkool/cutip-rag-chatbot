"""Tests for shared.services.ingest_failures (Firestore collection wrapper)."""
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_record_failure_creates_doc_on_first_call(monkeypatch):
    """First call writes a new doc with fail_count=1 and first_failed_at set."""
    from shared.services import ingest_failures as ifs

    fake_doc_ref = MagicMock()
    fake_col = MagicMock()
    fake_col.document = MagicMock(return_value=fake_doc_ref)
    fake_client = MagicMock()
    fake_client.collection = MagicMock(return_value=fake_col)

    ifs._get_client.cache_clear()
    monkeypatch.setattr(ifs, "_get_client", lambda: fake_client)

    await ifs.record_failure(
        tenant_id="tenant_a",
        drive_file_id="abc123",
        filename="x.pdf",
        drive_modified=1700000000.0,
        error="test error",
    )

    fake_client.collection.assert_called_with("ingest_failures")
    fake_col.document.assert_called_with("tenant_a__abc123")
    # .set called with merge=True
    assert fake_doc_ref.set.called
    args, kwargs = fake_doc_ref.set.call_args
    payload = args[0]
    assert payload["tenant_id"] == "tenant_a"
    assert payload["drive_file_id"] == "abc123"
    assert payload["filename"] == "x.pdf"
    assert payload["last_drive_modified"] == 1700000000.0
    assert "test error" in payload["last_error_short"]
    # Use merge=True so first_failed_at not clobbered on subsequent calls
    assert kwargs.get("merge") is True


@pytest.mark.asyncio
async def test_record_failure_uses_firestore_increment_for_fail_count(monkeypatch):
    from google.cloud import firestore
    from shared.services import ingest_failures as ifs

    fake_doc_ref = MagicMock()
    fake_col = MagicMock(document=MagicMock(return_value=fake_doc_ref))
    fake_client = MagicMock(collection=MagicMock(return_value=fake_col))
    ifs._get_client.cache_clear()
    monkeypatch.setattr(ifs, "_get_client", lambda: fake_client)

    await ifs.record_failure(
        tenant_id="t", drive_file_id="d", filename="x.pdf",
        drive_modified=1.0, error="e",
    )

    payload = fake_doc_ref.set.call_args[0][0]
    assert isinstance(payload["fail_count"], firestore.Increment)
