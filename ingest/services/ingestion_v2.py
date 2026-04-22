"""Ingestion v2: Opus 4.7-first universal pipeline.

Replaces v1's 5 format-specific paths (PDF/DOCX/XLSX/legacy/markdown)
with one path: any file → PDF → Opus parse+chunk → reuse _upsert.

See docs/superpowers/specs/2026-04-18-ingest-v2-design.md for design.
"""
from __future__ import annotations

import base64
import io
import logging
import os
import re
import zipfile
from functools import lru_cache
from typing import Any

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage

from ingest.services._v2_prompts import (
    CHUNK_TOOL_SCHEMA,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    format_sidecar,
    format_ocr_sidecar,  # NEW
)
from ingest.services.vision import _looks_like_refusal

logger = logging.getLogger(__name__)


# OCR fallback constants (used when ingest_v2 detects a pure-scan PDF)
OCR_MODEL = "claude-haiku-4-5-20251001"
OCR_CONCURRENCY = 4
OCR_DPI = 200
OCR_MAX_TOKENS_PER_PAGE = 4096
PURE_SCAN_TEXT_THRESHOLD = 0


@lru_cache(maxsize=1)
def _get_ocr_client():
    """Cached raw AsyncAnthropic client for per-page vision OCR.

    Intentionally uses the raw anthropic SDK rather than langchain_anthropic:
    the OCR call is a single image + text block with no tool use, and raw
    SDK has cleaner async semantics and direct access to response bodies for
    debugging. Tests monkeypatch this function (or its return value) — the
    cache is small so a cache_clear() in a fixture is cheap.
    """
    from anthropic import AsyncAnthropic
    from shared.config import settings
    return AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY, max_retries=3)


OCR_PROMPT = (
    "สกัดข้อความทั้งหมดที่มองเห็นจากภาพสแกนหน้านี้ "
    "คงรูปโครงสร้าง (หัวข้อ ย่อหน้า รายการหัวข้อ ตาราง) เท่าที่ทำได้ "
    "- หัวข้อให้ขึ้นบรรทัดใหม่ "
    "- ตารางให้ใช้ pipe markdown | col1 | col2 | "
    "- ไม่ต้องใส่คำอธิบายใด ๆ หรือบอกว่าเป็นภาพอะไร ให้คืนเฉพาะข้อความ "
    "- ถ้ามีภาษาอังกฤษปนให้คงไว้ตามต้นฉบับ"
)


async def ocr_pdf_pages(pdf_bytes: bytes, filename: str) -> dict[int, str]:
    """Per-page vision OCR using Haiku 4.5, parallelized up to OCR_CONCURRENCY.

    Returns ``{1-based page: text}``. A per-page exception yields an empty
    string for that page (partial OCR is better than total fail). If every
    page raises, the function raises ``RuntimeError``.
    """
    import asyncio
    import pymupdf

    client = _get_ocr_client()
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    n_pages = doc.page_count
    # Render page images up front so the async tasks don't fight over the pymupdf handle.
    page_pngs: dict[int, bytes] = {}
    try:
        for i, page in enumerate(doc):
            page_pngs[i + 1] = page.get_pixmap(dpi=OCR_DPI).tobytes("png")
    finally:
        doc.close()

    sem = asyncio.Semaphore(OCR_CONCURRENCY)

    async def _one(page_num: int) -> tuple[int, str | BaseException]:
        async with sem:
            try:
                b64 = base64.standard_b64encode(page_pngs[page_num]).decode("ascii")
                resp = await client.messages.create(
                    model=OCR_MODEL,
                    max_tokens=OCR_MAX_TOKENS_PER_PAGE,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                            {"type": "text", "text": OCR_PROMPT},
                        ],
                    }],
                )
                text_parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
                return page_num, "\n".join(text_parts).strip()
            except (asyncio.CancelledError, Exception) as exc:
                return page_num, exc

    results = await asyncio.gather(*[_one(p) for p in range(1, n_pages + 1)])

    out: dict[int, str] = {}
    n_failed = 0
    for page_num, payload in results:
        if isinstance(payload, BaseException):
            logger.warning("ocr_pdf_pages(%s): page %d failed: %r", filename, page_num, payload)
            out[page_num] = ""
            n_failed += 1
        else:
            out[page_num] = payload

    if n_failed == n_pages:
        raise RuntimeError(f"OCR failed for all pages of {filename!r}")

    logger.info(
        "ocr_pdf_pages(%s): OCR complete — %d pages, %d chars total, %d failed",
        filename, n_pages, sum(len(v) for v in out.values()), n_failed,
    )
    return out


_OCR_DOCX_PAGE_HEADING_RE = re.compile(r"^หน้า\s+(\d+)\s*$")


def _read_ocr_docx_as_pages(file_bytes: bytes) -> dict[int, str]:
    """Parse a .ocr.docx (produced by ``scripts/ocr_pdf_via_opus.py``) into
    ``{1-based page: joined text}`` matching ``ocr_pdf_pages``'s shape.

    The script writes: level-1 heading (doc title, ignored) → level-2
    ``หน้า N`` heading opening each page → paragraphs with OCR'd text.
    This parser walks paragraphs in document order; a Heading 2 matching
    ``r'^หน้า\\s+(\\d+)$'`` opens a new page bucket, subsequent non-heading
    paragraphs accumulate into it joined by ``\\n``.

    Fallback: if no page markers are found (hand-edited or tool-produced
    docx), return ``{1: <all paragraphs joined>}`` so ingest proceeds as
    single-page rather than fails outright.

    Raises ``ValueError`` when python-docx cannot open the bytes (wraps
    ``docx.opc.exceptions.PackageNotFoundError`` so callers see a stable
    exception type).
    """
    from docx import Document as DocxDocument
    from docx.opc.exceptions import PackageNotFoundError

    try:
        doc = DocxDocument(io.BytesIO(file_bytes))
    except (PackageNotFoundError, zipfile.BadZipFile, KeyError) as exc:
        raise ValueError(f"not a valid .ocr.docx: {exc}") from exc

    pages: dict[int, list[str]] = {}
    current_page: int | None = None

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style_name = (para.style.name or "") if para.style else ""
        if style_name == "Heading 2":
            m = _OCR_DOCX_PAGE_HEADING_RE.match(text)
            if m:
                current_page = int(m.group(1))
                pages.setdefault(current_page, [])
                continue
            # Other level-2 headings (unexpected) — fall through as content
            # on the currently open page, if any.
        if current_page is None:
            continue
        pages[current_page].append(text)

    if not pages:
        # No page markers — collect all non-empty paragraphs into page 1.
        joined = "\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())
        return {1: joined}

    return {p: "\n".join(lines) for p, lines in pages.items()}


def _format_pages_for_text_only(ocr_sidecar: dict[int, str]) -> str:
    """Render per-page OCR text for the text-only Opus prompt (no PDF block).

    Distinct from ``format_ocr_sidecar`` (in ``_v2_prompts``) which treats
    the rendered PDF image as ground truth and OCR as assistive. Here the
    text IS the ground truth — Opus has no image to cross-check. Page
    markers use ``### Page N`` to match ``format_ocr_sidecar``'s convention
    so chunk ``page`` attribution is consistent regardless of which path
    produced the text.
    """
    if not ocr_sidecar:
        return "(empty document)"
    lines: list[str] = []
    for page_num in sorted(ocr_sidecar.keys()):
        text = ocr_sidecar[page_num]
        lines.append(f"### Page {page_num}")
        lines.append(text if text else "(no text extracted on this page)")
        lines.append("")
    return "\n".join(lines).rstrip()


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


def extract_page_text(pdf_bytes: bytes) -> dict[int, str]:
    """Return {1-based page index: extracted text layer} for the PDF.

    Used by ``ingest_v2`` to detect pure-scan PDFs (all values empty). Also
    exposes per-page text so future work can feed hybrid PDFs' native text
    to Opus as an OCR-equivalent sidecar without triggering the LLM path.
    """
    import pymupdf

    out: dict[int, str] = {}
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        for i, page in enumerate(doc):
            out[i + 1] = page.get_text("text") or ""
    finally:
        doc.close()
    return out


async def opus_parse_and_chunk(
    pdf_bytes: bytes,
    hyperlinks: list[dict],
    filename: str,
    ocr_sidecar: dict[int, str] | None = None,
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

    When ``ocr_sidecar`` is provided (pure-scan path), per-page OCR text is
    injected into the user prompt via ``{ocr_block}`` alongside the hyperlink
    sidecar. The PDF document block is still sent so Opus can cross-check
    vision against OCR.

    Returns a list of LangChain ``Document`` objects with metadata
    ``{page, section_path, has_table}``. Higher-level ``_upsert`` layers
    on ``source_filename``, ``tenant_id``, ``ingest_ts`` etc.

    Empty / refusal / malformed responses return ``[]`` — the caller
    treats that as "no ingestable content".
    """
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    sidecar_block = format_sidecar(hyperlinks)
    ocr_block = format_ocr_sidecar(ocr_sidecar or {})  # NEW
    user_text = USER_PROMPT_TEMPLATE.format(
        filename=filename,
        sidecar_block=sidecar_block,
        ocr_block=ocr_block,  # NEW
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

    page_text = extract_page_text(pdf_bytes)
    ocr_sidecar: dict[int, str] | None = None
    total_text_chars = sum(len(t) for t in page_text.values())
    if total_text_chars <= PURE_SCAN_TEXT_THRESHOLD:
        logger.info(
            "ingest_v2(%s): pure-scan detected (0 text chars across %d pages), running OCR",
            filename, len(page_text),
        )
        ocr_sidecar = await ocr_pdf_pages(pdf_bytes, filename)
    else:
        logger.debug(
            "ingest_v2(%s): text-layer PDF (%d chars across %d pages), OCR skipped",
            filename, total_text_chars, len(page_text),
        )

    hyperlinks = extract_hyperlinks(pdf_bytes)
    chunks = await opus_parse_and_chunk(
        pdf_bytes, hyperlinks, filename, ocr_sidecar=ocr_sidecar,
    )

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
