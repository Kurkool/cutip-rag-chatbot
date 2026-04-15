"""Document ingestion pipeline: PDF, DOCX, XLSX/CSV, and web content to Pinecone vector store."""

import asyncio
import io
import logging
import os
import re
import subprocess
import tempfile
from typing import Any

import pandas as pd
import pymupdf
from docx import Document as DocxDocument
from langchain_anthropic import ChatAnthropic
from langchain_core.documents import Document
from langchain_experimental.text_splitter import SemanticChunker
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from shared.config import settings
from shared.services import usage
from shared.services.embedding import get_embedding_model
from shared.services.vectorstore import get_raw_index, get_vectorstore
from ingest.services.vision import interpret_spreadsheet, parse_page_image

logger = logging.getLogger(__name__)

# ──────────────────────────────────────
# Smart Chunking Pipeline
# ──────────────────────────────────────

_MAX_CHUNK_CHARS = 3000
_MIN_CHUNK_CHARS = 50

md_header_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=[
        ("#", "section"),
        ("##", "subsection"),
        ("###", "topic"),
    ],
    strip_headers=False,
)

_fallback_splitter = RecursiveCharacterTextSplitter(
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
    header_chunks = md_header_splitter.split_text(text)
    position_map: list[tuple[int, str]] = []
    search_start = 0
    for hchunk in header_chunks:
        header_path = " > ".join(
            hchunk.metadata[key]
            for key in ["section", "subsection", "topic"]
            if hchunk.metadata.get(key)
        )
        # Find where this chunk's content begins in the original text
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


def _make_semantic_chunker() -> SemanticChunker:
    """Factory: create a SemanticChunker per call (not thread-safe with lru_cache)."""
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
    # Build header map from markdown structure (works regardless of chunker used)
    try:
        header_map = _build_header_map(text)
    except Exception:
        header_map = []

    # ── Step 1: Attempt semantic chunking ──────────────────────────────────
    raw_chunks: list[Document] = []
    try:
        chunker = _make_semantic_chunker()
        raw_chunks = chunker.create_documents([text])
    except Exception as exc:
        logger.warning("SemanticChunker failed (%s), using fallback splitter", exc)

    # ── Step 2: Fallback if semantic chunking produced nothing ─────────────
    if not raw_chunks:
        raw_chunks = _fallback_splitter.create_documents(
            [text], metadatas=[{"source_filename": source}]
        )

    # ── Step 3: Cap oversized chunks ───────────────────────────────────────
    capped: list[Document] = []
    for chunk in raw_chunks:
        if len(chunk.page_content) > _MAX_CHUNK_CHARS:
            sub = _fallback_splitter.split_documents([chunk])
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

        # Determine header path by finding where this chunk starts in original text
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
        return _fallback_splitter.create_documents(
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

    # Identify header rows: first '|'-starting line and the immediately
    # following separator line (contains '---').
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

    # Group data lines into batches of _TABLE_SPLIT_ROWS (only count '|' lines)
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

    # ── Pass 1: merge incomplete table rows ───────────────────────────────
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
            i += 2  # skip the next chunk — it was consumed
        else:
            merged.append(current)
            i += 1

    # ── Pass 2: split large table chunks + tag metadata ───────────────────
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
# Metadata
# ──────────────────────────────────────

def _build_metadata(
    tenant_id: str,
    source_type: str,
    source_filename: str = "",
    doc_category: str = "general",
    url: str = "",
    download_link: str = "",
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "source_type": source_type,
        "source_filename": source_filename,
        "doc_category": doc_category,
        "url": url,
        "download_link": download_link,
    }


# ──────────────────────────────────────
# Legacy format conversion (.doc, .xls, .ppt → PDF)
# ──────────────────────────────────────

def _convert_to_pdf(file_bytes: bytes, src_ext: str) -> bytes:
    """Convert legacy formats to PDF using LibreOffice headless."""
    with tempfile.TemporaryDirectory() as tmpdir:
        src_path = os.path.join(tmpdir, f"input{src_ext}")
        with open(src_path, "wb") as f:
            f.write(file_bytes)

        result = subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", tmpdir, src_path],
            capture_output=True,
            timeout=settings.LIBREOFFICE_TIMEOUT,
        )
        if result.returncode != 0:
            logger.error("LibreOffice failed: %s", result.stderr.decode(errors="replace"))

        pdf_path = os.path.join(tmpdir, "input.pdf")
        if not os.path.exists(pdf_path):
            raise RuntimeError(f"LibreOffice conversion failed for {src_ext}")

        with open(pdf_path, "rb") as f:
            return f.read()


async def ingest_legacy(
    file_bytes: bytes,
    filename: str,
    namespace: str,
    tenant_id: str,
    skip_enrichment: bool = False,
    doc_category: str = "general",
    url: str = "",
    download_link: str = "",
) -> int:
    """Convert .doc/.xls/.ppt → PDF → Vision pipeline."""
    ext = os.path.splitext(filename)[1].lower()
    pdf_bytes = _convert_to_pdf(file_bytes, ext)
    return await ingest_pdf(
        file_bytes=pdf_bytes,
        filename=filename,
        namespace=namespace,
        tenant_id=tenant_id,
        skip_enrichment=skip_enrichment,
        doc_category=doc_category,
        url=url,
        download_link=download_link,
    )


# ──────────────────────────────────────
# Duplicate Detection: delete old vectors before re-ingest
# ──────────────────────────────────────

def _delete_existing_vectors(namespace: str, source_filename: str):
    """Delete all vectors with matching source_filename in the namespace."""
    try:
        index = get_raw_index()
        # Pinecone: delete by metadata filter
        index.delete(
            filter={"source_filename": source_filename},
            namespace=namespace,
        )
        logger.info("Deleted old vectors for '%s' in namespace '%s'", source_filename, namespace)
    except Exception:
        logger.warning("Could not delete old vectors for '%s' (may not exist)", source_filename)


# ──────────────────────────────────────
# PDF Ingestion (Hybrid: text extraction + Vision fallback)
# ──────────────────────────────────────

_VISION_THRESHOLD = settings.PDF_VISION_THRESHOLD
_PDF_BATCH_SIZE = settings.PDF_BATCH_SIZE


async def ingest_pdf(
    file_bytes: bytes,
    filename: str,
    namespace: str,
    tenant_id: str,
    skip_enrichment: bool = False,
    doc_category: str = "general",
    url: str = "",
    download_link: str = "",
) -> int:
    """
    Hybrid PDF ingestion:
    - Pages with enough text → PyMuPDF text extraction (fast, free)
    - Pages with little/no text (tables, forms, scanned) → Claude Vision (accurate)
    - Hidden hyperlinks extracted from all pages

    Handles: text, forms, slides, scanned, tables, diagrams, hidden hyperlinks.
    """
    _delete_existing_vectors(namespace, filename)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        doc = pymupdf.open(tmp_path)
        if doc.is_encrypted:
            logger.error("Password-protected PDF: %s", filename)
            return 0

        # Phase 1: Extract text + classify each page
        pages_data = []
        vision_pages = []
        for i, page in enumerate(doc):
            text = page.get_text("text").strip()
            hidden_links = _extract_hyperlinks(page)
            page_num = i + 1

            # Has tables? (PyMuPDF can detect table structures)
            has_tables = bool(page.find_tables().tables)

            if len(text) >= _VISION_THRESHOLD and not has_tables:
                # Enough text, no tables → use text extraction (fast)
                if hidden_links:
                    text += "\n\n**Links in this page:**\n" + "\n".join(
                        f"- [{t}]({u})" for t, u in hidden_links
                    )
                pages_data.append({"text": text, "page": page_num})
            else:
                # Low text or has tables → need Vision
                pix = page.get_pixmap(dpi=150)
                vision_pages.append({
                    "img_bytes": pix.tobytes("png"),
                    "links": hidden_links,
                    "page_num": page_num,
                })
        doc.close()

        # Phase 2: Process Vision pages in batches
        logger.info(
            "%s: %d text pages, %d vision pages",
            filename, len(pages_data), len(vision_pages),
        )
        for batch_start in range(0, len(vision_pages), _PDF_BATCH_SIZE):
            if batch_start > 0:
                await asyncio.sleep(2)  # Rate limit: pause between batches
            batch = vision_pages[batch_start:batch_start + _PDF_BATCH_SIZE]
            tasks = [_process_pdf_page(p) for p in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, dict) and result.get("text"):
                    pages_data.append(result)

        # Track vision calls
        if vision_pages:
            await usage.track(tenant_id, "vision_call", len(vision_pages))

        # Sort by page number
        pages_data.sort(key=lambda p: p["page"])
        page_texts = pages_data

        if not page_texts:
            return 0

        full_text = "\n\n---\n\n".join(p["text"] for p in page_texts)

        # Detect slides vs document
        avg_chars = len(full_text) / max(len(page_texts), 1)
        is_slides = len(page_texts) > 5 and avg_chars < 500

        if is_slides:
            chunks = _chunk_pages(page_texts, source=filename)
        else:
            chunks = _smart_chunk(full_text, source=filename)
            for chunk in chunks:
                if "page" not in chunk.metadata:
                    chunk.metadata["page"] = 1

        metadata = _build_metadata(
            tenant_id, "pdf", filename, doc_category, url, download_link
        )
        return await _upsert(chunks, namespace, metadata, full_text=full_text, skip_enrichment=skip_enrichment)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def _process_pdf_page(page_data: dict) -> dict:
    """Process a single PDF page: Vision + hyperlinks."""
    try:
        markdown = await parse_page_image(page_data["img_bytes"])
        if page_data["links"]:
            markdown += "\n\n**Links in this page:**\n" + "\n".join(
                f"- [{text}]({uri})" for text, uri in page_data["links"]
            )
        return {"text": markdown, "page": page_data["page_num"]}
    except Exception:
        logger.warning("Failed to process page %d", page_data["page_num"])
        return {"text": "", "page": page_data["page_num"]}


def _extract_hyperlinks(page) -> list[tuple[str, str]]:
    """Extract hidden hyperlinks from a PDF page (not visible as text)."""
    page_text = page.get_text("text")
    links = []
    for link in page.get_links():
        uri = link.get("uri", "")
        if not uri or uri in page_text:
            continue  # Skip if URI is already visible in text
        rect = link.get("from", pymupdf.Rect())
        text = page.get_text("text", clip=rect).strip() or uri
        links.append((text, uri))
    return links


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


# ──────────────────────────────────────
# DOCX Ingestion (paragraphs + tables + images)
# ──────────────────────────────────────

async def ingest_docx(
    file_bytes: bytes,
    filename: str,
    namespace: str,
    tenant_id: str,
    skip_enrichment: bool = False,
    doc_category: str = "general",
    url: str = "",
    download_link: str = "",
) -> int:
    """
    DOCX → extract paragraphs + tables + images → combined markdown → chunk → embed.
    No more missing tables or images.
    """
    _delete_existing_vectors(namespace, filename)

    doc = DocxDocument(io.BytesIO(file_bytes))

    parts = []

    # 1. Extract paragraphs
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            # Detect heading styles
            if para.style and para.style.name.startswith("Heading"):
                level = para.style.name.replace("Heading ", "")
                try:
                    hashes = "#" * int(level)
                except ValueError:
                    hashes = "##"
                parts.append(f"{hashes} {text}")
            else:
                parts.append(text)

    # 2. Extract tables → markdown tables
    for table in doc.tables:
        md_table = _docx_table_to_markdown(table)
        if md_table:
            parts.append(md_table)

    # 3. Extract images → Claude Vision
    vision_count = 0
    for rel in doc.part.rels.values():
        if "image" in rel.reltype:
            try:
                img_bytes = rel.target_part.blob
                caption = await parse_page_image(img_bytes)
                vision_count += 1
                if caption:
                    parts.append(f"[Image content: {caption}]")
            except Exception:
                logger.warning("Failed to extract image from DOCX '%s'", filename)

    if vision_count:
        await usage.track(tenant_id, "vision_call", vision_count)

    full_text = "\n\n".join(parts)
    chunks = _smart_chunk(full_text, source=filename)
    metadata = _build_metadata(
        tenant_id, "docx", filename, doc_category, url, download_link
    )
    return await _upsert(chunks, namespace, metadata, full_text=full_text, skip_enrichment=skip_enrichment)


def _docx_table_to_markdown(table) -> str:
    """Convert a python-docx table to markdown table."""
    rows = []
    for row in table.rows:
        cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
        rows.append(cells)

    if not rows:
        return ""

    # First row as header
    header = "| " + " | ".join(rows[0]) + " |"
    separator = "| " + " | ".join("---" for _ in rows[0]) + " |"
    body = "\n".join(
        "| " + " | ".join(row) + " |" for row in rows[1:]
    )
    return f"{header}\n{separator}\n{body}"


# ──────────────────────────────────────
# Markdown Ingestion (web content)
# ──────────────────────────────────────

async def ingest_markdown(
    content: str,
    title: str,
    namespace: str,
    tenant_id: str,
    skip_enrichment: bool = False,
    doc_category: str = "general",
    url: str = "",
    download_link: str = "",
) -> int:
    """Markdown content (from Jina Reader) → smart chunk → embed."""
    source_name = title or url or "web_content"
    _delete_existing_vectors(namespace, source_name)

    chunks = _smart_chunk(content, source=source_name)
    metadata = _build_metadata(
        tenant_id, "web", source_name, doc_category, url, download_link
    )
    return await _upsert(chunks, namespace, metadata, full_text=content, skip_enrichment=skip_enrichment)


# ──────────────────────────────────────
# Spreadsheet Ingestion (Claude interprets, batched for large sheets)
# ──────────────────────────────────────

_XLSX_BATCH_ROWS = settings.XLSX_BATCH_ROWS


async def ingest_spreadsheet(
    file_bytes: bytes,
    filename: str,
    namespace: str,
    tenant_id: str,
    skip_enrichment: bool = False,
    doc_category: str = "general",
    url: str = "",
    download_link: str = "",
) -> tuple[int, int]:
    """
    XLSX/CSV → raw dump → Claude interprets (batched for large sheets)
    → markdown → chunk → embed.
    """
    _delete_existing_vectors(namespace, filename)

    is_csv = filename.lower().endswith(".csv")
    total_chunks = 0

    if is_csv:
        df = pd.read_csv(io.BytesIO(file_bytes), header=None)
        structured, api_calls = await _interpret_dataframe(df)
        chunks = _smart_chunk(structured, source=filename)
        metadata = _build_metadata(
            tenant_id, "spreadsheet", filename, doc_category, url, download_link
        )
        total_chunks = await _upsert(chunks, namespace, metadata, full_text=structured, skip_enrichment=skip_enrichment)
        await usage.track(tenant_id, "vision_call", api_calls)
        return 1, total_chunks

    xls = pd.ExcelFile(io.BytesIO(file_bytes))
    sheets_processed = 0
    vision_calls = 0
    for sheet_name in xls.sheet_names:
        df = xls.parse(sheet_name, header=None)
        if df.dropna(how="all").empty:
            continue
        structured, api_calls = await _interpret_dataframe(df, sheet_name=sheet_name)
        vision_calls += api_calls
        chunks = _smart_chunk(structured, source=f"{filename} - {sheet_name}")
        metadata = _build_metadata(
            tenant_id, "spreadsheet", filename, doc_category, url, download_link
        )
        total_chunks += await _upsert(chunks, namespace, metadata, full_text=structured, skip_enrichment=skip_enrichment)
        sheets_processed += 1

    if vision_calls:
        await usage.track(tenant_id, "vision_call", vision_calls)

    return sheets_processed, total_chunks


async def _interpret_dataframe(df: pd.DataFrame, sheet_name: str = "") -> tuple[str, int]:
    """Send DataFrame to Claude in batches for large sheets. Returns (text, api_call_count)."""
    df_clean = df.dropna(how="all").dropna(axis=1, how="all")
    total_rows = len(df_clean)

    if total_rows <= _XLSX_BATCH_ROWS:
        # Small sheet: send all at once
        raw = _raw_dataframe_dump(df_clean)
        prefix = f"Sheet: {sheet_name}\n\n" if sheet_name else ""
        return await interpret_spreadsheet(f"{prefix}{raw}"), 1

    # Large sheet: process in batches
    parts = []
    for start in range(0, total_rows, _XLSX_BATCH_ROWS):
        batch = df_clean.iloc[start:start + _XLSX_BATCH_ROWS]
        raw = _raw_dataframe_dump(batch)
        prefix = f"Sheet: {sheet_name} (rows {start+1}-{start+len(batch)})\n\n"
        interpreted = await interpret_spreadsheet(f"{prefix}{raw}")
        parts.append(interpreted)

    return "\n\n".join(parts), len(parts)


def _raw_dataframe_dump(df: pd.DataFrame) -> str:
    """Dump raw cell data as readable text for Claude to interpret."""
    lines = []
    for i, row in df.iterrows():
        values = []
        for j, val in enumerate(row):
            if pd.notna(val):
                values.append(f"[{j}]={val}")
        if values:
            lines.append(f"Row {i}: {' | '.join(values)}")
    return "\n".join(lines)


# ──────────────────────────────────────
# Contextual Retrieval (Anthropic Research)
# ──────────────────────────────────────

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
    """Parse markdown headers to build section map with positions and text.

    Returns a list of dicts with keys: title, start, end, text.
    If no headers found, returns a single 'Document' section covering all text.
    """
    lines = text.splitlines(keepends=True)
    sections: list[dict] = []
    current_title: str | None = None
    current_start: int = 0
    pos: int = 0

    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("#"):
            # Detect markdown header (# Title, ## Subtitle, etc.)
            header_match = re.match(r"^(#+)\s+(.*)", stripped)
            if header_match:
                if current_title is not None:
                    # Close previous section
                    sections.append({
                        "title": current_title,
                        "start": current_start,
                        "end": pos,
                        "text": text[current_start:pos][:3000],
                    })
                current_title = header_match.group(2).strip()
                current_start = pos
        pos += len(line)

    # Close last section
    if current_title is not None:
        sections.append({
            "title": current_title,
            "start": current_start,
            "end": len(text),
            "text": text[current_start:len(text)][:3000],
        })

    # No headers found → single fallback section
    if not sections:
        return [{"title": "Document", "start": 0, "end": len(text), "text": text[:3000]}]

    return sections


def _find_section_for_chunk(sections: list[dict], chunk_text: str, full_text: str) -> dict:
    """Find which section a chunk belongs to by position matching.

    Locates the chunk in full_text, then returns the section whose start
    is <= the chunk position (reverse search for the last matching section).
    Falls back to the first section if the chunk is not found in full_text.
    """
    pos = full_text.find(chunk_text[:60]) if len(chunk_text) >= 60 else full_text.find(chunk_text)
    if pos == -1:
        return sections[0]

    # Walk backwards through sections to find the one that owns this position
    result = sections[0]
    for section in sections:
        if section["start"] <= pos:
            result = section
        else:
            break
    return result


async def _enrich_with_context(
    chunks: list[Document], full_text: str
) -> list[Document]:
    """Prepend section-level context to each chunk (~49% retrieval improvement).

    When the document has markdown headers, each chunk is enriched with
    context from its owning section. Otherwise, a global document context
    is used (first 4000 chars).
    """
    if not chunks:
        return chunks

    sections = _build_section_map(full_text)
    use_sections = len(sections) > 1 or sections[0]["title"] != "Document"

    llm = ChatAnthropic(
        model=settings.VISION_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        temperature=0,
        max_tokens=100,
        max_retries=3,
    )

    for i, chunk in enumerate(chunks):
        if i > 0 and i % 10 == 0:
            await asyncio.sleep(1)  # Rate limit: pause every 10 chunks
        try:
            if use_sections:
                section = _find_section_for_chunk(sections, chunk.page_content, full_text)
                prompt = _SECTION_CONTEXT_PROMPT.format(
                    section_title=section["title"],
                    section_text=section["text"],
                    chunk=chunk.page_content,
                )
            else:
                doc_summary = full_text[:4000]
                prompt = _GLOBAL_CONTEXT_PROMPT.format(
                    document=doc_summary,
                    chunk=chunk.page_content,
                )
            context = await llm.ainvoke(prompt)
            chunk.page_content = f"[{context.content.strip()}]\n{chunk.page_content}"
        except Exception:
            logger.warning("Failed to generate context for chunk, skipping")

    return chunks


# ──────────────────────────────────────
# Common: URL extraction + metadata + upsert
# ──────────────────────────────────────

_URL_PATTERN = re.compile(r'https?://[^\s\)\]\>"\']+')


async def _upsert(
    chunks: list[Document],
    namespace: str,
    extra_metadata: dict[str, Any],
    full_text: str = "",
    skip_enrichment: bool = False,
) -> int:
    """Contextual retrieval → URL extraction → metadata → upsert to Pinecone."""
    if full_text and not skip_enrichment:
        chunks = await _enrich_with_context(chunks, full_text)

    for chunk in chunks:
        chunk.metadata.update(extra_metadata)
        urls = _URL_PATTERN.findall(chunk.page_content)
        if urls:
            chunk.metadata["urls"] = urls

    vectorstore = get_vectorstore(namespace)
    await vectorstore.aadd_documents(chunks)

    # Invalidate BM25 cache — will be rebuilt from Pinecone on next search
    from shared.services.bm25_cache import invalidate_bm25_cache
    invalidate_bm25_cache(namespace)

    return len(chunks)
