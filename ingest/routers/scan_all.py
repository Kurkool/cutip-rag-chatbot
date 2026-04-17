"""Cross-tenant scan-all endpoint for the hourly auto-ingest scheduler.

One scheduler job hits this endpoint instead of one job per tenant. It
iterates active tenants that have ``drive_folder_id`` set, runs the
existing scan-only-new logic for each, and aggregates results. Tenants
without a drive_folder_id are explicitly skipped — this is the opt-out
signal for tenants that self-manage their ingest.
"""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends

from shared.schemas import ScanAllResult
from shared.services import firestore as firestore_service
from shared.services.auth import require_super_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingest", tags=["Ingestion"])


@router.post("/scan-all", response_model=ScanAllResult)
async def scan_all_tenants(
    _admin: dict[str, Any] = Depends(require_super_admin),
) -> ScanAllResult:
    """For each active tenant with drive_folder_id set, scan for new Drive files.

    Auth: super_admin (via Firebase Bearer token) OR X-API-Key from scheduler.
    Skip-existing logic lives in ``_process_gdrive_folder`` — docs already in
    Pinecone for that namespace are not re-ingested.

    This endpoint is intentionally serial (tenant-by-tenant) rather than
    parallel — Anthropic/Cohere rate limits are per-account, not per-tenant,
    so parallelizing would just move the 429 wall to here. Cloud Run 3600s
    timeout is enough for ~10 active tenants at current doc counts.
    """
    # Lazy import so router file stays lightweight at module-load time
    from ingest.routers.ingestion import _process_gdrive_folder

    tenants = await firestore_service.list_tenants()
    processed: list[dict] = []
    skipped: list[dict] = []
    errored: list[dict] = []

    for tenant in tenants:
        tid = tenant.get("tenant_id", "")
        if not tenant.get("is_active", False):
            skipped.append({"tenant_id": tid, "reason": "inactive"})
            continue
        folder_id = tenant.get("drive_folder_id", "") or ""
        if not folder_id:
            skipped.append({"tenant_id": tid, "reason": "no drive_folder_id"})
            continue

        try:
            result = await _process_gdrive_folder(
                tenant, folder_id, doc_category="general", skip_existing=True,
            )
            processed.append({
                "tenant_id": tid,
                "total_files": result.total_files,
                "ingested": len(result.ingested),
                "skipped": len(result.skipped),
                "errors": len(result.errors),
            })
            logger.info(
                "scan-all tenant=%s total=%d ingested=%d skipped=%d errors=%d",
                tid, result.total_files, len(result.ingested),
                len(result.skipped), len(result.errors),
            )
        except Exception as exc:
            logger.exception("scan-all failed for tenant=%s", tid)
            # Include truncated message so scheduler-alert readers can
            # distinguish "auth failed" from "folder not found" etc. without
            # cross-referencing Cloud Logging timestamps. Truncated to 200
            # chars so a multi-KB stack string can't bloat the response.
            errored.append({
                "tenant_id": tid,
                "error": type(exc).__name__,
                "message": str(exc)[:200],
            })

    if errored:
        logger.warning(
            "scan-all partial: total=%d processed=%d skipped=%d errored=%d",
            len(tenants), len(processed), len(skipped), len(errored),
        )

    return ScanAllResult(
        total_tenants=len(tenants),
        processed=processed,
        skipped_tenants=skipped,
        errored_tenants=errored,
    )
