"""Verify (p.1.0) → (p.1) fix on production chat-api."""
import json
import subprocess

import httpx

URL = "https://cutip-chat-api-secaaxwrgq-as.a.run.app/api/chat"
key = subprocess.check_output(
    ["gcloud", "secrets", "versions", "access", "latest", "--secret=ADMIN_API_KEY"],
    shell=True,
).decode().strip()

with httpx.Client(timeout=90) as client:
    r = client.post(
        URL,
        headers={"X-API-Key": key, "Content-Type": "application/json"},
        json={
            "query": "อยากรู้เรื่องการลงทะเบียนเรียน และ ขั้นตอนการรับสมัคร",
            "tenant_id": "cutip_01",
            "user_id": "verify_page_format",
        },
    )
    print(f"status: {r.status_code}")
    d = r.json()
    print(f"sources ({len(d.get('sources', []))}):")
    for s in d.get("sources", [])[:5]:
        print(f"  filename={s.get('filename')} page={s.get('page')!r} type={type(s.get('page')).__name__}")
