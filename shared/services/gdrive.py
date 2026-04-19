"""Google Drive integration — shared helpers for list / download / upload / delete.

Moved from ``ingest/services/gdrive.py`` on 2026-04-20 so both admin-api (delete
endpoints) and ingest-worker (scan + stage upload) can use the same Drive client.
"""

import io
import logging
from functools import lru_cache

import google.auth
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

logger = logging.getLogger(__name__)

SUPPORTED_MIMES = {
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "text/csv": "csv",
}


@lru_cache()
def _get_drive_service():
    """Build Google Drive API service using Application Default Credentials.

    Uses the full ``drive`` scope (not ``drive.readonly``) because the admin
    portal's "Stage upload" flow uploads files into the tenant's connected
    folder and the delete flow removes files. Requires the service account
    to have Editor role on the target folder (set up by the /gdrive/connect
    flow's auto-share step).
    """
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=credentials)


def list_files(folder_id: str) -> list[dict]:
    """List all supported files in a Google Drive folder (non-recursive)."""
    service = _get_drive_service()
    mime_filter = " or ".join(f"mimeType='{m}'" for m in SUPPORTED_MIMES)
    query = f"'{folder_id}' in parents and ({mime_filter}) and trashed=false"

    files = []
    page_token = None
    while True:
        response = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
            pageToken=page_token,
            pageSize=100,
        ).execute()
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return files


def download_file(file_id: str) -> bytes:
    """Download a file's content from Google Drive."""
    service = _get_drive_service()
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


def get_file_type(mime_type: str) -> str:
    """Map MIME type to our file type category."""
    return SUPPORTED_MIMES.get(mime_type, "unknown")


def upload_file(
    file_bytes: bytes, filename: str, folder_id: str, mime_type: str,
) -> dict:
    """Upload a file into a Drive folder and return {id, name, webViewLink}.

    Used by the admin portal's "Stage upload" flow. Requires the service
    account to have Editor role on ``folder_id``. The returned webViewLink
    is stored as ``download_link`` metadata so chat citations resolve to a
    clickable URL for admin-uploaded files.
    """
    service = _get_drive_service()
    metadata = {"name": filename, "parents": [folder_id]}
    media = MediaIoBaseUpload(
        io.BytesIO(file_bytes), mimetype=mime_type, resumable=False,
    )
    return service.files().create(
        body=metadata,
        media_body=media,
        fields="id, name, webViewLink",
        supportsAllDrives=True,
    ).execute()


def delete_file(file_id: str, max_retries: int = 3) -> bool:
    """Delete a file from Drive by file_id. Returns True on success.

    404 (already deleted / never existed) is treated as success — the goal
    state (file not in Drive) is already achieved. Transient errors (5xx,
    rate limits, network) are retried with exponential backoff. Persistent
    errors raise after the retry budget is exhausted.
    """
    import time
    service = _get_drive_service()
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
            return True
        except HttpError as e:
            status = getattr(e, "status_code", None) or getattr(
                getattr(e, "resp", None), "status", None
            )
            if status == 404 or "404" in str(e):
                logger.info("Drive delete: file %s already gone", file_id)
                return True
            # Retry on transient: 5xx, 429 (rate), 403 w/ rateLimitExceeded
            transient = (
                (isinstance(status, int) and 500 <= status < 600)
                or status == 429
                or "rateLimitExceeded" in str(e)
                or "userRateLimitExceeded" in str(e)
            )
            last_exc = e
            if not transient or attempt == max_retries - 1:
                logger.warning(
                    "Drive delete failed for %s (attempt %d/%d): %s",
                    file_id, attempt + 1, max_retries, e,
                )
                raise
            backoff = 2 ** attempt  # 1s, 2s, 4s
            logger.info(
                "Drive delete retry %d/%d for %s after %ds (transient %s)",
                attempt + 1, max_retries, file_id, backoff, status,
            )
            time.sleep(backoff)
        except Exception as e:
            # Non-HttpError (network, auth, etc.) — retry conservatively
            last_exc = e
            if attempt == max_retries - 1:
                logger.warning("Drive delete non-HTTP error for %s: %s", file_id, e)
                raise
            backoff = 2 ** attempt
            logger.info(
                "Drive delete retry %d/%d for %s after %ds (%s)",
                attempt + 1, max_retries, file_id, backoff, type(e).__name__,
            )
            time.sleep(backoff)
    # Defensive: shouldn't reach here
    if last_exc:
        raise last_exc
    return False


def find_file_id_by_name(folder_id: str, filename: str) -> str | None:
    """Find a file's ID by its name in a specific folder. Returns None if not found."""
    service = _get_drive_service()
    # Exact name match, any mime type, not trashed
    safe_name = filename.replace("'", "\\'")
    query = f"'{folder_id}' in parents and name='{safe_name}' and trashed=false"
    response = service.files().list(
        q=query, fields="files(id, name)", pageSize=5,
    ).execute()
    files = response.get("files", [])
    return files[0]["id"] if files else None
