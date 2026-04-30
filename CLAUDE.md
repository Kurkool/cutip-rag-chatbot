# VIRIYA (วิริยะ) — Claude Code Project Guide

**Product:** VIRIYA — *Relentlessly Relevant.* (formerly "CU TIP RAG Chatbot"). Multi-tenant agentic RAG platform for Thai university faculties.
**Owner:** Kurkool Ussawadisayangkool (CU-TIP master's thesis, 6780016820).
**Status:** Production v5.0.0 on `master` — v2 universal ingestion is sole path (post-2026-04-19 cutover); v2.1 hardening complete (2026-04-19); VIRIYA rebrand complete (2026-04-20). **Phase 1 image-blocks + JSON-fence rewrite complete on `feat/ingest-robustness` (2026-04-29) — 39 commits ahead of `master`, deployed as `cutip-ingest-worker-00032-j48`, NOT YET MERGED to master.** v1 code preserved on `legacy` branch for thesis reference only.
**GCP Project:** `cutip-rag` · **Region:** `asia-southeast1` · **Firestore DB:** `(default)` · **Pinecone Index:** `university-rag` (1536d, cosine).

## Read first (long-form context)

- [`docs/architecture.md`](docs/architecture.md) — **13 sections** (post-revision 2026-04-20 for IS submission). §4 primary v2 pipeline; §11 evolution v1→v2→v2.1; §12 file lifecycle semantics (drive_file_id rename-safe, delete order); §13 Drive Connect flow.
- [`docs/thesis-project-detail.md`](docs/thesis-project-detail.md) — 24 sections, thesis-grade detail (post-revision 2026-04-20). §§7.1–7.5 marked historical; §7.6 expanded v2 evolution narrative; **§7.7 NEW** — v2.1 post-demo hardening (9 subsections).
- [`docs/superpowers/specs/2026-04-18-ingest-v2-design.md`](docs/superpowers/specs/2026-04-18-ingest-v2-design.md) — v2 spec (master).
- [`docs/superpowers/plans/2026-04-18-ingest-v2.md`](docs/superpowers/plans/2026-04-18-ingest-v2.md) — v2 13-task TDD plan (complete, master).
- [`docs/superpowers/specs/2026-04-22-ingest-v2-image-blocks-design.md`](docs/superpowers/specs/2026-04-22-ingest-v2-image-blocks-design.md) — **Phase 1 spec (current production code)** — image blocks for pure-scan + JSON-fence output, dropping `bind_tools`/`tool_choice`. On `feat/ingest-robustness`.
- [`docs/superpowers/plans/2026-04-22-ingest-v2-image-blocks.md`](docs/superpowers/plans/2026-04-22-ingest-v2-image-blocks.md) — Phase 1 7-task TDD plan (complete).
- [`docs/superpowers/specs/2026-04-22-ingest-v2-text-only-path-design.md`](docs/superpowers/specs/2026-04-22-ingest-v2-text-only-path-design.md) — **superseded** by image-blocks design; kept for history (text-only `.ocr.docx` path; empirically failed → replaced).
- [`docs/superpowers/plans/2026-04-22-ingest-v2-text-only-path.md`](docs/superpowers/plans/2026-04-22-ingest-v2-text-only-path.md) — superseded plan.
- **Architecture docs are stale vs current code** — `docs/architecture.md` and `docs/thesis-project-detail.md` describe master's `tool_choice="auto"` + `record_chunks` tool pipeline. They were submitted with IS thesis 2026-04-20 and have NOT been updated to reflect Phase 1. For thesis defense, frame Phase 1 as "post-submission iteration after empirical smoke test exposed root cause" — see Known pending state below.

## Repo layout

This `CLAUDE.md` lives **inside** the `cutip-rag-chatbot/` git repo — the Python backend. Two sibling directories live OUTSIDE this repo (cloned/synced separately):
- `../admin-portal/` — Next.js 16 frontend (own git repo, own `CLAUDE.md` pointing at an `AGENTS.md` warning about Next.js 16 breaking changes)
- `../sample-doc/` — not version-controlled (PDPA-sensitive PDFs); `cutip-doc/` (14 files, GDrive folder `1duGSSJxj9g-A2dxNTLROnjBPn7V08aMk`) + `hsm-doc/` (8 files, deferred tenant)

```
cutip-rag-chatbot/              ← this repo (git)
├── CLAUDE.md                   ← this file
├── chat/                       ← LINE webhook + agentic RAG + search
├── ingest/                     ← document pipeline (v2 Opus 4.7 universal, v1 removed 2026-04-19)
│   ├── services/
│   │   ├── ingest_helpers.py     (helpers: _build_metadata, _convert_to_pdf, _delete_existing_vectors, _upsert)
│   │   ├── ingestion_v2.py       (main pipeline — ensure_pdf → extract_hyperlinks → Opus parse+chunk → _upsert)
│   │   ├── _v2_prompts.py        (v2 system prompt — JSON-fence output; tool schema removed in Phase 1)
│   │   ├── vision.py             (only _looks_like_refusal — filters Opus "can't read this" responses)
│   │   └── gdrive.py
│   └── routers/ingestion.py      (thin-wrapper routes: /document, /spreadsheet, /gdrive, /gdrive/scan, /gdrive/file, /v2/gdrive, /v2/gdrive/file — all call ingest_v2)
├── admin/                      ← tenants, users, analytics, privacy, backup
├── shared/                     ← config, schemas, middleware, auth, llm factory, firestore, vectorstore
├── scripts/                    ← audit + reingest + smoke tools (see below)
├── tests/                      ← 237 backend tests (pytest, asyncio auto) — frontend has 29 Vitest; total 266
├── Dockerfile                  ← chat-api default; see Deploy for swap pattern
├── {chat,ingest,admin}/Dockerfile
├── pytest.ini
└── docs/
    ├── architecture.md, thesis-project-detail.md
    └── superpowers/{specs,plans}/   ← design specs + implementation plans
```

## Dev environment (Windows + bash)

- **Shell:** Git Bash (Unix syntax, `/c/Users/...` paths).
- **Python venv:** `cutip-rag-chatbot/.venv/Scripts/python.exe` (Windows layout — use `.venv/Scripts/`, NOT `.venv/bin/`).
- **Run tests from:** `cutip-rag-chatbot/` dir.
- **Run scripts with:** `PYTHONPATH=. .venv/Scripts/python.exe scripts/<name>.py` (the `PYTHONPATH=.` is required for `from ingest.services ...` imports — needed because `scripts/` is a sibling to the package dirs).

### Common commands

```bash
# Tests (from cutip-rag-chatbot/)
.venv/Scripts/python.exe -m pytest tests/ -q            # all 279 tests
.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -v   # v2 module (11 tests)

# Audit tools (read-only against Pinecone + chat probes against /api/chat)
.venv/Scripts/python.exe scripts/full_audit.py                        # v1 prod (ns cutip_01)
.venv/Scripts/python.exe scripts/full_audit.py --namespace cutip_v2_audit   # v2 pilot audit
.venv/Scripts/python.exe scripts/ask_anything.py                      # 20 adversarial bot probes
PYTHONPATH=. .venv/Scripts/python.exe scripts/audit_v2.py             # drive v2 ingest over sample-doc (local — LibreOffice missing locally so non-PDF skipped)

# Single-file v2 ingest retry (Cloud Run endpoint, handles any format via LibreOffice)
# use when transient GDrive flakes stranded a file during batch /v2/gdrive
```

### Secrets

- Canonical source: **GCP Secret Manager** in project `cutip-rag`.
  - `ANTHROPIC_API_KEY`, `PINECONE_API_KEY`, `COHERE_API_KEY`, `ADMIN_API_KEY`.
- Local `.env` (at `cutip-rag-chatbot/.env`, gitignored) is read by `pydantic-settings` for local runs. **Can go stale** — prefer fetching fresh from Secret Manager in scripts: `gcloud secrets versions access latest --secret=<NAME>` (pattern used by `audit_v2.py`, `full_audit.py`, `ask_anything.py`).
- Cloud Run services mount secrets via `--set-secrets` (see Deploy).
- **Never paste API keys in chat or commit them.** If one leaks in session history, rotate immediately.

## Tech stack (short)

- **Agent:** Claude Opus 4.7 (`claude-opus-4-7`) with `thinking={"type": "adaptive"}`. No `temperature`/`top_p`/`top_k` — Opus 4.7 rejects them.
- **OCR (v1) + parse-and-chunk (v2):** Opus 4.7 via `shared/services/llm.py::get_ocr_llm` (v1, master) and `ingest/services/ingestion_v2.py::_get_opus_llm` (v2). On `master`: v2 uses `tool_choice="auto"` + `record_chunks` tool, max_tokens=32000. On `feat/ingest-robustness` (Phase 1): NO tool binding (free-form text + JSON-in-markdown-fence output), max_tokens=128000, timeout=600s, adaptive thinking enabled. See gotchas #2/#3/#18 for full details.
- **Utility LLM:** Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) for rewrite, decompose, multi-query, summarize, enrichment, spreadsheet-layout interp.
- **Embeddings:** Cohere `embed-v4.0` (1536d).
- **Reranker:** Cohere Rerank v3.5 with retry + neutral-0.5 fallback.
- **Vector store:** Pinecone serverless, one namespace per tenant (`cutip_01` is prod; `cutip_v2_audit` is v2 pilot).
- **Backend:** FastAPI + Uvicorn on Cloud Run (asia-southeast1).
- **Frontend:** Next.js 16 + shadcn/ui (see `admin-portal/CLAUDE.md` for Next.js 16 gotchas).
- **LangChain:** `langchain-anthropic`, `langchain-core`, `langchain-cohere`, `langchain-pinecone`, `langchain-experimental` (SemanticChunker). Lazy-imported where possible — `langchain_cohere` alone pulls ~6200 modules.

## Deploy (Windows quirks)

`gcloud run deploy --source=.` does **not** accept `--dockerfile`. Pattern:

```bash
cd cutip-rag-chatbot/
cp {service}/Dockerfile Dockerfile          # chat | ingest | admin
gcloud run deploy cutip-{service}-api --source=. --region=asia-southeast1 --project=cutip-rag --quiet
git checkout Dockerfile                     # restore chat Dockerfile (chat is the root default)
```

- **chat-api:** needs `--min-instances=1` (avoid LINE webhook cold-start timeout).
- **ingest-worker:** needs `--timeout=3600` (long batch ingests).
- **admin-api:** needs `--timeout=600` (Pinecone backup headroom).
- Secrets on deploy: `--set-secrets "PINECONE_API_KEY=PINECONE_API_KEY:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,COHERE_API_KEY=COHERE_API_KEY:latest,ADMIN_API_KEY=ADMIN_API_KEY:latest"`.
- `.gcloudignore` exists at `cutip-rag-chatbot/` — excludes `.venv/`, `tests/`, `docs/`, etc. Cloud Build falls back to `.gitignore` if this is missing; don't rely on `.gitignore` alone.

Cloud Run URLs (stable): `https://cutip-{service}-265709916451.asia-southeast1.run.app` where `{service}` is `chat-api`, `ingest-worker`, `admin-api`, `admin-portal`.

### Current deployed revisions (as of 2026-04-20)

- `cutip-chat-api-00024-gcr` — **rewriter bias fixed**: short-circuit Haiku on queries without follow-up markers (prevents empirically-observed 'ดาวน์โหลด/ฟอร์ม/เกณฑ์' qualifier injection on simple Thai noun queries); tighter `_REWRITE_PROMPT`; ANTHROPIC_API_KEY v7
- `cutip-ingest-worker-00032-j48` — **CURRENTLY DEPLOYED, from `feat/ingest-robustness` branch (NOT yet on master).** Phase 1 image-blocks + JSON-fence rewrite + max_tokens=128K + timeout=600s. Successfully ingested 35 chunks for `ประกาศจุฬาฯ 2563.pdf` (24-page Thai legal pure-scan) via auto-scheduler at 2026-04-28T22:09 UTC under prior rev `00030-mbt` — verified production behavior. Stack: image blocks for pure-scan, document block for text-layer, free-form text response with JSON fence, salvage helper for max_tokens-truncated output, C2 fail-tracking + cooldown, scan-all 5-state machine (NEW/RENAME/OVERWRITE/SKIP/COOLDOWN).
- `cutip-ingest-worker-00027-wgm` — **last revision deployed from master.** scan-all NEW/RENAME/OVERWRITE/SKIP via `drive_file_id` + `modifiedTime`. Uses `tool_choice="auto"` + `record_chunks` tool (silent-fails on pure-scan). +v2 cutover (ingest_helpers.py 215 lines, vision.py 35 lines, `chunking.py` + `enrichment.py` deleted; v1 archived on `legacy`). +`fonts-thai-tlwg`.
- `cutip-admin-api-00015-dsl` — **`gdrive.delete_file` retries 3× with exp backoff** on transient (5xx, 429, rateLimitExceeded). Pinecone-first delete order preserved. + atomic single-file delete + editable Pinecone namespace + Drive Connect endpoint + Stage Upload endpoint.
- `cutip-admin-portal-00019-b7s` — **VIRIYA (วิริยะ) logo added**: icon-mark SVG in sidebar (h-7 w-7), login page (h-8 w-8 in h-14 container), register page (same pattern). Logo files at `public/logo/viriya-{icon-mark,logo-horizontal,logo-primary}.svg`. + prior deploys: rebrand "CU TIP RAG" → "VIRIYA" in metadata/titles, Connect Drive button, Stage Upload, trash icon per row, editable Pinecone namespace. Note: revs 00016/00017 had Cloud Build race → overwrote full-brand with partial; 00018+ cleared.

## Branch conventions

- `master` — production. Docs revised for IS submission live here (architecture.md 733 lines / 13 sections; thesis-project-detail.md 1696 lines / added §7.7).
- `legacy` — v1 reference branch (pre-cutover snapshot, thesis reference only, don't merge forward).
- **User commits themselves** — you can stage + commit when task is complete, but **user pushes to remote**.

## Testing conventions

- TDD for all new code: failing test → minimal implementation → passing test → commit.
- Tests live in `cutip-rag-chatbot/tests/`. Module-level test files mirror source: `test_ingestion_v2.py`, `test_bm25.py`, etc.
- `pytest.ini` has `asyncio_mode = auto` but v2 tests use explicit `@pytest.mark.asyncio` for clarity.
- When a test file imports a module that transitively pulls `langchain_cohere`, expect ~7s startup overhead (intentional lazy imports in `shared/services/embedding.py` and `vectorstore.py` — don't break them).

## Critical gotchas (cross-machine)

1. **Opus 4.7 adaptive thinking returns `content: list[dict]`**, not `str`. Both `chat/services/agent.py::run_agent` and `ingest/services/vision.py::parse_page_image` must extract text blocks explicitly. Missing this = intermittent pydantic-500 with stringified list as answer.
2. **Thinking + forced `tool_choice` = 400; `tool_choice="auto"` lets Opus opt out on long Thai legal scans.** On `master`, v2 uses `tool_choice="auto"` + `record_chunks` tool — empirically required for 45-page slide.pdf (0 → 43 chunks) but Opus *silent-fails* on long pure-scan Thai docs (returns text content with no `tool_calls` populated → 0 chunks). **On `feat/ingest-robustness` (Phase 1), v2 drops `bind_tools` entirely** — Opus emits free-form text containing one ` ```json ` fence parsed in Python via `_extract_json_from_fence`. Mirrors what claude.ai does internally. Adaptive thinking stays enabled (no 400 because no forced tool).
3. **Opus output needs `max_tokens=128000` + `timeout=600s` (Phase 1 / Opus 4.7 ceiling).** Adaptive thinking shares the output budget with text. Empirically a 24-page Thai legal scan emits ~44K out_tok on success and got cut at 32K on a prior failure — 128K gives ~3× headroom. The langchain SDK refuses non-streaming requests with very large `max_tokens` (estimated >10min); explicit `timeout=600.0` bypasses that guard. Cloud Run `--timeout=3600` accommodates. **Salvage helper** (`_salvage_complete_chunks_from_truncated`) recovers complete chunk objects from JSON output that gets cut mid-array. *(On master, v2 uses `max_tokens=32000` + `record_chunks` tool — a 23-entry JSON array silently truncated at 8K before that bump.)*
4. **LangGraph silent "Sorry, need more steps..." fallback** when `remaining_steps < 2` with pending tool_calls. NOT an exception. Detect + replace (see `chat/services/agent.py::_LANGGRAPH_STEPS_FALLBACK`).
5. **PDF routing: `has_tables → Vision` is wrong.** Check text-layer size first (`len(text) >= PDF_VISION_THRESHOLD`). Vision-on-tables dropped 23/23 Thai names on an announcement PDF before the fix. v2's universal path sidesteps this entirely.
6. **Pinecone stores numeric metadata as doubles** — `page` int `1` comes back as `1.0`. Anywhere we render page numbers, use `chat/services/reranker.py::_fmt_page`.
7. **`is_thai` uses script dominance, not mere presence.** English queries referencing a Thai program name should route to English error messages.
8. **Multi-sheet XLSX dedup race.** All sheets of one file must go through a single `_upsert` call. Per-sheet upserts wipe each other because dedup is keyed on `source_filename` + `older_than_ts`.
9. **LibreOffice packages** — `libreoffice-core libreoffice-writer` alone handles .doc/.docx only. XLSX needs `libreoffice-calc`; PPTX needs `libreoffice-impress`. `ingest/Dockerfile` installs all four.
10. **Anthropic workspace ≠ credits.** "credit balance too low" despite console showing balance = the API key is tied to a different workspace from the one topped up. Generate a new key in the funded workspace.
11. **Windows Unicode output.** Always `sys.stdout.reconfigure(encoding='utf-8')` at the top of any script that prints Thai, emoji, or arrows — otherwise cp874 crashes with `UnicodeEncodeError`. Existing scripts in `scripts/` follow this.
12. **cp Dockerfile before deploy** — Cloud Build doesn't take a `--dockerfile` flag. See Deploy.
13. **`scripts/audit_v2.py` fetches `ANTHROPIC_API_KEY` from Secret Manager**, not `.env`. Other `scripts/` (`full_audit.py`, `ask_anything.py`, `reingest_all.py`) fetch `ADMIN_API_KEY` the same way. Pattern: `subprocess.check_output(['gcloud', 'secrets', 'versions', 'access', 'latest', '--secret=<NAME>'], shell=True).decode().strip()`.
14. **LibreOffice needs Thai fonts.** `python:3.11-slim + libreoffice-*` with `--no-install-recommends` ships English-only fonts; XLSX/PPTX Thai text renders as □ boxes in the PDF conversion step, Opus 4.7 vision sees boxes and reports "ไม่สามารถถอดความได้" → incomplete chunks (v2 coverage dropped 70%→21% on `ตารางเรียน`). `ingest/Dockerfile` now installs `fonts-thai-tlwg` + runs `fc-cache -f`.
15. **Firestore composite indexes.** `pending_registrations` needs `status ASC + created_at DESC` (created 2026-04-19 after `/api/registrations` 500'd with `FailedPrecondition: The query requires an index`). Existing `chat_logs`: `tenant_id ASC + created_at DESC` already covered the chat-logs-by-tenant query. Before adding any new endpoint with `.where().order_by()`, check via `gcloud firestore indexes composite list --project=cutip-rag --database='(default)'` and create missing with `gcloud firestore indexes composite create --collection-group=<coll> --field-config=field-path=<F>,order=<ASC|DESC>` (one `--field-config` per field). Index build on empty collection takes a few minutes.
16. **Cloud Monitoring uptime check resource is immutable.** Cannot change `monitoredResource.labels.host` via `gcloud monitoring uptime update` (no flag) or REST PATCH (400 "Cannot update the resource"). Pattern when a Cloud Run service gets renamed: (1) `gcloud monitoring uptime create` new check for new host, (2) PATCH any alert policies whose `conditionAbsent.filter` references the old host label — filter is keyed by `resource.labels.host`, not check ID, so policies don't auto-follow, (3) `gcloud monitoring uptime delete` the old check.
17. **Git Bash MSYS mangles `/path` flags in gcloud.** `gcloud ... --path=/health` becomes `--path=/C:/Program Files/Git/health` silently. `MSYS_NO_PATHCONV=1` breaks gcloud itself. Workaround: use REST API `curl -X PATCH` with single-quoted JSON body (`'{"httpCheck":{"path":"/health"}}'`), or double-slash (`//health`).
18. **Pure-scan PDFs route through image-blocks (Phase 1, on `feat/ingest-robustness`).** `ingest_v2` calls `extract_page_text` to detect text-layer; if `total_text_chars == 0` → `mode="images"`, else `mode="document"`. The `images` mode uses `_pdf_to_image_blocks` (pymupdf rasterize per page @ 150 DPI → Anthropic `image` content blocks); the `document` mode keeps the legacy base64 PDF document block. Anthropic's PDF document path silent-fails on long pure-scan Thai legal docs even with OCR sidecars; image blocks bypass that path entirely (mirrors what claude.ai does internally). Salvage helper `_salvage_complete_chunks_from_truncated` recovers partial JSON if Opus exceeds max_tokens. **C2 fail-tracking + cooldown:** `scan-all` state machine in `_process_gdrive_folder` consults `shared/services/ingest_failures.py` — after `MAX_CONSECUTIVE_FAILURES` (currently 3) consecutive 0-chunk or exception outcomes for the same `drive_file_id`, subsequent scans skip the file until Drive `modifiedTime` advances. Ingest failures live in Firestore collection `ingest_failures` keyed by `{tenant_id}__{drive_file_id}`. **The `.ocr.docx` workaround from `scripts/ocr_pdf_via_opus.py` was deleted in Phase 1 — users upload original scan PDFs directly.** *(On master, the Phase 1 architecture does NOT exist — pure-scan PDFs silent-fail without recovery; the Haiku-OCR-pre-flight C1 path was attempted and ALSO failed, so it was deleted in Phase 1.)*

## Audit + regression tooling (trust evidence, not aggregate tests)

Aggregate `pytest tests/` passing does **not** mean ingestion is correct for a specific file. Always run per-artifact source-vs-Pinecone diff before claiming ingestion quality:

- `scripts/full_audit.py [--namespace <ns>]` — source-vs-Pinecone diff per file + entity coverage sweep + 9 retrieval probes via `/api/chat`. `--namespace` flag lets you point at `cutip_v2_audit` for v2 audits.
- `scripts/ask_anything.py [--namespace <ns>]` — 20 adversarial bot probes (specific student, committee reverse lookup, numeric facts, language match, OOS refusal, follow-up pronouns, markdown link embedding). Note: currently requires a Firestore tenant that maps to the target namespace — running against `cutip_v2_audit` without creating the tenant will 404 all probes.
- `scripts/audit_v2.py` — local driver that ingests `sample-doc/` into `cutip_v2_audit` via direct `ingest_v2()` call (NOT Cloud Run). Useful for quick prompt iteration but **non-PDF formats fail locally** because LibreOffice isn't installed on the dev machine.
- `scripts/reingest_all.py` — trigger full re-ingest via `/api/tenants/{tenant_id}/ingest/gdrive` (v1 path). For v2 batch: POST to `/api/tenants/{tenant_id}/ingest/v2/gdrive?namespace_override=cutip_v2_audit` with the same body.
- `scripts/audit_ingestion.py`, `scripts/deep_recheck.py`, `scripts/verify_keu.py`, `scripts/broad_smoke.py`, `scripts/verify_page_format.py`, `scripts/smoke_test.py` — targeted diagnostic scripts.
- `scripts/compare_v1_v2.py` (2026-04-19) — Pinecone-side side-by-side of `cutip_01` vs `cutip_v2_audit`: chunk counts, avg size, coverage %, entity preservation, hygiene flags, metadata-field presence. Zero API cost (Pinecone list+fetch only).
- `scripts/diag_xlsx.py` (2026-04-19) — dump v1 + v2 chunks for a single `source_filename` alongside raw Excel cell dump; line-level "missing from v2" heuristic. Used to diagnose the LibreOffice-Thai-font regression.
- `scripts/reingest_xlsx.py` (2026-04-19) — template for single-file v2 re-ingest trigger (POST `/v2/gdrive/file?namespace_override=cutip_v2_audit`). Generalize by swapping `FILENAME`.

## Tenant model

- One tenant per faculty. Schema in `shared/schemas.py::Tenant*`. Fields: `tenant_id`, `pinecone_namespace` (pattern `^[a-z0-9_-]+$`, editable in portal), `faculty_name`, `line_channel_access_token`, `line_channel_secret`, `line_destination`, `persona`, `drive_folder_id` (set via Drive Connect flow), `drive_folder_name` (display), `bm25_invalidate_ts` (cross-process BM25 invalidation), `is_active`.
- **Only `cutip_01` exists in Firestore.** There is no `cutip_v2_audit` tenant — v2 audit writes to the namespace directly via `namespace_override` query param (suffix-validated to `_v2_audit` to prevent arbitrary namespace writes).
- To swap namespace: update `cutip_01.pinecone_namespace` in portal (field is editable post-v2.1) — auto-bumps `bm25_invalidate_ts`. chat-api re-warms BM25 on next query.

## File lifecycle (post-v2.1, read architecture.md §12 for full detail)

- Every chunk has `drive_file_id` in metadata (rename-safe). `source_filename` is still the human-readable key but can mutate.
- Smart Scan (`POST /api/tenants/{id}/ingest/gdrive/scan`) is a state machine: NEW / RENAME / OVERWRITE / SKIP.
- Delete order: Pinecone first, Drive second (3× exp backoff). Reverse order produces orphan chunks ("ghost answers") — do not flip.
- Stage Upload = local file → admin-api uploads to tenant's Drive folder via SA → `ingest_v2(webViewLink)`. Unifies data model; every Pinecone chunk ↔ a Drive file.
- `shared/services/gdrive.py` is the canonical Drive API module (used by both admin-api delete and ingest). `ingest/services/gdrive.py` is a compat shim — don't add logic there, and test patches should target `shared.services.gdrive`.

## When you pick this project up on another machine

1. Run `git status` and `git log --oneline -10` — you should be on `master`, up to date with origin.
2. Check tenant state: `python -c "from google.cloud import firestore; db=firestore.Client(project='cutip-rag'); print(db.collection('tenants').document('cutip_01').get().to_dict()['pinecone_namespace'])"`. **If it says `cutip_v2_audit`, the post-demo swap is still in effect — revert before production writes** (see "Known pending state" below).
3. Read `docs/architecture.md` §§4, 11–13 and `docs/thesis-project-detail.md` §§7.6, 7.7 for v2 + v2.1 context.
4. Check auto-memory in the harness (`memory/MEMORY.md`) — has machine-independent feedback lessons.

## Known pending state (as of 2026-04-29)

**⚠️ `feat/ingest-robustness` is 39 commits ahead of `master`, deployed to Cloud Run as `cutip-ingest-worker-00032-j48`, NOT YET MERGED.** Branch contains: C1+C2 fail-tracking work (early 2026-04-22, partly superseded), text-only path experiment (2026-04-22 evening, deleted in Phase 1), and **Phase 1 image-blocks + JSON-fence rewrite** (2026-04-29) which is the current production architecture. User wanted to defer merge until after the IS thesis presentation (architecture docs at `docs/architecture.md` + `docs/thesis-project-detail.md` describe master's `tool_choice="auto"` pipeline and were submitted with the thesis on 2026-04-20 — deviating production code from submitted thesis was a deliberate choice).

**For thesis defense framing:** the submitted thesis describes v2.1 architecture (`tool_choice="auto"` + `record_chunks` tool + Haiku C1 + .ocr.docx workaround). Phase 1 was a **post-submission iteration** triggered by an empirical smoke test on 2026-04-21 that exposed the silent-fail mode on long Thai legal scans. The diagnostic + fix process is documented in `docs/superpowers/specs/2026-04-22-ingest-v2-image-blocks-design.md`. Frame as "continued engineering rigor after thesis submission identified a previously-unverified failure mode."

**Cleanup follow-ups for post-merge** are tracked in auto-memory `ingest-robustness-post-merge-items.md` (SF1–SF14 + rollback notes). None block deploy or merge. Review-flagged Important items: hybrid-PDF routing edge case (text-layer detection threshold), `_looks_like_refusal` substring false-positives on long chunks, image-block token-budget cushion at 60+ pages.

**Verified production behavior (Phase 1):** `ประกาศจุฬาลงกรณ์มหาวิทยาลัยเรื่อง การกำหนดเกณฑ์และอัตราการจ่ายเงินประเภทต่างๆ พ.ศ. 2563.pdf` (24-page Thai legal pure-scan, drive_id `1JHgSosetumTpEzvDfaDUVz8LdNvD4wLp`) ingested 35 chunks at 2026-04-28T22:09 UTC via auto-scheduler under rev `00030-mbt` (with max_tokens=32K — Opus emitted 43.8K out_tok, just under the limit). Bumped to 64K (rev `00031-xc8`) then 128K (rev `00032-j48`) as insurance. Chunks live in `cutip_v2_audit` namespace (213 vectors total).

**⚠️ Tenant namespace revert pending.** During the 2026-04-19 faculty-staff demo, `cutip_01.pinecone_namespace` was temporarily swapped to `cutip_v2_audit` to showcase v2 quality. After the demo window closed the revert was not yet confirmed. Check current state before shipping new production changes. Target: `cutip_01.pinecone_namespace = cutip_01`, production namespace has 106 chunks and is idle-but-intact. **As of 2026-04-29 the swap is still in effect** — production traffic chats against `cutip_v2_audit` (now 213 vectors including the 35-chunk Phase 1 ingest of ประกาศ 2563).

Revert snippet:
```python
import time
from google.cloud import firestore
db = firestore.Client(project='cutip-rag')
db.collection('tenants').document('cutip_01').update({
    'pinecone_namespace': 'cutip_01',
    'bm25_invalidate_ts': time.time(),
})
```
chat-api re-warms BM25 on the next query automatically (logs `BM25 warmed for namespace 'cutip_01': 106 documents`). Smoke-test 1 LINE query after revert to confirm.

**⚠️ Uncommitted local changes — user pushes themselves:**
- `ingest/Dockerfile` — `+fonts-thai-tlwg`, `+fc-cache -f` (Thai rendering fix — already deployed as `cutip-ingest-worker-00020-xts`)
- `scripts/compare_v1_v2.py`, `scripts/diag_xlsx.py`, `scripts/reingest_xlsx.py` — new audit/diagnostic scripts (no runtime dependency)
- `../admin-portal/src/app/settings/page.tsx`, `../admin-portal/src/lib/auth-context.tsx` — 2 lint fixes (already deployed as `cutip-admin-portal-00010-wcg`)

**⚠️ GCP infra state changed 2026-04-19** (no code change, but visible in gcloud console):
- Uptime check `cu-tip-rag-bot-8nniU0hpQiE` **deleted**; replaced with `cu-tip-chat-api-4SQvqDdGABQ` targeting `cutip-chat-api-...run.app/health`. Alert policy `RAG Bot Down Alert` filter updated to new host. Old check had been failing silently for weeks (targeted old Cloud Run service name `cutip-rag-bot` that had been renamed to `cutip-chat-api`).
- Firestore composite index created on `pending_registrations`: `status` ASC + `created_at` DESC. Was missing → `/api/registrations` returned 500. Pre-demo fix.

## Where new docs must go

`TIP-RAG/` (the parent workspace holding this repo + `admin-portal/` + `sample-doc/`) is **not** a git repo. Only this repo (`cutip-rag-chatbot/`) and `admin-portal/` are tracked. Any doc/spec/plan that must travel with the code — including `CLAUDE.md`, design specs, implementation plans, architecture diagrams — must live under `cutip-rag-chatbot/docs/` or `cutip-rag-chatbot/CLAUDE.md`. Pre-2026-04-18 legacy docs sat at `TIP-RAG/docs/` and had to be moved in commit 4c2a491; don't recreate that trap.

## Session handoff (2026-04-29 — for picking up on a different machine / Claude account)

**Context not in any other doc:** Last working session ended after the Phase 1 + P1.1 + P1.2 deploy was verified. The user is preparing for the IS thesis presentation; deferring `feat/ingest-robustness` → `master` merge until after that. Do NOT auto-merge.

**Where to start picking up:**

1. `git status` should be clean on `feat/ingest-robustness` (39 commits ahead of master).
2. Read this file's "Known pending state" section first.
3. Read `docs/superpowers/specs/2026-04-22-ingest-v2-image-blocks-design.md` (Phase 1 spec — the architecture currently deployed).
4. The auto-memory MEMORY.md index at `~/.claude/projects/.../memory/MEMORY.md` is **machine-local** — won't follow to a new machine/account. The repo-resident equivalents that DO follow are this file + the spec/plan docs in `docs/superpowers/`.

**What's pending:**

- (a) Optional: chat smoke test to verify retrieval works end-to-end against the 35 ingested chunks of ประกาศ 2563.pdf (`/api/chat` query like "ค่าเบี้ยประชุมกรรมการสภามหาวิทยาลัย" — should find a chunk with `section_path: "บทนำ"` or similar)
- (b) After presentation: merge `feat/ingest-robustness` → `master`, push, then optionally update `docs/architecture.md` + `docs/thesis-project-detail.md` to reflect Phase 1 (mention it as post-submission iteration in §11 evolution narrative)
- (c) Post-merge cleanup pass per `ingest-robustness-post-merge-items.md` items SF1–SF14 (type hints, dead `cache_clear()` in tests, hybrid PDF routing tightening, refusal-substring filter narrowing)
- (d) Tenant namespace revert (`cutip_01.pinecone_namespace = "cutip_01"`) — but **only after confirming `cutip_v2_audit` data is no longer needed** (213 vectors there now include Phase 1's 35 from ประกาศ 2563)

**What's NOT to redo:**

- The whole "C1 Haiku pre-OCR + sidecar" path that earlier memory notes described — DELETED in Phase 1 commit `3ea3d95`. Don't bring it back.
- `.ocr.docx` filename branch / `_read_ocr_docx_as_pages` / `_format_pages_for_text_only` / `USER_PROMPT_TEMPLATE_TEXT_ONLY` — all deleted in Phase 1.
- `bind_tools` / `tool_choice` / `CHUNK_TOOL_SCHEMA` — Phase 1 architecture is no-tool-binding, JSON-fence output. The whole point.
- `scripts/ocr_pdf_via_opus.py` is still in the repo as a reference but **its output (`.ocr.docx` files) is no longer needed** for production ingest.

**Key facts to verify on resume (single machine OR new machine after `git pull`):**

```bash
cd cutip-rag-chatbot/
git log --oneline master..HEAD | wc -l                # should be 39 if not merged
git rev-parse HEAD                                     # should be cdfeb51 if no further commits
.venv/Scripts/python.exe -m pytest tests/ -q          # should be 280 passed
gcloud run services describe cutip-ingest-worker --region=asia-southeast1 --project=cutip-rag --format='value(status.latestReadyRevisionName)'  # should be cutip-ingest-worker-00032-j48
```

If any of those don't match, something happened between sessions — re-orient before making changes.

## Instruction priority

User instructions in chat always win. Then this file. Then automatic behavior. If something here conflicts with what the user just said, the user's latest message is authoritative.
