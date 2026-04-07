import io
import logging
import os
import tempfile
from typing import Any

import pandas as pd
import pymupdf4llm
from docx import Document as DocxDocument
from langchain_anthropic import ChatAnthropic
from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from config import settings
from services.vectorstore import get_vectorstore

logger = logging.getLogger(__name__)

# ──────────────────────────────────────
# Smart Chunking Pipeline
# ──────────────────────────────────────

# Step 1: Split markdown by headers (preserves document structure)
md_header_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=[
        ("#", "section"),
        ("##", "subsection"),
        ("###", "topic"),
    ],
    strip_headers=False,
)

# Step 2: Split large sections into smaller chunks
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=settings.CHUNK_SIZE,
    chunk_overlap=settings.CHUNK_OVERLAP,
    separators=["\n\n", "\n", "。", ".", " ", ""],
)


def _smart_chunk(text: str, source: str = "") -> list[Document]:
    """
    Smart chunking pipeline:
    1. MarkdownHeaderTextSplitter → split by document structure (H1/H2/H3)
    2. RecursiveCharacterTextSplitter → split large sections
    3. Context enrichment → prepend section headers to each chunk
    """
    # Step 1: Split by headers
    header_chunks = md_header_splitter.split_text(text)

    if not header_chunks:
        # Fallback: no headers found, use plain recursive splitting
        return text_splitter.create_documents(
            [text], metadatas=[{"source": source}]
        )

    # Step 2: Split large sections
    final_chunks = text_splitter.split_documents(header_chunks)

    # Step 3: Context enrichment - prepend section path to each chunk
    for chunk in final_chunks:
        header_path = " > ".join(
            chunk.metadata[key]
            for key in ["section", "subsection", "topic"]
            if chunk.metadata.get(key)
        )
        if header_path and not chunk.page_content.startswith(header_path):
            chunk.page_content = f"[{header_path}]\n{chunk.page_content}"
        chunk.metadata["source"] = source

    return final_chunks


def _smart_chunk_pages(pages: list[dict], source: str = "") -> list[Document]:
    """
    Page-aware chunking for slides/presentations:
    - Merge consecutive short pages (< 100 chars)
    - Keep each meaningful page as its own chunk
    """
    chunks: list[Document] = []
    buffer = ""
    buffer_pages: list[int] = []

    for page in pages:
        text = page["text"].strip()
        page_num = page["page"]

        if not text:
            continue

        if len(text) < 100:
            # Short page → accumulate in buffer
            buffer += f"\n{text}" if buffer else text
            buffer_pages.append(page_num)
        else:
            # Flush buffer first
            if buffer:
                chunks.append(Document(
                    page_content=buffer,
                    metadata={"source": source, "pages": buffer_pages},
                ))
                buffer = ""
                buffer_pages = []

            # Process this page with smart chunking
            page_chunks = _smart_chunk(text, source)
            for c in page_chunks:
                c.metadata["page"] = page_num
            chunks.extend(page_chunks)

    # Flush remaining buffer
    if buffer:
        chunks.append(Document(
            page_content=buffer,
            metadata={"source": source, "pages": buffer_pages},
        ))

    return chunks


# ──────────────────────────────────────
# Metadata Builder
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
# Ingestion Functions
# ──────────────────────────────────────

async def ingest_pdf(
    file_bytes: bytes,
    filename: str,
    namespace: str,
    tenant_id: str,
    doc_category: str = "general",
    url: str = "",
    download_link: str = "",
) -> int:
    """
    PyMuPDF4LLM: PDF → clean Markdown (Thai/English perfect)
    → Smart chunking → Cohere embed-v4 → Pinecone
    """
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        # PyMuPDF4LLM: outputs markdown with table support
        pages = pymupdf4llm.to_markdown(
            tmp_path,
            page_chunks=True,  # return list of pages
        )

        # Detect: is this a slide deck (many short pages) or a document?
        avg_chars = sum(len(p["text"]) for p in pages) / max(len(pages), 1)
        is_slides = len(pages) > 5 and avg_chars < 400

        full_text = "\n\n".join(p["text"] for p in pages)

        if is_slides:
            chunks = _smart_chunk_pages(pages, source=filename)
        else:
            chunks = _smart_chunk(full_text, source=filename)
            for chunk in chunks:
                if "page" not in chunk.metadata:
                    chunk.metadata["page"] = 1

        metadata = _build_metadata(
            tenant_id, "pdf", filename, doc_category, url, download_link
        )
        return await _upsert(chunks, namespace, metadata, full_text=full_text)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def ingest_docx(
    file_bytes: bytes,
    filename: str,
    namespace: str,
    tenant_id: str,
    doc_category: str = "general",
    url: str = "",
    download_link: str = "",
) -> int:
    """Parse DOCX → smart chunk → embed → upsert"""
    doc = DocxDocument(io.BytesIO(file_bytes))

    # Extract text preserving paragraph structure
    paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
    full_text = "\n\n".join(paragraphs)

    chunks = _smart_chunk(full_text, source=filename)
    metadata = _build_metadata(
        tenant_id, "docx", filename, doc_category, url, download_link
    )
    return await _upsert(chunks, namespace, metadata, full_text=full_text)


async def ingest_markdown(
    content: str,
    title: str,
    namespace: str,
    tenant_id: str,
    doc_category: str = "general",
    url: str = "",
    download_link: str = "",
) -> int:
    """Ingest Markdown content (from Jina Reader) → smart chunk → embed → upsert"""
    source_name = title or url or "web_content"
    chunks = _smart_chunk(content, source=source_name)
    metadata = _build_metadata(
        tenant_id, "web", source_name, doc_category, url, download_link
    )
    return await _upsert(chunks, namespace, metadata, full_text=content)


async def ingest_spreadsheet(
    file_bytes: bytes,
    filename: str,
    namespace: str,
    tenant_id: str,
    doc_category: str = "general",
    url: str = "",
    download_link: str = "",
) -> tuple[int, int]:
    """
    XLSX/CSV → Clean merged cells → Markdown tables → chunk → embed → upsert
    """
    is_csv = filename.lower().endswith(".csv")
    total_chunks = 0

    if is_csv:
        df = pd.read_csv(io.BytesIO(file_bytes))
        df = _clean_dataframe(df)
        md_table = df.to_markdown(index=False)
        chunks = _smart_chunk(md_table, source=filename)
        metadata = _build_metadata(
            tenant_id, "spreadsheet", filename, doc_category, url, download_link
        )
        total_chunks = await _upsert(chunks, namespace, metadata, full_text=md_table)
        return 1, total_chunks

    # XLSX: process each sheet
    xls = pd.ExcelFile(io.BytesIO(file_bytes))
    sheets_processed = 0
    for sheet_name in xls.sheet_names:
        df = xls.parse(sheet_name)
        df = _clean_dataframe(df)
        if df.empty:
            continue
        md_table = f"## {sheet_name}\n\n{df.to_markdown(index=False)}"
        chunks = _smart_chunk(md_table, source=f"{filename} - {sheet_name}")
        metadata = _build_metadata(
            tenant_id, "spreadsheet", filename, doc_category, url, download_link
        )
        total_chunks += await _upsert(chunks, namespace, metadata, full_text=md_table)
        sheets_processed += 1

    return sheets_processed, total_chunks


def _clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Clean messy spreadsheets: drop empty rows/cols, forward-fill merged cells"""
    df = df.dropna(how="all")  # drop fully empty rows
    df = df.dropna(axis=1, how="all")  # drop fully empty columns
    df = df.ffill()  # forward-fill merged cells
    # Clean column names
    df.columns = [
        str(c).strip() if not str(c).startswith("Unnamed") else ""
        for c in df.columns
    ]
    return df


# ──────────────────────────────────────
# Contextual Retrieval (Anthropic Research)
# ──────────────────────────────────────

_CONTEXT_PROMPT = (
    "Here is the full document:\n<document>\n{document}\n</document>\n\n"
    "Here is a specific chunk from that document:\n<chunk>\n{chunk}\n</chunk>\n\n"
    "Write a short 1-2 sentence context in the SAME LANGUAGE as the document "
    "that explains where this chunk fits within the document. "
    "Include the document topic, section name, and what this chunk is about. "
    "Reply with ONLY the context, nothing else."
)


async def _enrich_with_context(
    chunks: list[Document], full_text: str
) -> list[Document]:
    """
    Contextual Retrieval: ask Claude to generate a short context for each chunk,
    then prepend it. This dramatically improves search relevance (~49% per Anthropic).
    """
    if not chunks:
        return chunks

    # Truncate full document to avoid token limits (keep first 6000 chars)
    doc_summary = full_text[:6000]

    llm = ChatAnthropic(
        model="claude-haiku-4-5-20251001",  # Fast + cheap for context generation
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        temperature=0,
        max_tokens=150,
    )

    for chunk in chunks:
        try:
            context = await llm.ainvoke(
                _CONTEXT_PROMPT.format(document=doc_summary, chunk=chunk.page_content)
            )
            chunk.page_content = f"[{context.content.strip()}]\n{chunk.page_content}"
        except Exception:
            logger.warning("Failed to generate context for chunk, skipping enrichment")

    return chunks


# ──────────────────────────────────────
# Common: Attach metadata + Upsert
# ──────────────────────────────────────

async def _upsert(
    chunks: list[Document],
    namespace: str,
    extra_metadata: dict[str, Any],
    full_text: str = "",
) -> int:
    """Enrich chunks with contextual retrieval, attach metadata, upsert to Pinecone."""
    # Contextual Retrieval: prepend document context to each chunk
    if full_text:
        chunks = await _enrich_with_context(chunks, full_text)

    for chunk in chunks:
        chunk.metadata.update(extra_metadata)

    vectorstore = get_vectorstore(namespace)
    await vectorstore.aadd_documents(chunks)
    return len(chunks)
