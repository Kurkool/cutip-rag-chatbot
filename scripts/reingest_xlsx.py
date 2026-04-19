"""Trigger single-file v2 re-ingest of the ตารางเรียน XLSX into cutip_v2_audit namespace."""
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

import httpx

ENDPOINT = "https://cutip-ingest-worker-265709916451.asia-southeast1.run.app/api/tenants/cutip_01/ingest/v2/gdrive/file"
FOLDER_ID = "1duGSSJxj9g-A2dxNTLROnjBPn7V08aMk"  # cutip-doc
FILENAME = "ตารางเรียน ปี 2568 ปโท และ ปเอก CU-TIP.xlsx"

admin_key = subprocess.check_output(
    ["gcloud", "secrets", "versions", "access", "latest", "--secret=ADMIN_API_KEY"],
    shell=True,
).decode().strip()

print(f"Triggering v2 re-ingest of '{FILENAME}' into 'cutip_v2_audit'...")
r = httpx.post(
    ENDPOINT,
    params={"namespace_override": "cutip_v2_audit"},
    headers={"X-API-Key": admin_key, "Content-Type": "application/json"},
    json={
        "folder_id": FOLDER_ID,
        "filename": FILENAME,
        "doc_category": "general",
    },
    timeout=600,
)
print(f"HTTP {r.status_code}")
print(r.text)
