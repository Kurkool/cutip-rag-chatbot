"""Ingest every file in sample-doc/* into namespace cutip_v2_audit via v2.

Used to empirically compare v2 output against v1 production (cutip_01) via
the audit scripts in this folder. Safe to re-run — v2 uses the same
atomic-swap upsert as v1, so re-ingesting replaces prior v2 chunks.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from ingest.services.ingestion_v2 import ingest_v2

SAMPLE_DIRS = [
    Path(r"C:\Users\USER\PycharmProjects\TIP-RAG\sample-doc\cutip-doc"),
    Path(r"C:\Users\USER\PycharmProjects\TIP-RAG\sample-doc\hsm-doc"),
]
NAMESPACE = "cutip_v2_audit"
TENANT_ID = "cutip_v2_audit"

# Files skipped in v1's audit because they require special pre-processing
# that v1 could not handle — v2 should handle all of these via ensure_pdf.
SUPPORTED_EXTS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"}


async def main() -> None:
    files: list[Path] = []
    for d in SAMPLE_DIRS:
        for p in sorted(d.iterdir()):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                files.append(p)

    print(f"audit_v2: {len(files)} files → namespace '{NAMESPACE}'\n")

    for i, path in enumerate(files, 1):
        t0 = time.time()
        try:
            n_chunks = await ingest_v2(
                file_bytes=path.read_bytes(),
                filename=path.name,
                namespace=NAMESPACE,
                tenant_id=TENANT_ID,
                doc_category="general",
            )
            elapsed = time.time() - t0
            print(f"  [{i:2d}/{len(files)}] {path.name[:55]:55s} chunks={n_chunks:3d} ({elapsed:5.1f}s)")
        except Exception as exc:
            elapsed = time.time() - t0
            print(f"  [{i:2d}/{len(files)}] {path.name[:55]:55s} FAILED ({elapsed:5.1f}s): {exc}")

    print("\naudit_v2: done — next run `scripts/full_audit.py --namespace cutip_v2_audit`")


if __name__ == "__main__":
    asyncio.run(main())
