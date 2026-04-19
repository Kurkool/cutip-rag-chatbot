"""Compat shim — gdrive helpers moved to shared/services/gdrive.py on 2026-04-20.

Re-exports keep existing imports (``from ingest.services.gdrive import ...``)
and existing test monkeypatches working without changes. New code should
import directly from ``shared.services.gdrive``.
"""

from shared.services.gdrive import (  # noqa: F401
    SUPPORTED_MIMES,
    _get_drive_service,
    delete_file,
    download_file,
    find_file_id_by_name,
    get_file_type,
    list_files,
    upload_file,
)
