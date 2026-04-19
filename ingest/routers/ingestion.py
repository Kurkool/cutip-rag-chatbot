"""Document ingestion endpoints — all routes use v2 Opus 4.7 universal pipeline."""

import asyncio
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from shared.schemas import (
    GDriveIngestRequest,
    GDriveIngestResult,
    GDriveSingleRequest,
    IngestResponse,
    IngestSpreadsheetResponse,
)
from ingest.services import ingestion_v2
from shared.services.auth import get_accessible_tenant
from shared.services.dependencies import fix_filename, validate_upload
from shared.services.rate_limit import ingestion_key_func, ingestion_limit, limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tenants/{tenant_id}/ingest", tags=["Ingestion"])

ALLOWED_DOC_EXTENSIONS = {".pdf", ".doc", ".docx"}
ALLOWED_SHEET_EXTENSIONS = {".xlsx", ".csv"}


# ──────────────────────────────────────
# File upload endpoints
# ──────────────────────────────────────

@router.post("/document", response_model=IngestResponse)
@limiter.limit(ingestion_limit, key_func=ingestion_key_func)
async def ingest_document(
    request: Request,
    file: UploadFile = File(...),
    doc_category: str = Form("general"),
    url: str = Form(""),
    download_link: str = Form(""),
    tenant: dict = Depends(get_accessible_tenant),
):
    """Ingest PDF / DOC / DOCX via v2 Opus pipeline."""
    file_bytes = await validate_upload(file, ALLOWED_DOC_EXTENSIONS)
    filename = fix_filename(file.filename or "unknown")
    namespace = tenant["pinecone_namespace"]

    chunks = await ingestion_v2.ingest_v2(
        file_bytes=file_bytes, filename=filename, namespace=namespace,
        tenant_id=tenant["tenant_id"], doc_category=doc_category,
        url=url, download_link=download_link,
    )
    return IngestResponse(
        message=f"Ingested '{filename}' into namespace '{namespace}'",
        chunks_processed=chunks,
    )


@router.post("/spreadsheet", response_model=IngestSpreadsheetResponse)
@limiter.limit(ingestion_limit, key_func=ingestion_key_func)
async def ingest_spreadsheet(
    request: Request,
    file: UploadFile = File(...),
    doc_category: str = Form("general"),
    url: str = Form(""),
    download_link: str = Form(""),
    tenant: dict = Depends(get_accessible_tenant),
):
    """Ingest XLSX / CSV via v2 Opus pipeline."""
    file_bytes = await validate_upload(file, ALLOWED_SHEET_EXTENSIONS)
    filename = fix_filename(file.filename or "unknown")
    namespace = tenant["pinecone_namespace"]

    chunks = await ingestion_v2.ingest_v2(
        file_bytes=file_bytes, filename=filename, namespace=namespace,
        tenant_id=tenant["tenant_id"], doc_category=doc_category,
        url=url, download_link=download_link,
    )
    return IngestSpreadsheetResponse(
        message=f"Ingested '{filename}' into namespace '{namespace}'",
        chunks_processed=chunks,
    )


# ──────────────────────────────────────
# Google Drive ingestion
# ──────────────────────────────────────

@router.post("/gdrive/file", response_model=IngestResponse)
@limiter.limit(ingestion_limit, key_func=ingestion_key_func)
async def ingest_gdrive_file(
    request: Request,
    body: GDriveSingleRequest,
    tenant: dict = Depends(get_accessible_tenant),
):
    """Ingest a single file from Google Drive (v2 pipeline)."""
    from ingest.services.gdrive import download_file, list_files

    namespace = tenant["pinecone_namespace"]
    files = list_files(body.folder_id)
    matched = [f for f in files if f["name"] == body.filename]
    if not matched:
        raise HTTPException(status_code=404, detail="File not found in Drive folder")

    drive_file = matched[0]
    file_bytes = download_file(drive_file["id"])
    drive_link = f"https://drive.google.com/file/d/{drive_file['id']}/view"

    chunks = await ingestion_v2.ingest_v2(
        file_bytes=file_bytes, filename=drive_file["name"], namespace=namespace,
        tenant_id=tenant["tenant_id"], doc_category=body.doc_category,
        download_link=drive_link,
    )
    return IngestResponse(
        message=f"Ingested '{drive_file['name']}' into namespace '{namespace}'",
        chunks_processed=chunks,
    )


@router.post("/gdrive", response_model=GDriveIngestResult)
@limiter.limit(ingestion_limit, key_func=ingestion_key_func)
async def ingest_gdrive_folder(
    request: Request,
    body: GDriveIngestRequest,
    tenant: dict = Depends(get_accessible_tenant),
):
    """Batch ingest ALL files from a Google Drive folder (v2 pipeline)."""
    return await _process_gdrive_folder(
        tenant, body.folder_id, body.doc_category, skip_existing=False,
    )


@router.post("/gdrive/scan", response_model=GDriveIngestResult)
@limiter.limit(ingestion_limit, key_func=ingestion_key_func)
async def scan_gdrive_folder(
    request: Request,
    body: GDriveIngestRequest,
    tenant: dict = Depends(get_accessible_tenant),
):
    """Smart scan: only NEW files from a Google Drive folder (for Cloud Scheduler)."""
    return await _process_gdrive_folder(
        tenant, body.folder_id, body.doc_category, skip_existing=True,
    )


# ──────────────────────────────────────
# v2 audit endpoints (namespace_override for Phase-1 audits)
# ──────────────────────────────────────

@router.post("/v2/gdrive", response_model=GDriveIngestResult)
@limiter.limit(ingestion_limit, key_func=ingestion_key_func)
async def ingest_gdrive_folder_v2(
    request: Request,
    body: GDriveIngestRequest,
    namespace_override: str | None = None,
    tenant: dict = Depends(get_accessible_tenant),
):
    """v2 batch ingest with optional namespace_override for audit runs.

    ``namespace_override`` is restricted to names ending with ``_v2_audit`` so
    that even an authenticated tenant-admin cannot accidentally write into
    another tenant's production namespace or an arbitrary name.
    """
    from ingest.services.gdrive import download_file, list_files

    if namespace_override is not None and not namespace_override.endswith("_v2_audit"):
        raise HTTPException(
            status_code=400,
            detail=(
                "namespace_override must end with '_v2_audit' "
                "(e.g. 'cutip_v2_audit'). This endpoint cannot be used to "
                "write into arbitrary namespaces."
            ),
        )

    namespace = namespace_override or tenant["pinecone_namespace"]
    tenant_id = tenant["tenant_id"]
    files = list_files(body.folder_id)
    if not files:
        return GDriveIngestResult(total_files=0, ingested=[], skipped=[], errors=[])

    ingested: list[dict] = []
    errors: list[dict] = []
    skipped: list[dict] = []

    for drive_file in files:
        filename = drive_file["name"]
        try:
            file_bytes = download_file(drive_file["id"])
            drive_link = f"https://drive.google.com/file/d/{drive_file['id']}/view"
            chunks = await ingestion_v2.ingest_v2(
                file_bytes=file_bytes, filename=filename, namespace=namespace,
                tenant_id=tenant_id, doc_category=body.doc_category,
                download_link=drive_link,
            )
            ingested.append({"filename": filename, "chunks": chunks})
            logger.info("v2 ingest '%s' (%d chunks) tenant=%s", filename, chunks, tenant_id)
            await asyncio.sleep(3)
        except ValueError as exc:
            skipped.append({"filename": filename, "reason": str(exc)})
        except Exception:
            logger.exception("v2 failed to ingest '%s'", filename)
            errors.append({"filename": filename, "error": "v2 ingestion failed"})

    if errors:
        logger.warning(
            "v2 gdrive batch partial: tenant=%s folder=%s total=%d ingested=%d skipped=%d failed=%d files=%s",
            tenant_id, body.folder_id, len(files), len(ingested), len(skipped), len(errors),
            [e["filename"] for e in errors],
        )

    return GDriveIngestResult(
        total_files=len(files), ingested=ingested, skipped=skipped, errors=errors,
    )


@router.post("/v2/gdrive/file", response_model=IngestResponse)
@limiter.limit(ingestion_limit, key_func=ingestion_key_func)
async def ingest_gdrive_file_v2(
    request: Request,
    body: GDriveSingleRequest,
    namespace_override: str | None = None,
    tenant: dict = Depends(get_accessible_tenant),
):
    """Single-file v2 ingest with optional namespace_override for audits."""
    from ingest.services.gdrive import download_file, list_files

    if namespace_override is not None and not namespace_override.endswith("_v2_audit"):
        raise HTTPException(
            status_code=400,
            detail="namespace_override must end with '_v2_audit'",
        )

    namespace = namespace_override or tenant["pinecone_namespace"]
    tenant_id = tenant["tenant_id"]

    files = list_files(body.folder_id)
    matched = [f for f in files if f["name"] == body.filename]
    if not matched:
        raise HTTPException(status_code=404, detail="File not found in Drive folder")

    drive_file = matched[0]
    file_bytes = download_file(drive_file["id"])
    drive_link = f"https://drive.google.com/file/d/{drive_file['id']}/view"

    chunks = await ingestion_v2.ingest_v2(
        file_bytes=file_bytes, filename=drive_file["name"], namespace=namespace,
        tenant_id=tenant_id, doc_category=body.doc_category,
        download_link=drive_link,
    )
    return IngestResponse(
        message=f"Ingested '{drive_file['name']}' into namespace '{namespace}'",
        chunks_processed=chunks,
    )


# ──────────────────────────────────────
# Helpers
# ──────────────────────────────────────

def _get_existing_filenames(namespace: str) -> set[str]:
    """Fetch all unique source_filenames in a namespace via Pinecone metadata."""
    from shared.services.vectorstore import get_unique_filenames
    return get_unique_filenames(namespace)


async def _process_gdrive_folder(
    tenant: dict, folder_id: str, doc_category: str, skip_existing: bool,
) -> GDriveIngestResult:
    """Core logic for batch/scan Drive ingestion — all files go through v2."""
    from ingest.services.gdrive import download_file, list_files

    namespace = tenant["pinecone_namespace"]
    tenant_id = tenant["tenant_id"]

    files = list_files(folder_id)
    if not files:
        return GDriveIngestResult(total_files=0, ingested=[], skipped=[], errors=[])

    existing = await asyncio.to_thread(_get_existing_filenames, namespace) if skip_existing else set()
    ingested, skipped, errors = [], [], []

    for drive_file in files:
        filename = drive_file["name"]

        if skip_existing and filename in existing:
            skipped.append({"filename": filename, "reason": "already ingested"})
            continue

        try:
            file_bytes = download_file(drive_file["id"])
            drive_link = f"https://drive.google.com/file/d/{drive_file['id']}/view"
            chunks = await ingestion_v2.ingest_v2(
                file_bytes=file_bytes, filename=filename, namespace=namespace,
                tenant_id=tenant_id, doc_category=doc_category,
                download_link=drive_link,
            )
            ingested.append({"filename": filename, "chunks": chunks})
            logger.info("Ingested '%s' (%d chunks) for tenant %s", filename, chunks, tenant_id)
            await asyncio.sleep(3)

        except ValueError as exc:
            skipped.append({"filename": filename, "reason": str(exc)})
        except Exception:
            logger.exception("Failed to ingest '%s'", filename)
            errors.append({"filename": filename, "error": "ingestion failed"})

    if errors:
        logger.warning(
            "gdrive batch partial: tenant=%s folder=%s total=%d ingested=%d skipped=%d failed=%d files=%s",
            tenant_id, folder_id, len(files), len(ingested), len(skipped), len(errors),
            [e["filename"] for e in errors],
        )

    return GDriveIngestResult(
        total_files=len(files), ingested=ingested, skipped=skipped, errors=errors,
    )
