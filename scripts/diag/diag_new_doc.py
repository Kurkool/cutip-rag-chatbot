"""Diagnose why bot failed on 'หากอาจารย์จะเปลี่ยนแปลงตารางเรียนจะต้องแจ้งหลักสูตรภายในกี่วัน'.

Check: is 'บันทึกข้อความขอเรียนแจ้งอาจารย์ผู้สอน' ingested into cutip_v2_audit? If yes, does
the chunk text contain the answer keywords?
"""
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

from pinecone import Pinecone

NS = "cutip_v2_audit"
KEYWORDS = ["เปลี่ยน", "แจ้ง", "ล่วงหน้า", "วัน", "ตารางเรียน", "อาจารย์"]


def main():
    key = subprocess.check_output(
        ["gcloud", "secrets", "versions", "access", "latest", "--secret=PINECONE_API_KEY"],
        shell=True,
    ).decode().strip()
    pc = Pinecone(api_key=key)
    idx = pc.Index("university-rag")

    ids = []
    for page in idx.list(namespace=NS):
        ids.extend(page)

    by_file: dict[str, list[dict]] = {}
    for i in range(0, len(ids), 50):
        batch = idx.fetch(ids=ids[i:i + 50], namespace=NS)
        for vid, v in batch.vectors.items():
            meta = v.metadata or {}
            fn = meta.get("source_filename", "?")
            by_file.setdefault(fn, []).append({
                "id": vid,
                "text": str(meta.get("text", "")),
                "section_path": meta.get("section_path", ""),
                "page": meta.get("page"),
            })

    print("=" * 100)
    print(f"ALL SOURCE_FILENAMES in {NS} ({len(by_file)} files, {sum(len(v) for v in by_file.values())} chunks)")
    print("=" * 100)
    for fn, chs in sorted(by_file.items()):
        print(f"  [{len(chs):3d} chunks] {fn}")

    # Find target file
    target = None
    for fn in by_file:
        if "บันทึก" in fn or "แจ้งอาจารย์" in fn:
            target = fn
            break

    if not target:
        print(f"\n🚨 File with 'บันทึก' or 'แจ้งอาจารย์' NOT FOUND in namespace {NS}")
        print("   → The 168.72s manual scan might have ingested a different doc, or this doc was never added")
        return

    print(f"\n{'=' * 100}")
    print(f"TARGET FILE: {target} ({len(by_file[target])} chunks)")
    print(f"{'=' * 100}")
    for i, c in enumerate(by_file[target], 1):
        print(f"\n[chunk {i}]  page={c['page']}  section='{c['section_path']}'  len={len(c['text'])}")
        print("  " + c["text"].replace("\n", "\n  "))

    # Keyword presence check
    print(f"\n{'=' * 100}")
    print("KEYWORD PRESENCE (across all chunks of target file)")
    print(f"{'=' * 100}")
    merged = "\n".join(c["text"] for c in by_file[target])
    for kw in KEYWORDS:
        hits = merged.count(kw)
        mark = "✅" if hits > 0 else "❌"
        print(f"  {mark} '{kw}': {hits} occurrences")

    # Look for number patterns (x วัน)
    import re
    day_matches = re.findall(r"(\d+|หนึ่ง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า|สิบ)\s*วัน", merged)
    print(f"\n  'X วัน' patterns found: {day_matches[:10]}")


if __name__ == "__main__":
    main()
