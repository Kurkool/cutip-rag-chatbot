# scripts/ — Operational tools

Standalone Python scripts for audit, diagnostics, smoke testing, re-ingestion, and one-off setup. **Not** production code — `chat/`, `ingest/`, `admin/`, `shared/` are the actual application packages.

Run pattern (from `cutip-rag-chatbot/` directory):

```bash
PYTHONPATH=. .venv/Scripts/python.exe scripts/<subdir>/<name>.py
```

## Categories

### `audit/` — Recurring quality checks

| Script | Purpose |
|---|---|
| `full_audit.py` | Main audit: source-vs-Pinecone diff per file + entity coverage sweep + 9 retrieval probes via `/api/chat`. Run before any production data change. |
| `ask_anything.py` | 20 adversarial bot probes (specific-student lookup, committee reverse lookup, numeric facts, language match, OOS refusal, follow-up pronouns, markdown link embedding). |
| `compare_v1_v2.py` | Pinecone-side side-by-side of `cutip_01` (v1 prod) vs `cutip_v2_audit` (v2 pilot). Zero API cost — list+fetch only. |
| `assess_hsm.py` | Assessment of HSM tenant documents (deferred tenant — `hsm-doc/`). |

### `smoke/` — Quick health checks

| Script | Purpose |
|---|---|
| `smoke_test.py` | Basic smoke (small subset of probes). |
| `broad_smoke.py` | Wider smoke (more probes than `smoke_test.py`). |
| `verify_keu.py` | Specific test case (legacy — verify expected behavior on one document). |
| `verify_page_format.py` | Verify page-number rendering format (`page: 1.0` → `page 1` issue from Pinecone double metadata). |

### `reingest/` — Data refresh triggers

| Script | Purpose |
|---|---|
| `reingest_all.py` | Trigger full re-ingest of a tenant's Drive folder via `POST /api/tenants/{id}/ingest/gdrive` (v1) or `/v2/gdrive`. |
| `reingest_xlsx.py` | Template for single-file v2 re-ingest. Generalize by swapping `FILENAME`. |

### `diag/` — Debug specific issues

| Script | Purpose |
|---|---|
| `audit_ingestion.py` | Per-PDF detailed audit in `is-docs/sample-doc/cutip-doc/` — surfaces chunks per source file. |
| `audit_v2.py` | Local v2 ingest driver (direct `ingest_v2()` call, NOT Cloud Run). Useful for prompt iteration. Non-PDF formats fail locally because LibreOffice isn't installed on dev machine. |
| `deep_recheck.py` | Deep verification — broader than smoke, narrower than full_audit. |
| `diag_new_doc.py` | Diagnose ingestion issues when a new document doesn't behave as expected. |
| `diag_xlsx.py` | Excel-specific diagnosis. Used to debug LibreOffice Thai-font regression (boxes in PDF conversion → Opus vision sees boxes). |

### `setup/` — One-off configuration

| Script | Purpose |
|---|---|
| `setup_rich_menu.py` | Create the LINE Rich Menu (run once at LINE OA setup). |

## Notes

- Most audit/diag scripts fetch `ADMIN_API_KEY` or `ANTHROPIC_API_KEY` from GCP Secret Manager via `gcloud secrets versions access latest --secret=<NAME>`. Local `.env` is fallback only.
- `audit/ask_anything.py` requires a Firestore tenant that maps to the target namespace. Running against `cutip_v2_audit` without creating the tenant will 404 all probes.
- `diag/audit_v2.py` writes to `cutip_v2_audit` namespace directly via `namespace_override` query param (suffix-validated to `_v2_audit`).
