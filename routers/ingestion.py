"""Document ingestion endpoints (PDF, DOCX, Markdown, XLSX/CSV)."""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from schemas import IngestMarkdownRequest, IngestResponse, IngestSpreadsheetResponse
from services import ingestion as ingestion_service
from services.dependencies import fix_filename, get_tenant_or_404, parse_file_extension

router = APIRouter(prefix="/api/tenants/{tenant_id}/ingest", tags=["Ingestion"])

ALLOWED_DOC_EXTENSIONS = {".pdf", ".doc", ".docx"}
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
