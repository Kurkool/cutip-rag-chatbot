"""Analytics, chat logs, and vector management endpoints."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger(__name__)

from shared.schemas import AnalyticsResponse, ChatLogEntry
from shared.services import firestore as firestore_service
from shared.services import usage as usage_service
from shared.services.auth import get_accessible_tenant, get_current_user, require_super_admin
from shared.services.vectorstore import (
    delete_vectors_by_filename,
    get_document_list,
    get_drive_file_id_for,
    get_raw_index,
)

router = APIRouter(prefix="/api/tenants/{tenant_id}", tags=["Analytics"])


@router.get("/analytics", response_model=AnalyticsResponse)
async def get_analytics(tenant: dict = Depends(get_accessible_tenant)):
    """Usage stats: total chats, unique users."""
    return AnalyticsResponse(**await firestore_service.get_analytics(tenant["tenant_id"]))


@router.get("/chat-logs", response_model=list[ChatLogEntry])
async def get_chat_logs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    tenant: dict = Depends(get_accessible_tenant),
):
    """Paginated chat history for a tenant."""
    return await firestore_service.get_chat_logs(tenant["tenant_id"], limit=limit, offset=offset)


@router.get("/documents")
async def list_documents(tenant: dict = Depends(get_accessible_tenant)):
    """Vector count + list of unique ingested documents in the tenant's namespace."""
    namespace = tenant["pinecone_namespace"]
    index = get_raw_index()

    try:
        stats = index.describe_index_stats()
    except Exception:
        logger.exception("Failed to get Pinecone index stats")
        raise HTTPException(status_code=503, detail="Vector store temporarily unavailable")

    ns_stats = stats.get("namespaces", {}).get(namespace, {})
    vector_count = ns_stats.get("vector_count", 0)

    documents = await asyncio.to_thread(get_document_list, namespace) if vector_count > 0 else []

    return {
        "tenant_id": tenant["tenant_id"],
        "namespace": namespace,
        "vector_count": vector_count,
        "documents": sorted(documents, key=lambda d: d["filename"]),
    }


@router.get("/usage")
async def get_usage(
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    tenant: dict = Depends(get_accessible_tenant),
):
    """API usage stats for a tenant (current month by default)."""
    return await usage_service.get_usage(tenant["tenant_id"], month)


@router.delete("/documents", status_code=200)
async def delete_all_documents(
    tenant: dict = Depends(get_accessible_tenant),
    _admin: dict = Depends(require_super_admin),
):
    """Wipe tenant's Pinecone namespace AND delete all ingested files from Drive.

    The Drive-side delete is gated on the tenant having a ``drive_folder_id``
    set (via /gdrive/connect) and the service account having Editor. Files in
    Drive that are NOT in SUPPORTED_MIMES (non-ingest file types) are left
    untouched. The folder itself is preserved.
    """
    from shared.services import gdrive

    namespace = tenant["pinecone_namespace"]
    tenant_id = tenant["tenant_id"]
    folder_id = tenant.get("drive_folder_id", "")

    # 1) Pinecone wipe (fast)
    try:
        get_raw_index().delete(delete_all=True, namespace=namespace)
    except Exception:
        logger.warning("Pinecone delete_all failed (namespace may be empty)", exc_info=True)

    # 2) Drive wipe — only ingest-supported file types, non-recursive, keep folder
    drive_deleted = 0
    drive_errors: list[str] = []
    if folder_id:
        try:
            files = await asyncio.to_thread(gdrive.list_files, folder_id)
            for f in files:
                try:
                    await asyncio.to_thread(gdrive.delete_file, f["id"])
                    drive_deleted += 1
                except Exception as exc:
                    drive_errors.append(f"{f.get('name', f['id'])}: {exc}")
                    logger.warning("Drive delete failed for %s: %s", f.get("name"), exc)
        except Exception:
            logger.exception("Failed to list Drive folder %s for tenant %s", folder_id, tenant_id)

    # 3) BM25 invalidate
    try:
        await firestore_service.bump_bm25_invalidate_ts(tenant_id)
    except Exception:
        logger.warning("bm25 invalidate bump failed for tenant %s", tenant_id, exc_info=True)

    logger.info(
        "Delete-all for tenant %s: drive_deleted=%d drive_errors=%d",
        tenant_id, drive_deleted, len(drive_errors),
    )
    return {"drive_deleted": drive_deleted, "drive_errors": drive_errors}


@router.delete("/documents/{filename:path}")
async def delete_single_document(
    filename: str,
    tenant: dict = Depends(get_accessible_tenant),
):
    """Delete a file: Pinecone vectors + Drive file (if tenant is Connected).

    Steps:
      1. Pinecone: delete all vectors with matching ``source_filename``
      2. Drive: if tenant has ``drive_folder_id`` and file exists, delete it
      3. BM25: bump ``bm25_invalidate_ts`` so chat-api re-warms

    Drive delete is best-effort — 404 on Drive is treated as success (goal
    state: file not in Drive, already achieved). Other Drive errors are
    reported in the response but don't roll back the Pinecone delete.
    """
    from shared.services import gdrive

    namespace = tenant["pinecone_namespace"]
    tenant_id = tenant["tenant_id"]
    folder_id = tenant.get("drive_folder_id", "")

    # 1) Resolve Drive file ID from Pinecone metadata FIRST (survives renames).
    #    If not present (legacy chunks ingested before drive_file_id was stored),
    #    fall back to name-based lookup in the Drive folder.
    drive_file_id = await asyncio.to_thread(
        get_drive_file_id_for, namespace, filename,
    )

    # 2) Pinecone: delete vectors for this filename
    deleted = await asyncio.to_thread(
        delete_vectors_by_filename, namespace, filename,
    )

    # 3) Drive: delete by ID (rename-safe) or fall back to name lookup
    drive_removed = False
    drive_error: str | None = None
    if drive_file_id:
        try:
            await asyncio.to_thread(gdrive.delete_file, drive_file_id)
            drive_removed = True
        except Exception as exc:
            drive_error = str(exc)
            logger.exception("Drive delete by ID failed for '%s' (%s)", filename, drive_file_id)
    elif folder_id:
        # legacy fallback: no drive_file_id in chunks → search by name
        try:
            file_id = await asyncio.to_thread(
                gdrive.find_file_id_by_name, folder_id, filename,
            )
            if file_id:
                await asyncio.to_thread(gdrive.delete_file, file_id)
                drive_removed = True
            else:
                logger.info(
                    "Drive file '%s' not found in folder %s (already gone or renamed)",
                    filename, folder_id,
                )
        except Exception as exc:
            drive_error = str(exc)
            logger.exception("Drive delete by name failed for '%s'", filename)

    # 3) BM25
    try:
        await firestore_service.bump_bm25_invalidate_ts(tenant_id)
    except Exception:
        logger.warning("bm25 invalidate bump failed for tenant %s", tenant_id, exc_info=True)

    logger.info(
        "Deleted '%s' for tenant %s: vectors=%d drive_removed=%s",
        filename, tenant_id, deleted, drive_removed,
    )
    return {
        "filename": filename,
        "vectors_deleted": deleted,
        "drive_removed": drive_removed,
        "drive_error": drive_error,
    }


# ──────────────────────────────────────
# Global usage overview (Super Admin)
# ──────────────────────────────────────

global_router = APIRouter(prefix="/api/usage", tags=["Usage"])


@global_router.get("")
async def get_all_usage(
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    _admin: dict = Depends(require_super_admin),
):
    """Usage overview for all tenants (super admin only)."""
    return await usage_service.get_all_usage(month)
