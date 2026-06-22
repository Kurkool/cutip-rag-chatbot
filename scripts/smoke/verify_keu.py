"""Live smoke test: bot finds นายเกื้อกูล after re-ingest."""
import subprocess
import sys

import httpx

sys.stdout.reconfigure(encoding="utf-8")

URL = "https://cutip-chat-api-secaaxwrgq-as.a.run.app/api/chat"
key = subprocess.check_output(
    ["gcloud", "secrets", "versions", "access", "latest", "--secret=ADMIN_API_KEY"],
    shell=True,
).decode().strip()

TESTS = [
    "คณะกรรมการสอบของนายเกื้อกูล มีใครบ้าง",
    "หัวข้อวิทยานิพนธ์ของนายเกื้อกูลคืออะไร",
    "รหัสนักศึกษาของเกื้อกูล",
]

with httpx.Client(timeout=120) as client:
    for q in TESTS:
        print(f"\n=== Q: {q} ===")
        r = client.post(
            URL,
            headers={"X-API-Key": key, "Content-Type": "application/json"},
            json={"query": q, "tenant_id": "cutip_01", "user_id": "verify_keu"},
        )
        print(f"status: {r.status_code}")
        if r.status_code == 200:
            d = r.json()
            ans = d.get("answer", "")
            srcs = d.get("sources", [])
            print(f"answer (first 500): {ans[:500]}")
            print(f"sources: {len(srcs)}")
            mentions = sum(1 for marker in ["เกื้อกูล", "อัศวาดิศยางกูร", "6780016820", "RAG"] if marker in ans)
            print(f"key markers found in answer: {mentions}/4")
        else:
            print(f"error: {r.text[:300]}")
