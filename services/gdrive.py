"""Google Drive integration — list and download files from shared folders."""

import io
import logging
from functools import lru_cache

import google.auth
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

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
    """Build Google Drive API service using Application Default Credentials."""
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
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
