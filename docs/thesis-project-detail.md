# VIRIYA (วิริยะ) — Thesis Project Detail
## Multi-Tenant Agentic RAG Chatbot SaaS Platform for University Faculty Advisory

**Product name:** VIRIYA — *Relentlessly Relevant.* (formerly "CU TIP RAG Chatbot")
**Version:** 5.0.0 (v2 universal ingestion as sole production path; post-cutover + post-demo hardening)
**Author:** Kurkool Ussawadisayangkool
**Institution:** Chulalongkorn University — Technopreneurship and Innovation Management Program (TIP)
**Date:** 2026-04-20

> **How to read this document:** §§3–6 describe the system's public-facing design and the v2 universal ingestion pipeline as the current runtime architecture. §7.6 (expanded) narrates the evolution from the original v1 rule-based dispatcher to v2 — this narrative is load-bearing for the thesis argument that model capability now outpaces hand-written format rules. §7.7 covers the post-demo v2.1 hardening (rename-safe delete, Drive Connect flow, BM25 cross-process invalidation, rewriter bias fix, Thai-font regression fix). The v1 code is preserved on the `legacy` git branch for reference only.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Problem Statement & Motivation](#2-problem-statement--motivation)
3. [Objectives](#3-objectives)
4. [System Architecture](#4-system-architecture)
5. [Technology Stack](#5-technology-stack)
6. [RAG Pipeline Design (God Mode)](#6-rag-pipeline-design-god-mode)
7. [Document Ingestion Pipeline](#7-document-ingestion-pipeline)
8. [Chat Pipeline (Agentic RAG)](#8-chat-pipeline-agentic-rag)
9. [Search Pipeline (Hybrid Retrieval)](#9-search-pipeline-hybrid-retrieval)
10. [Conversation Memory Management](#10-conversation-memory-management)
11. [Multi-Tenant Architecture](#11-multi-tenant-architecture)
12. [Authentication & Authorization](#12-authentication--authorization)
13. [Admin Portal (Frontend)](#13-admin-portal-frontend)
14. [LINE Messaging Integration](#14-line-messaging-integration)
15. [PDPA Privacy Compliance](#15-pdpa-privacy-compliance)
16. [Deployment & Infrastructure](#16-deployment--infrastructure)
17. [Testing Strategy](#17-testing-strategy)
18. [Database Design](#18-database-design)
19. [API Design](#19-api-design)
20. [Cost Tracking & Billing](#20-cost-tracking--billing)
21. [Key Design Decisions & Rationale](#21-key-design-decisions--rationale)
22. [Performance Optimizations](#22-performance-optimizations)
23. [Feature Summary (21 Commercialization Items)](#23-feature-summary-21-commercialization-items)
24. [Limitations & Future Work](#24-limitations--future-work)

---

## 1. Project Overview

**VIRIYA** (Thai: วิริยะ — "diligence, perseverance") is a **production-grade, multi-tenant Retrieval Augmented Generation (RAG) chatbot SaaS platform** designed for Thai university faculties. The system enables each faculty to deploy its own AI-powered advisory chatbot on LINE Official Account, answering student questions about courses, tuition fees, schedules, forms, regulations, and more — all grounded in the faculty's actual documents.

The platform follows a **microservices architecture** with 4 independently scalable services:
- **Chat API** — Handles LINE webhook events and generates AI responses via an agentic RAG pipeline
- **Ingestion Worker** — Processes documents (PDF, DOCX, XLSX, CSV, Markdown, Google Drive) into searchable vector embeddings
- **Admin API** — Manages tenants, users, analytics, billing, privacy compliance, and backups
- **Admin Portal** — Web-based management interface for faculty administrators and super administrators

The system is deployed on **Google Cloud Run** in the `asia-southeast1` region, serving real students through LINE messaging with sub-second response times on warm instances.

**Key differentiator:** The "God Mode RAG" pipeline combines 9 advanced retrieval techniques — semantic chunking, table-aware chunking, hierarchical contextual enrichment, hybrid BM25+vector search, Reciprocal Rank Fusion, multi-query generation, query decomposition, confidence-aware reranking, and conversation summarization — to achieve superior answer quality compared to basic RAG implementations.

---

## 2. Problem Statement & Motivation

### 2.1 Problem

Thai university faculties face recurring challenges in student advisory:
- **Information overload:** Students struggle to find answers scattered across multiple documents (PDF course catalogs, XLSX fee schedules, DOCX forms, web announcements)
- **Repetitive inquiries:** Faculty staff repeatedly answer the same questions about tuition fees, course prerequisites, registration deadlines, and graduation requirements
- **Language barriers:** Documents may be in Thai, English, or mixed — students need answers in their preferred language
- **Accessibility:** Students expect instant answers via mobile messaging (LINE is the dominant messaging platform in Thailand with 53M+ users)
- **Scalability:** Each faculty has its own document set, LINE account, and administrative needs — a single-tenant solution does not scale

### 2.2 Motivation

- **Commercialization potential:** A multi-tenant SaaS model allows multiple faculties (and potentially multiple universities) to share infrastructure while maintaining strict data isolation
- **AI advancement:** Recent breakthroughs in LLMs (Claude Opus 4.7), embedding models (Cohere embed-v4.0), and reranking (Cohere Rerank v3.5) enable production-quality RAG systems
- **Cloud-native:** Serverless platforms (Cloud Run, Firestore, Pinecone) enable cost-effective operation with pay-per-use pricing
- **PDPA compliance:** Thailand's Personal Data Protection Act (PDPA) requires careful handling of student data — the system must support data export, deletion, anonymization, and retention policies

### 2.3 Research Questions

1. How can a multi-tenant RAG system achieve high retrieval accuracy across diverse Thai university document types (PDF, DOCX, XLSX)?
2. What combination of retrieval techniques (hybrid search, semantic chunking, contextual enrichment, multi-query, reranking) maximizes answer quality in a bilingual (Thai-English) context?
3. How can an agentic RAG architecture (ReAct loop) improve answer completeness compared to single-pass retrieval?

---

## 3. Objectives

### 3.1 Primary Objectives

1. **Design and implement** a multi-tenant RAG chatbot SaaS platform that supports multiple university faculties with strict data isolation
2. **Develop** an advanced RAG pipeline ("God Mode") combining 9 retrieval enhancement techniques for superior answer quality
3. **Deploy** the system on Google Cloud Platform as a production-ready service accessible via LINE messaging
4. **Build** a comprehensive admin portal for faculty administrators to manage documents, monitor usage, and track costs

### 3.2 Secondary Objectives

5. **Ensure PDPA compliance** with data export, deletion, anonymization, and configurable retention policies
6. **Implement cost tracking** per tenant per month for commercialization viability
7. **Achieve comprehensive test coverage** with 266 automated tests (237 backend + 29 frontend) using TDD methodology
8. **Support diverse document formats** including PDF (text + scanned), DOCX, XLSX, CSV, Markdown, and Google Drive integration

---

## 4. System Architecture

### 4.1 High-Level Architecture

```
                           ┌──────────────────────────┐
                           │      LINE Platform        │
                           │  (Messaging API + OA)     │
                           └─────────┬────────────────┘
                                     │ Webhook (HTTPS)
                                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Google Cloud Run (asia-southeast1)               │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────┐ │
│  │  Chat API    │  │Ingest Worker │  │  Admin API   │  │ Admin  │ │
│  │  (FastAPI)   │  │  (FastAPI)   │  │  (FastAPI)   │  │Portal  │ │
│  │ 1GB/2CPU     │  │ 2GB/2CPU     │  │ 512MB/1CPU   │  │Next.js │ │
│  │ min=1        │  │ 0-2 inst     │  │ 0-2 inst     │  │512MB   │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └───┬────┘ │
│         │                  │                  │              │      │
│         └──────────────────┼──────────────────┼──────────────┘      │
│                            │   shared/ package (common code)         │
└────────────────────────────┼────────────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          ▼                  ▼                  ▼
  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
  │   Pinecone   │  │  Firestore   │  │External APIs │
  │ Vector DB    │  │  (NoSQL)     │  │              │
  │ 1536d cosine │  │ 7 collections│  │ Claude Opus  │
  │ namespace/   │  │              │  │ Claude Haiku │
  │ tenant       │  │              │  │ Cohere Embed │
  └──────────────┘  └──────────────┘  │ Cohere Rerank│
                                      │ Google Drive │
                                      └──────────────┘
```

### 4.2 Microservices Monorepo Structure

```
cutip-rag-chatbot/
├── shared/                          # Shared code across all services
│   ├── __init__.py
│   ├── config.py                    # Pydantic BaseSettings (30+ env vars)
│   ├── schemas.py                   # Pydantic request/response models
│   ├── middleware.py                # CORS, rate limiting, error handler, logging
│   └── services/                    # 14 service modules
│       ├── auth.py                  # Firebase Auth + RBAC
│       ├── firestore.py             # Firestore CRUD (7 collections)
│       ├── vectorstore.py           # Pinecone ops + drive_file_id helpers (get_drive_file_id_for, get_existing_drive_state, delete_vectors_by_filename)
│       ├── embedding.py             # Cohere embed-v4.0 (cached singleton)
│       ├── llm.py                   # Claude model factory (4 presets)
│       ├── gdrive.py                # Canonical Drive API (upload_file, download_file, delete_file with 3× retry, find_file_id_by_name, list_files) — promoted from ingest/ when admin-api also needed delete
│       ├── lang.py                  # Thai/English language detection (script dominance)
│       ├── resilience.py            # Retry + circuit-breaker helpers
│       ├── rate_limit.py            # slowapi rate limiting
│       ├── usage.py                 # Per-tenant cost tracking
│       ├── notifications.py         # Slack alert integration
│       ├── backup.py                # Firestore/Pinecone backup to GCS
│       ├── bm25_cache.py            # BM25 index cache (+ cross-process invalidation via Firestore bm25_invalidate_ts)
│       └── dependencies.py          # Utility functions
│
├── chat/                            # Chat API microservice
│   ├── main.py                      # FastAPI app + lifespan (warm models)
│   ├── Dockerfile                   # python:3.11-slim (~290MB)
│   ├── requirements.txt             # 16 dependencies
│   ├── routers/
│   │   └── webhook.py               # LINE webhook + /api/chat endpoints
│   └── services/
│       ├── agent.py                 # Agentic RAG (Claude Opus ReAct loop)
│       ├── tools.py                 # ReAct tools (search, calculate, fetch)
│       ├── search.py                # Search orchestrator (decompose→multi-query→hybrid→RRF→rerank)
│       ├── bm25.py                  # BM25 keyword search index
│       ├── reranker.py              # Cohere Rerank v3.5 + confidence scoring
│       ├── memory.py                # Conversation memory + summarization
│       └── line.py                  # LINE message formatting + signature verification
│
├── ingest/                          # Ingestion Worker microservice (v2 universal)
│   ├── main.py                      # FastAPI app + lifespan
│   ├── Dockerfile                   # python:3.11-slim + LibreOffice + fonts-thai-tlwg (~1.3GB)
│   ├── requirements.txt             # 22 dependencies
│   ├── routers/
│   │   └── ingestion.py             # Drive/Stage/Scan endpoints — all thin-wrap ingest_v2()
│   └── services/
│       ├── ingestion_v2.py          # Universal pipeline (ensure_pdf → extract_hyperlinks → Opus parse+chunk → _upsert)
│       ├── _v2_prompts.py           # Opus 4.7 system prompt + record_chunks tool schema
│       ├── ingest_helpers.py        # 4 shared helpers: _build_metadata (+drive_file_id), _convert_to_pdf, _delete_existing_vectors, _upsert
│       ├── vision.py                # Refusal-pattern filter only (35 lines post-cutover)
│       └── gdrive.py                # Compat shim → shared/services/gdrive.py
│
├── admin/                           # Admin API microservice
│   ├── main.py                      # FastAPI app + lifespan
│   ├── Dockerfile                   # python:3.11-slim (~150MB)
│   ├── requirements.txt             # 13 dependencies
│   └── routers/
│       ├── tenants.py               # Tenant CRUD + Pinecone namespace management
│       ├── users.py                 # Admin user management (RBAC)
│       ├── analytics.py             # Chat logs, usage stats, vector stats
│       ├── privacy.py               # PDPA (export/delete/anonymize/retention)
│       ├── registration.py          # Self-service faculty registration + approval
│       └── backup.py                # Firestore/Pinecone backup exports
│
├── tests/                           # 237 backend tests (pytest)
│   ├── conftest.py                  # In-memory FakeFirestore + mock setup
│   ├── test_auth.py                 # Authentication & RBAC
│   ├── test_chat_auth.py            # Chat-specific auth paths
│   ├── test_tenants.py              # Tenant CRUD + Drive Connect
│   ├── test_users.py                # User management
│   ├── test_search_pipeline.py      # Hybrid search + RRF + multi-query
│   ├── test_bm25.py                 # BM25 keyword search
│   ├── test_confidence_rerank.py    # Confidence-aware reranking
│   ├── test_conversation_summary.py # Conversation summarization
│   ├── test_memory_tenant_scope.py  # Memory tenant isolation
│   ├── test_ingestion_v2.py         # v2 universal pipeline (includes drive_file_id tests)
│   ├── test_ingestion_router.py     # Router thin-wrappers + atomic delete
│   ├── test_scan_all.py             # Smart Scan NEW/RENAME/OVERWRITE/SKIP
│   ├── test_line.py                 # LINE webhook + signature verify
│   ├── test_webhook_dedup.py        # Event dedup cache
│   ├── test_lang.py                 # Thai/English detection (script dominance)
│   ├── test_reliability.py          # Retry + circuit breaker
│   ├── test_super_god.py            # Super admin flows
│   ├── test_privacy.py              # PDPA compliance
│   ├── test_registration.py         # Registration & onboarding
│   ├── test_schemas.py              # Data model validation
│   └── test_dependencies.py         # Utility functions
│
│   # Retired 2026-04-19 (v1 cutover): test_semantic_chunking.py,
│   # test_table_chunking.py, test_hierarchical_enrichment.py,
│   # test_vision_tracking.py — tested v1 modules now on legacy branch
│
├── docker-compose.yml               # Local dev (ports 8001-8003)
└── requirements.txt                 # All dependencies (union)

admin-portal/                        # Frontend (Next.js)
├── src/
│   ├── app/                         # 14 page routes (App Router)
│   ├── components/                  # shadcn/ui + custom components
│   └── lib/
│       ├── api.ts                   # API client (fetch + auth headers)
│       ├── firebase.ts              # Firebase Auth config
│       ├── types.ts                 # TypeScript interfaces
│       ├── hooks.ts                 # useApi, useAuth hooks
│       ├── auth-context.tsx         # React auth context provider
│       └── utils.ts                 # Utility helpers (cn, etc.)
├── src/__tests__/                   # 29 frontend tests (Vitest)
├── Dockerfile                       # Multi-stage Next.js build
└── package.json                     # Next.js 16, React 19, TailwindCSS 4
```

### 4.3 Service Communication

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| LINE Platform | Chat API | HTTPS (Webhook) | Student messages |
| Admin Portal | Admin API | HTTPS (REST) | Tenant/user management, analytics |
| Admin Portal | Ingest Worker | HTTPS (REST) | Document upload, Google Drive ingestion |
| Cloud Scheduler | Ingest Worker | HTTPS + API Key | Hourly auto-scan Google Drive |
| Cloud Scheduler | Admin API | HTTPS + API Key | Daily backup, retention cleanup |
| All Services | Firestore | gRPC | Configuration, logs, users |
| Chat + Ingest | Pinecone | HTTPS | Vector upsert/search |
| Chat | Claude API | HTTPS | LLM reasoning + summarization |
| Chat + Ingest | Cohere API | HTTPS | Embeddings + reranking |
| Ingest | Google Drive API | HTTPS | Document import |

---

## 5. Technology Stack

### 5.1 AI/ML Components

| Component | Technology | Version/Model | Purpose |
|-----------|-----------|--------------|---------|
| Agent Reasoning LLM | Anthropic Claude | Opus 4.7 (`thinking={"type":"adaptive"}`) | Agentic ReAct loop for chat responses |
| Ingestion Parse+Chunk LLM | Anthropic Claude | Opus 4.7 (adaptive thinking, `tool_choice="auto"`, `max_tokens=32000`) | Universal v2 pipeline — reads PDF natively, emits section-tagged chunks via `record_chunks` tool |
| Utility LLM | Anthropic Claude | Haiku 4.5 | Multi-query generation, query decomposition, conversation summarization, follow-up rewriter |
| Embedding Model | Cohere | embed-v4.0 (1536d) | Document and query vectorization |
| Reranking Model | Cohere | Rerank v3.5 | Cross-encoder precision reranking |
| Keyword Search | rank-bm25 | BM25Okapi | In-memory BM25 index per namespace + Firestore-ts cross-process invalidation |
| Agent Framework | LangGraph | Prebuilt ReAct | Agentic tool-use loop |
| LLM Orchestration | LangChain | v0.3+ | Model wrappers, embeddings, vector stores |

> v1 used `LangChain SemanticChunker` (embedding-based chunk boundaries) + section-level Haiku enrichment. Both were removed in the 2026-04-19 cutover — Opus 4.7 emits section-tagged chunks directly.

### 5.2 Backend

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Web Framework | FastAPI | 0.115+ | Async REST API with Pydantic validation |
| ASGI Server | Uvicorn | 0.30+ | Production HTTP server |
| Rate Limiting | slowapi | latest | Per-IP, per-user, per-tenant throttling |
| HTTP Client | httpx | latest | Async HTTP requests |
| PDF Parsing | PyMuPDF | 1.24+ | Text extraction from PDF pages |
| DOCX Parsing | python-docx | 1.1+ | Paragraph, table, and image extraction |
| Spreadsheet | pandas + openpyxl | 2.2+ | XLSX/CSV reading and interpretation |
| Legacy Formats | LibreOffice | headless | .doc/.xls/.ppt conversion to PDF |

### 5.3 Data Stores

| Component | Technology | Configuration | Purpose |
|-----------|-----------|--------------|---------|
| Vector Database | Pinecone | Serverless, 1536d, cosine | Semantic search with namespace isolation |
| Document Database | Google Cloud Firestore | Multi-region | Configuration, logs, users (7 collections) |
| Object Storage | Google Cloud Storage | Regional bucket | Backup exports (Firestore + Pinecone) |
| In-Memory Cache | Python lru_cache | Per-process | BM25 indexes, embedding model, LLM instances |

### 5.4 Frontend

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Framework | Next.js | 16.2.3 | App Router, SSR/ISR |
| UI Library | React | 19.2.4 | Component-based UI |
| Type Safety | TypeScript | 5+ | Static type checking |
| Styling | TailwindCSS | 4 | Utility-first CSS |
| UI Components | shadcn/ui | latest | Headless accessible components |
| Charts | Recharts | latest | Analytics visualization |
| Icons | Lucide React | latest | Icon library |
| Auth SDK | Firebase | latest | Client-side authentication |

### 5.5 Cloud Infrastructure

| Component | Service | Configuration | Purpose |
|-----------|---------|--------------|---------|
| Compute | Cloud Run | asia-southeast1, 4 services | Container hosting |
| Authentication | Firebase Auth | Email/password | User authentication |
| Secrets | Secret Manager | 4 API keys | Secure credential storage |
| Scheduling | Cloud Scheduler | 3 cron jobs | Auto-scan, backup, cleanup |
| Monitoring | Cloud Monitoring | 5-min uptime checks | Service health |
| Alerting | Slack Webhook | #rag-alerts channel | Error notifications |
| Container Registry | Artifact Registry | Docker images | Container storage |

### 5.6 Testing

| Component | Technology | Coverage | Purpose |
|-----------|-----------|---------|---------|
| Backend Tests | pytest + pytest-asyncio | 237 tests | Unit + integration testing |
| Frontend Tests | Vitest + React Testing Library | 29 tests | Component + integration testing |
| API Testing | Postman Collection | Full API coverage | Manual endpoint testing |
| Mock Database | In-memory FakeFirestore | All Firestore ops | Test isolation |

---

## 6. RAG Pipeline Design (God Mode)

The "God Mode" RAG pipeline is the core innovation of this system. It combines 9 advanced retrieval techniques to achieve significantly higher answer quality than basic RAG implementations.

### 6.1 The 9 Improvements

#### Ingestion-Side (Items 1-3)

| # | Improvement | Impact | Description |
|---|-----------|--------|-------------|
| 1 | Semantic Chunking | 30-40% better retrieval | Embedding-based boundary detection instead of fixed character splits |
| 2 | Table-Aware Chunking | Critical for schedule data | Preserves table integrity, merges incomplete rows, splits at row boundaries |
| 3 | Hierarchical Contextual Enrichment | 60% retrieval improvement | Section-level LLM-generated context prepended to each chunk |

#### Retrieval-Side (Items 4-6)

| # | Improvement | Impact | Description |
|---|-----------|--------|-------------|
| 4 | Hybrid Search (BM25 + Vector + RRF) | Catches keyword + semantic queries | Dual retrieval with Reciprocal Rank Fusion merge |
| 5 | Multi-Query Generation | Broader recall | Haiku generates English + Thai synonym variants |
| 6 | Query Decomposition | Handles complex questions | Haiku splits multi-topic queries into sub-queries |

#### Chat-Side (Items 7-9)

| # | Improvement | Impact | Description |
|---|-----------|--------|-------------|
| 7 | Confidence-Aware Reranking | Prevents low-relevance hallucination | 3-tier confidence scoring (HIGH/MEDIUM/filtered) |
| 8 | Source Audit Trail | Full traceability | Tracks which documents contributed to each answer |
| 9 | Conversation Summarization | Unlimited effective context | Haiku summarizes when turns > 5, preserving key details |

### 6.2 End-to-End Pipeline Flow

```
Student Question (LINE)
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│  AGENTIC RAG (Claude Opus 4.7 ReAct Loop)                  │
│                                                             │
│  1. Load conversation history (Firestore + summary)         │
│  2. System prompt: persona + rules + history                │
│  3. ReAct loop:                                             │
│     ├─ REASON: "Should I search? What tool to use?"         │
│     ├─ ACT: Call tool (search_knowledge_base)               │
│     │   └─ SEARCH PIPELINE:                                 │
│     │       ├─ Query Decomposition (Haiku)                  │
│     │       │   └─ simple → pass-through                    │
│     │       │   └─ complex → 2-3 sub-queries                │
│     │       ├─ Multi-Query Generation (Haiku)               │
│     │       │   └─ Per query: original + English + Thai     │
│     │       ├─ Hybrid Search (per variant):                 │
│     │       │   ├─ Vector Search (Pinecone, k=10)           │
│     │       │   └─ BM25 Search (in-memory, k=10)            │
│     │       ├─ RRF Merge (k=60)                             │
│     │       │   └─ Deduplicate by first 200 chars           │
│     │       ├─ Rerank (Cohere v3.5, top-5)                  │
│     │       └─ Confidence Assignment:                       │
│     │           ├─ > 0.6: [HIGH CONFIDENCE]                 │
│     │           ├─ 0.3-0.6: [MEDIUM]                        │
│     │           └─ < 0.3: filtered out                      │
│     ├─ OBSERVE: Search results with confidence labels       │
│     └─ LOOP until ready to answer                           │
│  4. Generate answer with inline source links                │
│  5. Extract sources from tool calls                         │
└─────────────────────────────────────────────────────────────┘
       │
       ├─ Save to conversation memory (Firestore)
       │   └─ If turns > 5: summarize with Haiku
       ├─ Log to chat_logs (Firestore) with sources
       └─ Reply via LINE (text + sources Flex bubble)
```

---

## 7. Document Ingestion Pipeline

> **Historical note:** §§7.1–7.5 describe the v1 pipeline as shipped between 2026-04-10 and 2026-04-18. On 2026-04-19 v1 was replaced by the v2 universal Opus 4.7 pipeline (§7.6). §7.7 covers the v2.1 hardening that followed the 2026-04-19 faculty-staff demo. The v1 sections are retained for thesis reference — they document the rule-based baseline against which v2's universal path was designed.

### 7.1 Supported Formats (v1, historical)

| Format | Extraction Method | Special Handling |
|--------|------------------|-----------------|
| PDF (text-heavy) | PyMuPDF | Page-by-page extraction with hyperlinks |
| PDF (tables/scanned) | Claude Haiku Vision | Image-to-markdown conversion |
| DOCX | python-docx | Paragraphs + tables + image OCR via Vision |
| XLSX | pandas + openpyxl → Claude Haiku Vision | Batch rows → LLM interpretation → markdown |
| CSV | pandas → Claude Haiku Vision | Same as XLSX |
| Markdown | Direct (via Jina Reader) | Web content conversion |
| Legacy (.doc/.xls/.ppt) | LibreOffice headless → PDF pipeline | Requires LibreOffice in Docker container |
| Google Drive | Google Drive API | Batch folder scan or single file import |

### 7.2 Ingestion Flow (v1, historical)

```
Input: File Upload or Google Drive URL
       │
       ▼
1. DUPLICATE DETECTION
   └─ Delete existing vectors with same source_filename in namespace
       │
       ▼
2. FORMAT DETECTION & TEXT EXTRACTION
   ├─ PDF: PyMuPDF for text-heavy pages (> 100 chars/page)
   │       Claude Vision for tables/scanned pages (< 100 chars/page)
   ├─ DOCX: python-docx (paragraphs + tables + image OCR)
   ├─ XLSX/CSV: pandas (raw data) → Claude Haiku Vision (interpretation)
   ├─ Markdown: direct use
   └─ Legacy: LibreOffice conversion → PDF pipeline
       │
       ▼
3. SMART CHUNKING (chunking.py)
   ├─ Build header map from markdown structure (H1, H2, H3)
   ├─ Primary: SemanticChunker (embedding-based boundaries, percentile=90)
   ├─ Fallback: RecursiveCharacterTextSplitter (if semantic fails)
   ├─ Post-processing:
   │   ├─ Cap oversized chunks (> 3000 chars → re-split)
   │   ├─ Fix table boundaries (merge incomplete rows)
   │   ├─ Split large tables at row boundaries (every 20 rows)
   │   ├─ Preserve table headers in every split chunk
   │   ├─ Filter tiny chunks (< 50 chars)
   │   └─ Annotate with header paths ([Section > Subsection])
   └─ Output: 500-1500 char chunks with structural context
       │
       ▼
4. CONTEXTUAL ENRICHMENT (enrichment.py)
   ├─ Parse markdown headers → build section map
   ├─ Assign each chunk to its owning section
   ├─ Haiku generates 1-2 sentence context per chunk:
   │   "Given section '{title}', this chunk contains..."
   ├─ Prepend: [Section: {title} | {context}]\n{chunk_text}
   ├─ Batch 10 chunks, 1-sec pause between batches (rate limiting)
   └─ Fallback: global document context if no headers detected
       │
       ▼
5. VECTORIZATION (Cohere embed-v4.0)
   ├─ Embed enriched chunk text → 1536-dimensional vector
   └─ Attach metadata:
       ├─ tenant_id, source_type (pdf/docx/xlsx/web/gdrive)
       ├─ source_filename, page number
       ├─ doc_category (general/form/curriculum/schedule/announcement/regulation)
       ├─ url, download_link
       ├─ has_table (boolean)
       └─ header_path (section context)
       │
       ▼
6. PINECONE UPSERT
   ├─ Namespace: tenant's pinecone_namespace
   ├─ ID: hash(tenant_id + filename + chunk_offset)
   └─ Batch upsert to avoid rate limits
       │
       ▼
7. POST-PROCESSING
   ├─ BM25 cache invalidation for namespace
   ├─ Usage tracking (embedding calls logged)
   └─ Firestore logging (document record + chunk count)
```

### 7.3 Semantic Chunking Details (v1, historical — removed in v2)

The system uses **LangChain's SemanticChunker** with Cohere embeddings for intelligent chunk boundary detection:

1. **Split** text into sentences
2. **Embed** each sentence using Cohere embed-v4.0
3. **Calculate** cosine distance between consecutive sentence embeddings
4. **Identify breakpoints** where distance exceeds the 90th percentile threshold
5. **Group** sentences between breakpoints into chunks

**Configuration:**
- `breakpoint_threshold_type`: "percentile"
- `breakpoint_percentile_threshold`: 90
- Maximum chunk size: 3000 characters
- Minimum chunk size: 50 characters

**Advantage over fixed-size chunking:** Semantic chunking respects natural topic boundaries in text, keeping related information together and separating unrelated content. This yields 30-40% better retrieval accuracy in benchmarks.

### 7.4 Table-Aware Chunking Details (v1, historical — removed in v2)

Post-processing step that preserves table integrity:

1. **Detect incomplete table rows:** Check if chunk ends with a row that has no closing `|`
2. **Merge incomplete rows** with the beginning of the next chunk
3. **Split oversized table chunks** (> 2000 chars) at row boundaries (every 20 rows)
4. **Preserve table header** in every split chunk (first row with `|---|` separator)
5. **Tag metadata:** `has_table: True` for chunks containing table data

### 7.5 Hierarchical Contextual Enrichment Details (v1, historical — removed in v2)

Section-level context enrichment (60% improvement over global document summary):

1. **Parse markdown headers** (`#`, `##`, `###`) to build a section map
2. **Map each chunk** to its owning section based on character position
3. **Generate context** using Claude Haiku:
   ```
   Prompt: "Write 1-2 sentences explaining what this chunk is about within
   the section '{section_title}'. Include what specific information it contains.
   Respond in the same language as the document."
   ```
4. **Prepend** the generated context: `[Section: {title} | {context}]\n{chunk_text}`
5. **Batch processing:** 10 chunks per batch, 1-second pause between batches
6. **Fallback:** If no headers detected, use global document context

### 7.6 Architectural Evolution — v2 Universal Ingestion (Production, sole path)

This section is the load-bearing argument of the thesis: **when model capability outpaces a hand-written rule, remove the rule.** The v1 pipeline (§§7.1–7.5) accumulated nine months of rule-based special-casing; v2 replaces the accretion with a single LLM-driven path. This subsection documents the design rationale, the empirical audit, the cutover, and the complexity reduction.

#### 7.6.1 Pre-Cutover Incidents

Three incidents in Q2 2026 surfaced a structural limitation of v1's rule-based dispatch:

| Date | Incident | v1 behavior | Root cause |
|------|----------|-------------|-----------|
| 2026-04-17 | Announcement PDF with 23 student records returned chunks missing all 23 names | `has_tables → Vision` routing forced Haiku OCR, which dropped Thai names and emitted English refusal strings ("I cannot read this image") | Haiku's Thai-OCR quality on dense tabular data was insufficient; the `has_tables` routing rule over-indexed on a false signal |
| 2026-04-17 | slide.pdf (45 pages) returned 0 chunks | Per-page Vision split couldn't reconstruct slide-level context; semantic chunker saw fragmented page-sized bits and failed boundary detection | Page-level splitting was wrong for presentations where each slide is a logical chunk |
| 2026-04-18 | New complex-document shape required a new `elif` branch in the format dispatcher | Every novel doc type = new code branch + new test fixture | Architectural churn: each fix taught the pipeline a rule the LLM already knows |

**Observation:** each fix taught the pipeline a rule that a capable multimodal LLM already knows. The architecture was doing the model's job badly.

#### 7.6.2 v2 Design Principle

**One universal path, driven by Opus 4.7's multimodal understanding.** New document shapes become prompt-tuning concerns, not new code branches. The deterministic pre-processing is minimal and serves only where the LLM cannot see:

- `ensure_pdf` — LibreOffice headless conversion for non-PDF inputs (Opus 4.7 accepts PDF natively via `document` content blocks).
- `extract_hyperlinks` — PyMuPDF sidecar extraction of URIs hidden in PDF link-annotations. Opus renders the PDF visually and sees the *text* that links are attached to, but not the URI targets; the sidecar fills this gap. Skips URIs already visible as plain text to avoid duplication.

Everything else — parsing, structure detection, chunking, section labeling — is delegated to Opus via a single tool call.

#### 7.6.3 v2 Pipeline

```
file_bytes (any of .pdf/.docx/.xlsx/.doc/.xls/.ppt/.pptx)
      │
      ▼
ensure_pdf ─────────── PDF passthrough, else LibreOffice headless convert
      │                 Dockerfile installs libreoffice-core + writer + calc + impress
      │                 + fonts-thai-tlwg (required for Thai XLSX/PPTX to render correctly)
      ▼
extract_hyperlinks ─── Deterministic PyMuPDF sidecar: URIs hidden in link
      │                 annotations that the model's visual rendering cannot see.
      │                 Skips URIs already visible in text (prevents duplication).
      ▼
Opus 4.7 API call ──── PDF sent as native document block + sidecar in user text.
      │                 thinking={"type":"adaptive"}, tool_choice={"type":"auto"},
      │                 max_tokens=32000. System prompt instructs a single call to
      │                 record_chunks tool returning:
      │                 [{text, section_path, page, has_table}, ...].
      ▼
Refusal filter ─────── Pattern list (_looks_like_refusal) catches rare cases where
      │                 Opus emits "I cannot process this image" as a chunk.
      │                 35-line module (was 185 lines in v1).
      ▼
_build_metadata ────── Attaches tenant_id, source_filename, source_type, url,
      │                 download_link, has_table, section_path, page, AND
      │                 drive_file_id (post-v2.1 — see §7.7).
      ▼
_upsert ────────────── Cohere embed-v4.0 → Pinecone atomic-swap dedup
                       → Firestore bm25_invalidate_ts (cross-process BM25 invalidation).
```

#### 7.6.4 Why `tool_choice="auto"` (and not forced)?

Anthropic's API disallows enabling adaptive thinking when `tool_choice` forces a specific tool. The project's initial v2 prototype used forced tool use and observed: 45-page `slide.pdf` returned **0 chunks** after 7 minutes of processing (no refusal, no truncation — Opus simply produced an empty `chunks` array, consistent with "model overwhelmed by multi-page multimodal content without the ability to think first"). Switching to `tool_choice={"type":"auto"}` with the system prompt instructing a single `record_chunks` call:

| Document | forced tool_choice | auto + thinking |
|----------|---------------------|------------------|
| slide.pdf (45 pages) | 0 chunks (7 min wasted) | **43 chunks** (~1/slide, as prompted) |
| ประกาศแจ้ง...โครงการพิเศษ.pdf | 0 chunks after `max_tokens=8K` (JSON array truncated mid-stream) | **25 chunks** after bump to 32K — one per student + 2 structural |
| ทุนการศึกษา.docx | 1 chunk | 1 chunk (short doc, single-chunk appropriate) |

In practice Opus complies with the prompt's instruction to call the tool; fallback (no `tool_call` → `[]`) is preserved defensively.

**Takeaway:** two Anthropic-API invariants forced the v2 design shape — (a) thinking is incompatible with forced tool use, (b) long/dense multimodal content empirically requires thinking. Therefore: prompt-driven tool invocation, not forced.

#### 7.6.5 Empirical Audit (Phase-1, 2026-04-18)

14 sample documents from `sample-doc/cutip-doc/` ingested into Pinecone namespace `cutip_v2_audit`, isolated from the production `cutip_01` namespace via `namespace_override` query param (suffix-validated to `_v2_audit` to prevent arbitrary writes):

| File | v2 chunks | v1 chunks | Notes |
|------|-----------|-----------|-------|
| slide.pdf (45 pages) | 43 | 0 | v1 produced zero chunks — regression that motivated v2 |
| ประกาศแจ้งคณะกรรมการสอบ.pdf | 25 | 14 | 23 student records + 2 structural in v2; v1 lost all 23 names |
| สอบโครงการพิเศษ.pdf | 13 | 11 | |
| ตารางเรียน ปี 2568.xlsx | 11 | 10 | Post-font-fix; pre-fix rendered as □ boxes (see §7.7) |
| ตารางเรียน-ห้องเรียน.xlsx | 8 | 7 | |
| docx-form.docx | 8 | 6 | |
| doc-form.doc | 8 | 6 | LibreOffice-writer → PDF → Opus |
| สอบโครงร่างวิทยานิพนธ์.pdf | 7 | 6 | |
| สอบวิทยานิพนธ์.pdf | 7 | 6 | |
| xlsx-table.xlsx | 4 | 4 | |
| annouce.pdf | 4 | 3 | |
| สอบความก้าวหน้าวิทยานิพนธ์.pdf | 4 | 3 | |
| pdf-form.pdf | 6 | 5 | Checkbox detection without Form Parser |
| ทุนการศึกษา.docx | 1 | 1 | Short doc, single-chunk appropriate |
| **Total** | **148** | **82** | — |

**Entity coverage sweep** (queries against `/api/chat` pointed at `cutip_v2_audit` via temporary tenant-metadata swap):
- 24/24 Thai committee-member names recalled
- 23/23 student IDs recalled from announcement PDF
- 2/2 emails present in chunks
- 0 refusal strings in chunks
- 0 empty/whitespace-only chunks

#### 7.6.6 Complexity Reduction

| Measure | v1 | v2 |
|---------|----|----|
| Format-specific code paths | 5 (PDF / DOCX / XLSX / legacy / markdown) | 1 (universal) |
| Anthropic models in ingestion | 3 (Opus Vision + Haiku Vision + Haiku Precise for enrichment) | 1 (Opus 4.7) |
| Rule-based routing | `has_text_layer`, `has_tables`, `is_slides`, `has_images` branches | None |
| Separate chunker + enricher | `_smart_chunk` + `_fix_table_boundaries` + `_chunk_pages` + `_enrich_with_context` + SemanticChunker | Single Opus call returns already-annotated chunks |
| Ingest-side LOC | ~1500 | ~250 |
| Ingestion tests | 34 (semantic/table/enrichment/vision) | 11 (v2 contract tests) + 10 (scan-all) + 12 (router) |
| Deployment image size | 1.2 GB | 1.3 GB (+100MB for Thai fonts, not v2-specific) |

**Net LOC delta:** −1100 / +250 ≈ **−85% ingestion surface**.

#### 7.6.7 Cutover Execution (2026-04-19)

The original 4-phase plan (audit → feature-flag → cutover → deletion) was compressed to same-day cutover. Phase-2 feature flag was skipped — with a single-tenant deployment (`cutip_01`) the feature flag offered no safety benefit, and the empirical audit on `cutip_v2_audit` provided sufficient evidence.

| Step | Action | Timestamp |
|------|--------|-----------|
| 1 | Router rewrite — all 5 ingest endpoints (`/document`, `/spreadsheet`, `/gdrive`, `/gdrive/scan`, `/gdrive/file`) thin-wrap `ingest_v2()` | 11:40 |
| 2 | `chunking.py` + `enrichment.py` deleted (v1-only) | 12:05 |
| 3 | `vision.py` trimmed: 185 → 35 lines (only `_looks_like_refusal` retained) | 12:15 |
| 4 | `ingestion.py` renamed to `ingest_helpers.py`; kept 4 shared helpers (`_build_metadata`, `_convert_to_pdf`, `_delete_existing_vectors`, `_upsert`) — 215 lines | 12:30 |
| 5 | v1-only schemas removed (`IngestMarkdownRequest`, `IngestMetadata`, `ALLOWED_DOC_CATEGORIES`); endpoint `POST /api/tenants/{id}/ingest/markdown` removed | 12:50 |
| 6 | v1 test files retired (`test_semantic_chunking.py`, `test_table_chunking.py`, `test_hierarchical_enrichment.py`, `test_vision_tracking.py`) | 13:10 |
| 7 | `legacy` branch created from pre-cutover commit for thesis reference | 13:20 |
| 8 | Cloud Run redeploy → `cutip-ingest-worker-00023-p2g` | 14:15 |

**Thesis principle demonstrated:** one day of structural simplification removed ~1100 LOC of rule-based scaffolding with zero regression. The speed of the cutover is evidence that the architectural debt was taxing ongoing work.

#### 7.6.8 Key Artifacts

- **Spec:** `docs/superpowers/specs/2026-04-18-ingest-v2-design.md`
- **Plan:** `docs/superpowers/plans/2026-04-18-ingest-v2.md` (13-task TDD plan; all 12 code tasks done + Phase-1 audit evidence)
- **Legacy branch:** `legacy` (v1 reference)
- **Post-cutover revision:** `cutip-ingest-worker-00023-p2g` (as of 2026-04-20)

### 7.7 Post-Demo Hardening (v2.1, 2026-04-19 → 2026-04-20)

On 2026-04-19, a faculty-staff demo exposed real-world scenarios the v2 cutover had not explicitly designed for. The following hardening wave turns v2 into v2.1:

#### 7.7.1 Rename + Overwrite Safety (`drive_file_id` in chunk metadata)

**Incident:** a faculty admin uploaded a file to Drive, ingested it, then renamed it in Drive, then deleted it from the admin portal. Outcome: Pinecone still contained chunks under the old filename — the portal couldn't find them (listed under the new name) and Smart Scan didn't re-ingest (Drive side was deleted). **Ghost chunks.**

**Fix:** every chunk now stores `drive_file_id` in its metadata. This turns the namespace into a two-key store:
- `source_filename` — human-readable, mutable on rename.
- `drive_file_id` — stable across renames, unique per file.

Helpers added to `shared/services/vectorstore.py`:
- `get_drive_file_id_for(namespace, source_filename) → str | None`
- `get_existing_drive_state(namespace) → dict[drive_file_id, {filename, ingest_ts}]`
- `delete_vectors_by_filename(namespace, source_filename) → int`

Smart Scan now detects four states per file:
- **NEW** — `drive_file_id` not in Pinecone → ingest.
- **OVERWRITE** — `drive_file_id` present, Drive `modifiedTime` > last `ingest_ts` → re-ingest (atomic-swap dedup handles old chunks).
- **RENAME** — `drive_file_id` present with different `source_filename` → delete old-name chunks + re-ingest under new name.
- **SKIP** — unchanged.

Tests: `tests/test_scan_all.py` (10 cases covering every state + combinations).

#### 7.7.2 Atomic Single-File + Bulk Delete

**Pre-demo behavior:** the admin portal had only "Delete all documents" (bulk wipe of Pinecone namespace — no Drive cleanup).

**v2.1 behavior:**
- Per-row trash icon on each document in the portal → `delete_vectors_by_filename` in Pinecone + `delete_file` on Drive (3× exponential-backoff retry).
- Delete-all iterates Pinecone's distinct filenames, deletes Drive files, then wipes the Pinecone namespace.

**Delete-order rationale:** Pinecone-first, Drive-second. If Drive fails after Pinecone succeeds, the file remains in Drive but no chunks reference it; next Smart Scan re-ingests cleanly. The reverse order produces "ghost answers" — orphan chunks citing a dead Drive link. The 3× retry covers transient Drive API failures without changing the order.

#### 7.7.3 BM25 Cross-Process Invalidation

**Pre-demo behavior:** each chat-api Cloud Run replica had its own `@lru_cache`-backed BM25 index. After an ingest on the ingest-worker, the chat-api's BM25 was stale until the replica restarted. Multi-replica chat-api exacerbates this.

**v2.1:** every ingest/delete/rename path writes `bm25_invalidate_ts = time.time()` on the tenant's Firestore doc. Chat-api checks this ts on each query and re-warms its in-process BM25 if the cached ts is older. Single Firestore read per query (cheap). Chat-api also logs `BM25 warmed for namespace '<ns>': <N> documents` on each re-warm — verifiable in Cloud Logs.

#### 7.7.4 Rewriter Bias Fix

**Incident during demo:** students typed plain Thai noun queries like `ตารางเรียน` ("class schedule"), `ประกาศ` ("announcement"), `สอบวิทยานิพนธ์` ("thesis defense"). The Haiku rewriter was injecting qualifiers the user never typed — appending `ดาวน์โหลด` ("download"), `ฟอร์ม` ("form"), `เกณฑ์` ("criteria") — which pulled the hybrid search off-topic and produced zero results. This had been invisible in pre-demo testing because test queries were longer and the rewriter's rewrites were largely benign.

**Fix:** the rewriter now short-circuits on queries without follow-up markers (pronouns, elliptical references). The regex `_FOLLOWUP_MARKERS` checks for `มัน / นี้ / นั้น / เขา / เธอ` and common ellipsis patterns. No markers → pass query through unchanged. For queries with markers, the rewrite prompt has been tightened with explicit anti-injection rules ("do not add qualifiers not in the user's text").

#### 7.7.5 Thai Font Regression (`fonts-thai-tlwg`)

**Regression discovered during post-demo audit:** XLSX coverage on `ตารางเรียน.xlsx` dropped 70% → 21%. Root cause: `python:3.11-slim + libreoffice-*` with `--no-install-recommends` ships English-only fonts. Thai glyphs in the XLSX rendered as □ boxes in the PDF conversion step. Opus vision saw boxes and emitted "ไม่สามารถถอดความได้" ("cannot transcribe") → incomplete chunks.

**Fix:** `ingest/Dockerfile` now installs `fonts-thai-tlwg` + runs `fc-cache -f`. One-line Dockerfile delta; +~80MB image size. Full XLSX coverage restored.

**Memory tag:** `memory/feedback_deploy_gotchas.md` records "LibreOffice needs fonts-thai-tlwg for XLSX Thai" to prevent re-regression on future re-provisioning.

#### 7.7.6 Drive Connect Flow (OAuth + Picker + SA auto-share)

**Pre-demo behavior:** connecting a tenant to a Drive folder required pasting a Drive folder ID into a textbox and manually sharing the Service Account email as Editor. Error-prone — most demo participants got one or both wrong.

**v2.1:** a "Connect Drive" button in the documents page drives the full flow:
1. Browser requests OAuth scope `drive.file` via Google Identity Services.
2. Google Picker (scoped to the user's Drive) lets the user select a folder.
3. On selection, the portal auto-calls Drive API `permissions.create` with `role=writer, emailAddress=SA_EMAIL`.
4. `POST /api/tenants/{id}/gdrive/connect` saves `drive_folder_id` + `drive_folder_name` on the tenant doc.

`drive.file` scope (not full `drive`) — the SA only sees files explicitly shared via the Picker, not the user's whole Drive.

#### 7.7.7 Stage Upload (local file → Drive → v2)

**v2.1:** "Stage Upload" on the documents page accepts a local file from the browser, streams it to the admin API, which (a) uploads it to the tenant's Drive folder via SA credentials, (b) calls `ingest_v2()` with the new Drive file's `webViewLink`. The net effect: every document in Pinecone has a corresponding file in the tenant's Drive, and citations link to a real browsable Drive file. Unifies the data model — there is no "uploaded-but-not-in-Drive" state.

#### 7.7.8 Editable Pinecone Namespace in Portal

**Pre-demo:** the `pinecone_namespace` field on the tenant detail page was disabled — a super admin could not reassign a tenant to a different namespace without hitting Firestore directly. This blocked the v2-audit → v2-prod swap workflow during the demo window.

**v2.1:** the field is editable with pattern validator `^[a-z0-9_-]+$`. Updating the namespace auto-bumps `bm25_invalidate_ts` so the chat-api re-warms BM25 on the next query. This enabled a clean demo-day workflow: temporarily point tenant at `cutip_v2_audit` → demo → revert to `cutip_01`.

#### 7.7.9 VIRIYA Branding (2026-04-20)

Product name finalized: **VIRIYA** (วิริยะ — "diligence, perseverance"), tagline *Relentlessly Relevant.* Admin portal replaced the default shadcn Bot icon with a custom SVG logo (V-mark with flame glyph, #26215C + #EF9F27 palette) across sidebar, login, and register pages. Logo files live at `admin-portal/public/logo/{viriya-icon-mark, viriya-logo-horizontal, viriya-logo-primary}.svg`.

---

## 8. Chat Pipeline (Agentic RAG)

### 8.1 Agent Architecture

The chat system uses a **ReAct (Reasoning + Acting) agent** built with LangGraph, powered by Claude Opus 4.7. Unlike simple RAG (retrieve → generate), the agent can:

- **Reason** about whether to search, what to search for, and how to combine results
- **Act** by calling tools (search, calculate, fetch webpage)
- **Observe** tool results and decide whether to search again or answer
- **Loop** until it has sufficient information to provide a comprehensive answer

### 8.2 Agent Configuration

```python
LLM: Claude Opus 4.7
Temperature: 0.1 (deterministic, factual)
Max tokens: 8192
Max retries: 3
```

### 8.3 Available Tools

| Tool | Description | Use Case |
|------|-----------|----------|
| `search_knowledge_base(query)` | Full hybrid search pipeline | Faculty-related questions |
| `search_by_category(query, category)` | Category-filtered search | When student asks about specific document type |
| `calculate(expression)` | Safe math evaluation | GPA calculation, tuition totals, credit counts |
| `fetch_webpage(url)` | Jina Reader API | Fetch referenced web content |

### 8.4 System Prompt Structure

The agent receives a carefully engineered system prompt:

```
{tenant.persona}  // Faculty-specific personality and context

You have tools to search the faculty's knowledge base and perform calculations.

## Core Rules
- ALWAYS search before answering faculty-related questions
- Answer in SAME LANGUAGE as user (Thai → Thai, English → English)
- For greetings/casual chat, respond WITHOUT searching
- For math, use calculate tool

## Search Result Confidence
- [HIGH CONFIDENCE]: Use directly, state confidently
- [MEDIUM]: Use but add disclaimer "จากข้อมูลที่พบ"
- No results above threshold: Say honestly you couldn't find it

## Answer Quality
- Structure: Clear headers, numbered steps, bullet points
- Inline links: [document_name](download_url)
- Length: 1500-3000 characters (thorough but concise)
- Tone: Formal but warm
- End with: Next step suggestion or offer for more details

## Conversation History
{formatted_turns_or_summary}
```

### 8.5 Source Tracking

The agent automatically tracks which documents contributed to each answer:

1. Parse `tool_calls` from agent response messages
2. Extract document metadata from search results
3. Store structured source list: `{filename, page, category, download_link, relevance_score, confidence}`
4. Pass sources to LINE reply for rich formatting

---

## 9. Search Pipeline (Hybrid Retrieval)

### 9.1 Pipeline Overview

The search pipeline is the most sophisticated component of the system, implementing 5 stages:

```
Query → Decomposition → Multi-Query → Hybrid Search → RRF Merge → Confidence Rerank → Results
```

### 9.2 Stage 1: Query Decomposition

**Model:** Claude Haiku (temp=0.3, max 150 tokens)

**Purpose:** Split complex multi-topic questions into simpler sub-queries.

**Prompt:**
```
If it asks about multiple topics or requires comparison, decompose into
separate search queries. If single-topic, return as-is.
Return JSON: {"type": "simple", "query": "..."} or
             {"type": "complex", "sub_queries": [...]}
```

**Example:**
- Input: "ค่าเทอมปริญญาบัตร 4 ปี vs 5 ปี"
- Output: `{"type": "complex", "sub_queries": ["ค่าเทอม 4 ปี", "ค่าเทอม 5 ปี"]}`

### 9.3 Stage 2: Multi-Query Generation

**Model:** Claude Haiku (temp=0.3, max 150 tokens)

**Purpose:** Generate search variants to improve recall across bilingual content.

For each query/sub-query, Haiku generates 2 additional variants:
1. **English translation** of key terms
2. **Thai synonym/rephrase**

**Result:** 3 parallel search paths per sub-query (original + 2 variants)

### 9.4 Stage 3: Hybrid Search (per variant)

Each variant is searched through two parallel channels:

**Vector Search (Pinecone):**
- Embed query with Cohere embed-v4.0
- Similarity search in tenant's namespace
- k=10 results with optional category filter
- Captures semantic similarity

**BM25 Search (in-memory):**
- Query tokenized (whitespace + punctuation split)
- Search against namespace's BM25 index
- k=10 results
- Captures exact keyword matches (course codes, form numbers, names)

### 9.5 Stage 4: Reciprocal Rank Fusion (RRF)

Merges vector and BM25 results using RRF formula:

```
score(document) = Σ 1 / (k + rank_i + 1)
```

Where:
- k = 60 (smoothing constant)
- rank_i = document's rank in each result list

**Deduplication:** First 200 characters of chunk content as dedup key.

**Output:** Top 15 unique documents with combined scores.

### 9.6 Stage 5: Confidence-Aware Reranking

**Model:** Cohere Rerank v3.5 (cross-encoder)

**Input:** Top 15 documents + original query
**Output:** Top 5 documents with relevance scores (0.0 - 1.0)

**Confidence Assignment:**
- Score > 0.6 → `[HIGH CONFIDENCE]` — Agent uses directly, states confidently
- Score 0.3 - 0.6 → `[MEDIUM - may not be exact match]` — Agent adds disclaimer
- Score < 0.3 → **Filtered out** — Not shown to agent, prevents hallucination

### 9.7 BM25 Index Management

- **Storage:** In-memory per-namespace cache
- **Building:** Lazy — built from Pinecone vectors on first search, or seeded from ingested chunks
- **Tokenization:** Whitespace + punctuation split (sufficient for Thai keyword search)
- **Invalidation:** Cache cleared when new documents are ingested into namespace
- **Thread safety:** Locking mechanism for concurrent access

---

## 10. Conversation Memory Management

### 10.1 Architecture

Conversation memory is stored in Firestore's `conversations` collection, keyed by LINE user_id.

### 10.2 Memory Schema

```python
{
    "user_id": "U1234567890",         # LINE user ID
    "turns": [                         # Recent conversation turns
        {"query": "ค่าเทอมเท่าไร", "answer": "ค่าเทอม..."},
        {"query": "สมัครอย่างไร", "answer": "ขั้นตอน..."}
    ],
    "summary": "นักศึกษาสอบถามเรื่อง...",  # Compressed earlier context
    "last_active": Timestamp            # TTL tracking
}
```

### 10.3 Memory Lifecycle

1. **Get history:** Load turns + summary from Firestore
2. **TTL check:** If `last_active` > 1800 seconds (30 min) ago → clear history (session expired)
3. **Add turn:** Append new `{query, answer}` to turns array
4. **Overflow check:** If turns > 5 (MAX_HISTORY_TURNS):
   - Summarize all turns + existing summary using Claude Haiku
   - Reset turns to empty array
   - Store summary string
5. **Update:** Save to Firestore with new `last_active` timestamp

### 10.4 Summarization Prompt

```
Summarize this conversation between a student and university assistant
in 1-2 sentences. Preserve key topics, specific details (course codes,
names, amounts), and any unresolved questions.
```

### 10.5 History Format for Agent

```
Previous context: {summary}
Recent conversation:
Student: {turn_1_query}
Assistant: {turn_1_answer}
Student: {turn_2_query}
Assistant: {turn_2_answer}
```

### 10.6 Design Rationale

- **Why summarize instead of dropping?** Summarization preserves key context (course codes, specific questions) that the student may reference later
- **Why Haiku?** 60x cheaper than Opus, sufficient quality for summarization
- **Why 30-minute TTL?** Balances context relevance with cost — most student sessions complete within 30 minutes
- **Effective result:** Unlimited conversation context at fixed memory cost

---

## 11. Multi-Tenant Architecture

### 11.1 Tenant Isolation

Each faculty (tenant) is completely isolated across all data stores:

| Layer | Isolation Mechanism |
|-------|-------------------|
| Vector Database | Pinecone **namespaces** (one per tenant) |
| Document Database | Firestore **tenant_id field** on every document |
| BM25 Index | **Separate in-memory index** per namespace |
| Chat Logs | Filtered by **tenant_id** |
| Usage Tracking | Per-tenant monthly documents (`{tenant_id}_{YYYY-MM}`) |
| LINE Bot | **line_destination** maps to specific tenant |
| Admin Access | RBAC: faculty_admin sees only **assigned tenant_ids** |

### 11.2 Tenant Configuration

Each tenant stores:

```python
{
    "tenant_id": "cutip_01",
    "faculty_name": "คณะวิศวกรรมศาสตร์",
    "line_destination": "U1a2b3c...",           # LINE OA User ID
    "line_channel_access_token": "eyJ...",       # LINE API token
    "line_channel_secret": "abc123...",          # For webhook signature
    "pinecone_namespace": "cutip_01",            # Vector namespace (editable in portal, pattern ^[a-z0-9_-]+$)
    "persona": "คุณเป็นผู้ช่วย...",              # Custom system prompt
    "drive_folder_id": "1duGSSJxj9g...",         # Connected Drive folder (set via Connect flow, §7.7.6)
    "drive_folder_name": "CUTIP Docs",           # Display name shown next to "Connected" badge
    "bm25_invalidate_ts": 1713537600.0,          # Cross-process BM25 invalidation (§7.7.3)
    "is_active": true,
    "onboarding_completed": [1, 2, 3],           # Wizard steps done
    "created_at": "2026-04-10T...",
    "updated_at": "2026-04-16T..."
}
```

### 11.3 Tenant Identification Flow

```
LINE Message → Webhook payload contains "destination" (bot's User ID)
    → Firestore query: tenants where line_destination == destination
    → If found and is_active: proceed with that tenant's config
    → If not found: 404 (unknown bot)
    → If inactive: skip processing
```

---

## 12. Authentication & Authorization

### 12.1 Authentication Methods

**Method 1: Firebase ID Token (Primary)**
- Used by: Admin Portal users (browser)
- Flow: Login with email/password → Firebase returns ID token → Token sent as `Authorization: Bearer {token}` → Backend verifies with Firebase Admin SDK
- Token contains: uid (Firebase user ID)

**Method 2: API Key (Programmatic)**
- Used by: Cloud Scheduler jobs, n8n integrations
- Flow: Send `X-API-Key: {ADMIN_API_KEY}` header → Backend validates against Secret Manager value
- Returns: Synthetic super_admin user (`system@api-key`)

### 12.2 Role-Based Access Control (RBAC)

| Role | Permissions |
|------|------------|
| `super_admin` | Full access: all tenants, user management, billing, registration approval, backup |
| `faculty_admin` | Limited access: assigned tenants only, document upload, chat logs, analytics, onboarding |
| (public) | Registration form, privacy policy only |

### 12.3 Access Control Implementation

```python
# Dependency injection chain:
get_current_user()        → Returns authenticated user dict or raises 401
require_super_admin()     → Wraps get_current_user, raises 403 if not super_admin
get_accessible_tenant()   → Returns tenant if user has access (super_admin=all, faculty=assigned)
```

---

## 13. Admin Portal (Frontend)

### 13.1 Technology

- **Framework:** Next.js 16.2.3 (App Router)
- **UI:** React 19, shadcn/ui, TailwindCSS 4
- **Charts:** Recharts
- **Auth:** Firebase Auth (client-side)
- **Deployment:** Cloud Run (standalone output mode)

### 13.2 Pages (14 Routes)

| Route | Access | Description |
|-------|--------|-------------|
| `/login` | Public | Firebase email/password login |
| `/register` | Public | Faculty self-registration form |
| `/` | All admins | Dashboard: tenant count, total chats, unique users, cost overview |
| `/tenants` | All admins | Tenant list (super admin: all, faculty: assigned only) |
| `/tenants/new` | Super admin | Create new tenant form |
| `/tenants/[id]` | Authorized | Tenant detail: config, LINE credentials, persona, **editable Pinecone namespace** |
| `/tenants/[id]/documents` | Authorized | **Connect Drive** (OAuth + Picker + SA auto-share), **Stage Upload** (local file → Drive → v2), **Smart Scan** (NEW / RENAME / OVERWRITE / SKIP), per-row trash-icon delete, bulk "Delete all" |
| `/tenants/[id]/chat-logs` | Authorized | Paginated chat history, query/answer preview, CSV export |
| `/tenants/[id]/analytics` | Authorized | Monthly cost chart, call counts, cost breakdown |
| `/users` | Super admin | Admin user CRUD (create, edit, delete, role assignment) |
| `/registrations` | Super admin | Pending registrations: approve → auto-create tenant + user, or reject |
| `/billing` | Super admin | Global cost dashboard, monthly trends, per-tenant breakdown |
| `/settings` | All admins | API key display, health check status |
| `/onboarding` | Faculty admin | 5-step setup wizard with progress tracking |

### 13.3 Self-Service Registration Flow

```
Faculty submits /register form (name, email, password, note)
    → Creates pending_registrations document in Firestore
    → Super admin sees in /registrations page
    → On "Approve":
        1. Create Firebase Auth user
        2. Create admin_users document (role: faculty_admin)
        3. Create tenant document (auto-generated tenant_id)
        4. Create Pinecone namespace
        5. Assign tenant to user
        6. Update registration status: "approved"
    → On "Reject":
        1. Update status: "rejected" with reason
```

---

## 14. LINE Messaging Integration

### 14.1 Webhook Flow

```
LINE Server → POST /webhook/line
    │
    ├─ Headers: X-Line-Signature (HMAC-SHA256)
    ├─ Body: JSON payload with events
    │
    ▼
1. Parse body, extract "destination" (bot's User ID)
2. Lookup tenant by line_destination in Firestore
3. Verify signature: HMAC-SHA256(body, tenant.line_channel_secret)
4. For each text event:
   a. Extract user_id, text
   b. Run agentic RAG: run_agent(text, user_id, tenant)
   c. Log chat to Firestore (query, answer, sources)
   d. Reply via LINE Messaging API
```

### 14.2 Reply Message Format

**Text Messages:**
- Split answer into chunks (max 5000 chars per LINE message)
- Smart splitting at paragraph boundaries (double-newline, then single-newline)
- Up to 5 message parts

**Sources Flex Bubble:**
- Compact LINE Flex Message showing source documents
- Each source: filename, page, category, confidence badge, download link (clickable)
- Maximum 5 sources displayed

### 14.3 Rich Menu

Custom 6-button Rich Menu for quick access:
- Configurable per-tenant
- Buttons: predefined common queries + help text
- Setup via `setup_rich_menu.py` script

### 14.4 Error Handling

| Error | Response to Student (Thai) |
|-------|---------------------------|
| Rate limit | "ระบบมีผู้ใช้งานจำนวนมาก กรุณาลองใหม่ในอีกสักครู่" |
| Auth error | "ระบบมีปัญหาด้านการยืนยันตัวตน กรุณาแจ้ง admin" |
| Quota exceeded | "ระบบหมดโควต้าการใช้งานชั่วคราว กรุณาแจ้ง admin" |
| Generic error | "เกิดข้อผิดพลาดในระบบ กรุณาลองใหม่อีกครั้ง" |

---

## 15. PDPA Privacy Compliance

Thailand's Personal Data Protection Act (PDPA) requires specific data handling capabilities.

### 15.1 Privacy Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tenants/{id}/privacy/export/{user_id}` | GET | Export all user data (chat logs, conversations, consents) |
| `/api/tenants/{id}/privacy/users/{user_id}` | DELETE | Right to be forgotten: delete all user data |
| `/api/tenants/{id}/privacy/anonymize/{user_id}` | POST | Replace user_id with SHA256 hash in all records |
| `/api/privacy/retention/cleanup` | POST | Global: delete chat logs older than retention period (super admin / API key) |
| `/api/privacy/policy` | GET | Public privacy policy text |
| `/api/tenants/{id}/privacy/consents` | POST | Record user consent |
| `/api/tenants/{id}/privacy/consents/{user_id}` | GET | Retrieve user's consents |
| `/api/tenants/{id}/privacy/consents/{user_id}/{consent_type}` | DELETE | Revoke a specific consent type |

### 15.2 Data Retention

- **Default retention:** 90 days (configurable via `RETENTION_DAYS`)
- **Automated cleanup:** Cloud Scheduler runs daily at 03:00 UTC
- **Scope:** Chat logs older than retention period are permanently deleted

### 15.3 Consent Tracking

```python
{
    "tenant_id": "cutip_01",
    "user_id": "U1234567890",
    "consent_type": "data_collection",  # or "analytics", "marketing"
    "version": "1.0",
    "is_active": true,
    "granted_at": "2026-04-10T..."
}
```

---

## 16. Deployment & Infrastructure

### 16.1 Cloud Run Services

| Service | Image Size | Resources | Scaling | Purpose |
|---------|-----------|-----------|---------|---------|
| cutip-chat-api | ~290MB | 1GB RAM, 2 CPU | 1-10 instances | LINE webhook, chat |
| cutip-ingest-worker | ~1.2GB | 2GB RAM, 2 CPU | 0-2 instances | Document processing |
| cutip-admin-api | ~150MB | 512MB RAM, 1 CPU | 0-2 instances | CRUD, analytics |
| cutip-admin-portal | ~200MB | 512MB RAM, 1 CPU | 0-2 instances | Web UI |

### 16.2 Cloud Scheduler Jobs

| Job | Schedule | Target | Purpose |
|-----|----------|--------|---------|
| cutip-01-auto-scan | Hourly | Ingest Worker | Auto-scan Google Drive folder for new files |
| cutip-backup-daily | 02:00 UTC daily | Admin API | Export Firestore + Pinecone to GCS |
| cutip-retention-cleanup | 03:00 UTC daily | Admin API | Delete expired chat logs (PDPA) |

### 16.3 Cloud Monitoring

- **Uptime checks:** Every 5 minutes on all 4 services (`/health` endpoint)
- **Slack alerts:** Critical errors sent to `#rag-alerts` channel
- **Request logging:** Method, path, status code, duration (ms) for every request

### 16.4 Deployment Commands

```bash
# Chat API
cd cutip-rag-chatbot && cp chat/Dockerfile Dockerfile
gcloud builds submit --tag asia-southeast1-docker.pkg.dev/cutip-rag/cloud-run-source-deploy/cutip-chat-api --region=asia-southeast1
gcloud run deploy cutip-chat-api --image ... --region asia-southeast1 \
  --set-secrets "PINECONE_API_KEY=PINECONE_API_KEY:latest,..." \
  --allow-unauthenticated --port 8000 --memory 1Gi --cpu 2 --min-instances=1

# Ingest Worker (similar with 2Gi memory, no min-instances)
# Admin API (similar with 512Mi memory, 1 CPU)
# Admin Portal (Next.js, port 3000)
```

### 16.5 Docker Strategy

- **Monorepo shared code:** Each Dockerfile copies `shared/` + its own service directory
- **Chat API:** Lightweight (no LibreOffice, no document parsers)
- **Ingest Worker:** Heavy (LibreOffice for legacy format conversion)
- **Admin API:** Lightest (no AI dependencies)
- **Workaround:** `cp {service}/Dockerfile Dockerfile` before `gcloud builds submit` (Cloud Build doesn't support `-f` flag)

---

## 17. Testing Strategy

### 17.1 Backend Tests (237 tests)

**Framework:** pytest + pytest-asyncio
**Mock Strategy:** In-memory FakeFirestore class replacing all Firestore operations

| Test File | Coverage Area |
|-----------|---------------|
| test_auth.py | Authentication, RBAC, tenant scoping |
| test_chat_auth.py | Chat-endpoint auth paths (LINE signature, bearer token, API key) |
| test_tenants.py | Tenant CRUD, duplicate check, scoped access, Drive Connect |
| test_users.py | User CRUD, role management, self-deletion prevention |
| test_search_pipeline.py | RRF, query decomposition, multi-query, hybrid search |
| test_bm25.py | BM25 keyword matching, Thai text, cache invalidation, cross-process ts |
| test_confidence_rerank.py | Reranker scoring, confidence classification |
| test_conversation_summary.py | History formatting, summarization, empty handling |
| test_memory_tenant_scope.py | Memory keyed by (user_id, tenant_id) pair — prevents cross-tenant leakage |
| test_ingestion_v2.py | v2 universal pipeline — Opus stubbed, tests cover ensure_pdf, sidecar, dedup, drive_file_id propagation |
| test_ingestion_router.py | Router thin-wrappers, atomic single/bulk delete, delete ordering |
| test_scan_all.py | Smart Scan state machine: NEW / RENAME / OVERWRITE / SKIP |
| test_line.py | LINE webhook + signature verify + Flex bubble formatting |
| test_webhook_dedup.py | LINE event-id dedup cache (retry-on-network-flake protection) |
| test_lang.py | Thai/English detection via script dominance (not mere presence) |
| test_reliability.py | Retry decorator + circuit-breaker (Cohere rerank neutral-0.5 fallback) |
| test_super_god.py | Super admin flows (registration approval, user CRUD, global billing) |
| test_privacy.py | PDPA: export, delete, anonymize, retention, consent |
| test_registration.py | Registration, approval, rejection, onboarding |
| test_schemas.py | Pydantic model validation |
| test_dependencies.py | Utility functions, filename parsing, rate limit keys |

> Retired during 2026-04-19 v1 cutover: `test_semantic_chunking.py`, `test_table_chunking.py`, `test_hierarchical_enrichment.py`, `test_vision_tracking.py` (covered v1-only modules `chunking.py`, `enrichment.py`, v1 portions of `vision.py`). Test contract migrated to `test_ingestion_v2.py` + `test_scan_all.py` + `test_ingestion_router.py`.

### 17.2 Frontend Tests (29 tests)

**Framework:** Vitest + React Testing Library

| Test File | Coverage |
|-----------|----------|
| API client tests | Fetch wrapper, auth headers, error handling |
| Registration form tests | Form validation, submission |
| Billing page tests | Cost display, chart rendering |
| Onboarding wizard tests | Step progression, state management |

### 17.3 Testing Methodology

- **TDD (Test-Driven Development):** Tests written before implementation for all God Mode features
- **In-memory mocks:** FakeFirestore eliminates external dependencies
- **Auth simulation:** Mock Firebase tokens for different roles (super_admin, faculty_admin)
- **Async-first:** All tests use `pytest.mark.asyncio` for async endpoint testing

---

## 18. Database Design

### 18.1 Firestore Collections (7)

#### 18.1.1 tenants
| Field | Type | Description |
|-------|------|-------------|
| tenant_id | string (PK) | Unique faculty identifier |
| faculty_name | string | Faculty display name |
| line_destination | string | LINE OA User ID |
| line_channel_access_token | string | LINE API token |
| line_channel_secret | string | Webhook signature secret |
| pinecone_namespace | string | Vector DB namespace |
| persona | string | Custom system prompt for agent |
| is_active | boolean | Enable/disable tenant |
| onboarding_completed | array[int] | Completed wizard steps |
| created_at | timestamp | Creation time |
| updated_at | timestamp | Last update time |

#### 18.1.2 chat_logs
| Field | Type | Description |
|-------|------|-------------|
| id | string (PK, auto) | Auto-generated document ID |
| tenant_id | string | Owner tenant |
| user_id | string | LINE user ID |
| query | string | Student's question |
| answer | string | Agent's response |
| sources | array[dict] | Source documents used (filename, page, category, download_link, relevance_score, confidence) |
| created_at | timestamp | Interaction time (TTL index for retention) |

#### 18.1.3 admin_users
| Field | Type | Description |
|-------|------|-------------|
| uid | string (PK) | Firebase user ID |
| email | string | Admin email |
| display_name | string | Display name |
| role | string | "super_admin" or "faculty_admin" |
| tenant_ids | array[string] | Assigned tenants (faculty_admin only) |
| is_active | boolean | Active status |
| created_at | timestamp | Creation time |
| updated_at | timestamp | Last update time |

#### 18.1.4 usage_logs
| Field | Type | Description |
|-------|------|-------------|
| id | string (PK) | Format: `{tenant_id}_{YYYY-MM}` |
| tenant_id | string | Owner tenant |
| month | string | "YYYY-MM" |
| llm_call_count | int | Claude API calls |
| embedding_call_count | int | Cohere embedding calls |
| reranker_call_count | int | Cohere reranker calls |
| vision_call_count | int | Claude Vision calls |
| llm_call_cost | float | USD cost for LLM |
| embedding_call_cost | float | USD cost for embeddings |
| reranker_call_cost | float | USD cost for reranking |
| vision_call_cost | float | USD cost for Vision |
| total_cost | float | Total USD cost |
| updated_at | timestamp | Last update time |

#### 18.1.5 conversations
| Field | Type | Description |
|-------|------|-------------|
| user_id | string (PK) | LINE user ID |
| turns | array[dict] | Recent conversation turns [{query, answer}] |
| summary | string | Compressed earlier context |
| last_active | timestamp | TTL tracking (30-min timeout) |

#### 18.1.6 consents
| Field | Type | Description |
|-------|------|-------------|
| id | string (PK, auto) | Auto-generated |
| tenant_id | string | Owner tenant |
| user_id | string | LINE user ID |
| consent_type | string | "data_collection", "analytics", "marketing" |
| version | string | Consent version |
| is_active | boolean | Active consent |
| granted_at | timestamp | Consent time |

#### 18.1.7 pending_registrations
| Field | Type | Description |
|-------|------|-------------|
| id | string (PK, auto) | Auto-generated |
| faculty_name | string | Requested faculty name |
| email | string | Registrant email |
| password_hash | string | SHA256 hashed password |
| note | string | Optional note |
| status | string | "pending", "approved", "rejected" |
| reject_reason | string | Reason if rejected |
| created_at | timestamp | Registration time |

### 18.2 Pinecone Vector Database

- **Index:** "university-rag"
- **Dimensions:** 1536 (Cohere embed-v4.0)
- **Metric:** Cosine similarity
- **Isolation:** Namespace per tenant
- **Metadata per vector:**
  ```python
  {
      "tenant_id": "cutip_01",
      "source_type": "pdf|docx|xlsx|web|gdrive",
      "source_filename": "ตารางเรียน.xlsx",
      "doc_category": "form|curriculum|schedule|general|announcement|regulation",
      "page": 1,
      "url": "https://...",
      "download_link": "https://...",
      "has_table": True,
      "urls": ["https://..."],
      "header_path": "Section > Subsection"
  }
  ```

---

## 19. API Design

### 19.1 Chat API Endpoints

| Method | Path | Auth | Rate Limit | Description |
|--------|------|------|-----------|-------------|
| POST | `/webhook/line` | LINE signature | 20/min | LINE webhook receiver |
| POST | `/api/chat` | Bearer/API-Key | 20/min | Standalone chat endpoint |
| GET | `/health` | None | None | Health check |

### 19.2 Ingestion Worker Endpoints

All endpoints are thin wrappers over `ingest_v2()` post-2026-04-19 cutover.

| Method | Path | Auth | Rate Limit | Description |
|--------|------|------|-----------|-------------|
| POST | `/api/tenants/{id}/ingest/stage` | Bearer | 10/min | **Stage Upload** — local file → SA uploads to tenant's Drive folder → v2 ingest |
| POST | `/api/tenants/{id}/ingest/gdrive` | Bearer | 10/min | Batch ingest of tenant's Drive folder |
| POST | `/api/tenants/{id}/ingest/gdrive/scan` | Bearer/API-Key | 10/min | **Smart Scan** — NEW / RENAME / OVERWRITE / SKIP state machine |
| POST | `/api/tenants/{id}/ingest/gdrive/file` | Bearer | 10/min | Single Drive file re-ingest (retry flakes) |
| POST | `/api/tenants/{id}/ingest/v2/gdrive` | Bearer | 10/min | Audit variant — accepts `?namespace_override=<name>_v2_audit` suffix |
| POST | `/api/tenants/{id}/ingest/v2/gdrive/file` | Bearer | 10/min | Single-file audit variant |
| GET | `/health` | None | None | Health check |

> Retired 2026-04-19: `POST /api/tenants/{id}/ingest/document`, `POST .../ingest/spreadsheet`, `POST .../ingest/markdown` — the Stage Upload flow supersedes these by routing everything through Drive.

> Document listing (`GET /api/tenants/{id}/documents`), bulk deletion (`DELETE /api/tenants/{id}/documents`), and single-file deletion (`DELETE /api/tenants/{id}/documents/{filename}`) are served by the **Admin API** (analytics router) — they do not perform ingestion but atomically wipe Pinecone chunks + Drive files.

### 19.3 Admin API Endpoints

| Method | Path | Auth | Rate Limit | Description |
|--------|------|------|-----------|-------------|
| GET/POST | `/api/tenants` | Bearer | 60/min | List/create tenants |
| GET/PUT/DELETE | `/api/tenants/{id}` | Bearer | 60/min | Tenant CRUD |
| GET/POST | `/api/users` | Bearer (super) | 60/min | List/create users |
| GET/PUT/DELETE | `/api/users/{uid}` | Bearer (super) | 60/min | User CRUD |
| GET | `/api/tenants/{id}/analytics` | Bearer | 60/min | Analytics data |
| GET | `/api/tenants/{id}/chat-logs` | Bearer | 60/min | Paginated logs |
| GET | `/api/tenants/{id}/usage` | Bearer | 60/min | Monthly costs |
| GET | `/api/usage` | Bearer (super) | 60/min | Global usage |
| POST | `/api/auth/register` | None | 3/min | Public registration |
| GET | `/api/registrations` | Bearer (super) | 60/min | Pending list |
| POST | `/api/registrations/{id}/approve` | Bearer (super) | 60/min | Approve |
| POST | `/api/registrations/{id}/reject` | Bearer (super) | 60/min | Reject |
| GET | `/api/tenants/{id}/documents` | Bearer | 60/min | List ingested documents in namespace (via Pinecone list+fetch, distinct by source_filename) |
| DELETE | `/api/tenants/{id}/documents/{filename}` | Bearer | 60/min | Atomic single-file delete: Pinecone first, then Drive with 3× retry |
| DELETE | `/api/tenants/{id}/documents` | Bearer (super) | 60/min | Bulk delete: iterate Drive deletions, then wipe Pinecone namespace |
| POST | `/api/tenants/{id}/gdrive/connect` | Bearer | 60/min | Save connected Drive folder (folder_id + folder_name) after Picker flow |
| GET | `/api/tenants/{id}/privacy/export/{uid}` | Bearer | 60/min | Data export |
| DELETE | `/api/tenants/{id}/privacy/users/{uid}` | Bearer | 60/min | Data deletion |
| POST | `/api/tenants/{id}/privacy/anonymize/{uid}` | Bearer | 60/min | Anonymize |
| POST | `/api/privacy/retention/cleanup` | Bearer (super)/API-Key | 60/min | Global retention cleanup |
| POST | `/api/tenants/{id}/privacy/consents` | Bearer | 60/min | Record user consent |
| GET | `/api/tenants/{id}/privacy/consents/{uid}` | Bearer | 60/min | Retrieve user consents |
| DELETE | `/api/tenants/{id}/privacy/consents/{uid}/{type}` | Bearer | 60/min | Revoke consent |
| GET | `/api/privacy/policy` | None | None | Public privacy policy |
| GET | `/api/tenants/{id}/onboarding` | Bearer | 60/min | Onboarding progress |
| PUT | `/api/tenants/{id}/onboarding` | Bearer | 60/min | Update onboarding steps |
| GET | `/api/users/me` | Bearer | 60/min | Current user profile |
| POST | `/api/auth/init` | None | 3/min | Bootstrap first super admin |
| GET | `/api/backups` | Bearer/API-Key | 60/min | List available backups |
| POST | `/api/backups/firestore` | Bearer/API-Key | 60/min | Firestore backup |
| POST | `/api/backups/pinecone` | Bearer/API-Key | 60/min | Vector backup |
| POST | `/api/backups/pinecone/restore` | Bearer/API-Key | 60/min | Restore vectors from backup |
| GET | `/health` | None | None | Health check |

---

## 20. Cost Tracking & Billing

### 20.1 Usage Tracking

Every API call to external services is tracked per tenant per month:

| Service | Cost per Call (est.) | Tracked As |
|---------|-------------------|-----------|
| Claude Opus 4.7 (agent) | ~$0.06 | llm_call_count/cost |
| Claude Haiku (utilities) | ~$0.001 | llm_call_count/cost |
| Cohere embed-v4.0 | ~$0.001 | embedding_call_count/cost |
| Cohere Rerank v3.5 | ~$0.002 | reranker_call_count/cost |
| Claude Haiku Vision | ~$0.01 | vision_call_count/cost |

### 20.2 Storage

- Document ID format: `{tenant_id}_{YYYY-MM}` (e.g., `cutip_01_2026-04`)
- Uses Firestore `Increment()` for atomic counter updates
- No risk of lost updates under concurrent access

### 20.3 Dashboard

- **Per-tenant view:** Monthly cost chart (Recharts), breakdown by service type
- **Global view (super admin):** All tenants' costs, stacked monthly chart, top consumers

---

## 21. Key Design Decisions & Rationale

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Agent LLM | Claude Opus 4.7 (adaptive thinking) | Best reasoning quality for agentic ReAct loop; Thai-fluent |
| Ingestion parse+chunk | Claude Opus 4.7 (adaptive thinking, `tool_choice="auto"`, `max_tokens=32000`) | Universal path — PDF native, sidecar-aware, thinking-required for long/dense docs |
| Utility LLM | Claude Haiku 4.5 | 60× cheaper than Opus; sufficient for rewrite/decompose/multi-query/summarize |
| Search strategy | Hybrid BM25+Vector+RRF | Catches both semantic and keyword queries |
| Rewriter short-circuit | No rewrite without follow-up markers | Prevents "ดาวน์โหลด/ฟอร์ม/เกณฑ์" qualifier injection on plain noun queries (demo-day bug) |
| Chunking | Opus-emitted (section-tagged) — post-v2 | Model returns already-contextualized chunks; v1 semantic chunker + table repair + Haiku enrichment removed |
| Architecture | Microservices monorepo | Independent scaling per service; shared/ package reduces duplication |
| Chat min-instances | 1 (always warm) | Avoid LINE webhook timeout on cold start (10-20s loading) |
| Memory strategy | Summarization via Haiku | Unlimited effective context; cost-effective |
| Confidence tiers | 3-tier (HIGH/MEDIUM/filtered) | Prevents low-relevance hallucination; agent adapts response style |
| File identity | `drive_file_id` in chunk metadata | Rename-safe delete; overwrite detection via modifiedTime |
| Delete order | Pinecone first, Drive second (3× retry) | Avoid orphan chunks / ghost answers; opposite order fails worse |
| BM25 invalidation | Firestore `bm25_invalidate_ts` read per query | In-process `@lru_cache` is insufficient across chat-api replicas |
| Drive-as-source-of-truth | Connect Drive + Stage Upload + Smart Scan | Every Pinecone chunk ↔ a Drive file the user owns |
| Vector DB | Pinecone (serverless) | Managed, namespace isolation, serverless scaling |
| Document DB | Firestore | NoSQL, real-time, PDPA compliance ready, pay-per-use |
| Auth | Firebase | Proven OAuth2, role-based, admin SDK for server-side verification |
| Chat platform | LINE | Dominant messaging platform in Thailand (53M+ users) |
| Frontend | Next.js 16 (standalone) | SSR capability, App Router, fast developer experience |
| UI components | shadcn/ui + Base UI | Accessible, customizable, no vendor lock-in (Base UI = new AlertDialog primitive, no `asChild`) |
| Deployment | Cloud Run | Serverless containers, per-request billing, auto-scaling |

---

## 22. Performance Optimizations

### 22.1 Warm Instances

- **Chat API:** `min-instances=1` keeps one instance always warm
- **Lifespan events:** Embedding model, vectorstore, and reranker warmed on startup

### 22.2 Caching

| Cache | Scope | Invalidation |
|-------|-------|-------------|
| Embedding model | Process-level (`@lru_cache`) | Never (singleton) |
| LLM instances | Process-level (`@lru_cache`, 4 presets) | Never |
| Vectorstore client | Per-namespace (thread-safe) | Never |
| BM25 index | Per-namespace (in-memory) | On document ingestion |

### 22.3 Async Processing

- All backend services use `async/await` throughout
- Firestore operations wrapped with `asyncio.to_thread` to avoid blocking
- Memory operations fully async (no event loop blocking)
- Vision processing batched (2 pages concurrent)

### 22.4 Rate Limiting

| Endpoint Type | Limit | Scope |
|--------------|-------|-------|
| Chat (webhook + /api/chat) | 20/minute | Per user |
| Admin operations | 60/minute | Per user |
| Document ingestion | 10/minute | Per tenant |
| Authentication (register) | 3/minute | Per IP |

---

## 23. Feature Summary (25 Commercialization Items)

| # | Feature | Status | Date |
|---|---------|--------|------|
| 1 | Multi-tenant FastAPI + Firestore + Pinecone namespace isolation | Done | 2026-04-10 |
| 2 | Multi-format ingestion (PDF, DOC, DOCX, XLSX, CSV, MD) — v1 | Done | 2026-04-11 |
| 3 | Cohere embed-v4.0 + Rerank v3.5 | Done | 2026-04-11 |
| 4 | Agentic RAG (Claude Opus 4.7 + LangGraph ReAct + 4 tools) | Done | 2026-04-12 |
| 5 | LINE OA webhook + text reply + sources Flex bubble | Done | 2026-04-12 |
| 6 | Conversation memory (Firestore + Haiku summarization) | Done | 2026-04-12 |
| 7 | Google Drive integration (batch/scan/single) | Done | 2026-04-13 |
| 8 | Auth (Firebase Auth + RBAC: Super Admin / Faculty Admin) | Done | 2026-04-13 |
| 9 | Security (rate limiting, input sanitization, CORS) | Done | 2026-04-13 |
| 10 | Monitoring (Slack alerts, uptime check, per-tenant cost tracking) | Done | 2026-04-13 |
| 11 | Backup (Firestore export + Pinecone JSONL to GCS) | Done | 2026-04-14 |
| 12 | Cloud Scheduler (3 jobs: auto-scan, backup, cleanup) | Done | 2026-04-14 |
| 13 | Testing (237 backend + 29 frontend = 266 tests, TDD) | Done | ongoing |
| 14 | Ingestion dedup fix (Pinecone list+fetch metadata) | Done | 2026-04-14 |
| 15 | PDPA Compliance (8 privacy endpoints, 27 tests) | Done | 2026-04-14 |
| 16 | Admin Portal (Next.js 16, 14 pages) | Done | 2026-04-14 |
| 17 | LINE Rich Menu (6 buttons) | Done | 2026-04-15 |
| 18 | Self-Service Registration + Onboarding Wizard | Done | 2026-04-15 |
| 19 | Billing/Cost Dashboard | Done | 2026-04-15 |
| 20 | God Mode RAG (9 improvements — items 1–3 superseded by v2 §7.6) | Done | 2026-04-15 |
| 21 | Microservices Split (3 services + shared package) | Done | 2026-04-15 |
| 22 | **v2 Universal Ingestion Cutover** — single Opus 4.7 path replaces 5 format dispatchers; 1500 → 250 LOC (−85%) | Done | 2026-04-19 |
| 23 | **v2.1 Hardening** — `drive_file_id` rename-safety, Smart Scan state machine, atomic delete, BM25 cross-process invalidation, rewriter bias fix, Thai-font regression fix | Done | 2026-04-19 |
| 24 | **Drive Connect Flow** — OAuth + Picker + SA auto-share; replaces manual folder-id paste | Done | 2026-04-19 |
| 25 | **VIRIYA Rebrand** — product name + icon-mark SVG logo across admin portal | Done | 2026-04-20 |

---

## 24. Limitations & Future Work

### 24.1 Current Limitations

1. **No CI/CD pipeline:** Deployment is manual via `gcloud` commands
2. **No custom domain:** Services use Cloud Run auto-generated URLs
3. **No load testing:** Cost of Claude Opus per request makes large-scale testing expensive (~$3-5/run)
4. **Single-region deployment:** asia-southeast1 only (no multi-region failover)
5. **Thai NLP:** BM25 tokenization uses simple whitespace/punctuation split (no proper Thai word segmentation like PyThaiNLP)
6. **No real-time updates:** Document changes require re-ingestion (no streaming vector updates)

### 24.2 Future Work

1. **CI/CD Pipeline:** GitHub Actions → Cloud Build → Cloud Run auto-deploy (currently manual via `gcloud run deploy --source=.`; the Dockerfile copy-pattern is fragile)
2. **Custom Domain + SSL:** Production-grade URLs with SSL certificates (currently `*.asia-southeast1.run.app`)
3. **Load Testing:** Locust/k6 framework for capacity planning (scale estimate from demo: 20-30 concurrent users on Anthropic Tier 1 is safe; beyond needs verification)
4. **Multi-region:** Failover to additional Cloud Run regions (currently `asia-southeast1` only)
5. **Thai NLP Enhancement:** Integrate PyThaiNLP for Thai word segmentation in BM25 (addresses observed zero-result case: query `หลักสูตรการจัดการเทคโนโลยีและนวัตกรรมผู้ประกอบการ` without internal spaces tokenizes as a single BM25 term)
6. **Multi-university SaaS:** Onboard additional universities beyond CU (tenant model already supports it; needs sales + onboarding runbook)
7. **Analytics Enhancement:** User satisfaction tracking, answer quality metrics (thumbs up/down on LINE answers)
8. **Streaming Responses:** Server-Sent Events for real-time chat responses in web interface (LINE doesn't support streaming, but web admin preview could)
9. **v3 Hypothesis — incremental ingestion:** v2 re-ingests the whole document on overwrite. For large docs, a diff-aware re-ingest (only changed sections) could reduce Opus spend. Not currently a bottleneck.

> **Item retired as of 2026-04-19:** "Complete v2 ingestion cutover" — previous drafts listed this as future work; the cutover is complete (§7.6.7). This note is preserved for reviewers cross-checking earlier drafts.

> **Item retired as of 2026-04-20:** "Product Branding" — finalized as VIRIYA (วิริยะ). See §7.7.9.

---

## Appendix A: Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| LLM_MODEL | claude-opus-4-7 | Agent reasoning model |
| OCR_MODEL | claude-opus-4-7 | v1 Vision OCR + v2 universal parse-and-chunk |
| VISION_MODEL | claude-haiku-4-5-20251001 | Vision/utility model |
| EMBEDDING_MODEL | embed-v4.0 | Cohere embedding model |
| RERANKER_MODEL | rerank-v3.5 | Cohere reranking model |
| CHUNK_SIZE | 1500 | Max chunk size (chars) |
| CHUNK_OVERLAP | 200 | Chunk overlap (chars) |
| SEMANTIC_CHUNK_PERCENTILE | 90 | Breakpoint threshold |
| RETRIEVAL_K | 10 | Initial retrieval count |
| TOP_K | 5 | Final results count |
| RRF_K | 60 | RRF smoothing constant |
| MAX_HISTORY_TURNS | 5 | Turns before summarization |
| MEMORY_TTL | 1800 | Session timeout (seconds) |
| RETENTION_DAYS | 90 | PDPA data retention |
| PDF_VISION_THRESHOLD | 100 | Chars to trigger Vision |
| PDF_BATCH_SIZE | 2 | Concurrent Vision calls |
| XLSX_BATCH_ROWS | 100 | Rows per interpretation batch |
| MAX_UPLOAD_SIZE_MB | 50 | Max file upload size |
| RATE_LIMIT_CHAT | 20/minute | Chat rate limit |
| RATE_LIMIT_ADMIN | 60/minute | Admin rate limit |
| RATE_LIMIT_INGESTION | 10/minute | Ingestion rate limit |
| RATE_LIMIT_AUTH | 3/minute | Auth rate limit |

---

## Appendix B: External Service Dependencies

| Service | Provider | Plan | Usage |
|---------|----------|------|-------|
| Claude API | Anthropic | Pay-per-use | Opus: agent, Haiku: utilities |
| Cohere API | Cohere | Pay-per-use | embed-v4.0, Rerank v3.5 |
| Pinecone | Pinecone | Serverless (free tier) | Vector storage + search |
| Cloud Run | Google Cloud | Pay-per-use | Container hosting |
| Firestore | Google Cloud | Pay-per-use | Document database |
| Firebase Auth | Google Cloud | Free tier | Authentication |
| Cloud Storage | Google Cloud | Pay-per-use | Backup storage |
| Cloud Scheduler | Google Cloud | Free tier (3 jobs) | Cron automation |
| Cloud Monitoring | Google Cloud | Free tier | Uptime checks |
| Secret Manager | Google Cloud | Pay-per-use | API key storage |
| LINE Messaging API | LINE | Free (with limits) | Chat messaging |
| Google Drive API | Google Cloud | Free | Document import |

---

*Document generated for thesis writing reference. All technical details verified against deployed revisions as of 2026-04-20: `cutip-chat-api-00024-gcr`, `cutip-ingest-worker-00023-p2g`, `cutip-admin-api-00009-zg9`, `cutip-admin-portal-00019-b7s`. v2 universal ingestion (§7.6) is the sole runtime path; v1 (§§7.1–7.5) retained for thesis reference on the `legacy` git branch. v2.1 hardening (§7.7) captures post-demo production fixes.*
