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
