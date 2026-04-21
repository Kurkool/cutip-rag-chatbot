"""Firestore-backed ingest failure tracking for scan-all cooldown.

Keeps a per-file fail counter in collection ``ingest_failures`` keyed by
``{tenant_id}__{drive_file_id}``. ``_process_gdrive_folder`` checks the
counter against MAX_CONSECUTIVE_FAILURES before attempting ingest and
clears the record on success, so a single broken file cannot hammer the
Opus API indefinitely.

All functions are async and non-blocking — Firestore SDK is sync, so
every operation is wrapped in ``asyncio.to_thread``. On Firestore
unavailability the functions log a warning and degrade gracefully (reads
return empty, writes silently no-op) so an outage never takes down the
scan path.
"""
from __future__ import annotations

import asyncio
import logging
import time
from functools import lru_cache
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

COLLECTION = "ingest_failures"
MAX_CONSECUTIVE_FAILURES = 3

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_client() -> firestore.Client:
    """Cached Firestore client. Tests monkeypatch this function."""
    from shared.config import settings
    return firestore.Client(project=settings.GOOGLE_CLOUD_PROJECT or None)


def _doc_id(tenant_id: str, drive_file_id: str) -> str:
    return f"{tenant_id}__{drive_file_id}"


def _short_error(error: Exception | str) -> str:
    if isinstance(error, Exception):
        msg = f"{type(error).__name__}: {error}"
    else:
        msg = str(error)
    return msg[:200]


def _record_failure_sync(tenant_id, drive_file_id, filename, drive_modified, error) -> None:
    now = time.time()
    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "drive_file_id": drive_file_id,
        "filename": filename,
        "fail_count": firestore.Increment(1),
        "last_failed_at": now,
        "first_failed_at": now,  # merge=True → written only if missing
        "last_drive_modified": drive_modified,
        "last_error_short": _short_error(error),
    }
    _get_client().collection(COLLECTION).document(_doc_id(tenant_id, drive_file_id)).set(
        payload, merge=True,
    )


async def record_failure(
    tenant_id: str,
    drive_file_id: str,
    filename: str,
    drive_modified: float,
    error: Exception | str,
) -> None:
    """Record a failure for (tenant_id, drive_file_id).

    Increments ``fail_count`` on every call (server-atomic via
    ``firestore.Increment``). ``first_failed_at`` is set on the initial
    write and preserved thereafter via ``merge=True``.
    """
    try:
        await asyncio.to_thread(
            _record_failure_sync,
            tenant_id, drive_file_id, filename, drive_modified, error,
        )
        logger.info(
            "ingest_failures.record_failure: tenant=%s drive_id=%s error=%s",
            tenant_id, drive_file_id, _short_error(error),
        )
    except Exception as exc:
        logger.warning(
            "ingest_failures.record_failure: Firestore unavailable — state not persisted (tenant=%s drive_id=%s): %r",
            tenant_id, drive_file_id, exc,
        )


def _get_failure_sync(tenant_id: str, drive_file_id: str) -> dict[str, Any] | None:
    snap = _get_client().collection(COLLECTION).document(_doc_id(tenant_id, drive_file_id)).get()
    if not snap.exists:
        return None
    return snap.to_dict()


async def get_failure(tenant_id: str, drive_file_id: str) -> dict[str, Any] | None:
    """Return the failure doc dict, or None if no failure recorded."""
    try:
        return await asyncio.to_thread(_get_failure_sync, tenant_id, drive_file_id)
    except Exception as exc:
        logger.warning(
            "ingest_failures.get_failure: Firestore unavailable (tenant=%s drive_id=%s): %r",
            tenant_id, drive_file_id, exc,
        )
        return None


def _clear_failure_sync(tenant_id: str, drive_file_id: str) -> None:
    _get_client().collection(COLLECTION).document(_doc_id(tenant_id, drive_file_id)).delete()


async def clear_failure(tenant_id: str, drive_file_id: str) -> None:
    """Delete the failure doc if present. Ignores 'not found'."""
    try:
        await asyncio.to_thread(_clear_failure_sync, tenant_id, drive_file_id)
        logger.info(
            "ingest_failures.clear_failure: tenant=%s drive_id=%s",
            tenant_id, drive_file_id,
        )
    except Exception as exc:
        logger.warning(
            "ingest_failures.clear_failure: Firestore unavailable (tenant=%s drive_id=%s): %r",
            tenant_id, drive_file_id, exc,
        )


def _list_failures_sync(tenant_id: str) -> dict[str, dict[str, Any]]:
    query = (
        _get_client()
        .collection(COLLECTION)
        .where(filter=FieldFilter("tenant_id", "==", tenant_id))
    )
    out: dict[str, dict[str, Any]] = {}
    for snap in query.stream():
        data = snap.to_dict() or {}
        drive_id = data.get("drive_file_id", "")
        if drive_id:
            out[drive_id] = data
    return out


async def list_failures(tenant_id: str) -> dict[str, dict[str, Any]]:
    """Return {drive_file_id: failure_doc} for all failures of this tenant.

    Intended for one-round-trip use in the scan loop.
    """
    try:
        return await asyncio.to_thread(_list_failures_sync, tenant_id)
    except Exception as exc:
        logger.warning(
            "ingest_failures.list_failures: Firestore unavailable (tenant=%s): %r",
            tenant_id, exc,
        )
        return {}
