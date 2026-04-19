"""Ingestion helpers reused by v2 pipeline: metadata builder, LibreOffice PDF conversion,
Pinecone upsert with atomic older-than-ts dedup.

The format-specific v1 pipelines (ingest_pdf, ingest_docx, ingest_spreadsheet, etc.)
were removed on 2026-04-19 — v2 Opus 4.7 universal parse+chunk handles every format
through `ingestion_v2.py::ingest_v2`. See the `legacy` branch for v1 history.
"""

import asyncio
import logging
import os
import re
import subprocess
import tempfile
import time
from typing import Any

from langchain_core.documents import Document

from shared.config import settings
from shared.services.vectorstore import (
    PINECONE_PAGE_SIZE,
    get_raw_index,
    get_vectorstore,
    list_all_vector_ids,
)

logger = logging.getLogger(__name__)

_URL_PATTERN = re.compile(r'https?://[^\s\)\]\>"\']+')


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
    drive_file_id: str = "",
) -> dict[str, Any]:
    """Chunk metadata stamp.

    ``drive_file_id`` stores the stable Drive file ID so admin delete can
    remove the file even after a rename — name-based lookup would miss
    renamed files. Empty string when ingest isn't Drive-backed (unused today).
    """
    meta = {
        "tenant_id": tenant_id,
        "source_type": source_type,
        "source_filename": source_filename,
        "doc_category": doc_category,
        "url": url,
        "download_link": download_link,
    }
    if drive_file_id:
        meta["drive_file_id"] = drive_file_id
    return meta


# ──────────────────────────────────────
# LibreOffice conversion (any non-PDF → PDF)
# ──────────────────────────────────────

def _convert_to_pdf(file_bytes: bytes, src_ext: str) -> bytes:
    """Convert any supported format to PDF using LibreOffice headless.

    Supported extensions: .doc, .docx, .xls, .xlsx, .ppt, .pptx, .csv (anything
    LibreOffice can open). Thai fonts are installed in the ingest-worker
    container (``fonts-thai-tlwg``) so Thai text renders correctly.
    """
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


# ──────────────────────────────────────
# Pinecone vector dedup
# ──────────────────────────────────────

def _delete_existing_vectors(
    namespace: str,
    source_filename: str,
    older_than_ts: float | None = None,
) -> int:
    """Delete vectors matching ``source_filename`` in the namespace.

    When ``older_than_ts`` is supplied, only vectors whose ``ingest_ts``
    metadata is strictly less than it are deleted — used by ``_upsert`` to
    dedup OLD copies after a fresh upsert has already landed (atomic swap:
    new vectors survive even if the delete is interrupted). When omitted,
    every matching vector is deleted (legacy behaviour retained for
    administrative wipes).

    Pinecone serverless does not support metadata-filter delete, so we list
    IDs + fetch metadata + delete by ID in batches.
    """
    ids = list_all_vector_ids(namespace)
    if not ids:
        return 0

    index = get_raw_index()
    deleted = 0
    for i in range(0, len(ids), PINECONE_PAGE_SIZE):
        batch = ids[i:i + PINECONE_PAGE_SIZE]
        fetched = index.fetch(ids=batch, namespace=namespace)
        matching: list[str] = []
        for vid, vec in fetched.vectors.items():
            meta = vec.metadata or {}
            if meta.get("source_filename") != source_filename:
                continue
            if older_than_ts is not None:
                # Keep vectors at or newer than this timestamp (the ones we
                # just upserted). Missing/zero ingest_ts counts as old.
                vec_ts = meta.get("ingest_ts", 0) or 0
                if vec_ts >= older_than_ts:
                    continue
            matching.append(vid)
        if matching:
            index.delete(ids=matching, namespace=namespace)
            deleted += len(matching)

    if deleted:
        logger.info(
            "Dedup: deleted %d old vectors for '%s' in namespace '%s'",
            deleted, source_filename, namespace,
        )
    return deleted


# ──────────────────────────────────────
# Atomic upsert (used by v2 ingest_v2)
# ──────────────────────────────────────

async def _upsert(
    chunks: list[Document],
    namespace: str,
    extra_metadata: dict[str, Any],
) -> int:
    """Upsert chunks to Pinecone with atomic older-than-ts dedup.

    Atomic swap: new vectors are upserted FIRST; only after they land do we
    delete older copies of the same ``source_filename``. If anything before
    or during upsert fails, old vectors survive and the doc remains
    searchable. Previously delete-first meant a failed upsert = data loss
    (e.g. ``slide.pdf`` vanishing during a Cloud Run timeout on 2026-04-17).
    """
    # Stamp each chunk with a monotonically-increasing ingest timestamp so
    # dedup can distinguish "just-upserted" vectors from prior generations.
    ingest_ts = time.time()
    for chunk in chunks:
        chunk.metadata.update(extra_metadata)
        chunk.metadata["ingest_ts"] = ingest_ts
        urls = _URL_PATTERN.findall(chunk.page_content)
        if urls:
            # Pinecone caps metadata at 40KB per vector. A page with many
            # footnote URLs can exceed that and cause a silent upsert failure.
            # Cap at 20 URLs (well below the limit for typical URL lengths).
            chunk.metadata["urls"] = urls[:20]

    vectorstore = get_vectorstore(namespace)
    await vectorstore.aadd_documents(chunks)

    # NEW vectors are now live. Dedup OLD copies of the same source_filename
    # (strictly older ingest_ts). If this step fails or is interrupted, the
    # worst case is a brief window of duplicate results — not data loss.
    source_filename = extra_metadata.get("source_filename", "")
    if source_filename:
        await asyncio.to_thread(
            _delete_existing_vectors,
            namespace, source_filename, older_than_ts=ingest_ts,
        )

    # Two-tier BM25 invalidation:
    #   1. Local (same-process) — drops this worker's cache if it happens to
    #      hold a stale copy. No-op on first ingest after cold start.
    from shared.services.bm25_cache import invalidate_bm25_cache
    invalidate_bm25_cache(namespace)

    #   2. Cross-process — bump tenant.bm25_invalidate_ts so chat-api
    #      (running in a DIFFERENT container) notices on next request and
    #      re-warms its own BM25 cache. Without this, chat keeps stale
    #      results until the container cycles (hours/days).
    tenant_id = extra_metadata.get("tenant_id", "")
    if tenant_id:
        from shared.services import firestore as firestore_service
        try:
            await firestore_service.bump_bm25_invalidate_ts(tenant_id)
        except Exception:
            logger.warning(
                "Failed to bump bm25_invalidate_ts for tenant %s", tenant_id,
                exc_info=True,
            )

    return len(chunks)
