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

    import ingest.services.ingestion as v1_mod
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
