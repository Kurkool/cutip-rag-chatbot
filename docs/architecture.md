# CU TIP RAG Chatbot — Architecture Document

**Version:** 4.2.0 | **Date:** 2026-04-18 | **Status:** Production (v1) + Pilot (v2 universal ingestion)

---

## 1. System Overview

```mermaid
graph TB
    subgraph Users
        S[Students via LINE]
        A[Faculty Admin via Browser]
    end

    subgraph "LINE Platform"
        LINE[LINE Official Account]
        RM[Rich Menu 6 Buttons]
    end

    subgraph "Google Cloud — Cloud Run"
        CHAT[Chat API<br/>1GB / 2CPU / min-instances=1]
        INGEST[Ingestion Worker<br/>2GB / 2CPU]
        ADMIN[Admin API<br/>512MB / 1CPU]
        PORTAL[Admin Portal<br/>Next.js 16]
    end

    subgraph "External AI Services"
        OPUS[Claude Opus 4.7<br/>Agentic Reasoning]
        HAIKU[Claude Haiku 4.5<br/>Vision + Enrichment + Multi-Query]
        COHERE_E[Cohere embed-v4.0<br/>1536d Embeddings]
        COHERE_R[Cohere Rerank v3.5<br/>Cross-Encoder]
    end

    subgraph "Google Cloud — Data"
        FS[(Firestore<br/>7 Collections)]
        PC[(Pinecone<br/>Vector DB)]
        GCS[(Cloud Storage<br/>Backups)]
        DRIVE[(Google Drive<br/>Document Source)]
    end

    subgraph "Google Cloud — Automation"
        SCHED[Cloud Scheduler<br/>3 Jobs]
        MONITOR[Cloud Monitoring<br/>Uptime Checks]
    end

    SLACK[Slack Alerts]

    S --> LINE --> CHAT
    A --> PORTAL --> ADMIN
    A --> PORTAL --> INGEST

    CHAT --> OPUS
    CHAT --> COHERE_E
    CHAT --> COHERE_R
    CHAT --> HAIKU
    CHAT --> PC
    CHAT --> FS

    INGEST --> HAIKU
    INGEST --> COHERE_E
    INGEST --> PC
    INGEST --> FS
    INGEST --> DRIVE

    ADMIN --> FS
    ADMIN --> PC
    ADMIN --> GCS

    SCHED --> INGEST
    SCHED --> ADMIN
    MONITOR --> CHAT
    MONITOR --> INGEST
    MONITOR --> ADMIN
    ADMIN --> SLACK
```

---

## 2. Microservices Architecture

```mermaid
graph LR
    subgraph "Monorepo: cutip-rag-chatbot/"
        subgraph "shared/ (14 files)"
            CONFIG[config.py]
            SCHEMAS[schemas.py]
            MW[middleware.py]
            LLM[llm.py<br/>4 LLM Presets]
            FS_SVC[firestore.py]
            AUTH[auth.py]
            EMBED[embedding.py]
            VS[vectorstore.py]
        end

        subgraph "chat/ (10 files)"
            C_MAIN[main.py]
            AGENT[agent.py]
            TOOLS[tools.py]
            SEARCH[search.py]
            BM25[bm25.py]
            RERANK[reranker.py]
            MEMORY[memory.py]
            LINE_SVC[line.py]
        end

        subgraph "ingest/ (v2 Opus universal, as of 2026-04-19)"
            I_MAIN[main.py]
            V2[ingestion_v2.py]
            V2_PROMPTS[_v2_prompts.py]
            HELPERS[ingest_helpers.py]
            VISION[vision.py<br/>refusal filter only]
            GDRIVE[gdrive.py]
        end

        subgraph "admin/ (7 files)"
            A_MAIN[main.py]
            TENANTS[tenants.py]
            USERS[users.py]
            ANALYTICS[analytics.py]
            PRIVACY[privacy.py]
        end
    end

    chat/ --> shared/
    ingest/ --> shared/
    admin/ --> shared/
```

| Service | Responsibility | Resources | Instances |
|---------|---------------|-----------|-----------|
| **Chat API** | LINE webhook, /api/chat, agentic RAG | 1GB, 2CPU | min=1, max=10 |
| **Ingestion Worker** | Document processing, Pinecone upsert | 2GB, 2CPU | 0-2 |
| **Admin API** | CRUD, analytics, backup, privacy | 512MB, 1CPU | 0-2 |
| **Admin Portal** | Web UI (Next.js 16 + shadcn/ui) | 512MB, 1CPU | 0-2 |

---

## 3. Chat Pipeline (Student Query Flow)

```mermaid
sequenceDiagram
    participant S as Student (LINE)
    participant W as Webhook
    participant A as Agent (Opus)
    participant Q as Query Pipeline
    participant H as Haiku
    participant P as Pinecone
    participant B as BM25
    participant R as Reranker
    participant M as Memory
    participant F as Firestore

    S->>W: Send message
    W->>F: Get tenant config
    W->>M: Get conversation history
    M->>F: Read turns + summary
    W->>A: Run agent (query + history + persona)

    Note over A: ReAct Loop: Reason → Act → Observe

    A->>Q: search_knowledge_base(query)

    Note over Q: Step 1: Query Decomposition
    Q->>H: Decompose complex query?
    H-->>Q: [sub_query_1, sub_query_2]

    Note over Q: Step 2: Multi-Query Generation
    Q->>H: Generate variants (EN + TH synonyms)
    H-->>Q: [original, english, synonym]

    Note over Q: Step 3: Hybrid Search (per variant)
    Q->>P: Vector search (k=10)
    P-->>Q: semantic results
    Q->>B: BM25 keyword search (k=10)
    B-->>Q: keyword results

    Note over Q: Step 4: Reciprocal Rank Fusion
    Q->>Q: RRF merge → top 15

    Note over Q: Step 5: Confidence Reranking
    Q->>R: Rerank top 15 → top 5
    R-->>Q: [(doc, score)] with confidence tiers

    Q-->>A: Formatted results with [HIGH/MEDIUM] labels

    A->>A: Generate answer with inline links
    A-->>W: (answer, sources)

    W->>M: Save turn (summarize if >5 turns)
    M->>H: Summarize conversation (if overflow)
    W->>F: Log chat + sources
    W->>S: Text message (copyable) + Sources Flex bubble
```

---

## 4. Ingestion Pipeline (Document Processing)

```mermaid
flowchart TD
    subgraph Input
        UPLOAD[File Upload<br/>PDF/DOC/DOCX/XLSX/CSV]
        GDRIVE[Google Drive<br/>Batch/Scan/Single]
        WEB[Web Content<br/>Markdown via Jina]
    end

    subgraph "Format Detection"
        DET{File Type?}
        LEGACY[Legacy .doc/.xls<br/>→ LibreOffice → PDF]
    end

    subgraph "Text Extraction"
        PDF_EXT[PDF: PyMuPDF Text]
        PDF_VIS[PDF: Claude Vision<br/>tables/scanned pages]
        DOCX_EXT[DOCX: Paragraphs<br/>+ Tables + Images]
        XLSX_EXT[XLSX/CSV: Pandas<br/>→ Claude Vision Interpret]
    end

    subgraph "Smart Chunking"
        SEM[Semantic Chunking<br/>Cohere Embeddings<br/>Percentile Boundaries]
        TAB[Table-Aware<br/>Post-Processing<br/>Preserve Row Integrity]
        FALL[Fallback: Recursive<br/>Character Splitter]
    end

    subgraph "Contextual Enrichment"
        SEC[Build Section Map<br/>from Markdown Headers]
        CTX[Haiku: Generate<br/>Section-Level Context]
        PRE["Prepend: [context]\nchunk_text"]
    end

    subgraph "Vector Storage"
        EMB[Cohere embed-v4.0<br/>1536 dimensions]
        UPS[Pinecone Upsert<br/>Namespace-Isolated]
        BM25_INV[Invalidate BM25<br/>Cache]
    end

    UPLOAD --> DET
    GDRIVE --> DET
    WEB --> SEM

    DET -->|PDF| PDF_EXT
    DET -->|PDF tables/scanned| PDF_VIS
    DET -->|DOC/XLS| LEGACY --> PDF_EXT
    DET -->|DOCX| DOCX_EXT
    DET -->|XLSX/CSV| XLSX_EXT

    PDF_EXT --> SEM
    PDF_VIS --> SEM
    DOCX_EXT --> SEM
    XLSX_EXT --> SEM

    SEM --> TAB --> CTX
    SEM -.->|fail| FALL --> TAB

    SEC --> CTX --> PRE --> EMB --> UPS --> BM25_INV
```

### Chunking Strategy

| Input Type | Text Extraction | Chunking | Enrichment |
|-----------|----------------|----------|------------|
| PDF (text-heavy) | PyMuPDF | Semantic | Section-level Haiku |
| PDF (tables/scanned) | Claude Vision | Semantic | Section-level Haiku |
| PDF (slides) | PyMuPDF/Vision | Page-level | Section-level Haiku |
| DOCX | python-docx + Vision (images) | Semantic | Section-level Haiku |
| XLSX/CSV | Pandas → Vision interpret | Semantic | Section-level Haiku |
| Markdown | Direct | Semantic | Section-level Haiku |
| Legacy (.doc/.xls) | LibreOffice → PDF → above | Same as PDF | Same as PDF |

---

## 5. Search Pipeline (God Mode)

```mermaid
flowchart LR
    Q[User Query] --> DECOMP{Complex?}
    DECOMP -->|Simple| MQ[Multi-Query<br/>Generate 3 Variants]
    DECOMP -->|Complex| SUB[Decompose<br/>2-3 Sub-Queries] --> MQ

    MQ --> V1[Variant 1: Original]
    MQ --> V2[Variant 2: English]
    MQ --> V3[Variant 3: Thai Synonym]

    V1 --> HS1[Hybrid Search]
    V2 --> HS2[Hybrid Search]
    V3 --> HS3[Hybrid Search]

    subgraph "Hybrid Search"
        HS1 --> VS[Vector Search<br/>Pinecone k=10]
        HS1 --> BS[BM25 Search<br/>Keyword k=10]
        VS --> RRF[RRF Merge<br/>k=60]
        BS --> RRF
    end

    RRF --> DEDUP[Deduplicate<br/>by content prefix]
    DEDUP --> RERANK[Cohere Rerank<br/>Top 5]

    RERANK --> CONF{Score?}
    CONF -->|"> 0.6"| HIGH["[HIGH CONFIDENCE]"]
    CONF -->|"0.3-0.6"| MED["[MEDIUM]"]
    CONF -->|"< 0.3"| FILTER[Filtered Out]

    HIGH --> AGENT[Agent]
    MED --> AGENT
```

---

## 6. Data Model (Firestore)

```mermaid
erDiagram
    TENANTS {
        string tenant_id PK
        string faculty_name
        string line_destination
        string pinecone_namespace
        string persona
        boolean is_active
        array onboarding_completed
    }

    CHAT_LOGS {
        string id PK
        string tenant_id FK
        string user_id
        string query
        string answer
        array sources
        datetime created_at
    }

    ADMIN_USERS {
        string uid PK
        string email
        string display_name
        string role
        array tenant_ids
        boolean is_active
    }

    USAGE_LOGS {
        string id PK "tenant_id_YYYY-MM"
        string tenant_id FK
        string month
        int llm_call_count
        int embedding_call_count
        int reranker_call_count
        int vision_call_count
        float total_cost
    }

    CONVERSATIONS {
        string user_id PK
        array turns
        string summary
        datetime last_active
    }

    CONSENTS {
        string id PK
        string tenant_id FK
        string user_id
        string consent_type
        string version
        boolean is_active
    }

    REGISTRATIONS {
        string id PK
        string faculty_name
        string email
        string status
        string reject_reason
        datetime created_at
    }

    TENANTS ||--o{ CHAT_LOGS : has
    TENANTS ||--o{ USAGE_LOGS : tracks
    ADMIN_USERS }o--o{ TENANTS : manages
```

---

## 7. Admin Portal

```mermaid
graph TD
    subgraph "Public"
        REG[/register<br/>Faculty Registration/]
        LOGIN[/login/]
    end

    subgraph "All Admins"
        DASH[/ Dashboard<br/>Tenants + Cost Overview/]
        TL[/tenants<br/>Tenant List/]
        TD[/tenants/id<br/>Tenant Detail/]
        DOC[/tenants/id/documents<br/>Upload + Drive Ingest/]
        CL[/tenants/id/chat-logs<br/>Chat History/]
        AN[/tenants/id/analytics<br/>Usage Stats/]
        SET[/settings<br/>API Config/]
    end

    subgraph "Super Admin Only"
        USR[/users<br/>User Management/]
        REGS[/registrations<br/>Approve / Reject/]
        BILL[/billing<br/>Cost Dashboard + Chart/]
    end

    subgraph "Faculty Admin Only"
        ONB[/onboarding<br/>5-Step Wizard/]
    end

    LOGIN --> DASH
    REG --> LOGIN
    DASH --> TL --> TD
    TD --> DOC
    TD --> CL
    TD --> AN
```

---

## 8. Infrastructure

```mermaid
graph TB
    subgraph "Cloud Run (asia-southeast1)"
        CR1[cutip-chat-api<br/>1GB / 2CPU / min=1]
        CR2[cutip-ingest-worker<br/>2GB / 2CPU]
        CR3[cutip-admin-api<br/>512MB / 1CPU]
        CR4[cutip-admin-portal<br/>512MB / 1CPU]
    end

    subgraph "Cloud Scheduler"
        J1[cutip-01-auto-scan<br/>Hourly]
        J2[cutip-backup-daily<br/>02:00 UTC]
        J3[cutip-retention-cleanup<br/>03:00 UTC]
    end

    subgraph "Cloud Monitoring"
        UC1[Chat Health Check<br/>Every 5 min]
        UC2[Ingest Health Check]
        UC3[Admin Health Check]
    end

    subgraph "Secret Manager"
        SK[PINECONE_API_KEY]
        SA[ANTHROPIC_API_KEY]
        SC[COHERE_API_KEY]
        SAD[ADMIN_API_KEY]
    end

    J1 -->|POST /ingest/gdrive/scan| CR2
    J2 -->|POST /api/backups/firestore| CR3
    J3 -->|POST /api/privacy/retention/cleanup| CR3

    UC1 --> CR1
    UC2 --> CR2
    UC3 --> CR3

    SK --> CR1 & CR2 & CR3
    SA --> CR1 & CR2 & CR3
    SC --> CR1 & CR2 & CR3
```

---

## 9. Tech Stack Summary

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **LLM** | Claude Opus 4.7 | Agentic reasoning (ReAct agent) |
| **LLM** | Claude Haiku 4.5 | Vision, enrichment, multi-query, summarization |
| **Embedding** | Cohere embed-v4.0 | 1536d document/query vectors |
| **Reranker** | Cohere Rerank v3.5 | Cross-encoder precision ranking |
| **Chunking** | SemanticChunker | Embedding-based boundary detection |
| **Vector DB** | Pinecone | Namespace-isolated vector storage |
| **Keyword Search** | rank-bm25 | BM25Okapi for exact term matching |
| **Backend** | FastAPI + Uvicorn | 3 async microservices |
| **Frontend** | Next.js 16 + shadcn/ui | Admin portal (14 pages) |
| **Auth** | Firebase Auth | Email/password + JWT tokens |
| **Database** | Firestore | 7 collections (config, logs, users) |
| **Chat** | LINE Messaging API | Webhook + Rich Menu + Flex Messages |
| **Storage** | Google Cloud Storage | Backup exports |
| **Documents** | Google Drive API | Source document management |
| **Scheduler** | Cloud Scheduler | 3 automated jobs |
| **Monitoring** | Cloud Monitoring + Slack | Uptime checks + error alerts |
| **Deploy** | Cloud Build + Cloud Run | Container-based deployment |
| **Testing** | pytest + Vitest | 279 tests (250 BE + 29 FE) |

---

## 10. Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM for agent | Claude Opus 4.7 | Best reasoning quality for agentic RAG |
| LLM for v2 parse+chunk | Claude Opus 4.7 w/ adaptive thinking | Universal ingestion — PDF native, tool-output JSON, thinking-aware for long/dense docs |
| LLM for utilities | Claude Haiku 4.5 | 60x cheaper, sufficient for summarize/enrich |
| Search strategy | Hybrid BM25+Vector+RRF | Catches both semantic and keyword queries |
| Chunking | Semantic (embedding-based) | 30-40% better retrieval than fixed-size |
| Enrichment | Section-level context | 60% improvement over global doc summary |
| Architecture | Microservices monorepo | Independent scaling, shared code package |
| Chat min-instances | 1 (always warm) | Avoid LINE webhook timeout on cold start |
| Memory | Summarization (Haiku) | Unlimited effective conversation context |
| Confidence | 3-tier (HIGH/MEDIUM/filtered) | Prevents low-relevance hallucination |

---

## 11. Ingestion v2 — Universal Opus 4.7 Pipeline (Pilot)

**Status:** Deployed on Cloud Run `cutip-ingest-worker-00019-7vr` as a parallel endpoint. v1 (§4) remains the production path; v2 is validated via the isolated `cutip_v2_audit` Pinecone namespace.

### 11.1 Motivation

The v1 pipeline (§4) accumulated 9 months of rule-based special-casing (format dispatcher × 5 paths, `has_tables → Vision` routing, `is_slides → page-chunk`, refusal-pattern filters, table-boundary repair, atomic-swap dedup). Each new complex-document shape required a new `elif` branch. v2 replaces the accretion with **one universal path** driven by Opus 4.7's multimodal understanding — new document shapes become prompt-tuning concerns, not new code branches.

### 11.2 Architecture

```mermaid
flowchart TD
    IN[Any supported file<br/>pdf/docx/xlsx/doc/xls/ppt/pptx] --> ENS[ensure_pdf<br/>passthrough or LibreOffice]
    ENS --> LINKS[extract_hyperlinks<br/>PyMuPDF sidecar<br/>URIs hidden in annotations]
    ENS --> OPUS[Opus 4.7<br/>PDF native input<br/>adaptive thinking<br/>tool_choice=auto]
    LINKS --> OPUS
    OPUS --> CHUNKS["record_chunks tool<br/>text, section_path, page, has_table"]
    CHUNKS --> FILT[Refusal filter<br/>empty-text filter]
    FILT --> UPS["_upsert reused<br/>Cohere embed-v4.0<br/>atomic-swap dedup<br/>BM25 invalidation"]
```

### 11.3 Key Design Choices

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Universal vs per-format | Universal (ensure_pdf → Opus) | 1 code path vs 5; new shapes handled via prompt, not code |
| Tool use | `tool_choice={"type": "auto"}` + system-prompt instruction | Auto unlocks adaptive thinking (forced tool use disables it). Thinking was empirically required for 45-page slide decks (0 chunks → 43 chunks) |
| Output tokens | `max_tokens=32000` | 8K truncated the `record_chunks` JSON array mid-stream on dense docs (23-student announcement: 0 → 25 chunks after bump) |
| Sidecar metadata | Deterministic `extract_hyperlinks()` | Opus renders PDFs visually; link-annotation URIs (not visible text) must be pre-extracted. Skips URIs already plain in text to avoid duplication |
| Namespace override | Query param on `/v2/gdrive`, suffix-validated `_v2_audit` | Audit runs into an isolated namespace without creating a fake tenant |
| Format expansion | `libreoffice-core writer calc impress` in Dockerfile | v1 had writer only; v2's universal path requires calc (.xlsx) and impress (.pptx) |

### 11.4 Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/tenants/{tenant_id}/ingest/v2/gdrive` | Batch ingest a Google Drive folder via v2 |
| POST | `/api/tenants/{tenant_id}/ingest/v2/gdrive/file` | Single-file retry (for transient GDrive download flakes) |

Both accept `?namespace_override=<name>_v2_audit` for isolated audit runs.

### 11.5 v2 Audit Result (Phase-1, 2026-04-18)

Ingested 14 sample documents from `sample-doc/cutip-doc/` into namespace `cutip_v2_audit`:

| File | Chunks (v2) | Notes |
|------|-------------|-------|
| slide.pdf (45 pages) | 43 | v1 dropped to 0 without thinking; 1 chunk/slide after fix |
| ประกาศแจ้งคณะกรรมการสอบ.pdf | 25 | 23 student records + 2 structural chunks (vs v1's 14) |
| สอบโครงการพิเศษ.pdf | 13 | |
| ตารางเรียน ปี 2568.xlsx | 11 | LibreOffice-calc → PDF → Opus |
| ตารางเรียน-ห้องเรียน.xlsx | 8 | |
| docx-form.docx | 8 | |
| doc-form.doc | 8 | LibreOffice-writer path |
| สอบโครงร่างวิทยานิพนธ์.pdf | 7 | |
| สอบวิทยานิพนธ์.pdf | 7 | |
| xlsx-table.xlsx | 4 | |
| annouce.pdf | 4 | |
| สอบความก้าวหน้าวิทยานิพนธ์.pdf | 4 | |
| pdf-form.pdf | 6 | Checkbox detection works without Form Parser |
| ทุนการศึกษา.docx | 1 | Short doc, single chunk appropriate |
| **Total** | **149** | **14 files, zero vision-error / refusal chunks** |

Net LOC delta (v1 → v2, *if v2 replaces v1*): **–1100 / +250 ≈ −85% ingestion surface**.

### 11.6 Rollout (completed 2026-04-19)

v2 is now the sole ingestion pipeline. v1 archived in the `legacy` branch.

1. Phase-1 audit (2026-04-18): v2 entity coverage 24/24 Thai names, 23/23 student IDs, 2/2 emails — on par with v1 ✓
2. Phase-2: skipped — single-tenant deployment, no feature flag needed
3. Phase-3 cutover: all routes (`/document`, `/spreadsheet`, `/gdrive`, `/gdrive/scan`, `/gdrive/file`) now thin-wrap `ingest_v2()` — 2026-04-19
4. Phase-4 (completed 2026-04-19): v1 dispatchers + helpers deleted. Removed: `ingest_pdf`, `ingest_docx`, `ingest_markdown`, `ingest_legacy`, `ingest_spreadsheet`, `_smart_chunk`, `_fix_table_boundaries`, `_chunk_pages`, `_enrich_with_context`, `parse_page_image`, `interpret_spreadsheet`, format dispatcher, chunking.py, enrichment.py. Shared helpers kept in renamed `ingest_helpers.py`: `_build_metadata`, `_convert_to_pdf`, `_delete_existing_vectors`, `_upsert`.

Spec: `docs/superpowers/specs/2026-04-18-ingest-v2-design.md`
Plan: `docs/superpowers/plans/2026-04-18-ingest-v2.md`
Legacy branch (v1 reference): `legacy`
