# TIP-RAG — Claude Code Project Guide

**Project:** CU TIP (Technopreneurship & Innovation Management) RAG Chatbot SaaS — multi-tenant agentic RAG platform for Thai university faculties.
**Owner:** Kurkool Ussawadisayangkool (CU-TIP master's thesis, 6780016820).
**Status:** Production v4.2.0 on `main`; v2 universal-ingestion pilot on branch `development-integration`.
**GCP Project:** `cutip-rag` · **Region:** `asia-southeast1` · **Firestore DB:** `(default)` · **Pinecone Index:** `university-rag` (1536d, cosine).

## Read first (long-form context)

- [`docs/architecture.md`](docs/architecture.md) — 11 sections, 8 Mermaid diagrams. v1 production + §11 v2 pilot.
- [`docs/thesis-project-detail.md`](docs/thesis-project-detail.md) — 24 sections, thesis-grade detail. v2 evolution narrative is §7.6.
- [`docs/superpowers/specs/2026-04-18-ingest-v2-design.md`](docs/superpowers/specs/2026-04-18-ingest-v2-design.md) — v2 spec.
- [`docs/superpowers/plans/2026-04-18-ingest-v2.md`](docs/superpowers/plans/2026-04-18-ingest-v2.md) — 13-task TDD plan (all 12 code tasks done; Phase-1 audit evidence recorded).

## Repo layout

This `CLAUDE.md` lives **inside** the `cutip-rag-chatbot/` git repo — the Python backend. Two sibling directories live OUTSIDE this repo (cloned/synced separately):
- `../admin-portal/` — Next.js 16 frontend (own git repo, own `CLAUDE.md` pointing at an `AGENTS.md` warning about Next.js 16 breaking changes)
- `../sample-doc/` — not version-controlled (PDPA-sensitive PDFs); `cutip-doc/` (14 files, GDrive folder `1duGSSJxj9g-A2dxNTLROnjBPn7V08aMk`) + `hsm-doc/` (8 files, deferred tenant)

```
cutip-rag-chatbot/              ← this repo (git)
├── CLAUDE.md                   ← this file
├── chat/                       ← LINE webhook + agentic RAG + search
├── ingest/                     ← document pipeline (v1 prod + v2 pilot)
│   ├── services/
│   │   ├── ingestion.py          (v1 — 5 format-specific paths)
│   │   ├── ingestion_v2.py       (v2 — universal Opus 4.7 pipeline)
│   │   ├── _v2_prompts.py        (v2 system prompt + tool schema)
│   │   ├── chunking.py, enrichment.py, vision.py  (v1 utilities)
│   │   └── gdrive.py
│   └── routers/ingestion.py      (has both /gdrive and /v2/gdrive endpoints)
├── admin/                      ← tenants, users, analytics, privacy, backup
├── shared/                     ← config, schemas, middleware, auth, llm factory, firestore, vectorstore
├── scripts/                    ← audit + reingest + smoke tools (see below)
├── tests/                      ← 250 backend tests (pytest, asyncio auto)
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
- **OCR (v1) + parse-and-chunk (v2):** Opus 4.7 via `shared/services/llm.py::get_ocr_llm` (v1) and `ingest/services/ingestion_v2.py::_get_opus_llm` (v2 — NO thinking kwarg reusable from v1 because v2 uses `tool_choice="auto"` pattern instead of forced tool, see gotcha below).
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

### Current deployed revisions (as of 2026-04-18)

- `cutip-ingest-worker-00019-7vr` — has v2 endpoints (`/v2/gdrive`, `/v2/gdrive/file` with `?namespace_override=*_v2_audit`)
- Other services on last revisions from `main` branch.

## Branch conventions

- `main` — production. Only commits that have been validated + user explicitly authorizes.
- `development-integration` — v2 pilot work (v2 ingestion + audit + docs updates). Current branch in this workspace.
- **User commits themselves** — you can stage + commit when task is complete, but **user pushes to remote**.

## Testing conventions

- TDD for all new code: failing test → minimal implementation → passing test → commit.
- Tests live in `cutip-rag-chatbot/tests/`. Module-level test files mirror source: `test_ingestion_v2.py`, `test_bm25.py`, etc.
- `pytest.ini` has `asyncio_mode = auto` but v2 tests use explicit `@pytest.mark.asyncio` for clarity.
- When a test file imports a module that transitively pulls `langchain_cohere`, expect ~7s startup overhead (intentional lazy imports in `shared/services/embedding.py` and `vectorstore.py` — don't break them).

## Critical gotchas (cross-machine)

1. **Opus 4.7 adaptive thinking returns `content: list[dict]`**, not `str`. Both `chat/services/agent.py::run_agent` and `ingest/services/vision.py::parse_page_image` must extract text blocks explicitly. Missing this = intermittent pydantic-500 with stringified list as answer.
2. **Thinking + forced `tool_choice` = 400.** Use `tool_choice={"type": "auto"}` and instruct the tool call in the system prompt. Empirically required for long/dense multimodal docs (45-page slide.pdf: 0 → 43 chunks). See `ingest/services/ingestion_v2.py::_get_opus_llm` and `opus_parse_and_chunk` for the pattern.
3. **Opus tool output needs `max_tokens=32000`**, not 4096. A 23-entry `record_chunks` JSON array silently truncates at 8K. No warning — just a shorter array.
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

## Audit + regression tooling (trust evidence, not aggregate tests)

Aggregate `pytest tests/` passing does **not** mean ingestion is correct for a specific file. Always run per-artifact source-vs-Pinecone diff before claiming ingestion quality:

- `scripts/full_audit.py [--namespace <ns>]` — source-vs-Pinecone diff per file + entity coverage sweep + 9 retrieval probes via `/api/chat`. `--namespace` flag lets you point at `cutip_v2_audit` for v2 audits.
- `scripts/ask_anything.py [--namespace <ns>]` — 20 adversarial bot probes (specific student, committee reverse lookup, numeric facts, language match, OOS refusal, follow-up pronouns, markdown link embedding). Note: currently requires a Firestore tenant that maps to the target namespace — running against `cutip_v2_audit` without creating the tenant will 404 all probes.
- `scripts/audit_v2.py` — local driver that ingests `sample-doc/` into `cutip_v2_audit` via direct `ingest_v2()` call (NOT Cloud Run). Useful for quick prompt iteration but **non-PDF formats fail locally** because LibreOffice isn't installed on the dev machine.
- `scripts/reingest_all.py` — trigger full re-ingest via `/api/tenants/{tenant_id}/ingest/gdrive` (v1 path). For v2 batch: POST to `/api/tenants/{tenant_id}/ingest/v2/gdrive?namespace_override=cutip_v2_audit` with the same body.
- `scripts/audit_ingestion.py`, `scripts/deep_recheck.py`, `scripts/verify_keu.py`, `scripts/broad_smoke.py`, `scripts/verify_page_format.py`, `scripts/smoke_test.py` — targeted diagnostic scripts.

## Tenant model

- One tenant per faculty. Schema in `shared/schemas.py::Tenant*`. Fields: `tenant_id`, `pinecone_namespace` (pattern `^[a-z0-9_-]+$`), `faculty_name`, `line_channel_access_token`, `line_channel_secret`, `line_destination`, `persona`, `drive_folder_id`, `bm25_invalidate_ts`, `is_active`.
- **Only `cutip_01` exists in Firestore.** There is no `cutip_v2_audit` tenant — v2 audit writes to the namespace directly via `namespace_override` query param (suffix-validated to `_v2_audit` to prevent arbitrary namespace writes).
- To test v2 via LINE: swap `cutip_01.pinecone_namespace` temporarily (affects all LINE users during the swap) + bump `bm25_invalidate_ts`. chat-api re-warms BM25 on next query. Revert after testing. Current LINE-test state: **revert pending** (task-tracker memory) if namespace is still `cutip_v2_audit`.

## When you pick this project up on another machine

1. Run `git status` and `git log --oneline -10` — see which branch and where things stand.
2. Check tenant state: `python -c "from google.cloud import firestore; db=firestore.Client(project='cutip-rag'); print(db.collection('tenants').document('cutip_01').get().to_dict()['pinecone_namespace'])"`. If it says `cutip_v2_audit`, a swap is still in effect — revert before production changes.
3. Read `docs/architecture.md` §11 and `docs/thesis-project-detail.md` §7.6 for v2 context.
4. Check auto-memory in the harness if available (`memory/MEMORY.md`) — it has machine-independent feedback lessons.

## Instruction priority

User instructions in chat always win. Then this file. Then automatic behavior. If something here conflicts with what the user just said, the user's latest message is authoritative.
