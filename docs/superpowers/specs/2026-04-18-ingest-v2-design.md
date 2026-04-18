# Ingestion v2 — Opus 4.7-first Universal Pipeline

**Status:** Draft  **Date:** 2026-04-18  **Branch:** `development-integration`

## Problem

Current ingestion (`ingest/services/ingestion.py`, ~720 LOC + chunking.py ~335 + enrichment.py ~175 + vision.py ~185 = ~1500 LOC total) is a rule-based accretion of bug fixes across 9 months:

- 5 format-specific paths (PDF / DOCX / XLSX / legacy / markdown)
- `has_text_layer → PyMuPDF` vs `no_text_layer → Claude Vision` routing
- `is_slides` / `has_tables` / `has_images` sub-rules
- 3 separate Anthropic models (Opus Vision for OCR, Haiku Vision for XLSX, Haiku Precise for enrichment)
- `_smart_chunk` (SemanticChunker via Cohere) + `_fix_table_boundaries` + `_chunk_pages`
- `_enrich_with_context` (per-chunk Haiku call)

Every new complex-doc shape (form with checkboxes, multi-column paper, vertical Thai text, embedded equations) = new `elif` branch + new test. Does not scale.

Audit on 2026-04-17 confirms the current pipeline works (24/24 names, 23/23 IDs, 20/20 bot probes) — the goal of v2 is **not to fix quality**, it is to **replace accretion with a simpler architecture** that handles novel doc types by prompt tuning rather than code branches.

## Architecture

Single universal path for all formats:

```
file_bytes ──► ensure_pdf() ────► pdf_bytes ──► extract_hyperlinks()
                                      │                 │
                                      ▼                 ▼
                              opus_parse_and_chunk(pdf_bytes, hyperlinks)
                                      │
                                      ▼
                                  chunks[]
                                      │
                                      ▼
                              _upsert() [reused, atomic swap + BM25 invalidate]
```

### Components

1. **`ensure_pdf(file_bytes: bytes, filename: str) -> bytes`** (~30 LOC)
   - `.pdf` → passthrough
   - `.docx/.doc/.xlsx/.xls/.pptx/.ppt` → LibreOffice headless convert
   - `.txt/.md/.csv` → inline wrap into a minimal PDF (keeps one code path)
   - Reuses `_convert_to_pdf()` from existing `ingestion.py`

2. **`extract_hyperlinks(pdf_bytes: bytes) -> list[dict]`** (~20 LOC)
   - Sidecar pre-extraction: PDF hyperlink URIs are not visible to Opus when sent as a file
   - Returns `[{"page": 1, "text": "ตรวจ Turnitin", "uri": "https://..."}, ...]`
   - Adapts existing `_extract_hyperlinks()` to accept bytes and return per-page list
   - **Explicitly out of scope for v1:** QR codes, form-widget metadata (add if audit shows need)

3. **`opus_parse_and_chunk(pdf_bytes, hyperlinks, filename) -> list[Document]`** (~100 LOC)
   - Single Opus 4.7 call via `anthropic.Messages.create` with:
     - `document` content block (PDF native, base64-encoded, mime `application/pdf`)
     - Hyperlink sidecar injected into system/user text
     - `tool_choice` forced to a `record_chunks` tool with JSON schema: `[{"text": str, "section_path": str, "page": int, "has_table": bool}, ...]`
   - Handles:
     - Adaptive-thinking content blocks (reuse `_extract_text_blocks` pattern from `vision.py`)
     - Rate limit via existing `call_with_backoff`
     - Refusal pattern filter (reuse `_looks_like_refusal`)
     - Tool-output JSON parse with retry on malformed
   - Each returned `Document` carries `page_content`, `metadata={"page", "section_path", "has_table"}`

4. **`ingest_v2(file_bytes, filename, namespace, tenant_id, ...) -> int`** (~40 LOC)
   - Pre-flight (reuse existing page-count / size guards)
   - `ensure_pdf` → `extract_hyperlinks` → `opus_parse_and_chunk` → `_upsert`
   - Reuses: `_build_metadata`, `_upsert` (atomic swap + URL cap + BM25 invalidate)

**Total target: ~190 LOC new code.** Replaces ~1100 LOC of format-specific paths + chunking + enrichment.

### What is reused unchanged

- `_upsert` (atomic-swap dedup, URL cap, BM25 invalidation, Firestore bump)
- `_build_metadata`
- `_delete_existing_vectors`
- `_convert_to_pdf` (LibreOffice)
- Vectorstore layer + Pinecone client
- Pre-flight guards (`PDF_MAX_PAGES`, `DOCX_MAX_IMAGES`, `XLSX_MAX_ROWS`)
- `call_with_backoff` resilience wrapper

### What is removed (after v2 proves out)

- `_smart_chunk` + `_fix_table_boundaries` + `_chunk_pages` → Opus does this
- `_enrich_with_context` → merged into the single Opus call
- `parse_page_image` / `interpret_spreadsheet` → Opus handles all formats
- Format dispatcher (5 paths) → single `ingest_v2` entrypoint
- `has_text_layer` / `has_tables` / `is_slides` routing — Opus decides

## Data flow

Input: uploaded file bytes + tenant metadata.

1. `ensure_pdf`: normalize to PDF. Non-PDF formats converted via LibreOffice. Keeps a single downstream type.
2. `extract_hyperlinks`: deterministic PyMuPDF pass over PDF to pull URIs that are visually hidden behind link text. Output is a compact list passed as sidecar.
3. `opus_parse_and_chunk`: Opus 4.7 receives the PDF as a document block, receives hyperlinks as structured sidecar text, and returns self-contained chunks via forced tool call. Chunk text already includes section context (Opus is prompted to prepend `[section > subsection]` where applicable) — no separate enrichment pass.
4. `_upsert`: embed with Cohere embed-v4.0, atomic-swap upsert into Pinecone, invalidate BM25 cache cross-process.

## Prompt strategy

System prompt (Opus 4.7):
- Role: document parser for Thai+English academic/administrative documents
- Objective: produce retrieval-ready chunks, each 300–1500 chars, self-contained, section-annotated
- Rules:
  - Preserve Thai characters exactly; no translation
  - Tables → markdown with headers preserved per chunk
  - Include hyperlink URIs inline as `[anchor](uri)` — sidecar provides URIs for visually-hidden links
  - Prepend `[section > subsection]` only when hierarchy is genuine (do not invent)
  - Slide decks: 1 slide = 1 chunk unless content is trivially short
  - Forms: capture field labels + checkbox states exactly
  - Diagrams: describe in `[brackets]` — do not fabricate

Tool: `record_chunks(chunks: [{"text": str, "section_path": str | null, "page": int, "has_table": bool}])`

## Error handling

| Failure | Response |
|---|---|
| LibreOffice conversion fail | `HTTPException 422` with filename (existing pattern) |
| Opus rate limit | `call_with_backoff` retry (existing helper) |
| Opus refusal string | Drop chunk, log warning (reuse `_looks_like_refusal`) |
| Opus tool-call malformed JSON | 1 retry with schema reminder; on 2nd fail: return `[]` and log |
| PDF too large for single call (>100 pages / >32MB) | Split into page batches of 30, merge chunk lists, dedup by `(page, section_path)` |
| Opus returns empty chunks | Return 0, surface to caller (existing behavior) |
| Adaptive-thinking content blocks (list[dict]) | Extract text blocks (reuse `_extract_text_blocks`) |

## Testing

### Unit tests (`tests/test_ingestion_v2.py`)

- `test_ensure_pdf_passthrough` — PDF input returns identical bytes
- `test_ensure_pdf_libreoffice_conversion` — DOCX input triggers conversion, returns PDF bytes
- `test_extract_hyperlinks_returns_hidden_uris` — synthetic PDF with hyperlink widget → URI extracted
- `test_opus_parse_mocked_response` — monkeypatched Opus returns valid tool-call → chunks built correctly
- `test_opus_refusal_filtered` — monkeypatched Opus returns refusal → chunk dropped
- `test_opus_malformed_json_retry` — first call returns bad JSON, second returns good → succeeds
- `test_ingest_v2_empty_chunks_returns_zero`
- `test_ingest_v2_calls_upsert_with_atomic_swap_metadata` — verify `source_filename` + `ingest_ts` stamped

### Integration test

Manual: ingest `sample-doc/cutip-doc/*` + `sample-doc/hsm-doc/*` into a dedicated Pinecone namespace `cutip_v2_audit`. No production traffic.

### Audit (primary success gate)

Run modified `scripts/full_audit.py --namespace cutip_v2_audit` + `scripts/ask_anything.py --namespace cutip_v2_audit`. Success criteria (match or beat v1 baseline recorded 2026-04-17):

| Metric | v1 baseline | v2 threshold |
|---|---|---|
| Files ingested | 14/14 | 14/14 |
| Entity coverage (names) | 24/24 | ≥ 24/24 |
| Entity coverage (IDs) | 23/23 | ≥ 23/23 |
| Vision-error chunks | 0 | 0 |
| Retrieval probes | 7/9 | ≥ 7/9 |
| Bot-answer probes | 20/20 | ≥ 19/20 (allow 1 variance for non-deterministic chunking) |

If v2 falls short on any hard metric → diagnose + iterate prompt before cutover. Do not cut over on "close enough."

## Rollout

1. **Phase 1** (this spec + writing-plans): build v2 alongside v1. No router change. `scripts/audit_v2.py` invokes `ingest_v2` directly on sample files, writes to `cutip_v2_audit` namespace.
2. **Phase 2:** audit v2 matches/beats v1 baseline. Decision: approve cutover or iterate.
3. **Phase 3:** feature flag `INGEST_V2_ENABLED` per-tenant in Firestore. Default off. Enable for one test tenant (not `cutip_01`).
4. **Phase 4:** enable for `cutip_01`. Re-run full audit. Monitor for 1 week.
5. **Phase 5:** remove v1 code paths (`_smart_chunk`, `_enrich_with_context`, `vision.py`, format dispatcher). Update docs.

Defense readiness: v1 remains the production path until Phase 4. v2 is a parallel experiment.

## Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Opus 4.7 PDF-native mode has lower Thai fidelity than image-render OCR | Medium | Audit compares per-file entity coverage; if gap found, add image-render fallback for specific filenames / doc_categories |
| Non-deterministic chunking breaks per-artifact diff audit | Medium | Tolerate ≤10% coverage variance; require ≥ baseline entity coverage (deterministic on content presence) |
| Single Opus call fails mid-doc → all chunks lost (vs current per-page Vision where 1 page can fail independently) | Medium | Page-batch splitter (30 pages/call) limits blast radius; `_upsert` atomic swap ensures no partial corrupt state |
| slide.pdf 45-page context > 200K tokens → long-context tax doubling cost | Low | Pricing acceptable at TIP-RAG scale (~$10/full re-ingest); batching already handles the limit |
| Hyperlink sidecar format confuses Opus / is ignored | Low | Prompt testing in Phase 1 with known-hyperlink sample (slide.pdf) before main audit |
| LibreOffice conversion in Cloud Run cold-start time | Low | Already in production path (`ingest_legacy`); no change |

## Out of scope for v1

- QR-code decoding (add if audit on `pdf-form.pdf` or incoming doc shows QR links)
- Form-widget metadata (add if audit on `pdf-form.pdf` shows Opus misreads checkboxes)
- Image-render fallback (add only if PDF-native audit reveals a class of failures)
- Chat-side retrieval changes (v2 ingestion produces chunks compatible with existing retrieval)

## Success = cut-over completion

v1 removed, v2 in production, audit scorecard matches baseline, bot QA ≥ 19/20, and LOC delta = –1100 / +190 = **–910 net lines, 6x simpler ingestion codebase.**
