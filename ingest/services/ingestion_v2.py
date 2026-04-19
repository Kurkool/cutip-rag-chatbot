"""Ingestion v2: Opus 4.7-first universal pipeline.

Replaces v1's 5 format-specific paths (PDF/DOCX/XLSX/legacy/markdown)
with one path: any file → PDF → Opus parse+chunk → reuse _upsert.

See docs/superpowers/specs/2026-04-18-ingest-v2-design.md for design.
"""
from __future__ import annotations

import base64
import logging
import os
from functools import lru_cache
from typing import Any

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage

from ingest.services._v2_prompts import (
    CHUNK_TOOL_SCHEMA,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    format_sidecar,
)
from ingest.services.vision import _looks_like_refusal

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_opus_llm():
    """Return the Opus 4.7 LLM used for v2 parse+chunk (cached per process).

    Adaptive thinking is ENABLED. Anthropic disallows thinking when
    ``tool_choice`` forces a specific tool, so ``opus_parse_and_chunk``
    pairs this factory with ``tool_choice={"type": "auto"}`` — the system
    prompt still instructs Opus to call ``record_chunks``, and Opus
    reliably complies, but the model is free to think first. This
    matters for long complex docs (45-page slide decks, dense
    announcement PDFs with 20+ per-item records) where empirically the
    non-thinking forced-tool path produced empty chunks after multi-
    minute stalls.

    Cached so a batch audit (e.g. 14 PDFs) does not re-instantiate the
    HTTP-pooled client once per file. Tests monkeypatch this function
    directly — ``monkeypatch.setattr`` replaces the module attribute so
    the cached original is bypassed entirely during the test.
    """
    from langchain_anthropic import ChatAnthropic
    from shared.config import settings
    return ChatAnthropic(
        model=settings.OCR_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        # 32K output budget: slide decks (45+ pages × ~500 tokens/chunk)
        # and dense announcement PDFs (23+ student records) both
        # overflowed the previous 8K cap, surfacing as silent 0-chunk
        # returns when the tool_call JSON was truncated mid-array.
        max_tokens=32000,
        max_retries=3,
        thinking={"type": "adaptive"},
    )


def ensure_pdf(file_bytes: bytes, filename: str) -> bytes:
    """Normalize any supported input to PDF bytes.

    PDF inputs are passed through untouched (byte-identity preserved).
    Other formats (DOC/DOCX/XLS/XLSX/PPT/PPTX/CSV) are converted via LibreOffice
    (delegated to the battle-tested `_convert_to_pdf` helper).
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return file_bytes
    if ext in {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv"}:
        from ingest.services.ingest_helpers import _convert_to_pdf
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
    """Send PDF + sidecar to Opus 4.7 with auto tool use, return chunks.

    Opus receives:
    - System prompt defining chunking rules and tool-call contract
    - User message: PDF as ``document`` content block + text describing
      filename and hyperlink sidecar
    - ``tool_choice={"type": "auto"}`` — the system prompt instructs Opus
      to call ``record_chunks`` exactly once, and in practice it does.
      Forced tool_choice is intentionally NOT used: Anthropic disallows
      adaptive thinking when a tool is forced, and without thinking
      Opus silently returned empty chunk arrays on long/dense docs
      (45-page slide decks, 20+ student announcement records).

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
        tool_choice={"type": "auto"},
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
    cleaned: list[Document] = []
    for c in raw_chunks:
        text = (c.get("text") or "").strip()
        if not text:
            continue
        if _looks_like_refusal(text):
            logger.warning(
                "opus_parse_and_chunk(%s): dropping refusal-pattern chunk on page %s",
                filename, c.get("page", "?"),
            )
            continue
        cleaned.append(Document(
            page_content=text,
            metadata={
                "page": int(c.get("page", 1)),
                "section_path": c.get("section_path", ""),
                "has_table": bool(c.get("has_table", False)),
            },
        ))
    return cleaned


async def ingest_v2(
    file_bytes: bytes,
    filename: str,
    namespace: str,
    tenant_id: str,
    doc_category: str = "general",
    url: str = "",
    download_link: str = "",
    drive_file_id: str = "",
) -> int:
    """v2 universal ingestion entrypoint.

    Pipeline:
      1. ``ensure_pdf`` — normalize any supported format to PDF bytes
      2. ``extract_hyperlinks`` — deterministic sidecar for hidden URIs
      3. ``opus_parse_and_chunk`` — one Opus 4.7 call returns chunks with
         section context already inlined (no separate enrichment pass)
      4. ``_upsert`` (reused from v1) — Cohere embed, Pinecone atomic swap,
         BM25 cross-process invalidation

    ``drive_file_id`` (optional) stores the Drive file ID in chunk metadata
    so admin delete can remove the Drive file by ID even after rename —
    name-based lookup breaks when users rename files in Drive after ingest.
    """
    from ingest.services.ingest_helpers import _build_metadata, _upsert

    pdf_bytes = ensure_pdf(file_bytes, filename)
    hyperlinks = extract_hyperlinks(pdf_bytes)
    chunks = await opus_parse_and_chunk(pdf_bytes, hyperlinks, filename)

    if not chunks:
        logger.warning("ingest_v2(%s): Opus returned 0 chunks — nothing upserted", filename)
        return 0

    metadata = _build_metadata(
        tenant_id=tenant_id,
        source_type="pdf",  # v2 universalizes to pdf
        source_filename=filename,
        doc_category=doc_category,
        url=url,
        download_link=download_link,
        drive_file_id=drive_file_id,
    )
    return await _upsert(chunks, namespace, metadata)
