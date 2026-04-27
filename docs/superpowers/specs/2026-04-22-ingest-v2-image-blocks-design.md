# Ingest v2 — Image Blocks + Free-Form JSON (Phase 1)

**Status:** Draft **Date:** 2026-04-22 **Branch:** `feat/ingest-robustness` (continuation)

## Problem

Two prior attempts to fix Opus 4.7 silent-fail (returning `chunks=[]`) on long Thai legal documents have not solved the issue:

- **C1 (pre-flight Haiku OCR + sidecar)** — deployed in `cutip-ingest-worker-00028-4vv`. Haiku correctly extracts ~45K chars of OCR'd text, but Opus parse+chunk still returns 0 chunks when given the PDF document block plus the OCR sidecar.
- **Text-only path** — deployed in `cutip-ingest-worker-00029-vkz` (this branch's most recent prior work). Drops the PDF entirely and sends only OCR'd text. Smart Scan on `.ocr.docx` at 2026-04-22 00:39 UTC: Opus call ran 5m 40s, returned `chunks=[]`, drove cooldown counter to 1.

Diagnostic analysis (see chat log on this branch and external second-opinion review) converges on a different root cause than originally hypothesised:

- The failure mode is **not** input context size or PDF visual quality. It is the combination of `tool_choice={"type": "auto"}` + `thinking={"type": "adaptive"}` + a long Thai document with a strict tool-call output schema. Adaptive thinking gives Opus an "escape hatch" to opt out of the `record_chunks` tool call when the schema feels constraining, returning text content with no `tool_calls` populated, which the v2 pipeline treats as 0 chunks.
- claude.ai succeeds on the same PDF because it (a) renders each page as an image block (not a `document` block), (b) does not bind any tool / impose a schema, and (c) lets the model output free-form text. The web flow's "68 chunks" is the model's free-form transcription consumed by a Python script — not a single tool call.

## Goals

- **Drop tool binding entirely.** No `bind_tools`, no `tool_choice`. Opus outputs free-form text containing one `\`\`\`json` markdown fence carrying the chunks list. Python parses the fence and validates the shape.
- **Pure-scan PDFs send rasterised page images** (one Anthropic `image` content block per page, PNG @ 150 DPI) instead of the legacy `document` content block. Mirrors what claude.ai does internally.
- **Text-layer PDFs keep the `document` block** (Anthropic's text-extraction-first handling is reliable on them; existing `slide.pdf` etc. work today and must keep working).
- **Remove dead branches:** `.ocr.docx` filename branch, `_read_ocr_docx_as_pages`, `_format_pages_for_text_only`, `USER_PROMPT_TEMPLATE_TEXT_ONLY`, in-pipeline Haiku pre-OCR (`OCR_PROMPT`, `_get_ocr_client`, `ocr_pdf_pages`, `format_ocr_sidecar`, `OCR_*` constants, `PURE_SCAN_TEXT_THRESHOLD`). These existed because we did not yet know the root cause was the tool binding.
- **Backward compatibility for non-failing flows.** Text-layer PDFs — slide decks, Word→PDF distiller output, audited `cutip-doc/` files — must produce the same chunk shape they do today (verified via the existing `tests/test_ingestion_v2.py::test_opus_parse_and_chunk_happy_path` and the `slide.pdf` 43-chunk historical baseline).

## Non-goals (deferred to Phase 2)

- Per-chunk metadata enrichment beyond what we have today: `urls`, `qr_codes`, `has_form_fields`, `embedded_images_count`. These require new dependencies (`pyzbar` + system `libzbar0`) and a separate plan/test cycle.
- Removing `extract_hyperlinks` or its sidecar pattern. Hyperlinks are still extracted deterministically and passed to Opus as a sidecar in the user prompt — the chunk text gets `[anchor](uri)` markdown inlined as before.
- Removing the C2 failure-tracking + cooldown machinery (`shared/services/ingest_failures.py`, `record_failure`/`clear_failure`/`get_failure`, `MAX_CONSECUTIVE_FAILURES`). Orthogonal to chunking, valuable, stays.
- Multi-call batching for documents over 100 pages. Anthropic's per-request image cap is 100; current production documents are well below that. If a 100+ page doc lands, surface a clear error and address with a separate batching spec.
- Changes to `_upsert`, embedding, Pinecone dedup, BM25 invalidation. The chunks list shape is identical (`page`, `section_path`, `has_table`, `urls` from existing `_URL_PATTERN.findall` post-processing).

## Architecture

```
ingest_v2(file_bytes, filename, …)
  │
  ├─ ensure_pdf(file_bytes, filename) → pdf_bytes        (unchanged)
  │   PDF → pass-through · DOCX/XLSX/PPTX/CSV → LibreOffice → PDF
  │
  ├─ extract_hyperlinks(pdf_bytes) → list[dict]          (unchanged)
  │
  ├─ extract_page_text(pdf_bytes) → dict[int, str]       (unchanged)
  │   Sum chars across all pages; 0 = pure-scan, >0 = text-layer
  │
  └─ opus_parse_and_chunk(pdf_bytes, hyperlinks, filename, mode)
        │
        ├─ mode = "document"  (text-layer PDF)
        │   HumanMessage content = [document_block, text_block]
        │
        ├─ mode = "images"    (pure-scan PDF)
        │   image_blocks = _pdf_to_image_blocks(pdf_bytes, dpi=150)
        │   HumanMessage content = [*image_blocks, text_block]
        │
        ├─ llm = _get_opus_llm()                          # NO bind_tools
        │   thinking = {"type": "adaptive"} retained
        │
        ├─ response = await llm.ainvoke(messages)
        ├─ text = _text_from_response(response)
        ├─ parsed = _extract_json_from_fence(text)
        │   {"chunks": [{"text", "page", "section_path", "has_table"}]}
        │
        └─ Filter empty / refusal / [page N: unreadable] → list[Document]
```

## Components

### Modified: `ingest/services/ingestion_v2.py`

**Removed (cleanup of failed text-only experiment + obsolete pre-OCR):**

- `OCR_MODEL`, `OCR_CONCURRENCY`, `OCR_DPI`, `OCR_MAX_TOKENS_PER_PAGE`, `PURE_SCAN_TEXT_THRESHOLD` constants
- `OCR_PROMPT` constant
- `_get_ocr_client()` function
- `ocr_pdf_pages()` function
- `_read_ocr_docx_as_pages()` function (added Task 1 of prior feature, now obsolete)
- `_OCR_DOCX_PAGE_HEADING_RE` constant
- `_format_pages_for_text_only()` function (added Task 2)
- `import zipfile`, `import re` if no longer used after removals (keep `import io` — used by image block writer)

**Added: `_pdf_to_image_blocks(pdf_bytes: bytes, dpi: int = 150) -> list[dict]`**

```python
def _pdf_to_image_blocks(pdf_bytes: bytes, dpi: int = 150) -> list[dict]:
    """Rasterize every PDF page to PNG and wrap as Anthropic image content blocks.

    Used by ``opus_parse_and_chunk`` when the PDF has no text layer (pure scan).
    Mirrors what claude.ai does internally for PDF uploads — Anthropic's PDF
    ``document`` block path is unreliable on long pure-scan Thai legal docs
    (silent ``chunks=[]`` even with an OCR sidecar). Sending pre-rendered images
    bypasses that path.

    DPI 150 balances OCR fidelity against payload size: a 24-page Thai legal
    scan at 150 DPI is ~36K input tokens, vs ~5K for the document block.
    Empirically claude.ai uses DPI in the 144–150 range. Bump to 200 if a
    document has tiny font / dense tables and OCR quality is the bottleneck.

    Anthropic limits a single request to 100 image blocks. This function
    raises ``ValueError`` if the PDF exceeds that — caller can split or fail.
    """
    import pymupdf
    blocks: list[dict] = []
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        if doc.page_count > 100:
            raise ValueError(
                f"_pdf_to_image_blocks: {doc.page_count} pages exceeds Anthropic's 100-image limit"
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
```

**Added: `_extract_json_from_fence(text: str) -> dict | None`**

```python
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json_from_fence(text: str) -> dict | None:
    """Extract a JSON object from a markdown fence, tolerating extra prose.

    Opus 4.7 reliably outputs JSON inside a ``\`\`\`json … \`\`\``` fence when
    the system prompt asks for it. We accept either a fenced code block or
    bare-JSON-with-extra-text by finding the outermost ``{ … }`` span.

    Returns ``None`` on parse failure — caller logs and treats as 0 chunks
    (same outcome as the legacy "no tool_call in response" branch).
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
```

**Added: `_text_from_response(response) -> str`**

```python
def _text_from_response(response) -> str:
    """Adaptive thinking returns ``content`` as a list of blocks; concatenate text."""
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
```

**Modified: `_get_opus_llm()`** — unchanged signature and body. Adaptive thinking stays. The function no longer needs to coexist with `tool_choice` constraints (forced or auto), so the elaborate docstring about why `tool_choice="auto"` is used can be replaced with one about why no tool binding is used.

**Modified: `opus_parse_and_chunk(pdf_bytes, hyperlinks, filename) -> list[Document]`**

Signature stays as `bytes` (no Optional — Phase 1 always has a real PDF since we removed the `.ocr.docx` text-only branch). Body branches on text-layer detection performed by the caller (see `ingest_v2` change below).

```python
async def opus_parse_and_chunk(
    pdf_bytes: bytes,
    hyperlinks: list[dict],
    filename: str,
    mode: str,  # "document" | "images"
) -> list[Document]:
    """Send PDF (or rasterised page images) to Opus 4.7, parse JSON-fence response.

    No tool binding. The system prompt instructs Opus to emit one
    ``\`\`\`json`` fence containing ``{"chunks": [...]}``. We accept text
    output and parse the fence.
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
        logger.warning(
            "opus_parse(%s): could not parse JSON. preview=%r",
            filename, text[:800],
        )
        return []

    raw_chunks = parsed.get("chunks") or []
    cleaned: list[Document] = []
    for c in raw_chunks:
        t = (c.get("text") or "").strip()
        if not t:
            continue
        if t.startswith("[page") and t.endswith("unreadable]"):
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
```

**Modified: `ingest_v2()`**

Remove the `.ocr.docx` branch added in the previous feature's Task 6. Add the text-layer-detection routing that picks `mode="document"` vs `mode="images"`:

```python
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
```

### Modified: `ingest/services/_v2_prompts.py`

**Removed:**
- `CHUNK_TOOL_SCHEMA` (no longer used — no tool binding)
- `format_ocr_sidecar()` function (was used only by removed `OCR_PROMPT` / sidecar path)
- `USER_PROMPT_TEMPLATE_TEXT_ONLY` (added in prior Task 3, now obsolete)

**Modified `SYSTEM_PROMPT`** — drop the "Call the `record_chunks` tool exactly once" instruction; replace with JSON-in-markdown-fence directive plus the "[page N: unreadable]" escape hatch:

```python
SYSTEM_PROMPT = """You are a document-parsing tool for a Thai+English academic/administrative knowledge base.

Your job: split the provided document into self-contained, retrieval-ready chunks.

RULES
- Preserve Thai characters exactly. Never translate or transliterate.
- Each chunk: 300–1500 characters of substantive content.
- Each chunk must stand alone — a reader who sees only one chunk should understand what it is about.
- Annotate with `section_path` (e.g. `ขั้นตอนสอบวิทยานิพนธ์ > สอบโครงร่าง`) when the document has genuine hierarchy. Leave `section_path` as an empty string if hierarchy would be invented.
- Tables: emit as markdown tables. If a table spans multiple chunks, REPEAT the header row in every chunk so each is self-contained.
- Hyperlinks: the user message includes a sidecar list of `{page, text, uri}` entries — these are URLs that are hidden in PDF link annotations and NOT visible in the rendered page. Inline them as `[anchor](uri)` markdown in the chunk whose text contains the anchor. If the URL is already plainly visible in the text, do not duplicate it.
- Forms: capture field labels and checkbox state exactly (☑ checked, ☐ unchecked).
- Diagrams / signatures / stamps: describe briefly in square brackets, e.g. `[signature of ผู้อำนวยการหลักสูตร]`. Do not fabricate content.
- Slides: 1 slide = 1 chunk unless the slide is trivially short (then merge with neighbors).
- Page numbers: set `page` to the 1-based page index where each chunk starts.
- Do not include navigation furniture (page numbers alone, running headers, "Q&A" slide titles) as standalone chunks.
- If a page is genuinely unreadable, emit one chunk with text "[page N: unreadable]" and continue with other pages. NEVER refuse the whole document.

OUTPUT FORMAT
Return ONE markdown json fence and nothing else. Exactly this shape:

```json
{
  "chunks": [
    {"text": "…", "section_path": "…", "page": 1, "has_table": false}
  ]
}
```

No prose before or after the fence. No explanation."""
```

**Modified `USER_PROMPT_TEMPLATE`** — drop the `{ocr_block}` placeholder:

```python
USER_PROMPT_TEMPLATE = """Document filename: {filename}

Hyperlink sidecar (URIs hidden in PDF annotations, not visible on the rendered page):
{sidecar_block}

Parse the attached content and emit chunks via the JSON output specified in the system prompt."""
```

`format_sidecar()` stays unchanged.

## Data flow

### Pure-scan PDF (e.g. ประกาศจุฬาฯ 2563.pdf — 24 pages, no text layer)

1. `ingest_v2` receives bytes; `ensure_pdf` returns identity (already PDF).
2. `extract_page_text` returns `{1: "", 2: "", …, 24: ""}`; `total_text_chars=0` → `mode="images"`.
3. `extract_hyperlinks` returns whatever is present (often `[]` for scans).
4. `opus_parse_and_chunk(pdf_bytes, [], filename, mode="images")`:
   - `_pdf_to_image_blocks` rasterises 24 pages at 150 DPI → 24 PNG blocks.
   - `HumanMessage.content` = 24 image blocks + 1 text block.
   - Single Opus 4.7 call (adaptive thinking enabled).
   - Response is text containing one `\`\`\`json` fence with `{"chunks": [...]}`.
   - `_extract_json_from_fence` parses; we filter empty/refusal/unreadable; build Documents.
5. `_upsert` embeds + Pinecone upsert + BM25 invalidate (unchanged).

### Text-layer PDF (e.g. slide.pdf — 45 pages, Word→Distiller text layer)

1. `extract_page_text` returns non-empty text per page; `total_text_chars > 0` → `mode="document"`.
2. `opus_parse_and_chunk` sends the document block + text block (legacy path, just JSON fence output now instead of tool call).
3. Everything else identical.

### `.ocr.docx` (legacy)

After this spec ships, `.ocr.docx` files routed through `ingest_v2` will go through `ensure_pdf` → LibreOffice DOCX→PDF conversion → text-layer PDF (LibreOffice always emits a text layer when the source has text) → `mode="document"` path. This is the same flow non-OCR DOCX files take. The standalone `scripts/ocr_pdf_via_opus.py` script remains in the repo as a reference but its output is no longer needed — users can upload original scan PDFs directly.

## Error handling

| Failure | Handling |
|---|---|
| `_pdf_to_image_blocks`: PDF > 100 pages | Raises `ValueError`; bubbles to `ingest_v2` → record_failure (existing). User receives a clear error and can split the PDF. |
| Opus returns text without a JSON fence | `_extract_json_from_fence` returns `None`; logger.warning with `text[:800]` preview; `opus_parse_and_chunk` returns `[]`; `ingest_v2` records failure (existing C2 cooldown applies). |
| Opus returns malformed JSON inside the fence | Same as above (parse fails, returns `None`). |
| Opus emits the `[page N: unreadable]` escape hatch on every page | All chunks filtered → 0 chunks → recorded as failure. Escape-hatch use on a subset of pages is fine and produces a partial-but-correct ingest. |
| Network / SDK error | Existing `max_retries=3` on the `ChatAnthropic` client. |
| Image-block payload too large | Anthropic returns 413 / size error; bubbled. Phase 1 does not implement DPI auto-downgrade — bump `dpi` constant if encountered. |

## Testing

Tests live in `tests/test_ingestion_v2.py`. Existing tests get re-evaluated:

**Tests deleted (the prior feature's text-only / `.ocr.docx` work is reverted):**
- `test_read_ocr_docx_as_pages_*` (4 tests)
- `test_format_pages_for_text_only_*` (2 tests)
- `test_user_prompt_template_text_only_has_required_placeholders`
- `test_opus_parse_and_chunk_text_only_omits_document_block`
- `test_opus_parse_and_chunk_text_only_accepts_none_pdf_bytes`
- `test_opus_parse_and_chunk_pdf_path_keeps_document_block`
- `test_opus_parse_and_chunk_injects_ocr_sidecar` (Haiku OCR sidecar removed)
- `test_opus_parse_and_chunk_without_ocr_sidecar_uses_placeholder` (placeholder removed)
- `test_user_prompt_template_has_ocr_block_placeholder` (placeholder removed)
- `test_format_ocr_sidecar_*` (function removed)
- `test_ocr_pdf_pages_*` (function removed)
- `test_get_ocr_client_is_cached_async_anthropic` (function removed)
- `test_ingest_v2_pure_scan_triggers_ocr_path` (path removed)
- `test_ingest_v2_text_layer_skips_ocr` (assertions need rewriting against new mode routing)
- `test_ingest_v2_ocr_docx_skips_libreoffice_and_hyperlinks` (branch removed)

**Tests added:**

- `test_pdf_to_image_blocks_returns_n_image_blocks_for_n_pages` — synthesise a 3-page text PDF via pymupdf, call `_pdf_to_image_blocks`, assert `len(blocks) == 3`, each has `type=image` and `media_type=image/png`.
- `test_pdf_to_image_blocks_raises_on_over_100_pages` — synthesise a 101-page PDF (smallest possible), assert `ValueError`.
- `test_extract_json_from_fence_parses_basic_fence` — input `"some text\n\`\`\`json\n{\"chunks\":[]}\n\`\`\`\n"` → `{"chunks": []}`.
- `test_extract_json_from_fence_parses_bare_json_with_prose` — input `"Here is the result: {\"chunks\": [{\"text\":\"a\",\"page\":1}]}"` → parses correctly.
- `test_extract_json_from_fence_returns_none_on_malformed` — input `"\`\`\`json\nthis is not json\n\`\`\`"` → `None`.
- `test_extract_json_from_fence_returns_none_on_empty` — input `""` → `None`.
- `test_text_from_response_handles_string_content` — AIMessage with `content="hello"` → `"hello"`.
- `test_text_from_response_concatenates_thinking_block_list` — AIMessage with `content=[{"type":"thinking",...},{"type":"text","text":"a"},{"type":"text","text":"b"}]` → `"a\nb"`.
- `test_opus_parse_and_chunk_images_mode_omits_document_block` — monkeypatch `_get_opus_llm` to capture messages, call with `mode="images"` and `pure_scan_pdf_bytes` fixture; assert content blocks include image type and exclude document type.
- `test_opus_parse_and_chunk_document_mode_includes_document_block` — same harness, `mode="document"`, `tiny_text_pdf_bytes`; assert content has document + text blocks.
- `test_opus_parse_and_chunk_returns_chunks_from_json_fence` — mock LLM returns AIMessage with `content="```json\n{\"chunks\":[{\"text\":\"x\",\"page\":1,\"section_path\":\"\",\"has_table\":false}]}\n```"`; assert returns 1 Document.
- `test_opus_parse_and_chunk_returns_empty_on_no_json_fence` — mock returns plain text; assert returns `[]`.
- `test_opus_parse_and_chunk_filters_unreadable_escape_hatch` — mock returns chunks list with one `[page 3: unreadable]` and one normal; assert only the normal one survives.
- `test_opus_parse_and_chunk_invalid_mode_raises` — `mode="bogus"` → `ValueError`.
- `test_ingest_v2_pure_scan_routes_to_images_mode` — monkeypatch `extract_page_text` to return `{1:"",2:""}`, capture `mode` arg passed to `opus_parse_and_chunk`; assert `mode=="images"`.
- `test_ingest_v2_text_layer_routes_to_document_mode` — monkeypatch `extract_page_text` to return `{1:"some text"}`, capture `mode`; assert `mode=="document"`.

## Open questions

None.
