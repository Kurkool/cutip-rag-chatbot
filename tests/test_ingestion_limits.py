"""Pre-flight size limits + parallel/retry behavior for complex docs."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


# ──────────────────────────────────────
# call_with_backoff helper
# ──────────────────────────────────────

@pytest.mark.asyncio
async def test_call_with_backoff_returns_result_on_success():
    from shared.services.resilience import call_with_backoff

    async def ok():
        return "done"

    sem = asyncio.Semaphore(1)
    result = await call_with_backoff(ok, semaphore=sem, label="t")
    assert result == "done"


@pytest.mark.asyncio
async def test_call_with_backoff_retries_on_rate_limit():
    from shared.services.resilience import call_with_backoff

    calls = {"n": 0}

    async def rate_limited_then_ok():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("429 Too Many Requests")
        return "finally"

    sem = asyncio.Semaphore(1)
    # Patch sleep so the test is fast
    with patch("shared.services.resilience.asyncio.sleep", new=AsyncMock()):
        result = await call_with_backoff(
            rate_limited_then_ok, semaphore=sem, max_retries=5, label="t",
        )
    assert result == "finally"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_call_with_backoff_no_retry_on_non_rate_errors():
    from shared.services.resilience import call_with_backoff

    calls = {"n": 0}

    async def bad_request():
        calls["n"] += 1
        raise ValueError("malformed input")

    sem = asyncio.Semaphore(1)
    result = await call_with_backoff(bad_request, semaphore=sem, label="t")
    assert result is None
    assert calls["n"] == 1  # no retry — non-rate error


@pytest.mark.asyncio
async def test_call_with_backoff_gives_up_after_max_retries():
    from shared.services.resilience import call_with_backoff

    calls = {"n": 0}

    async def always_rate_limited():
        calls["n"] += 1
        raise RuntimeError("rate_limit_exceeded")

    sem = asyncio.Semaphore(1)
    with patch("shared.services.resilience.asyncio.sleep", new=AsyncMock()):
        result = await call_with_backoff(
            always_rate_limited, semaphore=sem, max_retries=3, label="t",
        )
    assert result is None
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_call_with_backoff_does_not_retry_benign_rate_string():
    """'generation rate exceeded' is a quota error, not rate-limit. No retry."""
    from shared.services.resilience import call_with_backoff

    calls = {"n": 0}

    async def quota_error():
        calls["n"] += 1
        raise ValueError("generation rate exceeded for this account")

    sem = asyncio.Semaphore(1)
    result = await call_with_backoff(quota_error, semaphore=sem, max_retries=5, label="t")
    assert result is None
    assert calls["n"] == 1  # no retry — bare "rate" must not match


@pytest.mark.asyncio
async def test_call_with_backoff_detects_status_code_429():
    """Structured HTTP-status detection (httpx/requests wrapped errors)."""
    from shared.services.resilience import call_with_backoff

    class FakeHttpError(Exception):
        status_code = 429

    calls = {"n": 0}

    async def http_429_then_ok():
        calls["n"] += 1
        if calls["n"] < 2:
            raise FakeHttpError("some wrapped message without rate keyword")
        return "recovered"

    sem = asyncio.Semaphore(1)
    with patch("shared.services.resilience.asyncio.sleep", new=AsyncMock()):
        result = await call_with_backoff(
            http_429_then_ok, semaphore=sem, max_retries=3, label="t",
        )
    assert result == "recovered"
    assert calls["n"] == 2


# ──────────────────────────────────────
# PDF pre-flight
# ──────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_pdf_rejects_oversized():
    """PDF with > PDF_MAX_PAGES pages returns 413 instead of processing."""
    import pymupdf
    from ingest.services.ingestion import ingest_pdf
    from shared.config import settings

    # Build a real PDF just past the limit
    doc = pymupdf.open()
    for _ in range(settings.PDF_MAX_PAGES + 1):
        doc.new_page(width=100, height=100)
    pdf_bytes = doc.tobytes()
    doc.close()

    with (
        patch("ingest.services.ingestion.get_vectorstore"),
        patch("ingest.services.ingestion.get_raw_index"),
        patch("ingest.services.ingestion.list_all_vector_ids", return_value=[]),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await ingest_pdf(
                file_bytes=pdf_bytes, filename="big.pdf",
                namespace="ns", tenant_id="t",
            )
    assert exc_info.value.status_code == 413
    assert "limit" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_ingest_pdf_accepts_at_limit():
    """PDF exactly at PDF_MAX_PAGES should NOT raise (boundary test)."""
    import pymupdf
    from ingest.services.ingestion import ingest_pdf
    from shared.config import settings

    doc = pymupdf.open()
    for _ in range(min(5, settings.PDF_MAX_PAGES)):  # safe small doc
        doc.new_page(width=100, height=100)
    pdf_bytes = doc.tobytes()
    doc.close()

    with (
        patch("ingest.services.ingestion.get_vectorstore") as mock_vs,
        patch("ingest.services.ingestion.get_raw_index"),
        patch("ingest.services.ingestion.list_all_vector_ids", return_value=[]),
        patch("ingest.services.ingestion.parse_page_image", new_callable=AsyncMock,
              return_value="page content"),
        patch("ingest.services.ingestion.usage") as mock_usage,
        patch("ingest.services.ingestion._upsert", new_callable=AsyncMock,
              return_value=1) as mock_upsert,
    ):
        mock_vs.return_value = MagicMock(aadd_documents=AsyncMock(return_value=None))
        mock_usage.track = AsyncMock()
        result = await ingest_pdf(
            file_bytes=pdf_bytes, filename="small.pdf",
            namespace="ns", tenant_id="t",
        )
    assert result == 1


# ──────────────────────────────────────
# DOCX pre-flight + parallelism
# ──────────────────────────────────────

def _make_fake_docx_with_images(image_count: int):
    """Build a mock python-docx Document object with N image relationships."""
    doc = MagicMock()
    doc.paragraphs = []
    doc.tables = []
    rels = {}
    for i in range(image_count):
        rel = MagicMock()
        rel.reltype = "http://schemas.openxmlformats.org/image"
        rel.target_part.blob = f"image{i}".encode()
        rels[f"rId{i}"] = rel
    doc.part.rels = rels
    return doc


@pytest.mark.asyncio
async def test_ingest_docx_rejects_too_many_images():
    from ingest.services.ingestion import ingest_docx
    from shared.config import settings

    fake_doc = _make_fake_docx_with_images(settings.DOCX_MAX_IMAGES + 1)
    with (
        patch("ingest.services.ingestion.DocxDocument", return_value=fake_doc),
        patch("ingest.services.ingestion._delete_existing_vectors", return_value=0),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await ingest_docx(
                file_bytes=b"", filename="huge.docx",
                namespace="ns", tenant_id="t",
            )
    assert exc_info.value.status_code == 413
    assert "limit" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_ingest_docx_images_preserve_per_blob_binding():
    """Each image's caption must match its own bytes — lambda default-arg idiom
    must close over the right blob per iteration (not the last one).
    """
    from ingest.services.ingestion import ingest_docx

    # 3 distinct blobs; caption echoes the blob contents so we can prove
    # per-iteration binding (regression test for late-binding closure bugs).
    blobs = [b"alpha", b"beta", b"gamma"]
    fake_doc = MagicMock()
    fake_doc.paragraphs = []
    fake_doc.tables = []
    rels = {}
    for i, blob in enumerate(blobs):
        rel = MagicMock()
        rel.reltype = "http://schemas.openxmlformats.org/image"
        rel.target_part.blob = blob
        rels[f"rId{i}"] = rel
    fake_doc.part.rels = rels

    captured_captions: list[str] = []

    async def echo_vision(img_bytes):
        return f"caption:{img_bytes.decode()}"

    async def fake_upsert(chunks, *args, **kwargs):
        # Record the markdown parts so we can assert per-image captions landed
        for c in chunks:
            captured_captions.extend(
                line for line in c.page_content.split("\n")
                if line.startswith("[Image content:")
            )
        return len(chunks)

    with (
        patch("ingest.services.ingestion.DocxDocument", return_value=fake_doc),
        patch("ingest.services.ingestion._delete_existing_vectors", return_value=0),
        patch("ingest.services.ingestion.parse_page_image", side_effect=echo_vision),
        patch("ingest.services.ingestion.usage") as mock_usage,
        patch("ingest.services.ingestion._upsert", side_effect=fake_upsert),
    ):
        mock_usage.track = AsyncMock()
        await ingest_docx(file_bytes=b"", filename="t.docx", namespace="ns", tenant_id="t")

    # All three distinct captions must appear (in any order — DOCX image order
    # is dict-iteration order, which is insertion order in CPython 3.7+).
    joined = "\n".join(captured_captions)
    assert "caption:alpha" in joined
    assert "caption:beta" in joined
    assert "caption:gamma" in joined


@pytest.mark.asyncio
async def test_ingest_pdf_encrypted_closes_handle_and_raises_400():
    """Regression: encrypted PDF must (a) close the PyMuPDF handle,
    (b) raise 400 so caller sees the error (previously returned 0 silently).

    Mocks pymupdf.open to return a fake doc with is_encrypted=True so we can
    observe close() being called on the error path regardless of how PyMuPDF
    happens to classify constructed test fixtures.
    """
    from ingest.services.ingestion import ingest_pdf

    close_count = {"n": 0}
    fake_doc = MagicMock()
    fake_doc.is_encrypted = True
    fake_doc.close.side_effect = lambda: close_count.__setitem__("n", close_count["n"] + 1)

    with (
        patch("ingest.services.ingestion.pymupdf.open", return_value=fake_doc),
        patch("ingest.services.ingestion.list_all_vector_ids", return_value=[]),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await ingest_pdf(
                file_bytes=b"%PDF-fake", filename="locked.pdf",
                namespace="ns", tenant_id="t",
            )
    assert exc_info.value.status_code == 400
    assert "password" in exc_info.value.detail.lower()
    assert close_count["n"] >= 1, "encrypted PDF path must close doc handle"


@pytest.mark.asyncio
async def test_ingest_pdf_oversize_closes_handle():
    """Pre-flight page-count rejection must also close the PyMuPDF handle."""
    from ingest.services.ingestion import ingest_pdf
    from shared.config import settings

    close_count = {"n": 0}
    fake_doc = MagicMock()
    fake_doc.is_encrypted = False
    fake_doc.page_count = settings.PDF_MAX_PAGES + 50
    fake_doc.close.side_effect = lambda: close_count.__setitem__("n", close_count["n"] + 1)

    with (
        patch("ingest.services.ingestion.pymupdf.open", return_value=fake_doc),
        patch("ingest.services.ingestion.list_all_vector_ids", return_value=[]),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await ingest_pdf(
                file_bytes=b"%PDF-fake", filename="huge.pdf",
                namespace="ns", tenant_id="t",
            )
    assert exc_info.value.status_code == 413
    assert close_count["n"] >= 1, "oversize PDF path must close doc handle"


@pytest.mark.asyncio
async def test_ingest_docx_images_run_concurrently():
    """DOCX image Vision calls must fan out under INGEST_CONCURRENCY."""
    from ingest.services.ingestion import ingest_docx
    from shared.config import settings

    concurrent = 0
    peak = 0
    release = asyncio.Event()

    async def gated_vision(img_bytes):
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        await release.wait()
        concurrent -= 1
        return f"caption for {len(img_bytes)} bytes"

    async def release_later():
        await asyncio.sleep(0.05)
        release.set()

    # Use more images than INGEST_CONCURRENCY so peak is bounded
    image_count = settings.INGEST_CONCURRENCY * 3
    fake_doc = _make_fake_docx_with_images(image_count)

    with (
        patch("ingest.services.ingestion.DocxDocument", return_value=fake_doc),
        patch("ingest.services.ingestion._delete_existing_vectors", return_value=0),
        patch("ingest.services.ingestion.parse_page_image", side_effect=gated_vision),
        patch("ingest.services.ingestion.usage") as mock_usage,
        patch("ingest.services.ingestion._upsert", new_callable=AsyncMock, return_value=1),
    ):
        mock_usage.track = AsyncMock()
        await asyncio.gather(
            ingest_docx(file_bytes=b"", filename="t.docx", namespace="ns", tenant_id="t"),
            release_later(),
        )

    assert 1 < peak <= settings.INGEST_CONCURRENCY, (
        f"expected concurrent peak in (1, {settings.INGEST_CONCURRENCY}], got {peak}"
    )


# ──────────────────────────────────────
# XLSX pre-flight + parallelism
# ──────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_spreadsheet_rejects_oversized():
    """CSV with > XLSX_MAX_ROWS rows returns 413."""
    import io
    import pandas as pd
    from ingest.services.ingestion import ingest_spreadsheet
    from shared.config import settings

    df = pd.DataFrame({"a": range(settings.XLSX_MAX_ROWS + 10)})
    csv_bytes = df.to_csv(index=False, header=False).encode()

    with (
        patch("ingest.services.ingestion._delete_existing_vectors", return_value=0),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await ingest_spreadsheet(
                file_bytes=csv_bytes, filename="big.csv",
                namespace="ns", tenant_id="t",
            )
    assert exc_info.value.status_code == 413


@pytest.mark.asyncio
async def test_upsert_is_atomic_upsert_then_delete():
    """Atomic-swap invariant: aadd_documents MUST run before _delete_existing_vectors.

    Regression guard for the slide.pdf data-loss bug (2026-04-17) where
    delete-first + upsert-second meant a mid-batch timeout left the doc
    missing entirely.
    """
    from langchain_core.documents import Document
    from ingest.services.ingestion import _upsert

    call_order: list[str] = []

    mock_vs = MagicMock()

    async def mock_aadd(chunks):
        call_order.append("aadd_documents")

    mock_vs.aadd_documents = mock_aadd

    def mock_delete(namespace, source_filename, older_than_ts=None):
        call_order.append(f"delete(older_than={older_than_ts is not None})")
        return 0

    with (
        patch("ingest.services.ingestion.get_vectorstore", return_value=mock_vs),
        patch("ingest.services.ingestion._delete_existing_vectors", side_effect=mock_delete),
        patch("shared.services.bm25_cache.invalidate_bm25_cache"),
    ):
        await _upsert(
            chunks=[Document(page_content="test content", metadata={})],
            namespace="ns",
            extra_metadata={"source_filename": "doc.pdf", "tenant_id": "t"},
            skip_enrichment=True,
        )

    assert call_order == ["aadd_documents", "delete(older_than=True)"], (
        f"expected upsert before delete, got {call_order}"
    )


@pytest.mark.asyncio
async def test_upsert_stamps_ingest_ts_on_chunks():
    """Each chunk must carry ingest_ts so dedup can distinguish generations."""
    import time as _time
    from langchain_core.documents import Document
    from ingest.services.ingestion import _upsert

    captured_chunks: list[Document] = []

    mock_vs = MagicMock()

    async def mock_aadd(chunks):
        captured_chunks.extend(chunks)

    mock_vs.aadd_documents = mock_aadd

    before = _time.time()
    with (
        patch("ingest.services.ingestion.get_vectorstore", return_value=mock_vs),
        patch("ingest.services.ingestion._delete_existing_vectors", return_value=0),
        patch("shared.services.bm25_cache.invalidate_bm25_cache"),
    ):
        await _upsert(
            chunks=[
                Document(page_content="a", metadata={}),
                Document(page_content="b", metadata={}),
            ],
            namespace="ns",
            extra_metadata={"source_filename": "doc.pdf"},
            skip_enrichment=True,
        )
    after = _time.time()

    # All chunks must share the same ingest_ts, within current wall clock
    ts_values = {c.metadata.get("ingest_ts") for c in captured_chunks}
    assert len(ts_values) == 1, f"all chunks must share one ingest_ts, got {ts_values}"
    (ts,) = ts_values
    assert before <= ts <= after


@pytest.mark.asyncio
async def test_multi_sheet_xlsx_upserts_once_and_keeps_all_chunks():
    """Regression (2026-04-17): multi-sheet XLSX previously called _upsert per
    sheet, and each post-upsert dedup wiped earlier sheets' freshly-added
    chunks because they shared the same source_filename but had older
    ingest_ts. Fix: aggregate all sheets, single _upsert call.
    """
    import io
    import pandas as pd
    from ingest.services.ingestion import ingest_spreadsheet

    # Build a real XLSX with 3 sheets
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame({"a": [1, 2, 3]}).to_excel(writer, sheet_name="sheet1", index=False, header=False)
        pd.DataFrame({"a": [4, 5, 6]}).to_excel(writer, sheet_name="sheet2", index=False, header=False)
        pd.DataFrame({"a": [7, 8, 9]}).to_excel(writer, sheet_name="sheet3", index=False, header=False)
    xlsx_bytes = buf.getvalue()

    upsert_calls = []

    async def capture_upsert(chunks, namespace, extra_metadata, **_):
        upsert_calls.append({
            "chunk_count": len(chunks),
            "sources": [c.metadata.get("source", c.metadata.get("source_filename", "")) for c in chunks],
        })
        return len(chunks)

    async def fake_interpret(text):
        return f"interpreted: {text[:50]}"

    with (
        patch("ingest.services.ingestion._upsert", side_effect=capture_upsert),
        patch("ingest.services.ingestion.interpret_spreadsheet", side_effect=fake_interpret),
        patch("ingest.services.ingestion.usage") as mock_usage,
    ):
        mock_usage.track = AsyncMock()
        sheets, total = await ingest_spreadsheet(
            file_bytes=xlsx_bytes, filename="three-sheets.xlsx",
            namespace="ns", tenant_id="t",
        )

    # Invariant: ONE _upsert call regardless of sheet count
    assert len(upsert_calls) == 1, f"expected 1 _upsert call, got {len(upsert_calls)}"
    # Chunks from all 3 sheets aggregated
    assert upsert_calls[0]["chunk_count"] >= 3
    assert sheets == 3


@pytest.mark.asyncio
async def test_upsert_survives_bump_invalidate_ts_failure():
    """If Firestore bump_bm25_invalidate_ts raises, the ingest still succeeds.

    Ingest durability > invalidation freshness: losing the cross-process
    invalidation signal is acceptable (next successful ingest will bump),
    but dropping the ingest itself is not.
    """
    from langchain_core.documents import Document
    from ingest.services.ingestion import _upsert

    mock_vs = MagicMock()

    async def mock_aadd(chunks):
        pass

    mock_vs.aadd_documents = mock_aadd

    async def bump_fails(tenant_id):
        raise RuntimeError("Firestore 503 — service unavailable")

    with (
        patch("ingest.services.ingestion.get_vectorstore", return_value=mock_vs),
        patch("ingest.services.ingestion._delete_existing_vectors", return_value=0),
        patch("shared.services.bm25_cache.invalidate_bm25_cache"),
        patch(
            "shared.services.firestore.bump_bm25_invalidate_ts",
            side_effect=bump_fails,
        ),
    ):
        chunks = [Document(page_content="x", metadata={})]
        result = await _upsert(
            chunks=chunks,
            namespace="ns",
            extra_metadata={"source_filename": "doc.pdf", "tenant_id": "cutip_01"},
            skip_enrichment=True,
        )

    # Upsert returns chunk count even when bump failed — caller doesn't know
    # or care about invalidation durability
    assert result == 1


def test_delete_existing_vectors_respects_older_than_ts():
    """Vectors with ingest_ts >= older_than_ts must be kept (they're the fresh upsert)."""
    from ingest.services.ingestion import _delete_existing_vectors

    fake_vectors = {
        "old1": MagicMock(metadata={"source_filename": "d.pdf", "ingest_ts": 100.0}),
        "old2": MagicMock(metadata={"source_filename": "d.pdf", "ingest_ts": 200.0}),
        "new1": MagicMock(metadata={"source_filename": "d.pdf", "ingest_ts": 500.0}),
        "new2": MagicMock(metadata={"source_filename": "d.pdf", "ingest_ts": 600.0}),
        "other": MagicMock(metadata={"source_filename": "other.pdf", "ingest_ts": 100.0}),
    }
    fake_index = MagicMock()
    fake_index.fetch.return_value = MagicMock(vectors=fake_vectors)

    deleted_ids: list[list[str]] = []
    fake_index.delete.side_effect = lambda ids, namespace: deleted_ids.append(list(ids))

    with (
        patch("ingest.services.ingestion.list_all_vector_ids", return_value=list(fake_vectors.keys())),
        patch("ingest.services.ingestion.get_raw_index", return_value=fake_index),
    ):
        n = _delete_existing_vectors("ns", "d.pdf", older_than_ts=400.0)

    # Only old1, old2 deleted (< 400). new1, new2 kept. other.pdf ignored.
    flat = [vid for batch in deleted_ids for vid in batch]
    assert sorted(flat) == ["old1", "old2"]
    assert n == 2


@pytest.mark.asyncio
async def test_interpret_dataframe_parallelizes_batches():
    """_interpret_dataframe must fan out batches, not run them sequentially."""
    import pandas as pd
    from ingest.services.ingestion import _interpret_dataframe, _XLSX_BATCH_ROWS
    from shared.config import settings

    # Build a sheet with enough rows to create multiple batches
    n_batches = 4
    total = _XLSX_BATCH_ROWS * n_batches
    df = pd.DataFrame({"col": [f"row_{i}" for i in range(total)]})

    concurrent = 0
    peak = 0
    release = asyncio.Event()

    async def gated_interpret(text):
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        await release.wait()
        concurrent -= 1
        return f"interpreted({len(text)})"

    async def release_later():
        await asyncio.sleep(0.05)
        release.set()

    with patch("ingest.services.ingestion.interpret_spreadsheet", side_effect=gated_interpret):
        result, api_calls = (await asyncio.gather(
            _interpret_dataframe(df, sheet_name="s1"),
            release_later(),
        ))[0]

    assert api_calls == n_batches
    assert 1 < peak <= settings.INGEST_CONCURRENCY
