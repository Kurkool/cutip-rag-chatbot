"""Document ingestion endpoints (PDF, DOCX, Markdown, XLSX/CSV, Google Drive)."""

import asyncio
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from schemas import IngestMarkdownRequest, IngestResponse, IngestSpreadsheetResponse
from services import ingestion as ingestion_service
from services.dependencies import fix_filename, get_tenant_or_404, parse_file_extension

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tenants/{tenant_id}/ingest", tags=["Ingestion"])

ALLOWED_DOC_EXTENSIONS = {".pdf", ".doc", ".docx"}
LEGACY_EXTENSIONS = {".doc", ".xls", ".ppt"}
ALLOWED_SHEET_EXTENSIONS = {".xlsx", ".csv"}


@router.post("/document", response_model=IngestResponse)
async def ingest_document(
    tenant_id: str,
    file: UploadFile = File(...),
    doc_category: str = Form("general"),
    url: str = Form(""),
    download_link: str = Form(""),
):
    """Ingest PDF / DOC / DOCX with metadata (called by n8n or admin)."""
    tenant = await get_tenant_or_404(tenant_id)
    filename = fix_filename(file.filename or "unknown")
    ext = parse_file_extension(filename)

    if ext not in ALLOWED_DOC_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Supported formats: {', '.join(sorted(ALLOWED_DOC_EXTENSIONS))}",
        )

    file_bytes = await file.read()
    namespace = tenant["pinecone_namespace"]
    kwargs = dict(
        file_bytes=file_bytes,
        filename=filename,
        namespace=namespace,
        tenant_id=tenant_id,
        doc_category=doc_category,
        url=url,
        download_link=download_link,
    )

    if ext == ".pdf":
        chunks = await ingestion_service.ingest_pdf(**kwargs)
    elif ext in LEGACY_EXTENSIONS:
        chunks = await ingestion_service.ingest_legacy(**kwargs)
    else:
        chunks = await ingestion_service.ingest_docx(**kwargs)

    return IngestResponse(
        message=f"Ingested '{filename}' into namespace '{namespace}'",
        chunks_processed=chunks,
    )


@router.post("/markdown", response_model=IngestResponse)
async def ingest_markdown(tenant_id: str, body: IngestMarkdownRequest):
    """Ingest Markdown content (from n8n + Jina Reader)."""
    tenant = await get_tenant_or_404(tenant_id)
    namespace = tenant["pinecone_namespace"]

    chunks = await ingestion_service.ingest_markdown(
        content=body.content,
        title=body.title,
        namespace=namespace,
        tenant_id=tenant_id,
        doc_category=body.metadata.doc_category,
        url=body.metadata.url,
        download_link=body.metadata.download_link,
    )

    title = body.title or "web content"
    return IngestResponse(
        message=f"Ingested '{title}' into namespace '{namespace}'",
        chunks_processed=chunks,
    )


@router.post("/spreadsheet", response_model=IngestSpreadsheetResponse)
async def ingest_spreadsheet(
    tenant_id: str,
    file: UploadFile = File(...),
    doc_category: str = Form("general"),
    url: str = Form(""),
    download_link: str = Form(""),
):
    """Ingest XLSX / CSV → Markdown tables."""
    tenant = await get_tenant_or_404(tenant_id)
    filename = fix_filename(file.filename or "unknown")
    ext = parse_file_extension(filename)

    if ext not in ALLOWED_SHEET_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Supported formats: {', '.join(sorted(ALLOWED_SHEET_EXTENSIONS))}",
        )

    file_bytes = await file.read()
    namespace = tenant["pinecone_namespace"]

    sheets, chunks = await ingestion_service.ingest_spreadsheet(
        file_bytes=file_bytes,
        filename=filename,
        namespace=namespace,
        tenant_id=tenant_id,
        doc_category=doc_category,
        url=url,
        download_link=download_link,
    )

    return IngestSpreadsheetResponse(
        message=f"Ingested '{filename}' into namespace '{namespace}'",
        sheets_processed=sheets,
        chunks_processed=chunks,
    )


# ──────────────────────────────────────
# Google Drive Ingestion
# ──────────────────────────────────────

class GDriveIngestRequest(BaseModel):
    folder_id: str
    doc_category: str = "general"


class GDriveIngestResult(BaseModel):
    total_files: int
    ingested: list[dict]
    skipped: list[dict]
    errors: list[dict]


@router.post("/gdrive", response_model=GDriveIngestResult)
async def ingest_gdrive_folder(tenant_id: str, body: GDriveIngestRequest):
    """
    Batch: ingest ALL supported files from a Google Drive folder.
    Supported: PDF, DOCX, XLSX, CSV.
    """
    tenant = await get_tenant_or_404(tenant_id)
    return await _process_gdrive_folder(
        tenant, body.folder_id, body.doc_category, skip_existing=False,
    )


@router.post("/gdrive/scan", response_model=GDriveIngestResult)
async def scan_gdrive_folder(tenant_id: str, body: GDriveIngestRequest):
    """
    Smart: ingest only NEW files from a Google Drive folder.
    Skips files already ingested (by filename match).
    Use this for scheduled auto-ingest (Cloud Scheduler).
    """
    tenant = await get_tenant_or_404(tenant_id)
    return await _process_gdrive_folder(
        tenant, body.folder_id, body.doc_category, skip_existing=True,
    )


async def _process_gdrive_folder(
    tenant: dict, folder_id: str, doc_category: str, skip_existing: bool,
) -> GDriveIngestResult:
    from services.gdrive import download_file, get_file_type, list_files
    from services.vectorstore import get_vectorstore

    namespace = tenant["pinecone_namespace"]
    tenant_id = tenant["tenant_id"]

    # List files in Drive folder
    files = list_files(folder_id)
    if not files:
        return GDriveIngestResult(total_files=0, ingested=[], skipped=[], errors=[])

    # Get existing filenames to skip duplicates
    existing_filenames: set[str] = set()
    if skip_existing:
        vs = get_vectorstore(namespace)
        existing_docs = vs.similarity_search("document", k=100)
        for doc in existing_docs:
            fn = doc.metadata.get("source_filename", "")
            if fn:
                existing_filenames.add(fn)

    ingested = []
    skipped = []
    errors = []

    for f in files:
        filename = f["name"]
        file_type = get_file_type(f["mimeType"])

        # Skip existing?
        if skip_existing and filename in existing_filenames:
            skipped.append({"filename": filename, "reason": "already ingested"})
            continue

        try:
            file_bytes = download_file(f["id"])
            kwargs = dict(
                file_bytes=file_bytes,
                filename=filename,
                namespace=namespace,
                tenant_id=tenant_id,
                doc_category=doc_category,
            )

            # Skip contextual retrieval during batch to avoid rate limits
            kwargs["skip_enrichment"] = True

            if file_type == "pdf":
                chunks = await ingestion_service.ingest_pdf(**kwargs)
            elif file_type == "docx":
                chunks = await ingestion_service.ingest_docx(**kwargs)
            elif file_type in ("doc", "xls"):
                chunks = await ingestion_service.ingest_legacy(**kwargs)
            elif file_type in ("xlsx", "csv"):
                _, chunks = await ingestion_service.ingest_spreadsheet(**kwargs)
            else:
                skipped.append({"filename": filename, "reason": f"unsupported type: {file_type}"})
                continue

            ingested.append({"filename": filename, "chunks": chunks})
            logger.info("Ingested '%s' (%d chunks) for tenant %s", filename, chunks, tenant_id)

            # Rate limit: pause between files to avoid 429
            await asyncio.sleep(3)

        except Exception as e:
            logger.exception("Failed to ingest '%s'", filename)
            errors.append({"filename": filename, "error": str(e)})

    return GDriveIngestResult(
        total_files=len(files),
        ingested=ingested,
        skipped=skipped,
        errors=errors,
    )
