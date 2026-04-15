"""Backup management endpoints (Super Admin only)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from shared.schemas import PineconeRestoreRequest
from shared.services import backup as backup_service
from shared.services.auth import require_super_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backups", tags=["Backups"])


@router.get("")
async def list_backups(_admin: dict = Depends(require_super_admin)):
    """List available backups from GCS (Firestore + Pinecone)."""
    return await backup_service.list_backups()


@router.post("/firestore", status_code=202)
async def trigger_firestore_backup(_admin: dict = Depends(require_super_admin)):
    """Trigger a Firestore export to GCS. Returns immediately (async GCP operation)."""
    try:
        return await backup_service.export_firestore()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/pinecone")
async def trigger_pinecone_backup(
    namespace: str | None = Query(
        default=None,
        pattern=r"^[a-z0-9_-]+$",
        max_length=64,
        description="Specific namespace, or omit for all",
    ),
    _admin: dict = Depends(require_super_admin),
):
    """Backup Pinecone vectors to GCS as JSONL."""
    try:
        return await backup_service.backup_pinecone(namespace)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/pinecone/restore")
async def restore_pinecone_backup(
    body: PineconeRestoreRequest,
    _admin: dict = Depends(require_super_admin),
):
    """Restore Pinecone vectors from a JSONL backup in GCS."""
    try:
        return await backup_service.restore_pinecone(body.gcs_uri, body.namespace)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
