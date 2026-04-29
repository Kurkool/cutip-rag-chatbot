"""Ingestion v2: Opus 4.7-first universal pipeline.

Replaces v1's 5 format-specific paths (PDF/DOCX/XLSX/legacy/markdown)
with one path: any file → PDF → Opus parse+chunk → reuse _upsert.

See docs/superpowers/specs/2026-04-18-ingest-v2-design.md for design.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from functools import lru_cache

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage

from ingest.services._v2_prompts import (
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    format_sidecar,
)
from ingest.services.vision import _looks_like_refusal

logger = logging.getLogger(__name__)


def _extract_json_from_fence(text):
    """Extract a JSON object from a markdown fence, tolerating extra prose.

    Opus 4.7 reliably outputs JSON inside a ```json … ``` fence when
    the system prompt asks for it. We accept either a fenced code block or
    bare JSON with extra text by finding the outermost { … } span.

    Returns ``None`` on parse failure or empty input — caller logs and treats
    as 0 chunks.
    """
    if not text:
        return None
    m = _JSON_FENCE_RE.search(text)
    candidate = m.group(1) if m else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(candidate[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


_CHUNKS_ARRAY_START_RE = re.compile(r'"chunks"\s*:\s*\[')


def _salvage_complete_chunks_from_truncated(text):
    """Extract complete chunk objects from a possibly-truncated JSON response.

    When Opus hits ``max_tokens`` the JSON output is cut mid-array (and the
    closing ``]}`` of the wrapper never arrive), so :func:`_extract_json_from_fence`
    fails outright. We can still recover the chunks Opus completed before the
    cut by walking object-by-object using ``json.JSONDecoder.raw_decode``:

    1. Find ``"chunks": [`` in the text.
    2. Skip whitespace/commas, parse one ``{ ... }`` at a time with ``raw_decode``.
    3. On the first ``JSONDecodeError`` (the truncated trailing object) — stop.

    Returns ``[]`` for empty/None input, missing chunks marker, or truncation
    before the first complete object. Caller treats ``[]`` as 0 chunks.
    """
    if not text:
        return []
    m = _CHUNKS_ARRAY_START_RE.search(text)
    if not m:
        return []
    decoder = json.JSONDecoder()
    chunks = []
    i = m.end()  # position right after the opening [
    n = len(text)
    while i < n:
        # Skip whitespace + the comma between objects.
        while i < n and text[i] in " \t\n\r,":
            i += 1
        if i >= n or text[i] != "{":
            break
        try:
            obj, end_idx = decoder.raw_decode(text, idx=i)
        except json.JSONDecodeError:
            # Hit the truncated trailing object — stop.
            break
        chunks.append(obj)
        i = end_idx
    return chunks


def _text_from_response(response):
    """Return the concatenated text-block content from a langchain AIMessage.

    Opus 4.7 with adaptive thinking returns ``content`` as a list of typed
    blocks (``thinking``, ``text``, …). Plain string content is also handled
    for compatibility with simpler responses (and tests).
    """
    content = response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
        return "\n".join(parts)
    return str(content or "")


def _pdf_to_image_blocks(pdf_bytes, dpi=150):
    """Rasterise every PDF page to PNG and wrap as Anthropic image content blocks.

    Used by ``opus_parse_and_chunk`` when the PDF has no text layer.
    Mirrors what claude.ai does internally for PDF uploads — Anthropic's PDF
    ``document`` block path is unreliable on long pure-scan Thai legal docs
    (silent ``chunks=[]`` even with an OCR sidecar). Sending pre-rendered
    images bypasses that path.

    DPI 150 balances OCR fidelity against payload size: a 24-page Thai legal
    scan at 150 DPI is ~36K input tokens vs ~5K for the document block.

    Anthropic limits a single request to 100 image blocks. This function
    raises ``ValueError`` if the PDF exceeds that.
    """
    import pymupdf
    blocks = []
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        if doc.page_count > 100:
            raise ValueError(
                f"_pdf_to_image_blocks: {doc.page_count} pages exceeds "
                f"Anthropic's 100-image limit"
            )
        for page in doc:
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            png = pix.tobytes("png")
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.standard_b64encode(png).decode("utf-8"),
                },
            })
    finally:
        doc.close()
    return blocks


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_UNREADABLE_PAGE_RE = re.compile(r"\[page \d+: unreadable\]")


@lru_cache(maxsize=1)
def _get_opus_llm():
    """Return the Opus 4.7 LLM used for v2 parse+chunk (cached per process).

    Adaptive thinking is ENABLED. No tool binding — the system prompt
    instructs Opus to emit a ``\\`\\`\\`json`` fence and we parse it in Python.
    Earlier iterations of this pipeline used ``bind_tools`` + ``tool_choice``
    but empirically Opus would opt out of the tool call on long Thai legal
    docs (silent ``chunks=[]``). Free-form text + JSON fence reliably
    produces parseable output.

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
        # 128K is Opus 4.7's max output ceiling (1M context, 128K out).
        # Adaptive thinking shares this budget with text output, so for
        # dense Thai legal scans (where Opus emitted 44K out_tok on a
        # 24-page success and got cut off at 32K on a prior failure)
        # this gives ~3× headroom. Salvage helper still recovers partial
        # chunks if Opus exceeds even this on edge cases.
        max_tokens=128000,
        max_retries=3,
        thinking={"type": "adaptive"},
        # Bypass the SDK's "estimated >10min" guard that refuses
        # non-streaming requests with very large max_tokens. We use
        # ainvoke (not stream) — the Cloud Run service is configured
        # with --timeout=3600 so a 10-minute request fits comfortably.
        timeout=600.0,
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
    pdf_bytes,
    hyperlinks,
    filename,
    mode,
):
    """Send PDF (or rasterised page images) to Opus 4.7, parse JSON-fence response.

    No tool binding. The system prompt instructs Opus to emit one
    ``\\`\\`\\`json`` fence containing ``{"chunks": [...]}``. We accept text output
    and parse the fence.

    ``mode`` selects the content shape:
    - ``"document"`` — text-layer PDF: ``[document_block, text_block]``
    - ``"images"``   — pure-scan PDF: ``[image_block, …, text_block]``

    Empty / refusal / [page N: unreadable] chunks are filtered out. Any failure
    to parse JSON returns ``[]`` (caller logs and treats as 0 chunks).
    """
    sidecar_block = format_sidecar(hyperlinks)
    user_text = USER_PROMPT_TEMPLATE.format(
        filename=filename,
        sidecar_block=sidecar_block,
    )

    if mode == "images":
        image_blocks = _pdf_to_image_blocks(pdf_bytes)
        human_content = [*image_blocks, {"type": "text", "text": user_text}]
    elif mode == "document":
        pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
        human_content = [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": pdf_b64,
                },
            },
            {"type": "text", "text": user_text},
        ]
    else:
        raise ValueError(f"opus_parse_and_chunk: unknown mode {mode!r}")

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=human_content),
    ]
    response = await _get_opus_llm().ainvoke(messages)

    meta = response.response_metadata or {}
    stop_reason = meta.get("stop_reason")
    usage = meta.get("usage", {}) or {}
    text = _text_from_response(response)
    logger.info(
        "opus_parse(%s mode=%s): stop=%s in_tok=%s out_tok=%s text_len=%d",
        filename, mode, stop_reason,
        usage.get("input_tokens"), usage.get("output_tokens"), len(text),
    )

    parsed = _extract_json_from_fence(text)
    if not parsed or "chunks" not in parsed:
        # Output likely truncated by max_tokens — try to salvage the complete
        # chunk objects that arrived before the cut-off.
        salvaged = _salvage_complete_chunks_from_truncated(text)
        if salvaged:
            logger.warning(
                "opus_parse(%s): JSON parse failed (stop=%s); salvaged %d complete chunks from truncated output",
                filename, stop_reason, len(salvaged),
            )
            parsed = {"chunks": salvaged}
        else:
            logger.warning(
                "opus_parse(%s): could not parse JSON. preview=%r",
                filename, text[:800],
            )
            return []

    raw_chunks = parsed.get("chunks") or []
    cleaned = []
    for c in raw_chunks:
        t = (c.get("text") or "").strip()
        if not t:
            continue
        if _UNREADABLE_PAGE_RE.fullmatch(t):
            continue
        if _looks_like_refusal(t):
            logger.warning(
                "opus_parse(%s): dropping refusal chunk on page %s",
                filename, c.get("page", "?"),
            )
            continue
        try:
            page = int(c.get("page", 1))
        except (TypeError, ValueError):
            page = 1
        cleaned.append(Document(
            page_content=t,
            metadata={
                "page": page,
                "section_path": c.get("section_path", "") or "",
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
      1. ensure_pdf — normalize any supported format to PDF
      2. extract_page_text — detect text-layer; routes to either:
         - "document" mode: text-layer PDF → Anthropic document block
         - "images" mode:   pure-scan PDF → rasterised page image blocks
      3. opus_parse_and_chunk — free-form JSON fence response
      4. _upsert — Cohere embed, Pinecone atomic swap, BM25 invalidation

    ``drive_file_id`` (optional) stores the Drive file ID in chunk metadata
    so admin delete can remove the Drive file by ID even after rename.
    """
    from ingest.services.ingest_helpers import _build_metadata, _upsert

    pdf_bytes = ensure_pdf(file_bytes, filename)
    page_text = extract_page_text(pdf_bytes)
    total_text_chars = sum(len(t) for t in page_text.values())
    if total_text_chars <= 0:
        mode = "images"
        logger.info(
            "ingest_v2(%s): pure-scan detected (0 text chars across %d pages), using image blocks",
            filename, len(page_text),
        )
    else:
        mode = "document"
        logger.debug(
            "ingest_v2(%s): text-layer PDF (%d chars across %d pages), using document block",
            filename, total_text_chars, len(page_text),
        )
    hyperlinks = extract_hyperlinks(pdf_bytes)

    chunks = await opus_parse_and_chunk(pdf_bytes, hyperlinks, filename, mode=mode)
    if not chunks:
        logger.warning("ingest_v2(%s): Opus returned 0 chunks — nothing upserted", filename)
        return 0

    metadata = _build_metadata(
        tenant_id=tenant_id,
        source_type="pdf",
        source_filename=filename,
        doc_category=doc_category,
        url=url,
        download_link=download_link,
        drive_file_id=drive_file_id,
    )
    return await _upsert(chunks, namespace, metadata)
