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
async def test_ingest_v2_orchestrates_pipeline(monkeypatch):
    """End-to-end: ensure_pdf → extract_hyperlinks → opus → _upsert."""
    from langchain_core.documents import Document

    calls = {}

    def fake_ensure_pdf(blob, fn):
        calls["ensure_pdf"] = (blob, fn)
        return b"%PDF-1.4\nnormalized\n%%EOF"

    def fake_extract_page_text(pdf):
        # Return non-empty text so the OCR path is NOT triggered.
        return {1: "some text content"}

    def fake_extract_hyperlinks(pdf):
        calls["extract_hyperlinks"] = pdf
        return [{"page": 1, "text": "t", "uri": "https://x"}]

    async def fake_opus(pdf, links, fn, mode):
        calls["opus"] = (pdf, links, fn, mode)
        return [Document(page_content="body", metadata={"page": 1, "section_path": "", "has_table": False})]

    async def fake_upsert(chunks, namespace, extra_metadata):
        calls["upsert"] = {
            "chunks_len": len(chunks),
            "namespace": namespace,
            "extra_metadata": extra_metadata,
        }
        return len(chunks)

    monkeypatch.setattr(ingestion_v2, "ensure_pdf", fake_ensure_pdf)
    monkeypatch.setattr(ingestion_v2, "extract_page_text", fake_extract_page_text)
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
    assert calls["opus"][3] == "document"  # tiny text content → document mode
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


def test_extract_json_from_fence_parses_basic_fence():
    text = """some chatter
```json
{"chunks": [{"text": "a", "page": 1}]}
```
trailing prose"""
    result = ingestion_v2._extract_json_from_fence(text)
    assert result == {"chunks": [{"text": "a", "page": 1}]}


def test_extract_json_from_fence_parses_bare_json_with_prose():
    text = 'Here is the result: {"chunks": [{"text": "alpha", "page": 1}]} done.'
    result = ingestion_v2._extract_json_from_fence(text)
    assert result == {"chunks": [{"text": "alpha", "page": 1}]}


def test_extract_json_from_fence_returns_none_on_malformed():
    text = "```json\nthis is not json at all\n```"
    assert ingestion_v2._extract_json_from_fence(text) is None


def test_extract_json_from_fence_returns_none_on_empty():
    assert ingestion_v2._extract_json_from_fence("") is None
    assert ingestion_v2._extract_json_from_fence(None) is None


def test_text_from_response_handles_string_content():
    from unittest.mock import MagicMock
    fake = MagicMock()
    fake.content = "hello world"
    assert ingestion_v2._text_from_response(fake) == "hello world"


def test_text_from_response_concatenates_text_blocks_only():
    from unittest.mock import MagicMock
    fake = MagicMock()
    fake.content = [
        {"type": "thinking", "thinking": "internal monologue"},  # ignored
        {"type": "text", "text": "first"},
        {"type": "text", "text": "second"},
    ]
    assert ingestion_v2._text_from_response(fake) == "first\nsecond"


def test_pdf_to_image_blocks_returns_image_block_per_page():
    """3-page PDF → 3 image blocks, each base64 PNG with media_type=image/png."""
    import pymupdf

    doc = pymupdf.open()
    for _ in range(3):
        page = doc.new_page()
        page.insert_text((72, 72), "hello")
    pdf_bytes = doc.tobytes()
    doc.close()

    blocks = ingestion_v2._pdf_to_image_blocks(pdf_bytes)

    assert len(blocks) == 3
    for b in blocks:
        assert b["type"] == "image"
        assert b["source"]["type"] == "base64"
        assert b["source"]["media_type"] == "image/png"
        assert isinstance(b["source"]["data"], str)
        assert len(b["source"]["data"]) > 0


def test_pdf_to_image_blocks_raises_on_over_100_pages():
    """Anthropic limit is 100 image blocks per request; surface a clear error."""
    import pymupdf
    import pytest

    doc = pymupdf.open()
    for _ in range(101):
        doc.new_page()
    pdf_bytes = doc.tobytes()
    doc.close()

    with pytest.raises(ValueError, match="exceeds Anthropic's 100-image limit"):
        ingestion_v2._pdf_to_image_blocks(pdf_bytes)


def test_user_prompt_template_drops_ocr_block_placeholder():
    from ingest.services._v2_prompts import USER_PROMPT_TEMPLATE
    assert "{filename}" in USER_PROMPT_TEMPLATE
    assert "{sidecar_block}" in USER_PROMPT_TEMPLATE
    assert "{ocr_block}" not in USER_PROMPT_TEMPLATE


def test_system_prompt_instructs_json_fence_output():
    from ingest.services._v2_prompts import SYSTEM_PROMPT
    assert "```json" in SYSTEM_PROMPT
    # tool_call language must be gone
    assert "record_chunks" not in SYSTEM_PROMPT
    # escape hatch
    assert "[page" in SYSTEM_PROMPT and "unreadable]" in SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_opus_parse_and_chunk_images_mode_omits_document_block(
    monkeypatch, pure_scan_pdf_bytes
):
    """mode='images' → content blocks include image type and exclude document type."""
    from langchain_core.messages import AIMessage
    from unittest.mock import AsyncMock, MagicMock

    captured = {}

    async def fake_ainvoke(messages):
        captured["content"] = messages[1].content
        return AIMessage(content='```json\n{"chunks": []}\n```')

    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(side_effect=fake_ainvoke)

    ingestion_v2._get_opus_llm.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_opus_llm", lambda: fake_llm)

    await ingestion_v2.opus_parse_and_chunk(
        pdf_bytes=pure_scan_pdf_bytes,
        hyperlinks=[],
        filename="x.pdf",
        mode="images",
    )

    types = [b.get("type") for b in captured["content"]]
    assert "image" in types
    assert "document" not in types


@pytest.mark.asyncio
async def test_opus_parse_and_chunk_document_mode_includes_document_block(
    monkeypatch, tiny_text_pdf_bytes
):
    """mode='document' → content blocks include document + text."""
    from langchain_core.messages import AIMessage
    from unittest.mock import AsyncMock, MagicMock

    captured = {}

    async def fake_ainvoke(messages):
        captured["content"] = messages[1].content
        return AIMessage(content='```json\n{"chunks": []}\n```')

    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(side_effect=fake_ainvoke)

    ingestion_v2._get_opus_llm.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_opus_llm", lambda: fake_llm)

    await ingestion_v2.opus_parse_and_chunk(
        pdf_bytes=tiny_text_pdf_bytes,
        hyperlinks=[],
        filename="x.pdf",
        mode="document",
    )

    types = [b.get("type") for b in captured["content"]]
    assert types == ["document", "text"]


@pytest.mark.asyncio
async def test_opus_parse_and_chunk_returns_chunks_from_json_fence(
    monkeypatch, tiny_text_pdf_bytes
):
    """Chunks parsed from JSON fence are returned as Documents with metadata."""
    from langchain_core.messages import AIMessage
    from unittest.mock import AsyncMock, MagicMock

    payload = (
        '```json\n'
        '{"chunks": ['
        '{"text": "alpha", "page": 1, "section_path": "Intro", "has_table": false},'
        '{"text": "beta", "page": 2, "section_path": "", "has_table": true}'
        ']}\n'
        '```'
    )

    async def fake_ainvoke(messages):
        return AIMessage(content=payload)

    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(side_effect=fake_ainvoke)

    ingestion_v2._get_opus_llm.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_opus_llm", lambda: fake_llm)

    chunks = await ingestion_v2.opus_parse_and_chunk(
        pdf_bytes=tiny_text_pdf_bytes,
        hyperlinks=[],
        filename="x.pdf",
        mode="document",
    )

    assert len(chunks) == 2
    assert chunks[0].page_content == "alpha"
    assert chunks[0].metadata == {"page": 1, "section_path": "Intro", "has_table": False}
    assert chunks[1].metadata["has_table"] is True


@pytest.mark.asyncio
async def test_opus_parse_and_chunk_returns_empty_on_no_json_fence(
    monkeypatch, tiny_text_pdf_bytes
):
    """If Opus replies with prose (no JSON fence) we return [] and log a warning."""
    from langchain_core.messages import AIMessage
    from unittest.mock import AsyncMock, MagicMock

    async def fake_ainvoke(messages):
        return AIMessage(content="I cannot read this document clearly.")

    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(side_effect=fake_ainvoke)

    ingestion_v2._get_opus_llm.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_opus_llm", lambda: fake_llm)

    chunks = await ingestion_v2.opus_parse_and_chunk(
        pdf_bytes=tiny_text_pdf_bytes,
        hyperlinks=[],
        filename="x.pdf",
        mode="document",
    )

    assert chunks == []


@pytest.mark.asyncio
async def test_opus_parse_and_chunk_filters_unreadable_escape_hatch(
    monkeypatch, tiny_text_pdf_bytes
):
    """Chunks of the form [page N: unreadable] are filtered out."""
    from langchain_core.messages import AIMessage
    from unittest.mock import AsyncMock, MagicMock

    payload = (
        '```json\n{"chunks": ['
        '{"text": "[page 3: unreadable]", "page": 3, "section_path": "", "has_table": false},'
        '{"text": "real content", "page": 4, "section_path": "", "has_table": false}'
        ']}\n```'
    )

    async def fake_ainvoke(messages):
        return AIMessage(content=payload)

    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(side_effect=fake_ainvoke)

    ingestion_v2._get_opus_llm.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_opus_llm", lambda: fake_llm)

    chunks = await ingestion_v2.opus_parse_and_chunk(
        pdf_bytes=tiny_text_pdf_bytes,
        hyperlinks=[],
        filename="x.pdf",
        mode="document",
    )

    assert len(chunks) == 1
    assert chunks[0].page_content == "real content"


@pytest.mark.asyncio
async def test_opus_parse_and_chunk_invalid_mode_raises(tiny_text_pdf_bytes):
    import pytest
    with pytest.raises(ValueError, match="unknown mode"):
        await ingestion_v2.opus_parse_and_chunk(
            pdf_bytes=tiny_text_pdf_bytes,
            hyperlinks=[],
            filename="x.pdf",
            mode="bogus",
        )


@pytest.mark.asyncio
async def test_opus_parse_and_chunk_keeps_chunks_starting_with_page_word(
    monkeypatch, tiny_text_pdf_bytes
):
    """Ensure the escape-hatch filter doesn't false-positive on legitimate content."""
    from langchain_core.messages import AIMessage
    from unittest.mock import AsyncMock, MagicMock

    payload = (
        '```json\n{"chunks": ['
        '{"text": "[page heading describing unreadable historical text]", "page": 1, "section_path": "", "has_table": false},'
        '{"text": "[page 5: unreadable]", "page": 5, "section_path": "", "has_table": false}'
        ']}\n```'
    )

    async def fake_ainvoke(messages):
        return AIMessage(content=payload)

    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(side_effect=fake_ainvoke)

    ingestion_v2._get_opus_llm.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_opus_llm", lambda: fake_llm)

    chunks = await ingestion_v2.opus_parse_and_chunk(
        pdf_bytes=tiny_text_pdf_bytes,
        hyperlinks=[],
        filename="x.pdf",
        mode="document",
    )

    # Only the legitimate "starting-with-[page" chunk survives
    # The actual [page 5: unreadable] sentinel is filtered.
    assert len(chunks) == 1
    assert "[page heading" in chunks[0].page_content


@pytest.mark.asyncio
async def test_ingest_v2_pure_scan_routes_to_images_mode(monkeypatch, pure_scan_pdf_bytes):
    """A PDF with empty text layer must dispatch opus_parse_and_chunk(mode='images')."""
    captured = {}

    async def fake_opus(pdf, links, fn, mode):
        captured["mode"] = mode
        return []

    monkeypatch.setattr(ingestion_v2, "opus_parse_and_chunk", fake_opus)

    await ingestion_v2.ingest_v2(
        file_bytes=pure_scan_pdf_bytes,
        filename="scan.pdf",
        namespace="ns-test",
        tenant_id="t",
    )

    assert captured["mode"] == "images"


@pytest.mark.asyncio
async def test_ingest_v2_text_layer_routes_to_document_mode(monkeypatch, tiny_text_pdf_bytes):
    """A PDF with non-empty text layer must dispatch opus_parse_and_chunk(mode='document')."""
    captured = {}

    async def fake_opus(pdf, links, fn, mode):
        captured["mode"] = mode
        return []

    monkeypatch.setattr(ingestion_v2, "opus_parse_and_chunk", fake_opus)

    await ingestion_v2.ingest_v2(
        file_bytes=tiny_text_pdf_bytes,
        filename="text.pdf",
        namespace="ns-test",
        tenant_id="t",
    )

    assert captured["mode"] == "document"
