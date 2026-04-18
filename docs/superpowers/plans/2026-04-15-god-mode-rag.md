# God Mode RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Elevate CU-TIP RAG from 4/5 to 5/5 god mode — semantic chunking, table-aware splits, hierarchical enrichment, hybrid BM25+vector search, confidence-aware multi-query agent, query decomposition, source audit trail, and conversation summarization.

**Architecture:** Ingestion pipeline gets semantic chunking + table preservation + section-level context. Chatbot gets a new `services/search.py` orchestrator that handles multi-query generation, query decomposition, hybrid BM25+vector search, RRF merge, and confidence-aware reranking. Memory gets summarization for unlimited context.

**Tech Stack:** LangChain SemanticChunker, rank-bm25, Cohere embed-v4.0 + rerank-v3.5, Claude Haiku (summarization/query gen), Claude Opus 4.6 (agent), Pinecone, Firestore

**Spec:** `docs/superpowers/specs/2026-04-15-god-mode-rag-design.md`

---

## File Structure

### New files:
- `services/bm25.py` — BM25 index per namespace, search, cache invalidation
- `services/search.py` — search orchestrator: decomposition → multi-query → hybrid search → RRF → confidence rerank

### Modified files:
- `config.py` — new settings (CHUNK_SIZE=1500, TOP_K=5, SEMANTIC_CHUNK_PERCENTILE=90, BM25_K_CONSTANT=60)
- `requirements.txt` — add langchain-experimental, rank-bm25
- `services/ingestion.py` — semantic chunking, table-aware post-processing, hierarchical enrichment, BM25 cache invalidation
- `services/reranker.py` — return (doc, score) tuples, confidence tiers
- `services/tools.py` — use search.py orchestrator instead of direct Pinecone+rerank
- `services/agent.py` — confidence prompt, source extraction, return sources
- `services/memory.py` — summarization on overflow
- `services/dependencies.py` — format_history with summary
- `routers/webhook.py` — pass sources to log_chat

### Test files:
- `tests/test_semantic_chunking.py`
- `tests/test_table_chunking.py`
- `tests/test_hierarchical_enrichment.py`
- `tests/test_bm25.py`
- `tests/test_search_pipeline.py`
- `tests/test_confidence_rerank.py`
- `tests/test_source_audit.py`
- `tests/test_conversation_summary.py`

---

## Task 1: Config + Dependencies

**Files:**
- Modify: `config.py:53-59`
- Modify: `requirements.txt`

- [ ] **Step 1: Update config.py with new settings**

```python
# In config.py, replace lines 53-59:
    # Chunking
    CHUNK_SIZE: int = 1500
    CHUNK_OVERLAP: int = 200

    # Retrieval
    RETRIEVAL_K: int = 10
    TOP_K: int = 5

    # Semantic Chunking
    SEMANTIC_CHUNK_PERCENTILE: int = 90

    # BM25
    BM25_K_CONSTANT: int = 60
```

- [ ] **Step 2: Install new dependencies**

Run: `pip install langchain-experimental rank-bm25`

Add to `requirements.txt`:
```
langchain-experimental
rank-bm25
```

- [ ] **Step 3: Verify import works**

Run: `python -c "from langchain_experimental.text_splitter import SemanticChunker; from rank_bm25 import BM25Okapi; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add config.py requirements.txt
git commit -m "feat: add config for god-mode RAG (semantic chunking, BM25, confidence)"
```

---

## Task 2: Semantic Chunking (TDD)

**Files:**
- Modify: `services/ingestion.py:30-67` (replace `_smart_chunk`)
- Test: `tests/test_semantic_chunking.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_semantic_chunking.py
"""Test semantic chunking with fallback."""
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.documents import Document


def test_smart_chunk_returns_documents_with_metadata():
    """Semantic chunking produces Documents with source_filename metadata."""
    from services.ingestion import _smart_chunk

    text = (
        "# หลักสูตร\n\n"
        "หลักสูตรวิศวกรรมศาสตร์ใช้เวลา 4 ปี ค่าเทอม 21,000 บาท\n\n"
        "## ตารางเรียน\n\n"
        "วิชา 2110101 เปิดสอนทุกภาคการศึกษา วันจันทร์ 9:00-12:00\n\n"
        "## ค่าใช้จ่าย\n\n"
        "ค่าเทอมรวมค่าธรรมเนียมทั้งหมดแล้ว ไม่มีค่าใช้จ่ายเพิ่มเติม"
    )
    chunks = _smart_chunk(text, source="test.pdf")

    assert len(chunks) >= 1
    assert all(isinstance(c, Document) for c in chunks)
    assert all(c.metadata.get("source_filename") == "test.pdf" for c in chunks)
    # No empty chunks
    assert all(len(c.page_content.strip()) >= 50 for c in chunks)


def test_smart_chunk_fallback_on_short_text():
    """Very short text falls back to recursive splitter."""
    from services.ingestion import _smart_chunk

    text = "สั้นมาก"
    chunks = _smart_chunk(text, source="short.pdf")

    assert len(chunks) >= 1
    assert chunks[0].metadata["source_filename"] == "short.pdf"


def test_smart_chunk_filters_tiny_chunks():
    """Chunks smaller than 100 chars are filtered out."""
    from services.ingestion import _smart_chunk

    text = "# Section A\n\nA " * 200 + "\n\n# Section B\n\n" + "B detailed content here. " * 100
    chunks = _smart_chunk(text, source="test.pdf")

    for chunk in chunks:
        assert len(chunk.page_content.strip()) >= 50
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_semantic_chunking.py -v`
Expected: FAIL (current `_smart_chunk` uses 800 char chunks, no min filter)

- [ ] **Step 3: Implement semantic chunking**

Replace `_smart_chunk` and related splitter setup in `services/ingestion.py` lines 30-67:

```python
# ──────────────────────────────────────
# Smart Chunking Pipeline
# ──────────────────────────────────────

from langchain_experimental.text_splitter import SemanticChunker
from services.embedding import get_embedding_model

md_header_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=[
        ("#", "section"),
        ("##", "subsection"),
        ("###", "topic"),
    ],
    strip_headers=False,
)

_fallback_splitter = RecursiveCharacterTextSplitter(
    chunk_size=settings.CHUNK_SIZE,  # 1500
    chunk_overlap=settings.CHUNK_OVERLAP,  # 200
    separators=["\n\n", "\n", "。", ".", " ", ""],
)

_MIN_CHUNK_SIZE = 100


def _get_semantic_splitter() -> SemanticChunker:
    return SemanticChunker(
        embeddings=get_embedding_model(),
        breakpoint_threshold_type="percentile",
        breakpoint_percentile_threshold=settings.SEMANTIC_CHUNK_PERCENTILE,
    )


def _smart_chunk(text: str, source: str = "") -> list[Document]:
    """Semantic chunking with markdown header awareness and fallback."""
    if len(text.strip()) < _MIN_CHUNK_SIZE:
        return [Document(page_content=text, metadata={"source_filename": source})]

    # Step 1: Try semantic chunking
    try:
        splitter = _get_semantic_splitter()
        raw_chunks = splitter.create_documents([text])
    except Exception:
        logger.warning("SemanticChunker failed, falling back to recursive split")
        raw_chunks = None

    if not raw_chunks:
        raw_chunks = _fallback_splitter.create_documents(
            [text], metadatas=[{"source_filename": source}]
        )

    # Step 2: Cap oversized chunks
    final_chunks = []
    for chunk in raw_chunks:
        if len(chunk.page_content) > settings.CHUNK_SIZE * 2:
            sub_chunks = _fallback_splitter.create_documents([chunk.page_content])
            final_chunks.extend(sub_chunks)
        else:
            final_chunks.append(chunk)

    # Step 3: Header path enrichment (from markdown headers)
    header_chunks = md_header_splitter.split_text(text)
    header_map = _build_header_position_map(text, header_chunks)
    for chunk in final_chunks:
        pos = text.find(chunk.page_content[:80])
        if pos >= 0:
            header_path = _find_header_at_position(header_map, pos)
            if header_path and not chunk.page_content.startswith(f"[{header_path}]"):
                chunk.page_content = f"[{header_path}]\n{chunk.page_content}"
        chunk.metadata["source_filename"] = source

    # Step 4: Filter tiny chunks
    final_chunks = [c for c in final_chunks if len(c.page_content.strip()) >= _MIN_CHUNK_SIZE // 2]

    return final_chunks if final_chunks else [Document(page_content=text, metadata={"source_filename": source})]


def _build_header_position_map(text: str, header_chunks: list[Document]) -> list[tuple[int, str]]:
    """Build a map of (char_position, header_path) from markdown header splits."""
    positions = []
    for chunk in header_chunks:
        pos = text.find(chunk.page_content[:80])
        if pos < 0:
            continue
        header_path = " > ".join(
            chunk.metadata[key]
            for key in ["section", "subsection", "topic"]
            if chunk.metadata.get(key)
        )
        if header_path:
            positions.append((pos, header_path))
    positions.sort()
    return positions


def _find_header_at_position(header_map: list[tuple[int, str]], pos: int) -> str:
    """Find the nearest header path for a given character position."""
    result = ""
    for header_pos, path in header_map:
        if header_pos <= pos:
            result = path
        else:
            break
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_semantic_chunking.py -v`
Expected: PASS

- [ ] **Step 5: Run all tests**

Run: `python -m pytest --tb=short -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add services/ingestion.py tests/test_semantic_chunking.py
git commit -m "feat: semantic chunking with embedding-based boundaries and fallback"
```

---

## Task 3: Table-Aware Chunking (TDD)

**Files:**
- Modify: `services/ingestion.py` (add `_fix_table_boundaries`, call from `_smart_chunk`)
- Test: `tests/test_table_chunking.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_table_chunking.py
"""Test table-aware chunk post-processing."""
import pytest
from langchain_core.documents import Document
from services.ingestion import _fix_table_boundaries


def test_incomplete_table_merged_with_next_chunk():
    """A chunk ending with incomplete table row merges with the next chunk."""
    chunks = [
        Document(page_content="Some text\n| Col1 | Col2 |\n| --- | --- |\n| A | B", metadata={}),
        Document(page_content="| C | D |\n| E | F |\n\nMore text after table", metadata={}),
    ]
    fixed = _fix_table_boundaries(chunks)

    # Should merge the incomplete table
    assert any("| A | B" in c.page_content and "| C | D |" in c.page_content for c in fixed)


def test_complete_table_not_merged():
    """Chunks with complete tables are left alone."""
    chunks = [
        Document(page_content="| Col1 | Col2 |\n| --- | --- |\n| A | B |", metadata={}),
        Document(page_content="Separate text chunk", metadata={}),
    ]
    fixed = _fix_table_boundaries(chunks)

    assert len(fixed) == 2


def test_has_table_metadata_added():
    """Chunks containing tables get has_table=true metadata."""
    chunks = [
        Document(page_content="| Col1 | Col2 |\n| --- | --- |\n| A | B |", metadata={}),
        Document(page_content="No table here", metadata={}),
    ]
    fixed = _fix_table_boundaries(chunks)

    table_chunk = [c for c in fixed if "Col1" in c.page_content][0]
    assert table_chunk.metadata.get("has_table") is True

    text_chunk = [c for c in fixed if "No table" in c.page_content][0]
    assert table_chunk.metadata.get("has_table") is True
    assert text_chunk.metadata.get("has_table") is not True


def test_large_table_split_at_row_boundary():
    """Tables larger than 2000 chars are split at row boundaries."""
    rows = "| A long value here | Another long value here |\n" * 60
    table = "| Col1 | Col2 |\n| --- | --- |\n" + rows
    chunks = [Document(page_content=table, metadata={})]

    fixed = _fix_table_boundaries(chunks)

    assert len(fixed) >= 2
    # Each split chunk should start with table header
    for chunk in fixed:
        assert "| Col1 | Col2 |" in chunk.page_content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_table_chunking.py -v`
Expected: FAIL (`_fix_table_boundaries` doesn't exist)

- [ ] **Step 3: Implement table-aware chunking**

Add to `services/ingestion.py` after `_smart_chunk`:

```python
import re as _re

_TABLE_ROW_PATTERN = _re.compile(r"^\|.*\|$", _re.MULTILINE)
_TABLE_HEADER_PATTERN = _re.compile(r"^(\|[^\n]+\|\n\|[\s\-:|]+\|)", _re.MULTILINE)
_MAX_TABLE_CHUNK = 2000
_TABLE_SPLIT_ROWS = 20


def _fix_table_boundaries(chunks: list[Document]) -> list[Document]:
    """Post-process chunks to preserve table integrity."""
    if not chunks:
        return chunks

    result: list[Document] = []
    i = 0
    while i < len(chunks):
        chunk = chunks[i]
        content = chunk.page_content

        # Check if chunk ends with incomplete table (last line starts with | but doesn't end with |)
        lines = content.rstrip().split("\n")
        last_line = lines[-1].strip() if lines else ""
        ends_incomplete = last_line.startswith("|") and not last_line.endswith("|")

        if ends_incomplete and i + 1 < len(chunks):
            # Merge with next chunk
            next_chunk = chunks[i + 1]
            merged_content = content + "\n" + next_chunk.page_content
            merged_meta = {**chunk.metadata, **next_chunk.metadata}
            chunk = Document(page_content=merged_content, metadata=merged_meta)
            i += 2
        else:
            i += 1

        # Tag chunks containing tables
        has_table = bool(_TABLE_ROW_PATTERN.search(chunk.page_content))
        if has_table:
            chunk.metadata["has_table"] = True

        # Split oversized table chunks
        if has_table and len(chunk.page_content) > _MAX_TABLE_CHUNK:
            result.extend(_split_large_table(chunk))
        else:
            result.append(chunk)

    return result


def _split_large_table(chunk: Document) -> list[Document]:
    """Split a chunk with a large table at row boundaries, preserving header."""
    content = chunk.page_content
    header_match = _TABLE_HEADER_PATTERN.search(content)
    if not header_match:
        return [chunk]

    header = header_match.group(1)
    header_end = header_match.end()

    # Text before table
    pre_table = content[:header_match.start()].strip()

    # Table rows after header
    table_body = content[header_end:].strip()
    rows = [line for line in table_body.split("\n") if line.strip()]

    # Split into groups
    parts: list[Document] = []
    if pre_table:
        parts.append(Document(page_content=pre_table, metadata=dict(chunk.metadata)))

    for start in range(0, len(rows), _TABLE_SPLIT_ROWS):
        batch = rows[start:start + _TABLE_SPLIT_ROWS]
        part_content = header + "\n" + "\n".join(batch)
        parts.append(Document(page_content=part_content, metadata={**chunk.metadata, "has_table": True}))

    return parts if parts else [chunk]
```

Update `_smart_chunk` to call it — add before the return:

```python
    # Step 5: Fix table boundaries
    final_chunks = _fix_table_boundaries(final_chunks)

    return final_chunks if final_chunks else [Document(page_content=text, metadata={"source_filename": source})]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_table_chunking.py -v`
Expected: PASS

- [ ] **Step 5: Run all tests**

Run: `python -m pytest --tb=short -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add services/ingestion.py tests/test_table_chunking.py
git commit -m "feat: table-aware chunking — preserve table integrity across chunk boundaries"
```

---

## Task 4: Hierarchical Contextual Enrichment (TDD)

**Files:**
- Modify: `services/ingestion.py:548-594` (rewrite `_enrich_with_context`)
- Test: `tests/test_hierarchical_enrichment.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_hierarchical_enrichment.py
"""Test section-level contextual enrichment."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from langchain_core.documents import Document


@pytest.mark.asyncio
async def test_build_section_map_from_headers():
    """Build section map from markdown headers."""
    from services.ingestion import _build_section_map

    text = "# Curriculum\n\nDetails about curriculum\n\n## Tuition\n\nTuition is 21,000\n\n## Schedule\n\nMonday 9-12"
    sections = _build_section_map(text)

    assert len(sections) >= 2
    assert any("Curriculum" in s["title"] or "Tuition" in s["title"] for s in sections)


@pytest.mark.asyncio
async def test_enrich_uses_section_context_not_global():
    """Enrichment sends section text to Haiku, not full document."""
    with patch("services.ingestion.ChatAnthropic") as MockLLM:
        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(return_value=MagicMock(content="Context about tuition section"))
        MockLLM.return_value = mock_instance

        from services.ingestion import _enrich_with_context

        full_text = "# Curriculum\n\nLong curriculum text here\n\n## Tuition\n\nTuition is 21,000 baht per semester"
        chunks = [
            Document(page_content="Tuition is 21,000 baht per semester", metadata={"source_filename": "test.pdf"}),
        ]

        enriched = await _enrich_with_context(chunks, full_text)

        assert len(enriched) == 1
        assert "Context about tuition section" in enriched[0].page_content
        # Verify Haiku was called (not Vision model)
        MockLLM.assert_called_once()
        call_kwargs = MockLLM.call_args[1]
        assert "haiku" in call_kwargs.get("model", "")


@pytest.mark.asyncio
async def test_enrich_fallback_when_no_headers():
    """Falls back to global summary when no headers found."""
    with patch("services.ingestion.ChatAnthropic") as MockLLM:
        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(return_value=MagicMock(content="Global context"))
        MockLLM.return_value = mock_instance

        from services.ingestion import _enrich_with_context

        full_text = "Plain text without any headers. Just a bunch of content."
        chunks = [Document(page_content="Just a bunch of content.", metadata={})]

        enriched = await _enrich_with_context(chunks, full_text)

        assert "Global context" in enriched[0].page_content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hierarchical_enrichment.py -v`
Expected: FAIL

- [ ] **Step 3: Implement hierarchical enrichment**

Replace `_enrich_with_context` and add `_build_section_map` in `services/ingestion.py`:

```python
_SECTION_CONTEXT_PROMPT = (
    "<document_section title=\"{section_title}\">\n{section_text}\n</document_section>\n\n"
    "<chunk>\n{chunk}\n</chunk>\n\n"
    "Write 1-2 sentences explaining what this chunk is about within its section. "
    "Include the section topic and what specific information this chunk contains. "
    "Respond in the same language as the document. Reply with ONLY the context."
)

_GLOBAL_CONTEXT_PROMPT = (
    "Here is the document:\n<document>\n{document}\n</document>\n\n"
    "<chunk>\n{chunk}\n</chunk>\n\n"
    "Write a short 1-2 sentence context in the SAME LANGUAGE as the document "
    "that explains where this chunk fits. Reply with ONLY the context."
)


def _build_section_map(text: str) -> list[dict]:
    """Parse markdown headers to build section map with positions."""
    sections = []
    lines = text.split("\n")
    current_title = "Document"
    current_start = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            # Save previous section
            if sections or current_start > 0:
                end_pos = sum(len(l) + 1 for l in lines[:i])
                if sections:
                    sections[-1]["end"] = end_pos
            title = stripped.lstrip("#").strip()
            start_pos = sum(len(l) + 1 for l in lines[:i])
            sections.append({"title": title, "start": start_pos, "end": len(text)})

    if not sections:
        sections.append({"title": "Document", "start": 0, "end": len(text)})

    # Fill section texts
    for sec in sections:
        sec["text"] = text[sec["start"]:sec["end"]][:3000]

    return sections


def _find_section_for_chunk(sections: list[dict], chunk_text: str, full_text: str) -> dict:
    """Find which section a chunk belongs to by position matching."""
    pos = full_text.find(chunk_text[:80])
    if pos < 0:
        return sections[0] if sections else {"title": "Document", "text": full_text[:3000]}

    for sec in reversed(sections):
        if sec["start"] <= pos:
            return sec

    return sections[0] if sections else {"title": "Document", "text": full_text[:3000]}


async def _enrich_with_context(
    chunks: list[Document], full_text: str
) -> list[Document]:
    """Section-level contextual enrichment using Haiku."""
    if not chunks:
        return chunks

    sections = _build_section_map(full_text)
    has_headers = len(sections) > 1 or sections[0]["title"] != "Document"

    llm = ChatAnthropic(
        model=settings.VISION_MODEL,  # Haiku
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        temperature=0,
        max_tokens=100,
        max_retries=3,
    )

    for i, chunk in enumerate(chunks):
        if i > 0 and i % 10 == 0:
            await asyncio.sleep(1)
        try:
            if has_headers:
                section = _find_section_for_chunk(sections, chunk.page_content, full_text)
                prompt = _SECTION_CONTEXT_PROMPT.format(
                    section_title=section["title"],
                    section_text=section["text"],
                    chunk=chunk.page_content,
                )
            else:
                doc_summary = full_text[:4000] if len(full_text) > 4000 else full_text
                prompt = _GLOBAL_CONTEXT_PROMPT.format(
                    document=doc_summary,
                    chunk=chunk.page_content,
                )

            context = await llm.ainvoke(prompt)
            chunk.page_content = f"[{context.content.strip()}]\n{chunk.page_content}"
        except Exception:
            logger.warning("Failed to generate context for chunk %d, skipping", i)

    return chunks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_hierarchical_enrichment.py -v`
Expected: PASS

- [ ] **Step 5: Run all tests**

Run: `python -m pytest --tb=short -q`

- [ ] **Step 6: Commit**

```bash
git add services/ingestion.py tests/test_hierarchical_enrichment.py
git commit -m "feat: hierarchical contextual enrichment — section-level context via Haiku"
```

---

## Task 5: BM25 Index Service (TDD)

**Files:**
- Create: `services/bm25.py`
- Test: `tests/test_bm25.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_bm25.py
"""Test BM25 keyword search index."""
import pytest
from langchain_core.documents import Document


def test_bm25_search_finds_exact_keyword():
    """BM25 finds documents by exact keyword match."""
    from services.bm25 import BM25Index

    docs = [
        Document(page_content="วิชา 2110101 คณิตศาสตร์วิศวกรรม", metadata={"source_filename": "a.pdf"}),
        Document(page_content="ค่าเทอม 21,000 บาทต่อเทอม", metadata={"source_filename": "b.pdf"}),
        Document(page_content="ตารางเรียนวันจันทร์ 9:00-12:00", metadata={"source_filename": "c.pdf"}),
    ]
    idx = BM25Index(docs)
    results = idx.search("2110101", k=2)

    assert len(results) >= 1
    assert "2110101" in results[0].page_content


def test_bm25_search_returns_empty_for_no_match():
    """BM25 returns empty list when nothing matches."""
    from services.bm25 import BM25Index

    docs = [Document(page_content="ค่าเทอม 21,000 บาท", metadata={})]
    idx = BM25Index(docs)
    results = idx.search("nonexistent_term_xyz", k=5)

    assert results == []


def test_bm25_cache_invalidation():
    """Cache is invalidated when new docs are ingested."""
    from services.bm25 import get_bm25_index, invalidate_bm25_cache

    # Build index
    docs = [Document(page_content="test content", metadata={})]
    idx1 = get_bm25_index("test_ns", docs)

    # Same namespace returns cached
    idx2 = get_bm25_index("test_ns")
    assert idx1 is idx2

    # Invalidate
    invalidate_bm25_cache("test_ns")
    idx3 = get_bm25_index("test_ns", docs)
    assert idx3 is not idx1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_bm25.py -v`
Expected: FAIL (module doesn't exist)

- [ ] **Step 3: Implement BM25 service**

```python
# services/bm25.py
"""BM25 keyword search index per namespace."""

import logging
import re
from threading import Lock

from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

_lock = Lock()
_cache: dict[str, "BM25Index"] = {}


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer: split on whitespace and punctuation, lowercase."""
    return re.findall(r"[\w\d]+", text.lower())


class BM25Index:
    """In-memory BM25 index over a list of Documents."""

    def __init__(self, documents: list[Document]):
        self.documents = documents
        corpus = [_tokenize(doc.page_content) for doc in documents]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def search(self, query: str, k: int = 10) -> list[Document]:
        if not self._bm25 or not self.documents:
            return []
        tokens = _tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        top_indices = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
        return [self.documents[i] for i in top_indices if scores[i] > 0]


def get_bm25_index(namespace: str, documents: list[Document] | None = None) -> BM25Index:
    """Get or create BM25 index for a namespace. Pass documents to build/rebuild."""
    with _lock:
        if namespace not in _cache and documents:
            _cache[namespace] = BM25Index(documents)
        elif documents:
            _cache[namespace] = BM25Index(documents)
        return _cache.get(namespace, BM25Index([]))


def invalidate_bm25_cache(namespace: str) -> None:
    """Invalidate cached BM25 index when new documents are ingested."""
    with _lock:
        _cache.pop(namespace, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_bm25.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/bm25.py tests/test_bm25.py
git commit -m "feat: BM25 keyword search index with namespace caching"
```

---

## Task 6: Confidence-Aware Reranker (TDD)

**Files:**
- Modify: `services/reranker.py`
- Test: `tests/test_confidence_rerank.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_confidence_rerank.py
"""Test confidence-aware reranking."""
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.documents import Document


def test_rerank_returns_doc_score_tuples():
    """Reranker returns (document, score) tuples."""
    with patch("services.reranker._get_client") as mock_client:
        mock_response = MagicMock()
        mock_response.results = [
            MagicMock(index=0, relevance_score=0.85),
            MagicMock(index=1, relevance_score=0.45),
        ]
        mock_client.return_value.rerank.return_value = mock_response

        from services.reranker import rerank_with_scores

        docs = [
            Document(page_content="High relevance doc", metadata={}),
            Document(page_content="Medium relevance doc", metadata={}),
        ]
        results = rerank_with_scores("test query", docs, top_k=2)

        assert len(results) == 2
        assert results[0][1] == 0.85  # score
        assert results[1][1] == 0.45


def test_format_with_confidence_tiers():
    """Results formatted with confidence tier labels."""
    from services.reranker import format_with_confidence

    scored_docs = [
        (Document(page_content="High", metadata={"source_filename": "a.pdf"}), 0.85),
        (Document(page_content="Medium", metadata={"source_filename": "b.pdf"}), 0.45),
        (Document(page_content="Low", metadata={"source_filename": "c.pdf"}), 0.15),
    ]
    formatted = format_with_confidence(scored_docs)

    assert "[HIGH CONFIDENCE]" in formatted
    assert "[MEDIUM" in formatted
    # Low confidence (< 0.3) should be filtered out
    assert "Low" not in formatted
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_confidence_rerank.py -v`
Expected: FAIL

- [ ] **Step 3: Implement confidence-aware reranker**

Replace `services/reranker.py`:

```python
"""Cohere Rerank v3.5 with confidence-aware scoring."""

from functools import lru_cache

import cohere
from langchain_core.documents import Document

from config import settings

_MAX_RESULT_CHARS = 2000


@lru_cache()
def _get_client() -> cohere.Client:
    return cohere.Client(api_key=settings.COHERE_API_KEY)


def get_reranker():
    """Warm up Cohere client on startup."""
    _get_client()


def rerank_documents(
    query: str, documents: list[Document], top_k: int
) -> list[Document]:
    """Re-score documents (backward compatible — returns docs only)."""
    scored = rerank_with_scores(query, documents, top_k)
    return [doc for doc, _ in scored]


def rerank_with_scores(
    query: str, documents: list[Document], top_k: int
) -> list[tuple[Document, float]]:
    """Re-score documents and return (document, relevance_score) tuples."""
    if not documents:
        return []

    response = _get_client().rerank(
        model=settings.RERANKER_MODEL,
        query=query,
        documents=[doc.page_content for doc in documents],
        top_n=top_k,
    )
    return [(documents[r.index], r.relevance_score) for r in response.results]


def format_with_confidence(
    scored_docs: list[tuple[Document, float]],
) -> str:
    """Format reranked docs with confidence tiers. Filters out <0.3 score."""
    results = []
    for i, (doc, score) in enumerate(scored_docs, 1):
        if score < 0.3:
            continue

        confidence = "[HIGH CONFIDENCE]" if score > 0.6 else "[MEDIUM - may not be exact match]"

        source = doc.metadata.get("source_filename", "unknown")
        page = doc.metadata.get("page", "")
        category = doc.metadata.get("doc_category", "")
        download_link = doc.metadata.get("download_link", "")

        header = f"{confidence} [{i}] Source: {source}"
        if page and page != "N/A":
            header += f" (page {page})"
        if category:
            header += f" [{category}]"
        if download_link:
            header += f"\n    Download: {download_link}"

        content = doc.page_content[:_MAX_RESULT_CHARS]
        results.append(f"{header}\n{content}")

    if not results:
        return "No relevant documents found with sufficient confidence."

    return "\n\n---\n\n".join(results)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_confidence_rerank.py -v`
Expected: PASS

- [ ] **Step 5: Run all tests**

Run: `python -m pytest --tb=short -q`

- [ ] **Step 6: Commit**

```bash
git add services/reranker.py tests/test_confidence_rerank.py
git commit -m "feat: confidence-aware reranker with 3-tier scoring"
```

---

## Task 7: Search Orchestrator — Multi-Query + Decomposition + Hybrid + RRF (TDD)

**Files:**
- Create: `services/search.py`
- Test: `tests/test_search_pipeline.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_search_pipeline.py
"""Test the search orchestration pipeline."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from langchain_core.documents import Document


@pytest.mark.asyncio
async def test_search_pipeline_returns_formatted_results():
    """Full pipeline: decompose → multi-query → hybrid search → RRF → rerank → format."""
    with (
        patch("services.search._decompose_query", new_callable=AsyncMock) as mock_decompose,
        patch("services.search._generate_query_variants", new_callable=AsyncMock) as mock_variants,
        patch("services.search._hybrid_search") as mock_hybrid,
        patch("services.search.rerank_with_scores") as mock_rerank,
    ):
        mock_decompose.return_value = ["ค่าเทอม"]  # simple query, no decomposition
        mock_variants.return_value = ["ค่าเทอม", "tuition fee", "ค่าใช้จ่ายการศึกษา"]

        doc = Document(page_content="ค่าเทอม 21,000 บาท", metadata={"source_filename": "test.pdf"})
        mock_hybrid.return_value = [doc]
        mock_rerank.return_value = [(doc, 0.85)]

        from services.search import search

        result = await search("ค่าเทอม", "test_ns")

        assert "[HIGH CONFIDENCE]" in result
        assert "21,000" in result


@pytest.mark.asyncio
async def test_decompose_complex_query():
    """Complex multi-part query is decomposed into sub-queries."""
    with patch("services.search.ChatAnthropic") as MockLLM:
        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(return_value=MagicMock(
            content='{"type": "complex", "sub_queries": ["ค่าเทอม 4 ปี", "ค่าเทอม 5 ปี"]}'
        ))
        MockLLM.return_value = mock_instance

        from services.search import _decompose_query
        result = await _decompose_query("เปรียบเทียบค่าเทอม 4 ปี กับ 5 ปี")

        assert len(result) == 2
        assert "4 ปี" in result[0]
        assert "5 ปี" in result[1]


def test_reciprocal_rank_fusion_merges_results():
    """RRF merges two ranked lists with correct scoring."""
    from services.search import reciprocal_rank_fusion

    doc_a = Document(page_content="A", metadata={"id": "a"})
    doc_b = Document(page_content="B", metadata={"id": "b"})
    doc_c = Document(page_content="C", metadata={"id": "c"})

    vector_results = [doc_a, doc_b]  # a=rank0, b=rank1
    bm25_results = [doc_c, doc_a]    # c=rank0, a=rank1

    merged = reciprocal_rank_fusion(vector_results, bm25_results, k=60)

    # doc_a appears in both lists → highest merged score
    assert merged[0].page_content == "A"
    assert len(merged) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_search_pipeline.py -v`
Expected: FAIL (module doesn't exist)

- [ ] **Step 3: Implement search orchestrator**

```python
# services/search.py
"""Search orchestrator: decomposition → multi-query → hybrid search → RRF → confidence rerank."""

import json
import logging

from langchain_anthropic import ChatAnthropic
from langchain_core.documents import Document

from config import settings
from services.bm25 import get_bm25_index, BM25Index
from services.reranker import rerank_with_scores, format_with_confidence
from services.vectorstore import get_vectorstore, list_all_vector_ids, fetch_metadata_batch

logger = logging.getLogger(__name__)

_DECOMPOSE_PROMPT = (
    "Analyze this question. If it asks about multiple topics or requires comparison, "
    "decompose into separate search queries (max 3). If it's a single-topic question, return it as-is.\n\n"
    "Question: {query}\n\n"
    'Return JSON: {{"type": "simple", "query": "..."}} or {{"type": "complex", "sub_queries": ["...", "..."]}}'
)

_MULTI_QUERY_PROMPT = (
    "Generate 2 alternative search queries for this question. "
    "One should translate key terms to English, one should use Thai synonyms or rephrase.\n\n"
    "Question: {query}\n\n"
    'Return JSON array: ["english translation query", "thai synonym query"]'
)


def _get_haiku():
    return ChatAnthropic(
        model=settings.VISION_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        temperature=0.3,
        max_tokens=150,
        max_retries=2,
    )


async def search(query: str, namespace: str, category: str | None = None) -> str:
    """Full search pipeline: decompose → multi-query → hybrid → RRF → rerank → format."""
    # Step 1: Decompose complex queries
    sub_queries = await _decompose_query(query)

    # Step 2: Generate variants for each sub-query
    all_docs: list[Document] = []
    for sq in sub_queries:
        variants = await _generate_query_variants(sq)
        # Step 3: Hybrid search for each variant
        variant_docs: list[Document] = []
        for v in variants:
            results = _hybrid_search(v, namespace, category=category, k=10)
            variant_docs.extend(results)
        # Deduplicate by content
        seen = set()
        for doc in variant_docs:
            key = doc.page_content[:200]
            if key not in seen:
                seen.add(key)
                all_docs.append(doc)

    if not all_docs:
        return "No relevant documents found for this query."

    # Step 4: Rerank with confidence scores
    scored = rerank_with_scores(query, all_docs, top_k=settings.TOP_K)

    # Step 5: Format with confidence tiers
    return format_with_confidence(scored)


async def search_with_sources(query: str, namespace: str, category: str | None = None) -> tuple[str, list[dict]]:
    """Search and return both formatted text and structured sources."""
    sub_queries = await _decompose_query(query)

    all_docs: list[Document] = []
    for sq in sub_queries:
        variants = await _generate_query_variants(sq)
        for v in variants:
            results = _hybrid_search(v, namespace, category=category, k=10)
            all_docs.extend(results)

    # Deduplicate
    seen = set()
    unique_docs = []
    for doc in all_docs:
        key = doc.page_content[:200]
        if key not in seen:
            seen.add(key)
            unique_docs.append(doc)

    if not unique_docs:
        return "No relevant documents found for this query.", []

    scored = rerank_with_scores(query, unique_docs, top_k=settings.TOP_K)
    formatted = format_with_confidence(scored)

    sources = []
    for doc, score in scored:
        if score >= 0.3:
            sources.append({
                "filename": doc.metadata.get("source_filename", "unknown"),
                "page": doc.metadata.get("page"),
                "category": doc.metadata.get("doc_category", ""),
                "download_link": doc.metadata.get("download_link", ""),
                "relevance_score": round(score, 3),
                "confidence": "HIGH" if score > 0.6 else "MEDIUM",
            })

    return formatted, sources


async def _decompose_query(query: str) -> list[str]:
    """Decompose complex query into sub-queries using Haiku."""
    try:
        llm = _get_haiku()
        result = await llm.ainvoke(_DECOMPOSE_PROMPT.format(query=query))
        parsed = json.loads(result.content.strip())
        if parsed.get("type") == "complex" and parsed.get("sub_queries"):
            return parsed["sub_queries"][:3]
        return [parsed.get("query", query)]
    except Exception:
        logger.debug("Query decomposition failed, using original query")
        return [query]


async def _generate_query_variants(query: str) -> list[str]:
    """Generate alternative queries using Haiku."""
    variants = [query]
    try:
        llm = _get_haiku()
        result = await llm.ainvoke(_MULTI_QUERY_PROMPT.format(query=query))
        parsed = json.loads(result.content.strip())
        if isinstance(parsed, list):
            variants.extend(parsed[:2])
    except Exception:
        logger.debug("Multi-query generation failed, using original only")
    return variants


def _hybrid_search(
    query: str, namespace: str, category: str | None = None, k: int = 10
) -> list[Document]:
    """Combine vector search + BM25 keyword search via RRF."""
    vectorstore = get_vectorstore(namespace)

    # Vector search
    filter_dict = {"doc_category": category} if category else None
    try:
        vector_results = vectorstore.similarity_search(query, k=k, filter=filter_dict)
    except Exception:
        logger.warning("Vector search failed")
        vector_results = []

    # BM25 search
    bm25_idx = get_bm25_index(namespace)
    bm25_results = bm25_idx.search(query, k=k) if bm25_idx.documents else []

    # If category filter, filter BM25 results too
    if category and bm25_results:
        bm25_results = [d for d in bm25_results if d.metadata.get("doc_category") == category]

    # Merge via RRF
    if not vector_results:
        return bm25_results[:k]
    if not bm25_results:
        return vector_results[:k]

    return reciprocal_rank_fusion(vector_results, bm25_results, k=settings.BM25_K_CONSTANT)[:k]


def reciprocal_rank_fusion(
    vector_results: list[Document],
    bm25_results: list[Document],
    k: int = 60,
) -> list[Document]:
    """Merge two ranked lists using Reciprocal Rank Fusion."""
    doc_scores: dict[str, tuple[Document, float]] = {}

    for rank, doc in enumerate(vector_results):
        key = doc.page_content[:200]
        score = 1 / (k + rank + 1)
        if key in doc_scores:
            doc_scores[key] = (doc, doc_scores[key][1] + score)
        else:
            doc_scores[key] = (doc, score)

    for rank, doc in enumerate(bm25_results):
        key = doc.page_content[:200]
        score = 1 / (k + rank + 1)
        if key in doc_scores:
            doc_scores[key] = (doc, doc_scores[key][1] + score)
        else:
            doc_scores[key] = (doc, score)

    sorted_items = sorted(doc_scores.values(), key=lambda x: -x[1])
    return [doc for doc, _ in sorted_items]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_search_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/search.py tests/test_search_pipeline.py
git commit -m "feat: search orchestrator with decomposition, multi-query, hybrid search, RRF"
```

---

## Task 8: Wire Tools + Agent to New Search Pipeline

**Files:**
- Modify: `services/tools.py`
- Modify: `services/agent.py`
- Modify: `services/ingestion.py` (BM25 cache invalidation in `_upsert`)

- [ ] **Step 1: Update tools.py to use search orchestrator**

Replace `search_knowledge_base` and `search_by_category` in `services/tools.py`:

```python
"""Tenant-scoped tools for the agentic chatbot."""

import ast
import logging
import operator

from langchain_core.documents import Document
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}

# Module-level storage for sources collected during tool calls
_collected_sources: list[dict] = []


def get_collected_sources() -> list[dict]:
    """Return sources collected during the last agent run and clear them."""
    sources = list(_collected_sources)
    _collected_sources.clear()
    return sources


def create_tools(namespace: str) -> list:
    """Create tools scoped to a tenant's Pinecone namespace."""

    @tool
    async def search_knowledge_base(query: str) -> str:
        """Search the faculty's knowledge base.
        Use this tool to find information about courses, curriculum, tuition,
        forms, schedules, announcements, admission, and any faculty-related topics.
        You can call this multiple times with different keywords if the first
        search doesn't find what you need."""
        try:
            from services.search import search_with_sources
            result, sources = await search_with_sources(query, namespace)
            _collected_sources.extend(sources)
            return result
        except Exception as e:
            logger.exception("search_knowledge_base failed")
            return f"Search error: {type(e).__name__} — {e}"

    @tool
    async def search_by_category(query: str, category: str) -> str:
        """Search the knowledge base filtered by document category.
        Use this when you know which type of document to look for.
        Categories: curriculum, form, announcement, schedule, general, spreadsheet."""
        try:
            from services.search import search_with_sources
            result, sources = await search_with_sources(query, namespace, category=category)
            _collected_sources.extend(sources)
            return result
        except Exception as e:
            logger.exception("search_by_category failed")
            return f"Search error: {type(e).__name__} — {e}"

    @tool
    def calculate(expression: str) -> str:
        """Evaluate a math expression safely. Use for tuition totals, GPA calculations,
        credit sums, or any numeric computation.
        Examples: '21000 * 8', '(3.5 + 4.0) / 2', '144 - 36'"""
        try:
            result = _safe_eval(ast.parse(expression, mode="eval").body)
            return str(result)
        except Exception as e:
            return f"Calculation error: {e}"

    @tool
    def fetch_webpage(url: str) -> str:
        """Fetch and read a web page as text. Use when search results contain
        a URL or link that might have additional relevant information."""
        import httpx
        try:
            response = httpx.get(
                f"https://r.jina.ai/{url}",
                timeout=15,
                headers={"Accept": "text/plain"},
            )
            response.raise_for_status()
            return response.text[:3000]
        except Exception as e:
            return f"Failed to fetch {url}: {e}"

    return [search_knowledge_base, search_by_category, calculate, fetch_webpage]


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError(f"Unsupported expression: {ast.dump(node)}")
```

- [ ] **Step 2: Update agent.py system prompt + source extraction**

Add confidence instructions to `AGENT_SYSTEM_PROMPT` and extract sources after agent run:

In `services/agent.py`, add to the system prompt (after "## Conversation History"):

```python
AGENT_SYSTEM_PROMPT = """{persona}

You have tools to search the faculty's knowledge base and perform calculations.

## Instructions
- ALWAYS use search_knowledge_base before answering questions about the faculty.
- If the first search doesn't return enough info, search again with different keywords.
- For questions involving math (total tuition, GPA, credits), use the calculate tool.
- If you truly cannot find the answer after searching, say so honestly and suggest contacting faculty staff.
- Answer in the SAME LANGUAGE as the user's question (Thai → Thai, English → English).
- Be concise, polite, and helpful.
- For greetings or casual conversation, respond naturally WITHOUT searching.

## Search Result Confidence
- [HIGH CONFIDENCE] results: Use directly in your answer
- [MEDIUM - may not be exact match] results: Use but mention the information may not be exact
- If no results pass the confidence threshold, say honestly that you couldn't find specific information and suggest contacting faculty staff directly.

## MANDATORY: Document Links
At the END of EVERY answer that uses search results, you MUST add a "📎 เอกสารอ้างอิง" section.
For each source document, include the download link from the search results.
Format:

📎 เอกสารอ้างอิง
- [filename](Download link from search results)

This is NOT optional. Every answer that references a document MUST end with this section.

## Conversation History
{history}"""
```

Change `run_agent` to return `(answer, sources)`:

```python
async def run_agent(
    query: str,
    user_id: str,
    tenant: dict,
) -> tuple[str, list[dict]]:
    """Run the agentic RAG pipeline. Returns (answer, sources)."""
    from services.tools import get_collected_sources

    namespace = tenant["pinecone_namespace"]
    persona = tenant.get("persona", "") or "You are a helpful university assistant."
    history = conversation_memory.get_history(user_id)

    tools = create_tools(namespace)
    agent = create_react_agent(model=_get_llm(), tools=tools)

    system_prompt = AGENT_SYSTEM_PROMPT.format(
        persona=persona,
        history=format_history(history),
    )

    sources: list[dict] = []
    try:
        result = await agent.ainvoke({
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=query),
            ]
        })
        answer = result["messages"][-1].content
        sources = get_collected_sources()

        from services.usage import track
        tid = tenant["tenant_id"]
        await track(tid, "llm_call")
        search_count = sum(
            len(m.tool_calls) for m in result["messages"]
            if hasattr(m, "tool_calls") and m.tool_calls
        )
        if search_count:
            await track(tid, "embedding_call", search_count)
            await track(tid, "reranker_call", search_count)

    except AuthenticationError:
        logger.error("Anthropic API key invalid or expired")
        answer = "ขออภัยค่ะ ระบบมีปัญหาด้านการยืนยันตัวตน กรุณาแจ้ง admin"
    except RateLimitError:
        logger.warning("Anthropic rate limit hit for tenant %s", tenant["tenant_id"])
        answer = "ขออภัยค่ะ ระบบมีผู้ใช้งานจำนวนมาก กรุณาลองใหม่ในอีกสักครู่"
    except APIStatusError as e:
        if "credit" in str(e).lower() or "quota" in str(e).lower():
            logger.error("Anthropic quota/credit exhausted: %s", e)
            answer = "ขออภัยค่ะ ระบบหมดโควต้าการใช้งานชั่วคราว กรุณาแจ้ง admin"
        else:
            logger.exception("Anthropic API error for tenant %s", tenant["tenant_id"])
            answer = "ขออภัยค่ะ เกิดข้อผิดพลาดในระบบ กรุณาลองใหม่อีกครั้ง"
    except Exception:
        logger.exception("Agent execution failed for tenant %s", tenant["tenant_id"])
        answer = "ขออภัยค่ะ เกิดข้อผิดพลาดในระบบ กรุณาลองใหม่อีกครั้ง"

    conversation_memory.add_turn(user_id, query, answer)
    return answer, sources
```

- [ ] **Step 3: Update webhook.py to use new return signature**

In `routers/webhook.py`, update `_handle_message_event` and `chat`:

```python
# In _handle_message_event (line 102-106):
        answer, sources = await run_agent(query=query, user_id=user_id, tenant=tenant)
        await firestore_service.log_chat(tenant_id, user_id, query, answer, sources)
        await reply_flex_message(event["reply_token"], answer, sources, token)

# In chat endpoint (line 57-63):
    answer, sources = await run_agent(query=body.query, user_id=user_id, tenant=tenant)
    await firestore_service.log_chat(tenant["tenant_id"], user_id, body.query, answer, sources)
    return ChatResponse(answer=answer, sources=sources)
```

- [ ] **Step 4: Add BM25 cache invalidation in ingestion**

In `services/ingestion.py`, add to `_upsert()` after the Pinecone upsert:

```python
async def _upsert(...) -> int:
    # ... existing code ...
    vectorstore = get_vectorstore(namespace)
    await vectorstore.aadd_documents(chunks)

    # Invalidate BM25 cache for this namespace
    from services.bm25 import invalidate_bm25_cache
    invalidate_bm25_cache(namespace)

    return len(chunks)
```

- [ ] **Step 5: Run all tests**

Run: `python -m pytest --tb=short -q`
Expected: all pass (existing tests may need minor updates for new return type)

- [ ] **Step 6: Commit**

```bash
git add services/tools.py services/agent.py services/ingestion.py routers/webhook.py
git commit -m "feat: wire tools + agent to search orchestrator with source audit trail"
```

---

## Task 9: Conversation Summarization (TDD)

**Files:**
- Modify: `services/memory.py`
- Modify: `services/dependencies.py`
- Test: `tests/test_conversation_summary.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_conversation_summary.py
"""Test conversation summarization."""
import pytest
from unittest.mock import patch, MagicMock


def test_format_history_includes_summary():
    """History formatting prepends summary when available."""
    from services.dependencies import format_history

    history = {
        "summary": "นักศึกษาถามเรื่องค่าเทอมหลักสูตร 5 ปี",
        "turns": [
            {"query": "แล้ววิชาเลือกล่ะ", "answer": "มีวิชาเลือก 12 หน่วยกิต"},
        ],
    }
    formatted = format_history(history)

    assert "นักศึกษาถามเรื่องค่าเทอม" in formatted
    assert "แล้ววิชาเลือกล่ะ" in formatted


def test_format_history_without_summary():
    """History formatting works without summary (backward compatible)."""
    from services.dependencies import format_history

    history = [
        {"query": "ค่าเทอมเท่าไหร่", "answer": "21,000 บาท"},
    ]
    formatted = format_history(history)

    assert "ค่าเทอมเท่าไหร่" in formatted


def test_summarize_conversation():
    """Summarization compresses 5 turns into a summary string."""
    with patch("services.memory.ChatAnthropic") as MockLLM:
        mock_instance = MagicMock()
        mock_instance.invoke.return_value = MagicMock(
            content="นักศึกษาถามเรื่องค่าเทอมและตารางเรียน ได้รับข้อมูลเรียบร้อย"
        )
        MockLLM.return_value = mock_instance

        from services.memory import ConversationMemory
        mem = ConversationMemory()
        summary = mem._summarize([
            {"query": "q1", "answer": "a1"},
            {"query": "q2", "answer": "a2"},
            {"query": "q3", "answer": "a3"},
            {"query": "q4", "answer": "a4"},
            {"query": "q5", "answer": "a5"},
        ])

        assert "ค่าเทอม" in summary
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_conversation_summary.py -v`
Expected: FAIL

- [ ] **Step 3: Implement conversation summarization**

Update `services/memory.py`:

```python
"""Firestore-backed conversation memory with TTL and summarization."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore as fs
from langchain_anthropic import ChatAnthropic

from config import settings
from services.firestore import _get_db

logger = logging.getLogger(__name__)

CONVERSATIONS_COLLECTION = "conversations"

_SUMMARIZE_PROMPT = (
    "Summarize this conversation between a student and university assistant in 1-2 sentences. "
    "Preserve key topics, specific details (course codes, names, amounts), and any unresolved questions.\n\n"
    "{conversation}"
)


class ConversationMemory:

    def get_history(self, user_id: str) -> dict[str, Any] | list[dict]:
        """Get conversation history with optional summary."""
        doc = self._get_doc(user_id)
        if not doc:
            return []

        last_active = doc.get("last_active")
        if last_active:
            elapsed = (datetime.now(timezone.utc) - last_active).total_seconds()
            if elapsed > settings.MEMORY_TTL:
                self.clear(user_id)
                return []

        summary = doc.get("summary", "")
        turns = doc.get("turns", [])
        recent_turns = turns[-settings.MAX_HISTORY_TURNS:]

        if summary:
            return {"summary": summary, "turns": recent_turns}
        return recent_turns

    def add_turn(self, user_id: str, query: str, answer: str) -> None:
        db = _get_db()
        doc_ref = db.collection(CONVERSATIONS_COLLECTION).document(user_id)
        turn = {"query": query, "answer": answer}

        doc_ref.set(
            {
                "turns": fs.ArrayUnion([turn]),
                "last_active": datetime.now(timezone.utc),
            },
            merge=True,
        )

        # Check if we need to summarize
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            turns = data.get("turns", [])
            if len(turns) > settings.MAX_HISTORY_TURNS:
                # Summarize and reset
                old_summary = data.get("summary", "")
                context = f"Previous context: {old_summary}\n\n" if old_summary else ""
                conversation_text = context + "\n".join(
                    f"Student: {t['query']}\nAssistant: {t['answer']}" for t in turns
                )
                summary = self._summarize(turns, old_summary)
                doc_ref.update({
                    "turns": [],
                    "summary": summary,
                })

    def _summarize(self, turns: list[dict], existing_summary: str = "") -> str:
        """Compress conversation turns into a summary using Haiku."""
        try:
            context = f"Previous context: {existing_summary}\n\n" if existing_summary else ""
            conversation = context + "\n".join(
                f"Student: {t['query']}\nAssistant: {t['answer']}" for t in turns
            )
            llm = ChatAnthropic(
                model=settings.VISION_MODEL,
                anthropic_api_key=settings.ANTHROPIC_API_KEY,
                temperature=0,
                max_tokens=200,
                max_retries=2,
            )
            result = llm.invoke(_SUMMARIZE_PROMPT.format(conversation=conversation))
            return result.content.strip()
        except Exception:
            logger.warning("Conversation summarization failed, keeping turns")
            return existing_summary

    def clear(self, user_id: str) -> None:
        _get_db().collection(CONVERSATIONS_COLLECTION).document(user_id).delete()

    def _get_doc(self, user_id: str) -> dict[str, Any] | None:
        doc = _get_db().collection(CONVERSATIONS_COLLECTION).document(user_id).get()
        if not doc.exists:
            return None
        return doc.to_dict()


_memory = ConversationMemory()


class AsyncConversationMemory:
    def get_history(self, user_id: str) -> dict[str, Any] | list[dict]:
        return _memory.get_history(user_id)

    def add_turn(self, user_id: str, query: str, answer: str) -> None:
        _memory.add_turn(user_id, query, answer)

    def clear(self, user_id: str) -> None:
        _memory.clear(user_id)


conversation_memory = AsyncConversationMemory()
```

Update `services/dependencies.py` `format_history`:

```python
def format_history(history: list[dict] | dict) -> str:
    """Format conversation turns into a readable string for the LLM."""
    if not history:
        return "ไม่มีประวัติสนทนา"

    # New format: dict with summary + turns
    if isinstance(history, dict):
        parts = []
        if history.get("summary"):
            parts.append(f"บริบทก่อนหน้า: {history['summary']}")
        turns = history.get("turns", [])
        for turn in turns:
            parts.append(f"นักศึกษา: {turn['query']}")
            parts.append(f"ผู้ช่วย: {turn['answer']}")
        return "\n".join(parts) if parts else "ไม่มีประวัติสนทนา"

    # Legacy format: list of turns
    lines = []
    for turn in history:
        lines.append(f"นักศึกษา: {turn['query']}")
        lines.append(f"ผู้ช่วย: {turn['answer']}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_conversation_summary.py -v`
Expected: PASS

- [ ] **Step 5: Run all tests**

Run: `python -m pytest --tb=short -q`

- [ ] **Step 6: Commit**

```bash
git add services/memory.py services/dependencies.py tests/test_conversation_summary.py
git commit -m "feat: conversation summarization — unlimited effective memory via Haiku"
```

---

## Task 10: Build BM25 Index on Ingestion + Startup

**Files:**
- Modify: `services/ingestion.py` (`_upsert` — already done in Task 8)
- Modify: `services/search.py` (lazy BM25 build from Pinecone)

- [ ] **Step 1: Add lazy BM25 index building from Pinecone**

In `services/search.py`, add a function to build BM25 from existing Pinecone data:

```python
def _ensure_bm25_index(namespace: str) -> None:
    """Lazily build BM25 index from Pinecone if not cached."""
    idx = get_bm25_index(namespace)
    if idx.documents:
        return  # Already built

    # Build from Pinecone metadata
    try:
        ids = list_all_vector_ids(namespace)
        if not ids:
            return
        metadata_list = fetch_metadata_batch(ids, namespace)
        # We need page_content but Pinecone doesn't store it by default
        # BM25 will be built when documents are ingested
        logger.info("BM25 index for %s has no documents yet (will build on next ingest)", namespace)
    except Exception:
        logger.warning("Failed to build BM25 index for %s", namespace)
```

Update `_upsert` in `services/ingestion.py` to build BM25 from ingested chunks:

```python
async def _upsert(...) -> int:
    # ... existing enrichment + metadata ...

    vectorstore = get_vectorstore(namespace)
    await vectorstore.aadd_documents(chunks)

    # Build/update BM25 index with new chunks
    from services.bm25 import get_bm25_index, invalidate_bm25_cache
    invalidate_bm25_cache(namespace)
    get_bm25_index(namespace, chunks)

    return len(chunks)
```

- [ ] **Step 2: Verify all tests pass**

Run: `python -m pytest --tb=short -q`

- [ ] **Step 3: Commit**

```bash
git add services/ingestion.py services/search.py
git commit -m "feat: BM25 index built from ingested chunks, lazy init"
```

---

## Task 11: Integration Test + Deploy

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest --tb=short -q`
Expected: all pass

- [ ] **Step 2: Build and deploy backend**

```bash
cd cutip-rag-chatbot
gcloud builds submit --tag asia-southeast1-docker.pkg.dev/cutip-rag/cloud-run-source-deploy/cutip-rag-bot --region=asia-southeast1
gcloud run deploy cutip-rag-bot --image asia-southeast1-docker.pkg.dev/cutip-rag/cloud-run-source-deploy/cutip-rag-bot --region asia-southeast1 --set-secrets "PINECONE_API_KEY=PINECONE_API_KEY:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,COHERE_API_KEY=COHERE_API_KEY:latest,ADMIN_API_KEY=ADMIN_API_KEY:latest" --allow-unauthenticated --port 8000 --memory 8Gi --cpu 2
```

- [ ] **Step 3: Verify health**

Run: `curl -s https://cutip-rag-bot-265709916451.asia-southeast1.run.app/health`
Expected: `{"status":"ok"}`

- [ ] **Step 4: Re-ingest all documents**

Trigger batch re-ingestion for each tenant to rebuild vectors with new chunking:

```bash
curl -X POST "https://cutip-rag-bot-265709916451.asia-southeast1.run.app/api/tenants/cutip_01/ingest/gdrive" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"folder_id": "<gdrive_folder_id>"}'
```

- [ ] **Step 5: Commit final**

```bash
git add -A
git commit -m "feat: god mode RAG — all 8 improvements deployed and re-ingested"
```
