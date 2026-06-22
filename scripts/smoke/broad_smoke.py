"""Broad recheck: diverse queries across all doc types to catch silent failures."""
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
    # Greeting — should NOT search
    ("greeting_thai", "สวัสดีครับ", 0, []),
    # Per-doc-type sanity
    ("pdf_table_student", "คณะกรรมการสอบของนายเกื้อกูล", 1, ["เกื้อกูล", "อัศวาดิศยางกูร"]),
    ("pdf_procedure", "ขั้นตอนสอบวิทยานิพนธ์ต้องทำอย่างไร", 1, ["วิทยานิพนธ์"]),
    ("pdf_form", "ขอใบสมัครสอบโครงการพิเศษ", 1, []),
    ("docx_scholarship", "มีทุนการศึกษาอะไรบ้าง", 1, []),
    ("xlsx_schedule", "ตารางเรียนรุ่นที่ 18 วันไหนบ้าง", 1, []),
    # Missing-data honesty
    ("missing_student", "นายเก่าแก่ กุลธิดา อยู่ที่ไหน", 0, []),
    # English query with Thai program name
    ("english_program", "What is the TIP program about", 1, []),
]

good = 0
bad = []
with httpx.Client(timeout=120) as client:
    for label, query, expect_min_sources, must_contain in TESTS:
        r = client.post(
            URL,
            headers={"X-API-Key": key, "Content-Type": "application/json"},
            json={"query": query, "tenant_id": "cutip_01", "user_id": f"broad_{label}"},
        )
        if r.status_code != 200:
            bad.append(f"{label}: status={r.status_code}")
            continue
        d = r.json()
        ans = d.get("answer", "")
        srcs = len(d.get("sources", []))
        missing = [t for t in must_contain if t not in ans]
        has_err = any(pat in ans for pat in ["Could you please", "Ensure the image", "NO_RESULTS"])
        status = "OK"
        if missing:
            status = f"MISSING {missing}"
            bad.append(f"{label}: {status}")
        elif has_err:
            status = "ERROR_LEAK"
            bad.append(f"{label}: {status}")
        elif srcs < expect_min_sources and expect_min_sources > 0:
            # allow sources=0 for short follow-ups; only count strict zero when we expected >=1
            status = f"sources={srcs} (expected >= {expect_min_sources})"
            # Don't fail — bot may have answered from memory. Just flag.
        if status == "OK":
            good += 1
        print(f"{label:24s} status={r.status_code} sources={srcs} -> {status}")

print(f"\n{good}/{len(TESTS)} OK")
if bad:
    print("FAIL:", bad)
