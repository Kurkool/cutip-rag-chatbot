"""Document ingestion endpoints — all routes use v2 Opus 4.7 universal pipeline."""

import asyncio
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from shared.schemas import (
    GDriveIngestRequest,
    GDriveIngestResult,
    GDriveSingleRequest,
    IngestResponse,
)
from ingest.services import ingestion_v2
from shared.services import ingest_failures
from shared.services.auth import get_accessible_tenant
from shared.services.dependencies import fix_filename, validate_upload
from shared.services.rate_limit import ingestion_key_func, ingestion_limit, limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tenants/{tenant_id}/ingest", tags=["Ingestion"])

ALLOWED_DOC_EXTENSIONS = {".pdf", ".doc", ".docx"}
ALLOWED_SHEET_EXTENSIONS = {".xlsx", ".csv"}


# ──────────────────────────────────────
# Stage upload — admin portal uploads → Drive → ingest with citation
# ──────────────────────────────────────
# The old /document and /spreadsheet direct-ingest handlers were removed on
# 2026-04-20 because they produced chunks without a download_link → chat
# citations couldn't resolve to a clickable URL. Admin portal now uploads
# exclusively through /stage (Drive → ingest_v2 with webViewLink).

@router.post("/stage", response_model=IngestResponse)
@limiter.limit(ingestion_limit, key_func=ingestion_key_func)
async def stage_document(
    request: Request,
    file: UploadFile = File(...),
    doc_category: str = Form("general"),
    tenant: dict = Depends(get_accessible_tenant),
):
    """Upload a file to the tenant's connected Drive folder, then ingest it.

    The staging flow exists because direct ingestion via /document or
    /spreadsheet leaves chunks with empty download_link → chat citations
    can't resolve to a clickable URL. By uploading to Drive first and using
    the Drive webViewLink as download_link, admin-uploaded files become
    citable just like Drive-synced files.

    Requires the tenant's ``drive_folder_id`` to be set (via /gdrive/connect)
    and the service account to have Editor role on that folder.
    """
    from shared.services.gdrive import upload_file

    if not tenant.get("drive_folder_id"):
        raise HTTPException(
            status_code=400,
            detail=(
                "Tenant has no connected Drive folder. Ask an admin to "
                "connect Google Drive in the admin portal first."
            ),
        )

    allowed = ALLOWED_DOC_EXTENSIONS | ALLOWED_SHEET_EXTENSIONS
    file_bytes = await validate_upload(file, allowed)
    filename = fix_filename(file.filename or "unknown")
    namespace = tenant["pinecone_namespace"]
    mime_type = file.content_type or "application/octet-stream"

    try:
        drive_result = await asyncio.to_thread(
            upload_file, file_bytes, filename,
            tenant["drive_folder_id"], mime_type,
        )
    except Exception as exc:
        logger.exception("Drive stage upload failed for '%s'", filename)
        raise HTTPException(
            status_code=500,
            detail=(
                f"Failed to stage '{filename}' to Drive: {exc}. "
                "The service account may not have Editor role on the folder — "
                "re-run Connect from the admin portal."
            ),
        )

    drive_link = drive_result.get("webViewLink", "")
    drive_id = drive_result.get("id", "")
    logger.info(
        "Staged '%s' to Drive (file_id=%s) for tenant %s",
        filename, drive_id, tenant["tenant_id"],
    )

    # Ingest the bytes we already have; no need to re-download from Drive.
    chunks = await ingestion_v2.ingest_v2(
        file_bytes=file_bytes,
        filename=filename,
        namespace=namespace,
        tenant_id=tenant["tenant_id"],
        doc_category=doc_category,
        download_link=drive_link,
        drive_file_id=drive_id,
    )
    return IngestResponse(
        message=f"Staged '{filename}' to Drive and ingested {chunks} chunks",
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
    from shared.services.gdrive import download_file, list_files

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
        download_link=drive_link, drive_file_id=drive_file["id"],
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
    from shared.services.gdrive import download_file, list_files

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
                download_link=drive_link, drive_file_id=drive_file["id"],
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
    from shared.services.gdrive import download_file, list_files

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
        download_link=drive_link, drive_file_id=drive_file["id"],
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


def _iso_to_unix(iso_str: str) -> float:
    """Parse Drive's RFC3339 ``modifiedTime`` (e.g. ``2026-04-20T10:00:00.000Z``)
    into a Unix timestamp for comparison with Pinecone ``ingest_ts``.
    Returns 0.0 on parse failure (conservative: will trigger re-ingest).
    """
    if not iso_str:
        return 0.0
    from datetime import datetime
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


async def _process_gdrive_folder(
    tenant: dict, folder_id: str, doc_category: str, skip_existing: bool,
) -> GDriveIngestResult:
    """Core logic for batch/scan Drive ingestion — all files go through v2.

    When ``skip_existing`` is True (Smart Scan / scheduler), compares Drive
    state against Pinecone per drive_file_id:

      * NEW — drive_file_id not seen before → ingest
      * RENAME — same id, different Drive name → delete old vectors + re-ingest
      * OVERWRITE — same id, same name, Drive ``modifiedTime`` > ``ingest_ts`` → re-ingest
      * SKIP — same id, same name, Drive not newer → no-op

    Legacy chunks (no drive_file_id, ingested pre 2026-04-20) fall back to
    filename-based skip.
    """
    from shared.services.gdrive import download_file, list_files
    from shared.services.vectorstore import get_existing_drive_state, delete_vectors_by_filename

    namespace = tenant["pinecone_namespace"]
    tenant_id = tenant["tenant_id"]

    files = list_files(folder_id)
    if not files:
        return GDriveIngestResult(total_files=0, ingested=[], skipped=[], errors=[])

    # Build existing state from Pinecone + failures from Firestore (parallel when skip_existing)
    if skip_existing:
        drive_state, legacy_filenames, failures = await asyncio.gather(
            asyncio.to_thread(get_existing_drive_state, namespace),
            asyncio.to_thread(_get_existing_filenames, namespace),
            ingest_failures.list_failures(tenant_id),
        )
        state_filenames = {v["filename"] for v in drive_state.values()}
        legacy_only = legacy_filenames - state_filenames
    else:
        drive_state, legacy_only, failures = {}, set(), {}

    ingested, skipped, errors = [], [], []

    for drive_file in files:
        drive_id = drive_file["id"]
        filename = drive_file["name"]
        drive_modified = _iso_to_unix(drive_file.get("modifiedTime", ""))
        stale_filename_to_delete: str | None = None

        if skip_existing:
            entry = drive_state.get(drive_id)

            # 1. SKIP up-to-date — opportunistic clear of any stale failure doc.
            if entry is not None and entry["filename"] == filename and drive_modified <= entry["ingest_ts"]:
                await ingest_failures.clear_failure(tenant_id, drive_id)
                skipped.append({"filename": filename, "reason": "up to date"})
                continue

            # 2. LEGACY (no drive_file_id yet) — preserve existing behavior.
            if entry is None and filename in legacy_only:
                skipped.append({"filename": filename, "reason": "legacy, no drive_file_id"})
                continue

            # 3. FAIL_COOLDOWN — stop hammer before any expensive work.
            fail_rec = failures.get(drive_id)
            if (fail_rec
                    and fail_rec.get("fail_count", 0) >= ingest_failures.MAX_CONSECUTIVE_FAILURES
                    and drive_modified <= fail_rec.get("last_drive_modified", 0.0)):
                skipped.append({
                    "filename": filename,
                    "reason": (
                        f"cooldown: {fail_rec.get('fail_count', '?')} consecutive failures — "
                        "edit the file in Drive to retry"
                    ),
                })
                logger.info(
                    "scan-all: FAIL_COOLDOWN skip tenant=%s drive_id=%s filename=%r fail_count=%s",
                    tenant_id, drive_id, filename, fail_rec.get("fail_count"),
                )
                continue

            # 4. RENAME — mark old chunks for deletion, fall through to ingest.
            if entry is not None and entry["filename"] != filename:
                stale_filename_to_delete = entry["filename"]
                logger.info(
                    "Drive rename detected (tenant=%s): %r → %r",
                    tenant_id, entry["filename"], filename,
                )

            # else: OVERWRITE (entry + newer mtime) — fall through.
            # else: NEW (no entry, no legacy) — fall through.

        try:
            # RENAME cleanup first so dangling chunks don't linger
            if stale_filename_to_delete:
                await asyncio.to_thread(
                    delete_vectors_by_filename, namespace, stale_filename_to_delete,
                )

            file_bytes = download_file(drive_id)
            drive_link = f"https://drive.google.com/file/d/{drive_id}/view"
            chunks = await ingestion_v2.ingest_v2(
                file_bytes=file_bytes, filename=filename, namespace=namespace,
                tenant_id=tenant_id, doc_category=doc_category,
                download_link=drive_link, drive_file_id=drive_id,
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
