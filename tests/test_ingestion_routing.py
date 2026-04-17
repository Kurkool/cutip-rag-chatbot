"""Regression tests for the 2026-04-17 Vision-OCR-vs-text-layer routing fix.

Root cause: the announcement PDF with 23 Thai person names had a table on
every page → old routing kicked every page into Haiku Vision → 23/23 names
dropped, Vision error strings stored as content. Fix: prefer text layer +
PyMuPDF table markdown when text is substantial; filter Vision refusal
strings when Vision IS used.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_looks_like_refusal_catches_common_vision_errors():
    from ingest.services.vision import _looks_like_refusal
    assert _looks_like_refusal("Could you please re-upload the document") is True
    assert _looks_like_refusal("Ensure the image is clear and contains visible content") is True
    assert _looks_like_refusal("There is no visible text, tables, forms to convert") is True
    assert _looks_like_refusal("Once you provide a readable document, I'll be happy") is True
    assert _looks_like_refusal("") is False
    # Real OCR output must pass through
    assert _looks_like_refusal("2. นายเกื้อกูล อัศวาดิศยางกูร 6780016820") is False


def test_extract_text_blocks_handles_opus_47_shape():
    """Opus 4.7 adaptive thinking returns list-of-blocks — must extract text."""
    from ingest.services.vision import _extract_text_blocks
    # Opus 4.7 shape
    blocks = [
        {"type": "thinking", "thinking": "planning the OCR..."},
        {"type": "text", "text": "# หัวข้อ\nสวัสดี"},
    ]
    assert _extract_text_blocks(blocks) == "# หัวข้อ\nสวัสดี"
    # String shape (older models / simple responses)
    assert _extract_text_blocks("raw markdown here") == "raw markdown here"
    # Empty / None
    assert _extract_text_blocks(None) == ""
    assert _extract_text_blocks("") == ""


@pytest.mark.asyncio
async def test_parse_page_image_drops_refusal_response():
    """A Vision model returning "Could you please re-upload" must NOT be
    stored as chunk text — return empty string instead.
    """
    from ingest.services import vision

    response = MagicMock()
    response.content = "Could you please re-upload the document image?"

    with patch.object(vision, "_get_vision_llm") as mock_llm:
        mock_llm.return_value.ainvoke = AsyncMock(return_value=response)
        result = await vision.parse_page_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    assert result == ""


@pytest.mark.asyncio
async def test_parse_page_image_passes_through_real_ocr():
    """Genuine OCR output with Thai names must NOT be filtered."""
    from ingest.services import vision

    response = MagicMock()
    response.content = "2. นายเกื้อกูล อัศวาดิศยางกูร\nหัวข้อ RAG chatbot"

    with patch.object(vision, "_get_vision_llm") as mock_llm:
        mock_llm.return_value.ainvoke = AsyncMock(return_value=response)
        result = await vision.parse_page_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    assert "เกื้อกูล" in result


@pytest.mark.asyncio
async def test_parse_page_image_extracts_opus_47_thinking_blocks():
    """Opus 4.7 returns list-of-blocks; upstream must extract text only."""
    from ingest.services import vision

    response = MagicMock()
    response.content = [
        {"type": "thinking", "thinking": "..."},
        {"type": "text", "text": "2. นายเกื้อกูล อัศวาดิศยางกูร"},
    ]

    with patch.object(vision, "_get_vision_llm") as mock_llm:
        mock_llm.return_value.ainvoke = AsyncMock(return_value=response)
        result = await vision.parse_page_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    assert "เกื้อกูล" in result
    assert "thinking" not in result
