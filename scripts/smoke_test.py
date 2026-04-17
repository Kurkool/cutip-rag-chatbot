"""Live smoke test against chat-api latest revision."""
import json
import os
import subprocess
import sys

import httpx

URL = "https://cutip-chat-api-secaaxwrgq-as.a.run.app/api/chat"

key = subprocess.check_output(
    ["gcloud", "secrets", "versions", "access", "latest", "--secret=ADMIN_API_KEY"],
    shell=True,
).decode().strip()

TESTS = [
    ("thai_greeting", "สวัสดีครับ อยากสอบถามข้อมูล"),
    ("thai_tuition", "ค่าเทอมหลักสูตร TIP เท่าไหร่ครับ"),
    ("english_tuition", "what is the tuition fee for TIP program"),
    ("english_greeting", "hello, I would like to know about the program"),
]

with httpx.Client(timeout=60) as client:
    for label, query in TESTS:
        print(f"\n=== {label} ===")
        print(f"Q: {query}")
        r = client.post(
            URL,
            headers={"X-API-Key": key, "Content-Type": "application/json"},
            json={"query": query, "tenant_id": "cutip_01", "user_id": f"smoke_{label}"},
        )
        print(f"status: {r.status_code}")
        if r.status_code == 200:
            d = r.json()
            answer = d.get("answer", "")
            sources = d.get("sources", [])
            print(f"answer (first 300): {answer[:300]}")
            print(f"sources: {len(sources)}")
            # Language check
            has_thai = any("\u0e00" <= c <= "\u0e7f" for c in answer)
            if label.startswith("thai") and not has_thai:
                print("WARN: Thai query got non-Thai answer")
            if label.startswith("english") and has_thai:
                print("WARN: English query got Thai answer")
        else:
            print(f"error: {r.text[:300]}")
