"""20-query adversarial probe — checks: correctness, honest refusal, no fabrication.

Categories:
  - Specific students (3 different names from the announcement PDF)
  - Committee members (check cross-referencing)
  - Thesis exam facts (credit counts, time gaps)
  - Scholarship
  - Schedule/room lookups
  - Form/document references
  - English queries (language-match)
  - Out-of-domain (must refuse honestly)
  - Follow-up queries (conversation memory)
"""
import argparse
import subprocess
import sys
import time
import httpx

sys.stdout.reconfigure(encoding="utf-8")

CHAT_URL = "https://cutip-chat-api-secaaxwrgq-as.a.run.app/api/chat"
key = subprocess.check_output(
    ["gcloud", "secrets", "versions", "access", "latest", "--secret=ADMIN_API_KEY"],
    shell=True,
).decode().strip()

parser = argparse.ArgumentParser(description="20-query adversarial bot probe")
parser.add_argument("--namespace", default="cutip_01")
args = parser.parse_args()
TENANT_ID = args.namespace

# Each probe: (label, query, must_contain_any_of, must_not_contain, category)
PROBES = [
    # Specific students from announcement
    ("student_keu",
     "นายเกื้อกูล อัศวาดิศยางกูร หัวข้ออะไร",
     ["การพัฒนาระบบผู้ช่วย", "RAG", "LINE"],
     [], "specific_student"),
    ("student_charwan",
     "นายชัชวาล บุญสิทธิโสภณ รหัสและกรรมการสอบ",
     ["6780024820", "กวิน", "ธนารัตน์", "นกุล"],
     [], "specific_student"),
    ("student_kanjanee",
     "นางสาวกชกร สามนจิตติ หัวข้อวิทยานิพนธ์",
     ["ClarifyClay", "โคลน", "ทุเรียน"],
     [], "specific_student"),

    # Committee-member reverse lookup
    ("committee_kawin",
     "ผศ.ดร.กวิน อัศวานันท์ เป็นกรรมการให้ใครบ้าง",
     ["กวิน"],
     [], "committee_member"),

    # Thesis exam facts (cross-referenced from slide.pdf + สอบวิทยานิพนธ์.pdf)
    ("fact_credits",
     "ต้องลงทะเบียนวิทยานิพนธ์กี่หน่วยกิตก่อนสอบ",
     ["27", "หน่วยกิต"],
     [], "numeric_fact"),
    ("fact_gap_days",
     "สอบความก้าวหน้าห่างจากอนุมัติโครงร่างกี่วัน",
     ["45"],
     [], "numeric_fact"),
    ("fact_gap_days_100",
     "สอบ 100% ห่างจาก 75% กี่วัน",
     ["20"],
     [], "numeric_fact"),

    # Schedule & classroom
    ("schedule_gen18",
     "ตารางเรียนภาคปลาย ปริญญาโท รุ่น 19",
     ["68", "ปริญญา"],
     [], "schedule"),

    # Scholarship
    ("scholarship_list",
     "มีทุนการศึกษาอะไรบ้าง",
     [],
     [], "scholarship"),

    # Form download intention
    ("form_progress",
     "ขอแบบฟอร์มขอสอบความก้าวหน้าวิทยานิพนธ์",
     [],
     [], "form"),

    # English queries — must answer in English
    ("en_tuition",
     "What subjects are offered in the TIP program",
     [],
     ["ขออภัย", "ครับ", "ค่ะ"],
     "english"),
    ("en_process",
     "How does the thesis proposal exam work",
     [],
     ["ขออภัย"],
     "english"),

    # Greeting — must NOT search
    ("greeting_thai",
     "สวัสดี",
     ["ช่วย", "สอบถาม", "สวัสดี"],
     ["NO_RESULTS", "Could you please"],
     "greeting"),

    # Out-of-domain — must refuse honestly
    ("oos_weather",
     "พยากรณ์อากาศวันนี้เป็นยังไงบ้าง",
     ["ไม่"],
     ["NO_RESULTS:"],
     "out_of_domain"),
    ("oos_politics",
     "ใครเป็นนายกรัฐมนตรีไทย",
     ["ไม่", "หลักสูตร"],
     [], "out_of_domain"),
    ("oos_fake_name",
     "นายทองดี มีสุข อยู่ชั้นปีไหน",
     ["ไม่พบ", "ไม่มี", "contact", "ไม่สามารถ", "ข้อมูลส่วนบุคคล"],
     [], "out_of_domain_fake_name"),

    # Multi-turn follow-up (shares user_id — memory test)
    ("followup_1a",
     "นายเกื้อกูล หัวข้ออะไร",
     ["RAG", "LINE"],
     [], "followup_setup"),
    ("followup_1b",
     "แล้วรหัสเขาเท่าไร",   # must resolve "เขา" from previous turn
     ["6780016820"],
     [], "followup_pronoun"),

    # Markdown link embedding (system prompt says inline as [name](url))
    ("markdown_form",
     "ขอลิงก์ไฟล์แบบฟอร์มสอบวิทยานิพนธ์",
     ["https://", ")"],
     [], "markdown_link"),

    # Edge: extremely short query
    ("very_short",
     "ค่าเทอม",
     [],
     ["Could you please", "NO_RESULTS:"],
     "short_query"),
]


def check(ans: str, must_any: list[str], must_not: list[str]) -> tuple[bool, list[str]]:
    errs = []
    if must_any:
        found = [k for k in must_any if k in ans]
        if not found:
            errs.append(f"missing ANY of: {must_any}")
    for k in must_not:
        if k in ans:
            errs.append(f"leaked substring: {k!r}")
    return (not errs), errs


with httpx.Client(timeout=120) as client:
    ok = 0
    fails = []
    for label, q, must_any, must_not, category in PROBES:
        # Use same user_id for followup pair so memory accumulates
        uid = "ask_any"
        if label.startswith("followup_"):
            uid = "ask_any_followup"
        r = client.post(
            CHAT_URL,
            headers={"X-API-Key": key, "Content-Type": "application/json"},
            json={"query": q, "tenant_id": TENANT_ID, "user_id": uid},
        )
        if r.status_code != 200:
            fails.append((label, f"HTTP {r.status_code}"))
            print(f"❌ {label:25s} HTTP {r.status_code}")
            continue
        d = r.json()
        ans = d.get("answer", "")
        srcs = len(d.get("sources", []))
        passed, errs = check(ans, must_any, must_not)
        if passed:
            ok += 1
            print(f"✅ {label:25s} ({category:22s}) srcs={srcs:2d}  {ans[:80]!r}")
        else:
            fails.append((label, errs))
            print(f"❌ {label:25s} ({category:22s}) srcs={srcs:2d}")
            for e in errs:
                print(f"     {e}")
            print(f"     first 200: {ans[:200]!r}")
        time.sleep(2.0)

print(f"\n{ok}/{len(PROBES)} passed")
if fails:
    print(f"\nFAILS: {len(fails)}")
    for label, errs in fails:
        print(f"  {label}: {errs}")
