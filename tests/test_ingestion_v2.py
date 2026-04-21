"""Tests for ingestion v2 (Opus 4.7-first universal pipeline)."""
import pytest

from ingest.services import ingestion_v2


def test_module_imports():
    assert hasattr(ingestion_v2, "ingest_v2")
    assert hasattr(ingestion_v2, "ensure_pdf")
    assert hasattr(ingestion_v2, "extract_hyperlinks")
    assert hasattr(ingestion_v2, "opus_parse_and_chunk")


def test_ensure_pdf_passthrough_for_pdf_input():
    # Minimal valid PDF bytes (header only — PyMuPDF can still open this for a sanity round-trip).
    pdf_bytes = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
    result = ingestion_v2.ensure_pdf(pdf_bytes, "doc.pdf")
    assert result is pdf_bytes  # identity check: no copy, no re-encode


def test_ensure_pdf_invokes_libreoffice_for_docx(monkeypatch):
    """DOCX input routes through _convert_to_pdf (no real LibreOffice call)."""
    calls = {}

    def fake_convert(blob, ext):
        calls["blob"] = blob
        calls["ext"] = ext
        return b"%PDF-1.4\nconverted\n%%EOF"

    import ingest.services.ingest_helpers as v1_mod
    monkeypatch.setattr(v1_mod, "_convert_to_pdf", fake_convert)

    out = ingestion_v2.ensure_pdf(b"DOCX-fake-bytes", "form.docx")

    assert out == b"%PDF-1.4\nconverted\n%%EOF"
    assert calls["blob"] == b"DOCX-fake-bytes"
    assert calls["ext"] == ".docx"


def test_ensure_pdf_rejects_unsupported_extension():
    with pytest.raises(ValueError, match="unsupported extension"):
        ingestion_v2.ensure_pdf(b"junk", "image.jpg")


def test_extract_hyperlinks_returns_per_page_uris():
    """Synthetic PDF with one hyperlink annotation → one sidecar entry."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Click here for details")
    rect = pymupdf.Rect(72, 70, 200, 90)
    page.insert_link({"kind": pymupdf.LINK_URI, "from": rect, "uri": "https://example.org/details"})
    pdf_bytes = doc.tobytes()
    doc.close()

    links = ingestion_v2.extract_hyperlinks(pdf_bytes)

    assert len(links) == 1
    assert links[0]["page"] == 1
    assert links[0]["uri"] == "https://example.org/details"
    assert "Click here" in links[0]["text"]


def test_extract_hyperlinks_empty_pdf_returns_empty_list():
    import pymupdf

    doc = pymupdf.open()
    doc.new_page()
    pdf_bytes = doc.tobytes()
    doc.close()

    links = ingestion_v2.extract_hyperlinks(pdf_bytes)

    assert links == []


def test_extract_hyperlinks_skips_uris_already_visible_in_text():
    """URIs that already appear as visible text should not be duplicated in the sidecar.

    v2's Opus prompt tells the model that sidecar URIs are 'hidden in PDF
    annotations and NOT visible on the rendered page'. If we leak a visible
    URI into the sidecar, we break that contract and Opus emits duplicate
    markdown links.
    """
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    # The URL is written as visible text on the page.
    page.insert_text((72, 72), "Visit https://example.org/visible for details")
    # And there's also a link annotation pointing to the SAME URL.
    rect = pymupdf.Rect(72, 70, 400, 90)
    page.insert_link({
        "kind": pymupdf.LINK_URI,
        "from": rect,
        "uri": "https://example.org/visible",
    })
    # Plus a SECOND link whose URI is NOT visible in the text — this one must survive.
    rect2 = pymupdf.Rect(72, 100, 400, 120)
    page.insert_text((72, 102), "Click here for more")
    page.insert_link({
        "kind": pymupdf.LINK_URI,
        "from": rect2,
        "uri": "https://example.org/hidden",
    })
    pdf_bytes = doc.tobytes()
    doc.close()

    links = ingestion_v2.extract_hyperlinks(pdf_bytes)

    # Only the hidden one should be in the sidecar.
    assert len(links) == 1
    assert links[0]["uri"] == "https://example.org/hidden"


@pytest.mark.asyncio
async def test_opus_parse_and_chunk_happy_path(monkeypatch):
    """Mocked Opus returns a valid tool call → list of Document chunks."""
    from langchain_core.messages import AIMessage

    async def fake_ainvoke(messages):
        return AIMessage(
            content="",
            tool_calls=[{
                "name": "record_chunks",
                "args": {
                    "chunks": [
                        {"text": "chunk one body", "section_path": "Intro", "page": 1, "has_table": False},
                        {"text": "chunk two body", "section_path": "", "page": 2, "has_table": True},
                    ],
                },
                "id": "call_1",
            }],
        )

    class FakeLLM:
        def bind_tools(self, tools, tool_choice=None):
            return self

        async def ainvoke(self, messages):
            return await fake_ainvoke(messages)

    # Patch the LLM factory used by v2.
    monkeypatch.setattr(ingestion_v2, "_get_opus_llm", lambda: FakeLLM())

    pdf_bytes = b"%PDF-1.4\nminimal\n%%EOF"
    hyperlinks = [{"page": 1, "text": "ref", "uri": "https://example.org"}]

    chunks = await ingestion_v2.opus_parse_and_chunk(pdf_bytes, hyperlinks, "test.pdf")

    assert len(chunks) == 2
    assert chunks[0].page_content == "chunk one body"
    assert chunks[0].metadata["section_path"] == "Intro"
    assert chunks[0].metadata["page"] == 1
    assert chunks[0].metadata["has_table"] is False
    assert chunks[1].metadata["has_table"] is True


@pytest.mark.asyncio
async def test_opus_parse_and_chunk_filters_refusal_chunks(monkeypatch):
    """Chunks whose text matches a known refusal pattern are dropped."""
    from langchain_core.messages import AIMessage

    class FakeLLM:
        def bind_tools(self, tools, tool_choice=None):
            return self

        async def ainvoke(self, messages):
            return AIMessage(content="", tool_calls=[{
                "name": "record_chunks",
                "args": {
                    "chunks": [
                        {"text": "I cannot process this document — please re-upload.", "page": 1},
                        {"text": "real substantive content about วิทยานิพนธ์", "page": 1},
                    ],
                },
                "id": "c1",
            }])

    monkeypatch.setattr(ingestion_v2, "_get_opus_llm", lambda: FakeLLM())

    chunks = await ingestion_v2.opus_parse_and_chunk(b"%PDF-1.4\n%%EOF", [], "t.pdf")

    assert len(chunks) == 1
    assert "real substantive content" in chunks[0].page_content


@pytest.mark.asyncio
async def test_opus_parse_and_chunk_returns_empty_when_no_tool_call(monkeypatch):
    """If Opus replies without calling the tool, we return [] and do not crash."""
    from langchain_core.messages import AIMessage

    class FakeLLM:
        def bind_tools(self, tools, tool_choice=None):
            return self

        async def ainvoke(self, messages):
            # Note: no tool_calls attribute populated (model did not call the tool)
            return AIMessage(content="I have nothing to say.")

    monkeypatch.setattr(ingestion_v2, "_get_opus_llm", lambda: FakeLLM())

    chunks = await ingestion_v2.opus_parse_and_chunk(b"%PDF-1.4\n%%EOF", [], "t.pdf")

    assert chunks == []


@pytest.mark.asyncio
async def test_ingest_v2_orchestrates_pipeline(monkeypatch):
    """End-to-end: ensure_pdf → extract_hyperlinks → opus → _upsert."""
    from langchain_core.documents import Document

    calls = {}

    def fake_ensure_pdf(blob, fn):
        calls["ensure_pdf"] = (blob, fn)
        return b"%PDF-1.4\nnormalized\n%%EOF"

    def fake_extract_hyperlinks(pdf):
        calls["extract_hyperlinks"] = pdf
        return [{"page": 1, "text": "t", "uri": "https://x"}]

    async def fake_opus(pdf, links, fn):
        calls["opus"] = (pdf, links, fn)
        return [Document(page_content="body", metadata={"page": 1, "section_path": "", "has_table": False})]

    async def fake_upsert(chunks, namespace, extra_metadata):
        calls["upsert"] = {
            "chunks_len": len(chunks),
            "namespace": namespace,
            "extra_metadata": extra_metadata,
        }
        return len(chunks)

    monkeypatch.setattr(ingestion_v2, "ensure_pdf", fake_ensure_pdf)
    monkeypatch.setattr(ingestion_v2, "extract_hyperlinks", fake_extract_hyperlinks)
    monkeypatch.setattr(ingestion_v2, "opus_parse_and_chunk", fake_opus)

    import ingest.services.ingest_helpers as v1_mod
    monkeypatch.setattr(v1_mod, "_upsert", fake_upsert)

    result = await ingestion_v2.ingest_v2(
        file_bytes=b"DOCX-bytes",
        filename="form.docx",
        namespace="cutip_v2_audit",
        tenant_id="cutip_01",
        doc_category="form",
        download_link="https://drive.google.com/file/d/xyz/view",
    )

    assert result == 1
    assert calls["ensure_pdf"] == (b"DOCX-bytes", "form.docx")
    assert calls["extract_hyperlinks"] == b"%PDF-1.4\nnormalized\n%%EOF"
    assert calls["opus"][2] == "form.docx"
    assert calls["upsert"]["namespace"] == "cutip_v2_audit"
    meta = calls["upsert"]["extra_metadata"]
    assert meta["tenant_id"] == "cutip_01"
    assert meta["source_filename"] == "form.docx"
    assert meta["doc_category"] == "form"
    assert meta["source_type"] == "pdf"  # everything normalizes to pdf in v2
    assert meta["download_link"] == "https://drive.google.com/file/d/xyz/view"


def test_extract_page_text_returns_per_page_dict(tiny_text_pdf_bytes):
    result = ingestion_v2.extract_page_text(tiny_text_pdf_bytes)
    assert set(result.keys()) == {1}
    assert "hello" in result[1]


def test_extract_page_text_pure_scan_returns_all_empty(pure_scan_pdf_bytes):
    result = ingestion_v2.extract_page_text(pure_scan_pdf_bytes)
    assert set(result.keys()) == {1, 2}
    assert all(v == "" for v in result.values())
    assert sum(len(v) for v in result.values()) == 0


def test_get_ocr_client_is_cached_async_anthropic():
    from anthropic import AsyncAnthropic

    # Clear the cache from any prior test run so we verify caching in isolation.
    ingestion_v2._get_ocr_client.cache_clear()

    c1 = ingestion_v2._get_ocr_client()
    c2 = ingestion_v2._get_ocr_client()

    assert isinstance(c1, AsyncAnthropic)
    assert c1 is c2  # lru_cache returns the same instance


@pytest.mark.asyncio
async def test_ocr_pdf_pages_returns_per_page_dict(pure_scan_pdf_bytes, monkeypatch):
    """Mock anthropic client returns scripted text per page → dict[int,str]."""
    from unittest.mock import AsyncMock, MagicMock

    class FakeContentBlock:
        def __init__(self, text):
            self.type = "text"
            self.text = text

    call_count = {"n": 0}

    async def fake_create(**kwargs):
        call_count["n"] += 1
        resp = MagicMock()
        resp.content = [FakeContentBlock(f"page {call_count['n']} ocr text")]
        return resp

    fake_client = MagicMock()
    fake_client.messages = MagicMock()
    fake_client.messages.create = AsyncMock(side_effect=fake_create)

    ingestion_v2._get_ocr_client.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_ocr_client", lambda: fake_client)

    result = await ingestion_v2.ocr_pdf_pages(pure_scan_pdf_bytes, "test.pdf")

    assert set(result.keys()) == {1, 2}
    assert "ocr text" in result[1]
    assert "ocr text" in result[2]
    assert call_count["n"] == 2  # one call per page


@pytest.mark.asyncio
async def test_ocr_pdf_pages_partial_failure_returns_empty_string(pure_scan_pdf_bytes, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    class FakeContentBlock:
        def __init__(self, text):
            self.type = "text"
            self.text = text

    # First call raises; second succeeds. MagicMock's side_effect iterates.
    call_count = {"n": 0}

    async def fake_create(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated rate limit")
        resp = MagicMock()
        resp.content = [FakeContentBlock("page two ok")]
        return resp

    fake_client = MagicMock()
    fake_client.messages = MagicMock()
    fake_client.messages.create = AsyncMock(side_effect=fake_create)

    ingestion_v2._get_ocr_client.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_ocr_client", lambda: fake_client)

    result = await ingestion_v2.ocr_pdf_pages(pure_scan_pdf_bytes, "test.pdf")

    # One page failed → empty string at that key, no raise.
    assert "" in result.values()
    assert any("page two" in v for v in result.values())


@pytest.mark.asyncio
async def test_ocr_pdf_pages_all_pages_fail_raises(pure_scan_pdf_bytes, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    async def fake_create(**kwargs):
        raise RuntimeError("every call fails")

    fake_client = MagicMock()
    fake_client.messages = MagicMock()
    fake_client.messages.create = AsyncMock(side_effect=fake_create)

    ingestion_v2._get_ocr_client.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_ocr_client", lambda: fake_client)

    with pytest.raises(RuntimeError, match="OCR failed for all pages"):
        await ingestion_v2.ocr_pdf_pages(pure_scan_pdf_bytes, "test.pdf")
