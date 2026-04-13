"""Firestore + Pinecone backup to GCS.

Firestore: managed export via Admin API (all collections).
Pinecone: fetch all vectors per namespace → JSONL in GCS.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from google.cloud import firestore_admin_v1, storage

from config import settings

logger = logging.getLogger(__name__)

FETCH_BATCH_SIZE = 100  # Pinecone fetch/upsert batch size
MAX_BACKUP_LIST = 20


# ──────────────────────────────────────
# GCS helpers
# ──────────────────────────────────────

@lru_cache()
def _get_storage_client() -> storage.Client:
    return storage.Client(project=settings.GOOGLE_CLOUD_PROJECT)


def _get_bucket() -> storage.Bucket:
    """Get the backup GCS bucket. Raises if not accessible."""
    client = _get_storage_client()
    bucket = client.bucket(settings.BACKUP_GCS_BUCKET)
    if not bucket.exists():
        raise RuntimeError(f"Backup bucket '{settings.BACKUP_GCS_BUCKET}' not found")
    return bucket


def _get_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _validate_gcs_uri(gcs_uri: str) -> str:
    """Validate GCS URI belongs to our backup bucket. Returns the blob path.

    Raises:
        ValueError: If URI is invalid or points outside the backup bucket.
    """
    expected_prefix = f"gs://{settings.BACKUP_GCS_BUCKET}/"
    if not gcs_uri.startswith(expected_prefix):
        raise ValueError("URI must point to the authorized backup bucket")
    path = gcs_uri[len(expected_prefix):]
    if ".." in path or path.startswith("/"):
        raise ValueError("Invalid path: directory traversal not allowed")
    return path


# ──────────────────────────────────────
# Firestore backup
# ──────────────────────────────────────

def _export_firestore_sync() -> dict[str, Any]:
    """Trigger a Firestore managed export to GCS (async GCP operation)."""
    client = firestore_admin_v1.FirestoreAdminClient()
    database = f"projects/{settings.GOOGLE_CLOUD_PROJECT}/databases/(default)"
    timestamp = _get_timestamp()
    output_uri = f"gs://{settings.BACKUP_GCS_BUCKET}/firestore/{timestamp}"

    request = firestore_admin_v1.ExportDocumentsRequest(
        name=database,
        output_uri_prefix=output_uri,
        collection_ids=[],
    )

    operation = client.export_documents(request=request)
    logger.info("Firestore export started: %s → %s", operation.operation.name, output_uri)

    return {
        "type": "firestore",
        "operation_name": operation.operation.name,
        "output_uri": output_uri,
        "timestamp": timestamp,
        "status": "started",
    }


# ──────────────────────────────────────
# Pinecone backup
# ──────────────────────────────────────

def _backup_pinecone_sync(namespace: str | None = None) -> dict[str, Any]:
    """Export Pinecone vectors to GCS as JSONL.

    Each namespace becomes one JSONL file with format:
    {"id": "...", "values": [...], "metadata": {...}}
    """
    from services.vectorstore import get_raw_index

    index = get_raw_index()
    timestamp = _get_timestamp()
    bucket = _get_bucket()

    stats = index.describe_index_stats()
    all_namespaces = stats.get("namespaces", {})

    if namespace:
        if namespace not in all_namespaces:
            raise ValueError(f"Namespace '{namespace}' not found")
        namespaces_to_backup = {namespace: all_namespaces[namespace]}
    else:
        namespaces_to_backup = all_namespaces

    results = []

    for ns, ns_stats in namespaces_to_backup.items():
        vector_count = ns_stats.get("vector_count", 0)
        if vector_count == 0:
            results.append({"namespace": ns, "vectors": 0, "status": "skipped (empty)"})
            continue

        try:
            lines = _fetch_all_vectors(index, ns)
            gcs_path = f"pinecone/{timestamp}/{ns}.jsonl"
            blob = bucket.blob(gcs_path)
            blob.upload_from_string("\n".join(lines), content_type="application/jsonl")

            results.append({
                "namespace": ns,
                "vectors": len(lines),
                "gcs_uri": f"gs://{settings.BACKUP_GCS_BUCKET}/{gcs_path}",
                "status": "completed",
            })
            logger.info("Pinecone backup: %s → %d vectors", ns, len(lines))

        except Exception as exc:
            logger.exception("Failed to backup namespace '%s'", ns)
            results.append({
                "namespace": ns,
                "vectors": 0,
                "status": f"failed: {type(exc).__name__}",
            })

    return {"type": "pinecone", "timestamp": timestamp, "namespaces": results}


def _fetch_all_vectors(index, namespace: str) -> list[str]:
    """Fetch all vectors in a namespace, return JSONL lines (id + values + metadata)."""
    from services.vectorstore import list_all_vector_ids

    all_ids = list_all_vector_ids(namespace)
    lines: list[str] = []

    for i in range(0, len(all_ids), FETCH_BATCH_SIZE):
        batch_ids = all_ids[i:i + FETCH_BATCH_SIZE]
        try:
            fetched = index.fetch(ids=batch_ids, namespace=namespace)
        except Exception:
            logger.exception("Pinecone fetch failed for batch at offset %d", i)
            continue

        for vec_id, vec in fetched.vectors.items():
            record = {
                "id": vec_id,
                "values": vec.values,
                "metadata": dict(vec.metadata) if vec.metadata else {},
            }
            lines.append(json.dumps(record, ensure_ascii=False))

    return lines


# ──────────────────────────────────────
# Pinecone restore (streaming)
# ──────────────────────────────────────

def _restore_pinecone_sync(gcs_uri: str, namespace: str) -> dict[str, Any]:
    """Restore Pinecone vectors from a JSONL backup in GCS.

    Streams the file to avoid loading everything into memory.
    """
    from services.vectorstore import get_raw_index

    path = _validate_gcs_uri(gcs_uri)
    index = get_raw_index()
    bucket = _get_bucket()
    blob = bucket.blob(path)

    if not blob.exists():
        raise ValueError(f"Backup file not found: {gcs_uri}")

    upserted = 0
    skipped = 0
    batch: list[dict] = []

    # Stream line-by-line to handle large files
    with blob.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                batch.append({
                    "id": record["id"],
                    "values": record["values"],
                    "metadata": record.get("metadata", {}),
                })
            except (json.JSONDecodeError, KeyError):
                skipped += 1
                continue

            if len(batch) >= FETCH_BATCH_SIZE:
                index.upsert(vectors=batch, namespace=namespace)
                upserted += len(batch)
                batch = []

    if batch:
        index.upsert(vectors=batch, namespace=namespace)
        upserted += len(batch)

    logger.info("Pinecone restore: %d vectors → namespace '%s' (%d skipped)", upserted, namespace, skipped)

    return {
        "namespace": namespace,
        "vectors_restored": upserted,
        "skipped": skipped,
        "source": gcs_uri,
        "status": "completed",
    }


# ──────────────────────────────────────
# List backups
# ──────────────────────────────────────

def _list_backups_sync() -> dict[str, Any]:
    """List available backups from GCS."""
    try:
        bucket = _get_bucket()
    except RuntimeError:
        return {"firestore": [], "pinecone": []}

    # Firestore backups
    fs_blobs = bucket.list_blobs(prefix="firestore/", delimiter="/")
    list(fs_blobs)  # consume iterator to populate prefixes
    firestore_backups = []
    for prefix in sorted(fs_blobs.prefixes, reverse=True)[:MAX_BACKUP_LIST]:
        timestamp = prefix.strip("/").split("/")[-1]
        firestore_backups.append({
            "timestamp": timestamp,
            "uri": f"gs://{settings.BACKUP_GCS_BUCKET}/{prefix.rstrip('/')}",
        })

    # Pinecone backups
    pc_blobs = bucket.list_blobs(prefix="pinecone/", delimiter="/")
    list(pc_blobs)  # consume iterator to populate prefixes
    pinecone_backups = []
    for prefix in sorted(pc_blobs.prefixes, reverse=True)[:MAX_BACKUP_LIST]:
        timestamp = prefix.strip("/").split("/")[-1]
        files = list(bucket.list_blobs(prefix=prefix))
        namespaces = [
            f.name.split("/")[-1].replace(".jsonl", "")
            for f in files if f.name.endswith(".jsonl")
        ]
        pinecone_backups.append({
            "timestamp": timestamp,
            "uri": f"gs://{settings.BACKUP_GCS_BUCKET}/{prefix.rstrip('/')}",
            "namespaces": namespaces,
        })

    return {"firestore": firestore_backups, "pinecone": pinecone_backups}


# ──────────────────────────────────────
# Async wrappers
# ──────────────────────────────────────

async def export_firestore() -> dict[str, Any]:
    """Trigger Firestore backup (async GCP operation)."""
    return await asyncio.to_thread(_export_firestore_sync)


async def backup_pinecone(namespace: str | None = None) -> dict[str, Any]:
    """Backup Pinecone vectors to GCS as JSONL."""
    return await asyncio.to_thread(_backup_pinecone_sync, namespace)


async def restore_pinecone(gcs_uri: str, namespace: str) -> dict[str, Any]:
    """Restore Pinecone vectors from GCS backup (streaming)."""
    return await asyncio.to_thread(_restore_pinecone_sync, gcs_uri, namespace)


async def list_backups() -> dict[str, Any]:
    """List all available backups from GCS."""
    return await asyncio.to_thread(_list_backups_sync)
