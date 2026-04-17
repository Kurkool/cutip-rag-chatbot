"""Ingestion v2: Opus 4.7-first universal pipeline.

Replaces v1's 5 format-specific paths (PDF/DOCX/XLSX/legacy/markdown)
with one path: any file → PDF → Opus parse+chunk → reuse _upsert.

See docs/superpowers/specs/2026-04-18-ingest-v2-design.md for design.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from langchain_core.documents import Document

logger = logging.getLogger(__name__)


def ensure_pdf(file_bytes: bytes, filename: str) -> bytes:
    """Normalize any supported input to PDF bytes.

    PDF inputs are passed through untouched (byte-identity preserved).
    DOCX/XLSX/PPT and their legacy variants are converted via LibreOffice
    (delegated to v1's battle-tested `_convert_to_pdf`).
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return file_bytes
    if ext in {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}:
        from ingest.services.ingestion import _convert_to_pdf
        return _convert_to_pdf(file_bytes, ext)
    raise ValueError(f"ensure_pdf: unsupported extension '{ext}' for '{filename}'")


def extract_hyperlinks(pdf_bytes: bytes) -> list[dict]:
    """Extract hidden hyperlink URIs per page. Placeholder."""
    raise NotImplementedError


async def opus_parse_and_chunk(
    pdf_bytes: bytes,
    hyperlinks: list[dict],
    filename: str,
) -> list[Document]:
    """Opus 4.7 reads PDF + sidecar, returns chunks. Placeholder."""
    raise NotImplementedError


async def ingest_v2(
    file_bytes: bytes,
    filename: str,
    namespace: str,
    tenant_id: str,
    skip_enrichment: bool = False,
    doc_category: str = "general",
    url: str = "",
    download_link: str = "",
) -> int:
    """Main v2 entrypoint. Placeholder."""
    raise NotImplementedError
