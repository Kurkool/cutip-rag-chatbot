# Ingest Robustness — Pure-Scan OCR Fallback + Fail-Tracking

**Status:** Draft **Date:** 2026-04-22 **Branch:** TBD (spawn from `master`)

## Problem

On 2026-04-21 a single PDF (`ประกาศจุฬาฯ การกำหนดเกณฑ์การจ่ายเงิน พ.ศ. 2563.pdf`, 24 pages, 10.3 MB, PDFium-generated scan) was added to tenant `cutip_01`'s Drive folder. The hourly `scan-all` scheduler attempted to ingest it 8 times in 5 hours — each call burned a ~5-minute Opus 4.7 parse-and-chunk cycle and returned 0 chunks. No crash, no alert; the file was simply never retrievable in chat.

Root cause (two compounding bugs):

1. **`ingest_v2` has no handling for pure-scan PDFs.** The file had zero text-layer content across all 24 pages (pymupdf `get_text() == ""` everywhere). v2 sends the PDF as a `document` content block to Opus 4.7, relying on Anthropic's internal PDF-to-image rendering for vision OCR. On long dense Thai legal scans this empirically returns a `record_chunks` tool call with empty `chunks=[]` or all-empty-`text` entries. No refusal log, no parse error — just silent empty output. Historically proven v2 pipeline samples (`sample-doc/cutip-doc/`) all have text layers (Word→Distiller PDFs); pure-scan was never tested.

2. **`scan-all` state machine re-classifies 0-chunk failures as NEW every run.** `_process_gdrive_folder` decides NEW/RENAME/OVERWRITE/SKIP based on `get_existing_drive_state(namespace)` — a Pinecone lookup. When `ingest_v2` returns 0 chunks, no `ingest_ts` is written to Pinecone, so the next hourly scan sees the file as NEW and retries. There is no fail-counter. Costs (Opus time, Anthropic API spend) compound until someone manually removes the file from Drive.

Immediate fix (already done, 2026-04-21): user removed the file from Drive; `scripts/ocr_pdf_via_opus.py` produced a `.ocr.docx` via Haiku-style per-page LLM OCR which ingests successfully through the existing LibreOffice+fonts-thai-tlwg path.

This spec closes both gaps in the pipeline itself.

## Goals

- **C1:** When `ingest_v2` receives a PDF with zero text-layer content, auto-OCR per page via Haiku 4.5 vision, inject OCR'd text as a sidecar alongside the document block, then proceed to Opus parse-and-chunk as normal. Pure-scan PDFs become first-class citizens.
- **C2:** When any ingest attempt fails (0 chunks OR exception), record the failure in a new Firestore collection `ingest_failures`. After `MAX_CONSECUTIVE_FAILURES` consecutive failures for the same `(tenant_id, drive_file_id)`, `scan-all` skips the file until Drive `modifiedTime` advances (indicating user intervention). Stop the hammer.
- **Observability:** every decision (pure-scan detected, OCR start/end, failure recorded, cooldown skip) emits a structured `logger.info`.

## Non-goals

- Admin portal UI to surface / manage failing files. Firestore data will be available; a dedicated page is a follow-up spec.
- Manual "retry now" admin action.
- Time-based auto-retry (wait N hours and try again). `modifiedTime` change is the unblock signal; time-based retry is YAGNI.
- Fallback-on-0-chunk path (C1 "approach B"). Pre-flight detection is targeted at the known class; C2 stops hammering for any other 0-chunk cause (e.g., Opus bad day).
- Migration of existing Firestore / Pinecone state. Nothing to migrate — `ingest_failures` starts empty and self-populates.
- Changes to `/stage`, `/gdrive/file`, `/v2/gdrive`, `/v2/gdrive/file` endpoints. C1 runs for them automatically (internal to `ingest_v2`); C2 is scoped to the scan-all loop only.

## Architecture

```
file_bytes → ensure_pdf() → pdf_bytes
                              │
                              ▼
                    extract_page_text(pdf_bytes) → {page_n: str}
                              │
                    sum(len(text)) == 0 ?
                        ┌─────┴─────┐
                       YES         NO
                        │           │
                        ▼           │
              ocr_pdf_pages(pdf_bytes, filename)
                (Haiku 4.5 vision, async, semaphore=4)
                        │           │
                        ▼           ▼
                        ocr_sidecar (dict[int, str] | None)
                              │
                              ▼
              extract_hyperlinks(pdf_bytes)  (unchanged)
                              │
                              ▼
              opus_parse_and_chunk(
                pdf_bytes, hyperlinks,
                filename, ocr_sidecar=…)    ← new kwarg
                              │
                              ▼
                    chunks[]  →  _upsert(...)
```

`_process_gdrive_folder` wraps the outer call with C2 bookkeeping:

```
for drive_file in files:
    fail_rec = failures.get(drive_id)                      # from ingest_failures
    if fail_rec and fail_rec.fail_count >= MAX_FAILS:
        if drive_modified <= fail_rec.last_drive_modified:
            skip "FAIL_COOLDOWN"
            continue

    # existing SKIP / RENAME / OVERWRITE / NEW branches
    # on SKIP "up to date": opportunistic clear_failure
    try:
        chunks = await ingest_v2(...)
        if chunks == 0:
            await record_failure(..., "ingest returned 0 chunks")
            skipped.append(...)
        else:
            await clear_failure(...)
            ingested.append(...)
    except Exception as exc:
        await record_failure(..., exc)
        errors.append(...)
```

## Components

### C1.1 `extract_page_text(pdf_bytes: bytes) -> dict[int, str]`

Location: `ingest/services/ingestion_v2.py` (new).

Pymupdf-based per-page text extraction. Returns `{1: "...", 2: "...", ...}` keyed by 1-based page number.

Used for:
- Pre-flight pure-scan detection: `sum(len(t) for t in d.values()) == 0` → pure-scan.
- Could also feed the sidecar on hybrid PDFs (future; out of scope for this spec).

### C1.2 `ocr_pdf_pages(pdf_bytes: bytes, filename: str) -> dict[int, str]`

Location: `ingest/services/ingestion_v2.py` (new).

Async Haiku 4.5 vision OCR per page.

- Renders each page via `pymupdf.Document[i].get_pixmap(dpi=200).tobytes("png")`.
- Sends to Anthropic via the raw `anthropic.AsyncAnthropic` SDK (not `langchain_anthropic`) — matches the battle-tested pattern in `scripts/ocr_pdf_via_opus.py` and avoids a LangChain abstraction layer for a simple vision call. The `anthropic` package is already pinned in `requirements.txt`.
- Request shape: `{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}` + a Thai-first OCR prompt (reuse prompt text from `scripts/ocr_pdf_via_opus.py`).
- Parallelized with `asyncio.Semaphore(4)` and `asyncio.gather(..., return_exceptions=True)`.
- Per-page exception → log warning + empty string at that page key.
- All pages exception → raise `RuntimeError("OCR failed for all pages of <filename>")`.
- Returns `{1: "extracted text", 2: "...", ...}`.

Constants at module top:
```
OCR_MODEL = "claude-haiku-4-5-20251001"
OCR_CONCURRENCY = 4
OCR_DPI = 200
OCR_MAX_TOKENS_PER_PAGE = 4096
PURE_SCAN_TEXT_THRESHOLD = 0
```

Client factory: `_get_ocr_client()` (similar to `_get_opus_llm`) with `@lru_cache(maxsize=1)` — tests monkeypatch this.

### C1.3 `format_ocr_sidecar(ocr_text: dict[int, str]) -> str`

Location: `ingest/services/_v2_prompts.py` (add alongside `format_sidecar`).

Returns a markdown-like block (empty string if dict is empty or all values empty):

```
## OCR sidecar (per-page text extracted by Haiku 4.5 vision)

OCR may contain errors; treat the rendered image as ground truth and
the OCR text as assistive. Correct obvious mis-reads (e.g. mis-segmented
Thai tone marks, digit/letter confusion) by consulting the image.

### Page 1
<ocr text page 1>

### Page 2
<ocr text page 2>
```

### C1.4 `opus_parse_and_chunk(..., ocr_sidecar: dict[int, str] | None = None)`

Location: `ingest/services/ingestion_v2.py` (modify existing).

Signature extension only. `ocr_sidecar=None` → current behavior unchanged. When provided, append `format_ocr_sidecar(ocr_sidecar)` after the existing hyperlink sidecar in the user text block.

`USER_PROMPT_TEMPLATE` gets a new placeholder `{ocr_block}` after `{sidecar_block}`. When sidecar empty → empty string substitution (whitespace-only). No downstream prompt change needed for Opus.

### C1.5 `ingest_v2()` orchestration

Modify existing `ingest_v2()` in `ingest/services/ingestion_v2.py`:

```python
pdf_bytes = ensure_pdf(file_bytes, filename)
page_text = extract_page_text(pdf_bytes)
ocr_sidecar: dict[int, str] | None = None
if sum(len(t) for t in page_text.values()) <= PURE_SCAN_TEXT_THRESHOLD:
    logger.info("ingest_v2(%s): pure-scan detected (0 text chars / %d pages), running OCR", filename, len(page_text))
    ocr_sidecar = await ocr_pdf_pages(pdf_bytes, filename)

hyperlinks = extract_hyperlinks(pdf_bytes)
chunks = await opus_parse_and_chunk(pdf_bytes, hyperlinks, filename, ocr_sidecar=ocr_sidecar)
# ... existing 0-chunk warning + _upsert as today
```

No behavioral change for text-layer PDFs. Pure-scan triggers one extra code path: `ocr_pdf_pages`.

### C2.1 `shared/services/ingest_failures.py` (new module)

Thin async wrapper around Firestore collection `ingest_failures`. Document id is `f"{tenant_id}__{drive_file_id}"` (predictable key, no composite index needed, double-underscore separator avoids collision with underscore-permitted ids).

Schema:
```
ingest_failures/{doc_id}
  tenant_id           : str
  drive_file_id       : str
  filename            : str                (snapshot at fail time)
  fail_count          : int
  first_failed_at     : float              (unix)
  last_failed_at      : float              (unix)
  last_drive_modified : float              (unix — modifiedTime at fail time)
  last_error_short    : str                (≤200 chars: "<ExceptionType>: <msg truncated>")
```

API:

- `async get_failure(tenant_id: str, drive_file_id: str) -> dict | None`
- `async list_failures(tenant_id: str) -> dict[str, dict]` — keyed by `drive_file_id` for O(1) lookup by the state machine. Fetches via `where("tenant_id", "==", tenant_id)` in one round-trip.
- `async record_failure(tenant_id, drive_file_id, filename, drive_modified, error: Exception | str) -> None`
  - Uses `firestore.Increment(1)` for `fail_count`.
  - Uses `SetOptions(merge=True)` so `first_failed_at` is written only if missing.
  - On Firestore error: `logger.warning` + return (never raise).
- `async clear_failure(tenant_id: str, drive_file_id: str) -> None`
  - `.delete()`; ignore "not found".
  - On Firestore error: `logger.warning` + return.

Client factory: `_get_client()` monkeypatchable in tests.

Constants:
```
MAX_CONSECUTIVE_FAILURES = 3
```

### C2.2 `_process_gdrive_folder` integration

Modify `ingest/routers/ingestion.py::_process_gdrive_folder`.

**Parallel state fetch at the top of the function (only when `skip_existing=True`):**

```python
drive_state, legacy_filenames, failures = await asyncio.gather(
    asyncio.to_thread(get_existing_drive_state, namespace),
    asyncio.to_thread(_get_existing_filenames, namespace),
    ingest_failures.list_failures(tenant_id),
)
```

**Per-file decision (replaces the existing `if skip_existing:` block):**

```python
stale_filename_to_delete: str | None = None

if skip_existing:
    entry = drive_state.get(drive_id)

    # 1. SKIP up-to-date (successful state) — opportunistic failure-doc cleanup
    if entry is not None and entry["filename"] == filename and drive_modified <= entry["ingest_ts"]:
        await ingest_failures.clear_failure(tenant_id, drive_id)
        skipped.append({"filename": filename, "reason": "up to date"})
        continue

    # 2. LEGACY — pre-drive_file_id chunks; keep existing behavior
    if entry is None and filename in legacy_only:
        skipped.append({"filename": filename, "reason": "legacy, no drive_file_id"})
        continue

    # 3. FAIL_COOLDOWN — block further Opus calls once the streak hits MAX
    #    Applies to NEW / RENAME / OVERWRITE alike; unblock is always
    #    drive_modified advancing past the last recorded failure mtime.
    fail_rec = failures.get(drive_id)
    if (fail_rec
            and fail_rec["fail_count"] >= MAX_CONSECUTIVE_FAILURES
            and drive_modified <= fail_rec["last_drive_modified"]):
        skipped.append({
            "filename": filename,
            "reason": f"cooldown: {fail_rec['fail_count']} consecutive failures — edit the file in Drive to retry",
        })
        continue

    # 4. RENAME — mark stale chunks for deletion, then fall through to ingest
    if entry is not None and entry["filename"] != filename:
        stale_filename_to_delete = entry["filename"]
        logger.info("Drive rename detected (tenant=%s): %r → %r",
                    tenant_id, entry["filename"], filename)

    # Else: OVERWRITE (entry exists, same name, newer mtime) — fall through
    # Else: NEW (no entry, no legacy) — fall through

# Ingest path (new or existing file) with failure bookkeeping:
try:
    if stale_filename_to_delete:
        await asyncio.to_thread(delete_vectors_by_filename, namespace, stale_filename_to_delete)

    file_bytes = download_file(drive_id)
    chunks = await ingestion_v2.ingest_v2(...)

    if chunks == 0:
        await ingest_failures.record_failure(
            tenant_id, drive_id, filename, drive_modified, "ingest returned 0 chunks",
        )
        skipped.append({"filename": filename, "reason": "0 chunks produced"})
    else:
        await ingest_failures.clear_failure(tenant_id, drive_id)
        ingested.append({"filename": filename, "chunks": chunks})

except ValueError as exc:
    # Unsupported-ext etc. — user input problem, not pipeline. Not tracked as failure.
    skipped.append({"filename": filename, "reason": str(exc)})

except Exception as exc:
    logger.exception("Failed to ingest '%s'", filename)
    await ingest_failures.record_failure(
        tenant_id, drive_id, filename, drive_modified, exc,
    )
    errors.append({"filename": filename, "error": "ingestion failed"})
```

**Rationale for branch order (SKIP → LEGACY → COOLDOWN → RENAME → OVERWRITE/NEW):**

- SKIP up-to-date first so a successful ingest always clears any stale failure doc, even if the failure doc was never cleared after a prior manual recovery.
- COOLDOWN before RENAME: renaming a broken file in Drive does update `modifiedTime`, so a user-initiated rename with no content fix will advance `drive_modified > last_drive_modified`, which lifts cooldown naturally. No separate rename-bypass needed.
- COOLDOWN before OVERWRITE/NEW: this is where the hammer originates. Cut it here.

No change to `/v2/gdrive` (batch, `skip_existing=False`): forces re-ingest, does not read or write `ingest_failures`.

## Data flow — failure lifecycle

```
attempt 1  →  ingest_v2 returns 0 chunks
              → record_failure (fail_count=1, first=last=now, drive_mod=now)

attempt 2 (next hourly scan)
              → list_failures → fail_rec{count:1}
              → count < MAX (3) → proceed
              → ingest_v2 returns 0 chunks
              → record_failure (fail_count=2)

attempt 3
              → count < MAX → proceed
              → 0 chunks
              → record_failure (fail_count=3)

attempt 4 (next hour)
              → count >= MAX, drive_modified == last_drive_modified
              → SKIP "cooldown" — no Opus call
              → repeat N hours

user edits the file in Drive
              → Drive modifiedTime advances
              → scan next hour sees drive_modified > last_drive_modified
              → cooldown lifted → ingest_v2 called
              → success → clear_failure (doc removed)
              OR fail → record_failure (fail_count bumps to 4;
                        last_drive_modified updated → cooldown at 4 now
                        relative to new mtime)
```

## Error handling

**C1 — OCR path:**

| failure mode | behavior |
|---|---|
| Single page OCR raises (rate limit / timeout / parse) | log warning, set `ocr_sidecar[page_num] = ""` (partial OCR; Opus still has the vision block) |
| Every page raises | `ocr_pdf_pages` raises `RuntimeError("OCR failed for all pages of <filename>")` → `ingest_v2` propagates → `_process_gdrive_folder` catches → `record_failure` |
| Anthropic 429 / 5xx transient | `AsyncAnthropic(max_retries=3)` handles internally; only surfaces after exhaustion |
| Encrypted / corrupt / 0-byte PDF | `pymupdf.open()` raises in `extract_page_text` or `ensure_pdf` → bubbles up → `record_failure` |
| OCR succeeds but `opus_parse_and_chunk` still returns `[]` | treated the same as 0-chunk — `record_failure(..., "ingest returned 0 chunks")` |
| Very long pure-scan (>50 pages) | no hard limit; `ocr_pdf_pages` logs an informational `may take ~Ns` message for monitoring; Cloud Run 3600s timeout is the safety net |

**C2 — Firestore availability:**

| failure mode | behavior |
|---|---|
| `list_failures` Firestore unreachable | fall back to empty dict, log warning. Cooldown is temporarily disabled for this scan — non-fatal; one extra Opus call at worst |
| `record_failure` Firestore unreachable | log warning, do not raise. Failure state is lost for one round; self-heals on the next attempt |
| `clear_failure` Firestore unreachable | log warning, do not raise. Stale doc lingers one round; next SKIP-up-to-date path clears it opportunistically |
| Concurrent writes (scheduler + manual scan overlap — rare) | `firestore.Increment(1)` is server-atomic; `SetOptions(merge=True)` protects `first_failed_at` from being overwritten |

**Ingestion failure semantics:** `fail_count` increments on every recorded failure regardless of whether Drive `modifiedTime` has advanced. After a user edit that unblocks cooldown, the pipeline gets exactly **one** retry before cooldown may re-engage (if that retry also fails). If this proves too aggressive in practice, a future change can reset `fail_count` on mtime advance — but that requires a read-then-write transaction and is not in this scope.

## Testing

All three test modules live under `cutip-rag-chatbot/tests/`.

### `tests/test_ingestion_v2.py` (extend)

- `test_extract_page_text_text_layer_pdf` — one small Word→PDF fixture → all pages have positive chars.
- `test_extract_page_text_pure_scan_pdf` — one pymupdf-generated image-only PDF → all pages return 0 chars.
- `test_ocr_pdf_pages_success` — AsyncMock Anthropic client returns scripted content per page; assert `{1: "text-a", 2: "text-b"}` returned.
- `test_ocr_pdf_pages_partial_failure` — first page raises, second succeeds → `{1: "", 2: "text-b"}`.
- `test_ocr_pdf_pages_all_failure` — all raise → `RuntimeError` raised.
- `test_format_ocr_sidecar_empty` — `{}` returns empty string.
- `test_format_ocr_sidecar_populated` — dict formats as markdown block with per-page headers.
- `test_ingest_v2_pure_scan_triggers_ocr` — monkeypatch `ocr_pdf_pages` + `opus_parse_and_chunk`; assert OCR called and sidecar passed through.
- `test_ingest_v2_text_layer_skips_ocr` — text-layer PDF fixture → OCR not called, `opus_parse_and_chunk` called with `ocr_sidecar=None`.
- `test_opus_parse_and_chunk_prompt_includes_ocr_block` — when `ocr_sidecar` dict is non-empty, the user message contains formatted OCR section.

### `tests/test_ingest_failures.py` (new)

- `test_record_failure_creates_doc` — AsyncMock Firestore client; first call writes with `fail_count=1`, `first_failed_at` set.
- `test_record_failure_increments` — second call → `Increment(1)` used.
- `test_record_failure_firestore_outage_does_not_raise` — client raises; function returns None, warning logged.
- `test_clear_failure_deletes_doc`.
- `test_clear_failure_not_found_ok`.
- `test_get_failure_returns_none_for_missing`.
- `test_list_failures_returns_dict_keyed_by_drive_id` — 3 docs for tenant → dict of 3 entries keyed by drive_file_id.
- `test_list_failures_firestore_outage_returns_empty`.

### `tests/test_ingestion_router.py` (extend `_process_gdrive_folder` tests)

- `test_scan_fail_cooldown_blocks_after_max_fails` — `fail_count=3`, `drive_modified == last_drive_modified` → skip with "cooldown" reason; `ingest_v2` NOT called.
- `test_scan_fail_cooldown_unblocks_on_drive_modified` — `fail_count=5`, `drive_modified > last_drive_modified` → `ingest_v2` called.
- `test_scan_below_threshold_ingests` — `fail_count=2` → `ingest_v2` called.
- `test_scan_records_failure_on_zero_chunks` — `ingest_v2 returns 0` → `record_failure` called with "0 chunks" message.
- `test_scan_records_failure_on_exception` — `ingest_v2 raises` → `record_failure` called.
- `test_scan_clears_failure_on_success` — `ingest_v2 returns > 0` → `clear_failure` called.
- `test_scan_skip_up_to_date_clears_failure` — existing SKIP "up to date" path → `clear_failure` called opportunistically (stale doc cleanup).
- `test_scan_ordering_skip_wins_over_cooldown` — stale failure doc + up-to-date Pinecone entry → SKIP, NOT cooldown.

### Fixtures

Build PDFs programmatically in `tests/conftest.py` via pymupdf:
- `tiny_text_pdf_bytes` — one 1-page PDF with `insert_textbox` writing "hello"
- `pure_scan_pdf_bytes` — one 2-page PDF with only `insert_image` (no text layer)

## Rollout

1. Implement per TDD order: tests first (red), code to pass (green), refactor. Each commit small and passing.
2. Run `pytest tests/ -q` locally — all green, no regressions.
3. Deploy ingest-worker via existing Windows pattern:
   ```
   cp ingest/Dockerfile Dockerfile
   gcloud run deploy cutip-ingest-worker --source=. --region=asia-southeast1 --project=cutip-rag --quiet
   git checkout Dockerfile
   ```
   No Dockerfile change required (OCR uses the existing anthropic SDK already in `requirements.txt`).
4. Post-deploy smoke:
   - `POST /api/tenants/cutip_01/ingest/v2/gdrive/file?namespace_override=cutip_v2_audit` with a test upload of the historical scan PDF (still in `sample-doc/cutip-doc/`). Verify Cloud Run logs show `pure-scan detected` + `ocr_pdf_pages` + `Ingested '...' (N chunks)` with N > 0.
   - Observe next two hourly `scan-all` runs → existing 19 files still SKIP (up-to-date), no regression.
   - Re-upload the scan PDF to Drive (replace `.ocr.docx` from the interim workaround) → next scan-all picks it up as NEW → C1 pre-flight fires → `cutip_01` namespace gets the regulation chunks.
5. Rollback path: `gcloud run services update-traffic cutip-ingest-worker --to-revisions=cutip-ingest-worker-00027-wgm=100 --region=asia-southeast1`.

## Observability

New log lines (all `logger.info` except where noted):

- `ingest_v2(<filename>): pure-scan detected (0 text chars / <N> pages), running OCR`
- `ocr_pdf_pages(<filename>): OCR complete in <s>s — <N> pages, <total_chars> chars total, <failed> per-page failures` (INFO; WARNING if any per-page failures)
- `ingest_failures.record_failure: tenant=<tid> drive_id=<id> fail_count=<N> error=<short>`
- `ingest_failures.clear_failure: tenant=<tid> drive_id=<id>`
- `scan-all: FAIL_COOLDOWN skip tenant=<tid> drive_id=<id> filename=<n> fail_count=<N>`

Cloud Logging filter recipes for monitoring:
- `textPayload:"pure-scan detected"` — how often C1 fires
- `textPayload:"FAIL_COOLDOWN skip"` — how often C2 saves an Opus call
- `textPayload:"ingest_failures.record_failure"` — raw failure stream

## Open questions

None. Resolved in brainstorming:

- OCR model = Haiku 4.5 (cost-optimized).
- Trigger = pre-flight only; no fallback-on-0-chunk.
- Storage = standalone Firestore collection.
- Threshold = 3 consecutive fails.
- Unblock = Drive `modifiedTime` advance only.

## Follow-ups (separate specs)

- Admin portal page to list / clear failing files from the Firestore collection.
- Periodic cleanup job for orphan `ingest_failures` docs (file deleted from Drive).
- Hybrid-PDF OCR sidecar (even when text layer exists, feed OCR as ground-truth augmentation).
- Promote `scripts/ocr_pdf_via_opus.py` into a supported CLI tool or retire now that the pipeline handles it in-process.
