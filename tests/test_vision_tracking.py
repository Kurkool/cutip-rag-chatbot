"""Test that vision calls during ingestion are tracked in usage logs."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_ingest_pdf_tracks_vision_calls():
    """When PDF pages use vision (low text), usage.track is called."""
    with (
        patch("services.ingestion.get_vectorstore") as mock_vs,
        patch("services.ingestion.get_raw_index") as mock_idx,
        patch("services.ingestion.parse_page_image", new_callable=AsyncMock) as mock_vision,
        patch("services.ingestion.usage") as mock_usage,
    ):
        mock_vs.return_value = MagicMock(
            aadd_documents=AsyncMock(return_value=None)
        )
        mock_idx.return_value = MagicMock(
            list=MagicMock(return_value=MagicMock(vectors=[])),
        )
        mock_vision.return_value = "# Parsed content from vision"
        mock_usage.track = AsyncMock()

        from services.ingestion import ingest_pdf

        # Minimal 1-page blank PDF → triggers vision (no text)
        import pymupdf
        doc = pymupdf.open()
        doc.new_page(width=200, height=200)
        pdf_bytes = doc.tobytes()
        doc.close()

        await ingest_pdf(
            file_bytes=pdf_bytes,
            filename="test.pdf",
            namespace="test_ns",
            tenant_id="tenant_a",
        )

        # Vision was called for the blank page
        assert mock_vision.call_count >= 1
        # Usage tracking called with correct tenant and call type
        mock_usage.track.assert_any_call("tenant_a", "vision_call", 1)


@pytest.mark.asyncio
async def test_ingest_csv_tracks_vision_calls():
    """CSV ingestion uses interpret_spreadsheet which is a vision call."""
    with (
        patch("services.ingestion.get_vectorstore") as mock_vs,
        patch("services.ingestion.get_raw_index") as mock_idx,
        patch("services.ingestion.interpret_spreadsheet", new_callable=AsyncMock) as mock_interpret,
        patch("services.ingestion.usage") as mock_usage,
    ):
        mock_vs.return_value = MagicMock(
            aadd_documents=AsyncMock(return_value=None)
        )
        mock_idx.return_value = MagicMock(
            list=MagicMock(return_value=MagicMock(vectors=[])),
        )
        mock_interpret.return_value = "# Sheet interpretation"
        mock_usage.track = AsyncMock()

        from services.ingestion import ingest_spreadsheet

        csv_bytes = b"Name,Score\nAlice,95\nBob,87\n"

        sheets, chunks = await ingest_spreadsheet(
            file_bytes=csv_bytes,
            filename="test.csv",
            namespace="test_ns",
            tenant_id="tenant_a",
        )

        assert sheets == 1
        mock_interpret.assert_called_once()
        mock_usage.track.assert_any_call("tenant_a", "vision_call", 1)
