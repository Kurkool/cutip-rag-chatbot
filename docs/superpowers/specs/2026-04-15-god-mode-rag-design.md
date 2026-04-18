# God Mode RAG — Design Spec

## Overview

8 improvements to elevate the CU-TIP RAG system from 4/5 to 5/5 "god mode" — making ingestion understand every complex document and the chatbot answer with confidence and precision.

**Decisions made during brainstorming:**
- Re-ingest all existing documents after deploy (Option A)
- Use Claude Haiku for summarization + multi-query generation (cheap, fast, sufficient)
- 3-tier confidence: >0.6 high, 0.3-0.6 medium/warn, <0.3 filtered out

---

## Part 1: Ingestion Pipeline

### 1. Semantic Chunking

**Replace** `RecursiveCharacterTextSplitter` (800 char fixed splits) **with** embedding-based semantic boundary detection.

**How it works:**
1. Split full text into sentences
2. Embed every sentence with Cohere embed-v4.0
3. Calculate cosine distance between consecutive sentence embeddings
4. Where distance > percentile threshold (top 10%) = chunk boundary
5. Merge sentences within each segment into a chunk

**Implementation:**
- Use `langchain_experimental.text_splitter.SemanticChunker` with Cohere embeddings
- `breakpoint_threshold_type="percentile"`, `breakpoint_percentile_threshold=90`
- Max chunk size cap: 1500 chars (prevent oversized chunks)
- Min chunk size: 100 chars (filter tiny/empty chunks)
- Fallback: if SemanticChunker fails (e.g., very short text), use RecursiveCharacterTextSplitter with chunk_size=1500, overlap=200

**Files to modify:**
- `services/ingestion.py` — replace `_smart_chunk()` function
- `config.py` — update CHUNK_SIZE to 1500, add SEMANTIC_CHUNK_PERCENTILE=90
- `requirements.txt` — add `langchain-experimental`

**Impact:** 30-40% better retrieval by keeping related concepts together.

### 2. Table-Aware Chunking

**Add post-processing step** after semantic chunking to preserve table integrity.

**How it works:**
1. After semantic chunking, scan each chunk for markdown table patterns
2. If a chunk ends with an incomplete table row (no closing `|`), merge with next chunk
3. If a standalone table > 1500 chars, split at row boundaries (not mid-row)
4. Add `"has_table": true` metadata to table-containing chunks

**Detection:** Regex pattern `^\|.*\|$` (multiline) for markdown table rows.

**Merge rules:**
- Chunk ends with incomplete table → merge with next chunk
- Merged chunk > 2000 chars → split at empty line or every 20 table rows
- Preserve table header (first row + separator) in every split chunk

**Files to modify:**
- `services/ingestion.py` — add `_fix_table_boundaries()` post-processing function
- Called after `_smart_chunk()` / semantic chunking, before `_upsert()`

**Impact:** Tables from XLSX, PDF, DOCX no longer split mid-row. Critical for CU-TIP schedule data (218 merged cells).

### 3. Hierarchical Contextual Enrichment

**Replace** global doc summary context **with** section-level context.

**How it works:**
1. Parse markdown headers from full text → build section map: `{section_title: section_text}`
2. For each chunk, find which section it belongs to (by character position matching)
3. Prompt Haiku with section text (not full doc): "Given this section, describe where this chunk fits"
4. Prepend `[Section: {title} | {context}]\n{chunk_text}`

**Prompt for Haiku:**
```
<document_section title="{section_title}">
{section_text (max 3000 chars)}
</document_section>

<chunk>
{chunk_text}
</chunk>

Write 1-2 sentences explaining what this chunk is about within its section. Include the section topic and what specific information this chunk contains. Respond in the same language as the document.
```

**Model:** Claude Haiku (max 100 tokens, temp=0)
**Batching:** 10 chunks per batch, 1-sec pause between batches
**Fallback:** If section detection fails (no headers), fall back to global doc summary (current behavior)

**Files to modify:**
- `services/ingestion.py` — rewrite `_enrich_with_context()`, add `_build_section_map()`
- Use Haiku instead of Vision model for enrichment (cheaper, faster)

**Impact:** 60%+ retrieval improvement over global context. Each chunk gets precise, section-specific metadata.

---

## Part 2: Chatbot Pipeline

### 4. Hybrid Search (BM25 + Vector)

**Add BM25 keyword search** alongside existing Pinecone vector search, merge via Reciprocal Rank Fusion.

**Architecture:**
```
Query → ┬→ Vector search (Pinecone, k=10) ──────┐
        └→ BM25 search (in-memory index, k=10) ─┤
                                                  ↓
                                    Reciprocal Rank Fusion (RRF)
                                                  ↓
                                        Merged results (top 15)
                                                  ↓
                                      Cohere Rerank (top 5)
                                                  ↓
                                        Final results to agent
```

**BM25 Implementation:**
- Library: `rank_bm25` (lightweight, no Elasticsearch needed)
- Build BM25 index per namespace from Pinecone chunk texts
- Cache in memory with `@lru_cache()` per namespace
- Invalidate cache when new documents ingested (add `_invalidate_bm25_cache(namespace)` call in `_upsert()`)
- Thai tokenization: split on spaces + punctuation (Thai doesn't use spaces between words, but course codes, numbers, and English terms are space-separated — sufficient for keyword matching)

**RRF Merge:**
```python
def reciprocal_rank_fusion(vector_results, bm25_results, k=60):
    scores = {}
    for rank, doc in enumerate(vector_results):
        scores[doc.id] = scores.get(doc.id, 0) + 1 / (k + rank + 1)
    for rank, doc in enumerate(bm25_results):
        scores[doc.id] = scores.get(doc.id, 0) + 1 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: -x[1])[:15]
```

**Rerank:** Increase from top_k=4 to top_k=5 (more candidates from hybrid search).

**Files to modify/create:**
- `services/bm25.py` — new file: BM25 index management, search, cache
- `services/tools.py` — update `search_knowledge_base` and `search_by_category` to use hybrid search
- `services/ingestion.py` — add cache invalidation after upsert
- `requirements.txt` — add `rank-bm25`
- `config.py` — add `TOP_K=5`

**Impact:** Catches exact keyword queries (course codes, form numbers, instructor names) that pure vector search misses. Critical for Thai academic domain.

### 5. Confidence-Aware Agent + Multi-Query

**A) Reranker returns relevance scores:**

Modify reranker to return `(document, score)` tuples:
```python
def rerank_documents(query, documents, top_k):
    response = client.rerank(...)
    return [(documents[r.index], r.relevance_score) for r in response.results]
```

Format results with confidence tiers:
- score > 0.6 → `"[HIGH CONFIDENCE]"` prefix
- score 0.3-0.6 → `"[MEDIUM - may not be exact match]"` prefix
- score < 0.3 → filtered out entirely (not sent to agent)

**B) Multi-Query Generation:**

Before searching, Haiku generates 2 alternative queries:
```
Original: "ค่าเทอมหลักสูตร 5 ปี"
→ Haiku generates:
  1. "tuition fee 5-year program" (translation)
  2. "ค่าใช้จ่ายการศึกษา โปรแกรม 5 ปี" (synonym/rephrase)
```

All 3 queries go through hybrid search → RRF merge all results → single rerank pass.

**Haiku prompt for multi-query:**
```
Generate 2 alternative search queries for this question. One should translate key terms to English, one should use Thai synonyms. Return as JSON array.
Question: {query}
```

**Model:** Haiku, max 100 tokens, temp=0.3

**C) System prompt update:**

Add to AGENT_SYSTEM_PROMPT:
```
## Search Result Confidence
- [HIGH CONFIDENCE] results: Use directly in your answer
- [MEDIUM] results: Use but add a note that the information may not be exact
- If no results pass the confidence threshold, say honestly that you couldn't find the information
```

**Files to modify:**
- `services/reranker.py` — return scores, add confidence tier formatting
- `services/tools.py` — integrate multi-query in search tools
- `services/agent.py` — update system prompt with confidence instructions
- `services/search.py` — new file: orchestrate multi-query + hybrid search + rerank

### 6. Query Decomposition

**For complex multi-part questions, Haiku decomposes into sub-queries.**

**Flow:**
1. Haiku classifies query: simple or complex (single prompt)
2. If simple → pass through unchanged
3. If complex → decompose into 2-3 sub-queries → search each → merge results

**Haiku prompt:**
```
Analyze this question. If it asks about multiple topics or requires comparison, decompose into separate search queries. If it's a single-topic question, return it as-is.

Question: {query}

Return JSON: {"type": "simple", "query": "..."} or {"type": "complex", "sub_queries": ["...", "..."]}
```

**Integration:** Built into `services/search.py` — called before multi-query generation. If decomposed, each sub-query gets its own multi-query variants → hybrid search → merge all → single rerank.

**Files to modify:**
- `services/search.py` — add decomposition step in search pipeline

### 7. Source Audit Trail

**Track which documents contributed to each answer.**

**How it works:**
1. After agent execution, parse all `tool_calls` from result messages
2. Extract document metadata from search results that the agent actually used
3. Store structured source list in `chat_logs.sources`

**Source schema:**
```python
{
    "filename": "ตารางเรียน 2568.xlsx",
    "page": null,
    "category": "schedule",
    "download_link": "https://drive.google.com/...",
    "relevance_score": 0.82,
    "confidence": "HIGH"
}
```

**Files to modify:**
- `services/agent.py` — extract sources from tool call results after agent execution
- `routers/webhook.py` — pass extracted sources to `log_chat()`
- `services/firestore.py` — sources field already exists, just needs real data

### 8. Conversation Summarization

**When memory reaches 5 turns, summarize instead of dropping.**

**Flow:**
```
turns = [t1, t2, t3, t4, t5]  (full)
  → Haiku: "Summarize this conversation in 1-2 sentences"
  → memory = {summary: "Student asked about...", turns: []}
  → Next query: history = summary + new turns
  → When full again: summarize(old_summary + 5 turns) → loop
```

**Haiku prompt:**
```
Summarize this conversation between a student and university assistant in 1-2 sentences. Preserve key topics, specific details (course codes, names, amounts), and any unresolved questions.

{conversation}
```

**Model:** Haiku, max 200 tokens, temp=0
**Firestore schema change:** Add `summary: string` field to conversations collection
**System prompt format:** `"Previous context: {summary}\nRecent conversation:\n{formatted_turns}"`

**Files to modify:**
- `services/memory.py` — add `_summarize()` method, modify `add_turn()` to trigger summarization
- `services/agent.py` — update history formatting to include summary
- `services/dependencies.py` — update `format_history()` to prepend summary

---

## Part 3: Re-ingestion

After deploying all ingestion improvements (items 1-3), re-ingest all existing documents to rebuild vectors with new chunking strategy.

**Method:** Call `POST /api/tenants/{tenant_id}/ingest/gdrive/scan` for each tenant — the scan endpoint re-processes all files.

Actually, scan skips existing files. Use `POST /api/tenants/{tenant_id}/ingest/gdrive` (batch, non-scan) which re-ingests everything. The dedup logic (`_delete_existing_vectors`) will clean old vectors before inserting new ones.

---

## New Dependencies

| Package | Purpose | Size |
|---------|---------|------|
| `langchain-experimental` | SemanticChunker | Light |
| `rank-bm25` | BM25 keyword search | Light |

---

## Config Changes

| Setting | Old | New |
|---------|-----|-----|
| CHUNK_SIZE | 800 | 1500 |
| CHUNK_OVERLAP | 150 | 200 |
| TOP_K | 4 | 5 |
| SEMANTIC_CHUNK_PERCENTILE | (new) | 90 |
| BM25_K_CONSTANT | (new) | 60 |

---

## Files Summary

### New files:
- `services/bm25.py` — BM25 index management + search
- `services/search.py` — search orchestration (multi-query, decomposition, hybrid, rerank)

### Modified files:
- `services/ingestion.py` — semantic chunking, table-aware, hierarchical enrichment, BM25 cache invalidation
- `services/reranker.py` — return relevance scores with confidence tiers
- `services/tools.py` — use new search pipeline
- `services/agent.py` — confidence-aware prompt, source extraction, updated history format
- `services/memory.py` — conversation summarization
- `services/dependencies.py` — format_history with summary support
- `routers/webhook.py` — pass real sources to log_chat
- `config.py` — new settings
- `requirements.txt` — new packages

### Test files (new):
- `tests/test_semantic_chunking.py`
- `tests/test_table_chunking.py`
- `tests/test_hierarchical_enrichment.py`
- `tests/test_bm25.py`
- `tests/test_hybrid_search.py`
- `tests/test_confidence_rerank.py`
- `tests/test_multi_query.py`
- `tests/test_query_decomposition.py`
- `tests/test_source_audit.py`
- `tests/test_conversation_summary.py`
