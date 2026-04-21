# Ingest v2 — Text-Only Path for OCR'd Content

**Status:** Draft **Date:** 2026-04-22 **Branch:** `feat/ingest-robustness` (continuation)

## Problem

The [2026-04-22 ingest-robustness spec](./2026-04-22-ingest-robustness-design.md) shipped C1 (pure-scan pre-flight OCR) and C2 (fail-tracking cooldown) as `cutip-ingest-worker-00028-4vv`. C1's pre-flight detection and Haiku 4.5 per-page OCR both work correctly (24/24 pages OCR'd, ~45K chars extracted, sidecar reaches the Opus user prompt), **but Opus 4.7 parse+chunk still returns 0 chunks on `ประกาศจุฬาฯ…2563.pdf`** — the original failure mode persists.

Then on 2026-04-22 a second failure mode surfaced: the `.ocr.docx` workaround (pre-generated via `scripts/ocr_pdf_via_opus.py`) **also returns 0 chunks** when ingested through v2. Smart Scan on 2026-04-21 22:31 and 22:35 UTC both hit the same file:

```
ingest_v2(…2563.ocr.docx): Opus returned 0 chunks — nothing upserted
ingest_failures.record_failure: tenant=cutip_01 drive_id=1M4DYekeP5xJYmf4umy2a8qVha5sgOpaw error=ingest returned 0 chunks
```

Forensic analysis of the `.ocr.docx` (48,113 chars / 464 paragraphs of clean Thai legal text, readable by python-docx) revealed:

- `word/document.xml` contains **zero `<w:rFonts>` tags** — every run relies on the default style
- Default style font = `Courier` (Latin monospace, no Thai glyphs, no `w:cs=` for complex scripts)
- LibreOffice must substitute a Thai-capable font for every Thai character when rendering to PDF

Hypothesis (shared between both failure modes): sending a PDF `document` content block to Opus for OCR'd/problem-font content forces Opus to reconcile vision extraction vs. text-layer content. On long dense Thai legal documents this empirically triggers a silent-empty `record_chunks` tool call — no refusal log, no parse error, just `chunks=[]`.

Two-thirds of this spec's prior work (pre-flight OCR extraction, failure tracking) is sound and stays. What needs to change is how we hand the OCR'd content to Opus.

## Goals

- **Text-only path to Opus when content is already OCR'd.** Drop the `document` content block entirely. Send the OCR'd text as a single `text` block with page delineation, preserving smart-chunking semantics (`page`, `section_path`, `has_table`) via the existing `record_chunks` tool schema.
- **Unify two input sources into one downstream path.** Pure-scan PDFs (C1's Haiku OCR) and `.ocr.docx` files (paragraph extraction) both normalize to `ocr_sidecar: dict[int, str]`, then feed a single text-only branch in `opus_parse_and_chunk`.
- **Preserve Opus as smart chunker.** No dumb text splitter. Chunks retain section hierarchy, page numbers, and table flags.
- **Backward compatible.** Text-layer PDFs, non-OCR'd DOCX/XLSX/PPTX — all unchanged.

## Non-goals

- Regenerating existing `.ocr.docx` files with better font declarations. The text-only path removes the LibreOffice+Opus-vision dependency, making font declarations irrelevant.
- Automatic fallback to a dumb text splitter when Opus returns 0 chunks even on the text-only path. If Opus fails on plain text, that's a new failure class — out of scope. C2 cooldown already stops the hammer.
- Changing detection for pure-scan PDFs. C1's existing `sum(len(text)) == 0` trigger is retained untouched.
- Exposing a manual "force text-only" admin flag. Detection is deterministic from filename / content.
- Deprecating `scripts/ocr_pdf_via_opus.py` or the `.ocr.docx` convention. The script remains useful for producing a Drive-ingestible artifact from pure-scan PDFs; this spec just makes the artifact ingestable.

## Architecture

```
ingest_v2(file_bytes, filename, …)
  │
  ├─ Branch A: filename.lower().endswith(".ocr.docx")
  │     │
  │     ▼
  │     ocr_sidecar = _read_ocr_docx_as_pages(file_bytes)    # NEW
  │     pdf_bytes   = None
  │     hyperlinks  = []
  │
  ├─ Branch B: ensure_pdf + extract_page_text → pure-scan
  │     │
  │     ▼
  │     ocr_sidecar = await ocr_pdf_pages(pdf_bytes, filename)  # existing C1
  │     hyperlinks  = extract_hyperlinks(pdf_bytes)
  │
  └─ Branch C: ensure_pdf + extract_page_text → has text layer
        │
        ▼
        ocr_sidecar = None
        hyperlinks  = extract_hyperlinks(pdf_bytes)

                             │
                             ▼
        opus_parse_and_chunk(pdf_bytes, hyperlinks, filename, ocr_sidecar=…)
                             │
              ┌──────────────┴──────────────┐
              │                             │
      ocr_sidecar is not None       ocr_sidecar is None
              │                             │
              ▼                             ▼
      TEXT-ONLY content block       PDF document block + text block
      (no document block)            (existing behaviour, unchanged)
              │                             │
              └──────────────┬──────────────┘
                             ▼
                  Opus calls record_chunks(chunks=[…])
                             │
                             ▼
                        _upsert(chunks, …)
```

## Components

### New: `_read_ocr_docx_as_pages(file_bytes: bytes) -> dict[int, str]`

Lives in `ingest/services/ingestion_v2.py` alongside `ocr_pdf_pages`.

Reads a `.ocr.docx` produced by `scripts/ocr_pdf_via_opus.py` and reconstructs the per-page dict that mirrors `ocr_pdf_pages`'s output. The script's convention:

- `docx.add_heading(pdf_path.stem, level=1)` — document title, ignored
- `docx.add_heading(f"หน้า {page_num + 1}", level=2)` — page markers (1-indexed text)
- `docx.add_paragraph(line)` — content lines for that page

Parser walks `Document.paragraphs` in order. A paragraph with `style.name == "Heading 2"` matching `r"^หน้า\s+(\d+)$"` opens a new page bucket; all subsequent non-heading paragraphs accumulate into that bucket's text (joined with `\n`). Paragraphs before the first `หน้า` heading are discarded (the title heading).

Fallback: if no `หน้า N` heading is found (malformed docx, or produced by a different tool), return `{1: "all_paragraphs_joined"}` — better to attempt ingestion as single-page than to fail outright.

Returns `dict[int, str]` keyed by 1-based page number. Raises `ValueError` if python-docx cannot open the bytes (corrupted docx).

### Modified: `ingest_v2()`

Insert the `.ocr.docx` branch at the top of the function, before `ensure_pdf`:

```python
ext = os.path.splitext(filename)[1].lower()
is_ocr_docx = filename.lower().endswith(".ocr.docx")

if is_ocr_docx:
    ocr_sidecar = _read_ocr_docx_as_pages(file_bytes)
    pdf_bytes = None
    hyperlinks: list[dict] = []
    logger.info(
        "ingest_v2(%s): .ocr.docx detected — %d pages, %d total chars, skipping LibreOffice + PDF path",
        filename, len(ocr_sidecar), sum(len(t) for t in ocr_sidecar.values()),
    )
else:
    pdf_bytes = ensure_pdf(file_bytes, filename)
    page_text = extract_page_text(pdf_bytes)
    total_text_chars = sum(len(t) for t in page_text.values())
    if total_text_chars <= PURE_SCAN_TEXT_THRESHOLD:
        logger.info(
            "ingest_v2(%s): pure-scan detected (0 text chars across %d pages), running OCR",
            filename, len(page_text),
        )
        ocr_sidecar = await ocr_pdf_pages(pdf_bytes, filename)
    else:
        ocr_sidecar = None
    hyperlinks = extract_hyperlinks(pdf_bytes)

chunks = await opus_parse_and_chunk(
    pdf_bytes, hyperlinks, filename, ocr_sidecar=ocr_sidecar,
)
```

The rest of `ingest_v2` (chunk-empty check, metadata build, `_upsert` call) is unchanged.

### Modified: `opus_parse_and_chunk()`

Signature changes `pdf_bytes: bytes` → `pdf_bytes: bytes | None`.

Logic splits on `ocr_sidecar`:

```python
if ocr_sidecar is not None:
    # Text-only path
    page_text_block = _format_pages_for_text_only(ocr_sidecar)
    sidecar_block = format_sidecar(hyperlinks)
    user_text = USER_PROMPT_TEMPLATE_TEXT_ONLY.format(
        filename=filename,
        page_text_block=page_text_block,
        sidecar_block=sidecar_block,
    )
    human_content = [{"type": "text", "text": user_text}]
else:
    # Existing PDF path (unchanged)
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    user_text = USER_PROMPT_TEMPLATE.format(
        filename=filename,
        sidecar_block=format_sidecar(hyperlinks),
        ocr_block=format_ocr_sidecar({}),
    )
    human_content = [
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64}},
        {"type": "text", "text": user_text},
    ]

messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=human_content)]
# bind_tools + ainvoke + tool_calls processing unchanged
```

The `ocr_block` kwarg to the old template is now unused on the PDF path (always empty) — the text-only path subsumes its purpose. Clean up by dropping `ocr_block` and `format_ocr_sidecar` from the PDF template in a follow-up; for this spec, leave them in place for diff minimalism.

### New: `_format_pages_for_text_only(ocr_sidecar: dict[int, str]) -> str`

Format the per-page OCR text with explicit page boundaries that Opus can parse for the `page` chunk field:

```
=== Page 1 ===
<page 1 text>

=== Page 2 ===
<page 2 text>
…
```

Page markers use `===` bars (distinct from any markdown headings in content) so Opus can unambiguously attribute each chunk to the right page.

### New: `USER_PROMPT_TEMPLATE_TEXT_ONLY`

Lives in `ingest/services/_v2_prompts.py`. Parallel to existing `USER_PROMPT_TEMPLATE`:

```python
USER_PROMPT_TEMPLATE_TEXT_ONLY = """\
Filename: {filename}

The document below has been pre-OCR'd; no PDF is attached. Use the text as the sole source of truth and produce chunks via record_chunks().

Page boundaries are marked with `=== Page N ===` — use them to set each chunk's `page` field.

{sidecar_block}

{page_text_block}
"""
```

The existing `SYSTEM_PROMPT` instructing Opus to call `record_chunks` + produce `{page, section_path, has_table, text}` entries is reused unchanged.

## Data flow (text-only branch, end-to-end)

1. `POST /api/tenants/cutip_01/ingest/gdrive/scan` routes a `.ocr.docx` file to `ingest_v2`.
2. `ingest_v2` detects `.ocr.docx` suffix → calls `_read_ocr_docx_as_pages(file_bytes)` → `{1: "page 1…", 2: "page 2…", …, 24: "page 24…"}`.
3. `pdf_bytes = None`, `hyperlinks = []`.
4. `opus_parse_and_chunk(None, [], filename, ocr_sidecar={…})` → takes text-only branch.
5. `_format_pages_for_text_only` builds the page-delineated string.
6. Single Anthropic message to Opus: SystemMessage + HumanMessage with one `text` content block (no `document` block).
7. Opus calls `record_chunks` with N chunks, each `{page, section_path, has_table, text}` populated normally.
8. `opus_parse_and_chunk` filters empty-text / refusal chunks (unchanged), returns `list[Document]`.
9. `_upsert` embeds with Cohere, writes to Pinecone, runs atomic older-than-ts dedup, bumps BM25 ts.
10. Response: chunk count.

For the pure-scan PDF branch, steps 1-3 differ (runs Haiku OCR to produce `ocr_sidecar`) but 4-10 are identical.

## Error handling

| Failure | Handling |
|---|---|
| `_read_ocr_docx_as_pages` — docx won't open (corrupt) | Raise `ValueError`; caller `ingest_v2` propagates; `ingest_failures.record_failure` in outer scan-all loop. |
| `_read_ocr_docx_as_pages` — no `หน้า N` headings | Fallback to `{1: all_paragraphs_joined}`; log warning. |
| Opus returns 0 chunks on text-only path | Same as existing: log warning, return 0, `ingest_failures.record_failure`, C2 cooldown after 3 consecutive. |
| Opus returns `no tool_call` (refusal) | Existing log warning path, return `[]`. |
| Thai text longer than Opus output budget | Not expected (text-only removes the PDF+vision overhead that was causing the budget exhaustion hypothesis), but if it happens, same 0-chunks handling. Future work: split `.ocr.docx` into half-page batches if single-call fails. |

No rollback flag. If the text-only path regresses `.ocr.docx` or pure-scan ingest, revert is `git revert` + redeploy. Text-layer PDFs are untouched, so blast radius is confined to the two known broken classes.

## Testing

Added to `tests/test_ingestion_v2.py` (currently 11 tests):

- **`test_read_ocr_docx_as_pages_splits_on_page_headings()`** — build a fake docx with `docx.add_heading("หน้า 1", level=2)` + paragraphs + `หน้า 2` + paragraphs; assert return dict splits correctly by page with paragraphs joined by `\n`.
- **`test_read_ocr_docx_as_pages_fallback_single_page_when_no_markers()`** — build a fake docx without any `หน้า` headings; assert returns `{1: <all_text>}`.
- **`test_read_ocr_docx_as_pages_raises_on_corrupt_bytes()`** — pass `b"not a zip"`; assert raises `ValueError`. Implementation wraps python-docx's `docx.opc.exceptions.PackageNotFoundError` in `ValueError` so callers get a stable exception type.
- **`test_ingest_v2_ocr_docx_skips_libreoffice_and_extract_hyperlinks()`** — monkeypatch `_convert_to_pdf` and `extract_hyperlinks` to raise if called; monkeypatch `opus_parse_and_chunk` to capture args; ingest a `.ocr.docx` sample; assert LibreOffice never called, `pdf_bytes` is None, `ocr_sidecar` populated.
- **`test_opus_parse_and_chunk_text_only_omits_document_block()`** — monkeypatch `_get_opus_llm` to return a mock whose `bind_tools().ainvoke()` captures the `messages` arg; call with `ocr_sidecar={1: "…", 2: "…"}`; assert the human message content has exactly one `text` block and NO `document` block.
- **`test_opus_parse_and_chunk_pdf_path_includes_document_block()`** — same mock pattern; call with `ocr_sidecar=None`; assert human message has both `document` and `text` blocks (regression guard for the untouched path).
- **`test_opus_parse_and_chunk_text_only_includes_page_markers()`** — call with `ocr_sidecar={1: "A", 2: "B"}`; assert the captured text block contains `=== Page 1 ===\nA` and `=== Page 2 ===\nB`.

Integration smoke (manual, post-deploy): Smart Scan on `cutip_01` with the existing `.ocr.docx` file in Drive → expect > 0 chunks upserted, Pinecone count matches sum of page text character counts roughly.

## Open questions

None. Design is concrete enough to write a TDD task plan against.
