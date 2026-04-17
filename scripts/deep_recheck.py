"""Deep recheck — hit the 3 outstanding concerns:

1. Retrieval misses — are they actually WRONG answers or just cosmetic
   file-name mismatches? Look at full answer + source content.
2. XLSX 70% coverage — real data loss or interpret_spreadsheet reformatting?
3. Duplicate chunk prefixes — genuine duplicates or header repetition?
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import httpx
import pandas as pd
from pinecone import Pinecone

CHAT_URL = "https://cutip-chat-api-secaaxwrgq-as.a.run.app/api/chat"
SAMPLE_DIR = Path(r"C:\Users\USER\PycharmProjects\TIP-RAG\sample-doc\cutip-doc")

key = subprocess.check_output(
    ["gcloud", "secrets", "versions", "access", "latest", "--secret=PINECONE_API_KEY"],
    shell=True,
).decode().strip()
admin_key = subprocess.check_output(
    ["gcloud", "secrets", "versions", "access", "latest", "--secret=ADMIN_API_KEY"],
    shell=True,
).decode().strip()

pc = Pinecone(api_key=key)


# ── Concern 1: do the 2 "misses" produce WRONG answers? ────────────────
print("=== CONCERN 1: RETRIEVAL MISSES — DO USERS GET WRONG ANSWERS? ===\n")
QUERIES = [
    "สอบความก้าวหน้าวิทยานิพนธ์คืออะไร ต้องทำอย่างไรบ้าง",
    "slide มีเนื้อหาเกี่ยวกับอะไรบ้าง",
]
with httpx.Client(timeout=120) as client:
    for q in QUERIES:
        r = client.post(
            CHAT_URL,
            headers={"X-API-Key": admin_key, "Content-Type": "application/json"},
            json={"query": q, "tenant_id": "cutip_01", "user_id": "deep_recheck"},
        )
        d = r.json()
        print(f"Q: {q}")
        print(f"  answer (600): {d.get('answer', '')[:600]}")
        print(f"  sources: {[s.get('filename', '') for s in d.get('sources', [])[:3]]}")
        print()


# ── Concern 2: XLSX 70% — what's actually lost? ─────────────────────────
print("=== CONCERN 2: XLSX 70% COVERAGE — REAL LOSS? ===\n")
xlsx_path = SAMPLE_DIR / "ตารางเรียน ปี 2568 ปโท และ ปเอก CU-TIP.xlsx"
xls = pd.ExcelFile(xlsx_path)
print(f"Sheets: {xls.sheet_names}\n")

# Collect every non-empty cell value from source
src_values = set()
for sheet in xls.sheet_names:
    df = xls.parse(sheet, header=None)
    for _, row in df.iterrows():
        for cell in row:
            if pd.notna(cell):
                v = str(cell).strip()
                if v:
                    src_values.add(v)
print(f"Source has {len(src_values)} distinct non-empty cell values")

# Fetch chunks for this file
idx = pc.Index("university-rag")
all_ids = []
for page in idx.list(namespace="cutip_01"):
    all_ids.extend(page)
merged = []
for i in range(0, len(all_ids), 50):
    batch = idx.fetch(ids=all_ids[i : i + 50], namespace="cutip_01")
    for v in batch.vectors.values():
        meta = v.metadata or {}
        if meta.get("source_filename") == xlsx_path.name:
            merged.append(str(meta.get("text", "")))
chunk_text = "\n".join(merged)
print(f"Pinecone chunks total text: {len(chunk_text)} chars\n")

# Check which source cell values are present in chunks
missing = [v for v in src_values if v not in chunk_text]
missing_meaningful = [v for v in missing if len(v) >= 3 and not v.replace(".", "").replace("-", "").isdigit()]
print(f"Missing distinct values (any): {len(missing)} / {len(src_values)}")
print(f"Missing meaningful values (len>=3, non-numeric): {len(missing_meaningful)}")
if missing_meaningful:
    print("First 20 missing:")
    for v in list(missing_meaningful)[:20]:
        print(f"  {v!r}")


# ── Concern 3: duplicate chunk prefixes — what are they? ────────────────
print("\n=== CONCERN 3: DUPLICATE CHUNK PREFIXES ===\n")
files_to_check = ["slide.pdf", "xlsx-table.xlsx", "ตารางเรียน-ห้องเรียน ภาคปลาย ปีการศึกษา 2568.xlsx"]
by_file: dict[str, list[str]] = {}
for i in range(0, len(all_ids), 50):
    batch = idx.fetch(ids=all_ids[i : i + 50], namespace="cutip_01")
    for v in batch.vectors.values():
        meta = v.metadata or {}
        fn = meta.get("source_filename", "?")
        if fn in files_to_check:
            by_file.setdefault(fn, []).append(str(meta.get("text", "")))

for fn in files_to_check:
    chunks = by_file.get(fn, [])
    seen_prefix: dict[str, list[int]] = {}
    for i, t in enumerate(chunks):
        p = t[:100]
        seen_prefix.setdefault(p, []).append(i)
    dups = {p: ixs for p, ixs in seen_prefix.items() if len(ixs) > 1}
    print(f"\n--- {fn} ({len(chunks)} chunks, {len(dups)} duplicate-prefix group(s)) ---")
    for p, ixs in dups.items():
        print(f"  prefix (shared by chunks {ixs}): {p!r}")
        # Show the full chunks to see if they're really identical or just share header
        for ix in ixs:
            txt = chunks[ix]
            print(f"    chunk[{ix}] len={len(txt)}: {txt[:300]!r}")
