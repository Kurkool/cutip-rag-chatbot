"""Ingestion v2: Opus 4.7-first universal pipeline.

Replaces v1's 5 format-specific paths (PDF/DOCX/XLSX/legacy/markdown)
with one path: any file → PDF → Opus parse+chunk → reuse _upsert.

See docs/superpowers/specs/2026-04-18-ingest-v2-design.md for design.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage

from ingest.services._v2_prompts import (
    CHUNK_TOOL_SCHEMA,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    format_sidecar,
)

logger = logging.getLogger(__name__)


def _get_opus_llm():
    """Return the Opus 4.7 Vision LLM used for v2 parsing.

    Reuses the existing OCR LLM factory. Kept as a private function so
    tests can monkeypatch it without touching the shared services layer.
    """
    from shared.services.llm import get_ocr_llm
    return get_ocr_llm()


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
    """Extract hidden hyperlink URIs from every page as sidecar metadata.

    Returns a list of ``{"page": int, "text": str, "uri": str}`` entries.
    ``text`` is the visible anchor text (from the PDF text layer clipped
    to the link rectangle); ``uri`` is the target URL. Page numbering is
    1-based to match how users refer to pages.

    URIs that already appear as visible text on the page are skipped —
    Opus 4.7 reads them directly from the rendered PDF and a duplicate
    sidecar entry would cause it to emit duplicate markdown links.

    Opus 4.7 reading a PDF cannot see link annotations — only the rendered
    visual. We inject this sidecar so generated chunks can still emit
    inline ``[anchor](uri)`` markdown links when relevant.
    """
    import pymupdf

    links: list[dict] = []
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        for page_index, page in enumerate(doc):
            page_text = page.get_text("text")
            for link in page.get_links():
                uri = link.get("uri", "")
                if not uri:
                    continue
                # Skip URIs already visible in the rendered page text — Opus
                # will read them directly. Sidecar is for *hidden* link
                # annotations only (matches v1 behavior + v2 prompt contract).
                if uri in page_text:
                    continue
                rect = link.get("from", pymupdf.Rect())
                anchor_text = page.get_text("text", clip=rect).strip() or uri
                links.append({
                    "page": page_index + 1,
                    "text": anchor_text,
                    "uri": uri,
                })
    finally:
        doc.close()
    return links


async def opus_parse_and_chunk(
    pdf_bytes: bytes,
    hyperlinks: list[dict],
    filename: str,
) -> list[Document]:
    """Send PDF + sidecar to Opus 4.7 with forced tool use, return chunks.

    Opus receives:
    - System prompt defining chunking rules and tool-call contract
    - User message: PDF as ``document`` content block + text describing
      filename and hyperlink sidecar
    - Forced ``tool_choice="record_chunks"`` so the response always comes
      back as structured JSON via tool arguments rather than free-form text

    Returns a list of LangChain ``Document`` objects with metadata
    ``{page, section_path, has_table}``. Higher-level ``_upsert`` layers
    on ``source_filename``, ``tenant_id``, ``ingest_ts`` etc.

    Empty / refusal / malformed responses return ``[]`` — the caller
    treats that as "no ingestable content".
    """
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    sidecar_block = format_sidecar(hyperlinks)
    user_text = USER_PROMPT_TEMPLATE.format(
        filename=filename,
        sidecar_block=sidecar_block,
    )

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=[
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": pdf_b64,
                },
            },
            {"type": "text", "text": user_text},
        ]),
    ]

    llm = _get_opus_llm().bind_tools(
        [CHUNK_TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": CHUNK_TOOL_SCHEMA["name"]},
    )
    response = await llm.ainvoke(messages)

    tool_calls = getattr(response, "tool_calls", None) or []
    if not tool_calls:
        logger.warning(
            "opus_parse_and_chunk(%s): no tool_call in response — returning []",
            filename,
        )
        return []

    raw_chunks = tool_calls[0].get("args", {}).get("chunks", [])
    return [
        Document(
            page_content=c["text"],
            metadata={
                "page": int(c.get("page", 1)),
                "section_path": c.get("section_path", ""),
                "has_table": bool(c.get("has_table", False)),
            },
        )
        for c in raw_chunks
        if c.get("text", "").strip()
    ]


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
