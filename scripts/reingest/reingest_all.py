"""Full re-ingest all 14 docs via /api/ingest/gdrive (skip_existing=False).

Triggers the fixed routing path:
- PDFs with digital text layer → PyMuPDF text + table markdown (no Vision)
- PDFs with true scanned pages → Opus 4.7 Vision OCR + refusal-string filter
"""
import subprocess
import sys
import time

import httpx

sys.stdout.reconfigure(encoding="utf-8")

INGEST_URL = "https://cutip-ingest-worker-secaaxwrgq-as.a.run.app/api/tenants/cutip_01/ingest/gdrive"
DRIVE_FOLDER = "1duGSSJxj9g-A2dxNTLROnjBPn7V08aMk"

key = subprocess.check_output(
    ["gcloud", "secrets", "versions", "access", "latest", "--secret=ADMIN_API_KEY"],
    shell=True,
).decode().strip()

t0 = time.time()
with httpx.Client(timeout=3600) as client:
    r = client.post(
        INGEST_URL,
        headers={"X-API-Key": key, "Content-Type": "application/json"},
        json={
            "folder_id": DRIVE_FOLDER,
            "doc_category": "general",
        },
    )
elapsed = time.time() - t0
print(f"status: {r.status_code}  elapsed: {elapsed:.1f}s")
if r.status_code == 200:
    d = r.json()
    print(f"total_files:   {d.get('total_files')}")
    print(f"succeeded:     {d.get('succeeded')}")
    print(f"failed:        {d.get('failed')}")
    print(f"skipped:       {d.get('skipped')}")
    print(f"total_chunks:  {d.get('total_chunks')}")
    for det in d.get("details", [])[:20]:
        print(f"  {det.get('filename', '?')[:60]:60s} status={det.get('status')} chunks={det.get('chunks')}")
else:
    print(r.text[:500])
