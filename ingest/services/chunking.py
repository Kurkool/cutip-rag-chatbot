"""Chunking utilities: semantic, markdown-header-aware, and table-safe splitting.

``langchain_text_splitters`` package init loads ``sentence_transformers`` →
``transformers`` → ``torch`` (~5s cold). We defer that import until actually
needed so modules that merely touch ``ingest.services.*`` (tests, admin
router imports) don't pay the cost.
"""

import logging
import re
from functools import lru_cache
from typing import TYPE_CHECKING

from langchain_core.documents import Document

from shared.config import settings
from shared.services.embedding import get_embedding_model

if TYPE_CHECKING:
    from langchain_experimental.text_splitter import SemanticChunker
    from langchain_text_splitters import (
        MarkdownHeaderTextSplitter,
        RecursiveCharacterTextSplitter,
    )

logger = logging.getLogger(__name__)

# ──────────────────────────────────────
# Smart Chunking Pipeline
# ──────────────────────────────────────

_MAX_CHUNK_CHARS = 3000
_MIN_CHUNK_CHARS = 50


@lru_cache(maxsize=1)
def _get_md_header_splitter() -> "MarkdownHeaderTextSplitter":
    from langchain_text_splitters import MarkdownHeaderTextSplitter
    return MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#", "section"),
            ("##", "subsection"),
            ("###", "topic"),
        ],
        strip_headers=False,
    )


@lru_cache(maxsize=1)
def _get_fallback_splitter() -> "RecursiveCharacterTextSplitter":
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", ".", " ", ""],
    )


def _build_header_map(text: str) -> list[tuple[int, str]]:
    """Return [(char_offset, header_path), ...] sorted by offset.

    Uses md_header_splitter to find where each header section starts, then
    maps that back to a character position in the original text so we can
    annotate semantic chunks that land inside that region.
    """
    header_chunks = _get_md_header_splitter().split_text(text)
    position_map: list[tuple[int, str]] = []
    search_start = 0
    for hchunk in header_chunks:
        header_path = " > ".join(
            hchunk.metadata[key]
            for key in ["section", "subsection", "topic"]
            if hchunk.metadata.get(key)
        )
        snippet = hchunk.page_content[:80].strip()
        if snippet:
            pos = text.find(snippet, search_start)
            if pos == -1:
                pos = search_start
        else:
            pos = search_start
        position_map.append((pos, header_path))
        search_start = pos
    return position_map


def _header_for_position(pos: int, header_map: list[tuple[int, str]]) -> str:
    """Return the header path that covers *pos* in the original text."""
    result = ""
    for offset, path in header_map:
        if offset <= pos:
            result = path
        else:
            break
    return result


def _make_semantic_chunker() -> "SemanticChunker":
    """Factory: create a SemanticChunker per call (not thread-safe with lru_cache)."""
    from langchain_experimental.text_splitter import SemanticChunker
    return SemanticChunker(
        embeddings=get_embedding_model(),
        breakpoint_threshold_type="percentile",
        breakpoint_threshold_amount=settings.SEMANTIC_CHUNK_PERCENTILE,
    )


def _smart_chunk(text: str, source: str = "") -> list[Document]:
    """Semantic chunking pipeline:

    1. Try SemanticChunker (Cohere embeddings) for boundary detection.
    2. Fallback to RecursiveCharacterTextSplitter if semantic chunking fails.
    3. Split any chunk > 3000 chars with the fallback splitter.
    4. Remove chunks < 50 chars (after strip).
    5. Annotate each chunk with its markdown header path.
    """
    try:
        header_map = _build_header_map(text)
    except Exception:
        header_map = []

    fallback = _get_fallback_splitter()

    # ── Step 1: Attempt semantic chunking ──────────────────────────────────
    raw_chunks: list[Document] = []
    try:
        chunker = _make_semantic_chunker()
        raw_chunks = chunker.create_documents([text])
    except Exception as exc:
        logger.warning("SemanticChunker failed (%s), using fallback splitter", exc)

    # ── Step 2: Fallback if semantic chunking produced nothing ─────────────
    if not raw_chunks:
        raw_chunks = fallback.create_documents(
            [text], metadatas=[{"source_filename": source}]
        )

    # ── Step 3: Cap oversized chunks ───────────────────────────────────────
    capped: list[Document] = []
    for chunk in raw_chunks:
        if len(chunk.page_content) > _MAX_CHUNK_CHARS:
            sub = fallback.split_documents([chunk])
            capped.extend(sub)
        else:
            capped.append(chunk)

    # ── Step 3b: Fix table boundaries (merge incomplete, split large) ─────
    capped = _fix_table_boundaries(capped)

    # ── Step 4 + 5: Filter tiny, then annotate with header & source ────────
    final: list[Document] = []
    for chunk in capped:
        content = chunk.page_content.strip()
        if len(content) < _MIN_CHUNK_CHARS:
            continue

        pos = text.find(content[:60]) if len(content) >= 60 else text.find(content)
        if pos == -1:
            pos = 0
        header_path = _header_for_position(pos, header_map)

        if header_path and not content.startswith(f"[{header_path}]"):
            content = f"[{header_path}]\n{content}"

        chunk.page_content = content
        chunk.metadata["source_filename"] = source
        final.append(chunk)

    # Edge case: everything was filtered — return a single fallback chunk
    if not final:
        return fallback.create_documents(
            [text], metadatas=[{"source_filename": source}]
        )

    return final


# ──────────────────────────────────────
# Table-Aware Chunking Helpers
# ──────────────────────────────────────

_TABLE_ROW_RE = re.compile(r"^\|.*\|$", re.MULTILINE)
_TABLE_SPLIT_ROWS = 20
_TABLE_CHUNK_MAX = 2000


def _chunk_has_table(content: str) -> bool:
    """Return True if the content contains at least one markdown table row."""
    return bool(_TABLE_ROW_RE.search(content))


def _last_line_is_incomplete_table_row(content: str) -> bool:
    """Return True if the last non-empty line starts with '|' but does NOT end with '|'."""
    lines = content.rstrip("\n").splitlines()
    if not lines:
        return False
    last = lines[-1].rstrip()
    return last.startswith("|") and not last.endswith("|")


def _split_large_table(doc: Document) -> list[Document]:
    """Split a table-heavy chunk > _TABLE_CHUNK_MAX chars at row boundaries.

    The table header (first row + separator row) is prepended to every split
    so each resulting chunk is self-contained.
    """
    content = doc.page_content
    lines = content.splitlines(keepends=True)

    header_lines: list[str] = []
    data_lines: list[str] = []
    found_header = False
    found_separator = False

    for line in lines:
        stripped = line.strip()
        if not found_header and stripped.startswith("|"):
            header_lines.append(line)
            found_header = True
        elif found_header and not found_separator and re.match(r"^\|[\s\-|]+\|$", stripped):
            header_lines.append(line)
            found_separator = True
        else:
            data_lines.append(line)

    header_text = "".join(header_lines)

    splits: list[Document] = []
    batch: list[str] = []
    row_count = 0

    def _flush(batch: list[str]) -> None:
        chunk_text = header_text + "".join(batch)
        new_doc = Document(
            page_content=chunk_text,
            metadata={**doc.metadata, "has_table": True},
        )
        splits.append(new_doc)

    for line in data_lines:
        batch.append(line)
        if line.strip().startswith("|"):
            row_count += 1
        if row_count >= _TABLE_SPLIT_ROWS:
            _flush(batch)
            batch = []
            row_count = 0

    if batch:
        _flush(batch)

    return splits if splits else [doc]


def _fix_table_boundaries(chunks: list[Document]) -> list[Document]:
    """Post-process chunks to preserve table integrity.

    1. Merge incomplete table rows: if a chunk ends mid-row (starts with '|'
       but the last non-empty line lacks a closing '|'), it is merged with the
       following chunk.
    2. Split large table chunks: chunks > _TABLE_CHUNK_MAX chars that contain
       tables are split every _TABLE_SPLIT_ROWS rows, preserving the header.
    3. Tag metadata: chunks that contain markdown tables receive
       ``has_table: True`` in their metadata.
    """
    if not chunks:
        return chunks

    merged: list[Document] = []
    i = 0
    while i < len(chunks):
        current = chunks[i]
        if (
            _last_line_is_incomplete_table_row(current.page_content)
            and i + 1 < len(chunks)
        ):
            next_doc = chunks[i + 1]
            combined_content = current.page_content + "\n" + next_doc.page_content
            combined_meta = {**current.metadata, **next_doc.metadata}
            merged.append(Document(page_content=combined_content, metadata=combined_meta))
            i += 2
        else:
            merged.append(current)
            i += 1

    result: list[Document] = []
    for doc in merged:
        if _chunk_has_table(doc.page_content):
            if len(doc.page_content) > _TABLE_CHUNK_MAX:
                result.extend(_split_large_table(doc))
            else:
                doc.metadata["has_table"] = True
                result.append(doc)
        else:
            result.append(doc)

    return result


# ──────────────────────────────────────
# Slide Chunking
# ──────────────────────────────────────

def _chunk_pages(pages: list[dict], source: str = "") -> list[Document]:
    """Page-level chunking for slides: merge short pages."""
    chunks: list[Document] = []
    buffer = ""
    buffer_pages: list[int] = []

    for page in pages:
        text = page["text"].strip()
        if not text:
            continue
        if len(text) < 100:
            buffer += f"\n{text}" if buffer else text
            buffer_pages.append(page["page"])
        else:
            if buffer:
                chunks.append(Document(
                    page_content=buffer,
                    metadata={"source_filename": source, "pages": buffer_pages},
                ))
                buffer = ""
                buffer_pages = []
            page_chunks = _smart_chunk(text, source)
            for c in page_chunks:
                c.metadata["page"] = page["page"]
            chunks.extend(page_chunks)

    if buffer:
        chunks.append(Document(
            page_content=buffer,
            metadata={"source_filename": source, "pages": buffer_pages},
        ))
    return chunks
