"""Demo: ตัวอย่าง chunk แบบ JSON เต็ม + จำลองการ filter retrieval ด้วย metadata"""
import json

with open("/home/claude/chunks.json", encoding="utf-8") as f:
    data = json.load(f)

chunks = data["chunks"]

# ========== 1) แสดง chunk กลางๆ แบบเต็ม (ข้อ 9) ==========
print("=" * 70)
print("ตัวอย่าง 1: Chunk สมบูรณ์ (ข้อ 9 อัตราค่าตอบแทน) — JSON ที่พร้อม embed")
print("=" * 70)
sample = next(c for c in chunks if c["metadata"]["item_number"] == "9")
print(json.dumps(sample, ensure_ascii=False, indent=2)[:2200] + "\n...")

# ========== 2) จำลอง retrieval ด้วย metadata filter ==========
print("\n" + "=" * 70)
print("ตัวอย่าง 2: จำลองคำถามของผู้ใช้ → ใช้ metadata filter ช่วย retrieval")
print("=" * 70)

# คำถาม: "ค่าเบี้ยประชุมนายกสภามหาวิทยาลัยเท่าไหร่?"
print("\nQ: ค่าเบี้ยประชุมนายกสภามหาวิทยาลัยเท่าไหร่?")
print("   → Filter: tags contains 'ค่าเบี้ยประชุม' AND tags contains 'กรรมการสภามหาวิทยาลัย'")
hits = [c for c in chunks
        if "ค่าเบี้ยประชุม" in c["metadata"]["tags"]
        and "กรรมการสภามหาวิทยาลัย" in c["metadata"]["tags"]]
for c in hits:
    print(f"   ✓ {c['chunk_id']}  |  {c['metadata']['breadcrumb']}  |  {c['metadata']['baht_mentions']} อัตรา")

# คำถาม: "ไปประชุมที่ญี่ปุ่น ค่าที่พักเหมาจ่ายเท่าไหร่?"
print("\nQ: ไปประชุมที่ญี่ปุ่น ค่าที่พักเหมาจ่ายเท่าไหร่?")
print("   → Step 1: ค้น annex หาว่าญี่ปุ่นอยู่กลุ่มไหน")
japan_hits = [c for c in chunks
              if c["metadata"]["chapter"] == "annex" and "ญี่ปุ่น" in c["text"]]
for c in japan_hits:
    print(f"   ✓ {c['chunk_id']}  |  {c['metadata']['title']}")
print("   → Step 2: filter chapter=7 + section=2 + tags contains 'เดินทางต่างประเทศ'")
hits = [c for c in chunks
        if c["metadata"]["chapter"] == "7"
        and c["metadata"]["section"] == "2"
        and "ที่พัก" in c["metadata"]["tags"]]
for c in hits:
    print(f"   ✓ {c['chunk_id']}  |  {c['metadata']['title']}")

# คำถาม: "ค่าตรวจข้อสอบปริญญาโทต่อชั่วโมงเท่าไหร่?"
print("\nQ: ค่าตรวจข้อสอบปริญญาโทเท่าไหร่?")
print("   → Filter: chapter=4 AND tags contains 'การสอบ'")
hits = [c for c in chunks
        if c["metadata"]["chapter"] == "4" and "การสอบ" in c["metadata"]["tags"]]
for c in hits:
    print(f"   ✓ {c['chunk_id']}  |  ข้อ {c['metadata']['item_number']} {c['metadata']['title']}")

# ========== 3) สถิติ chunk densest (มีเลขเงินเยอะที่สุด) ==========
print("\n" + "=" * 70)
print("ตัวอย่าง 3: Top 5 chunks ที่ information-dense ที่สุด (อัตราเงินเยอะ)")
print("=" * 70)
top = sorted(chunks, key=lambda c: -c["metadata"]["baht_mentions"])[:5]
for c in top:
    m = c["metadata"]
    print(f"  {m['baht_mentions']:3d} อัตรา | {m['char_count']:5d} chars | {c['chunk_id']}")
    print(f"           {m['breadcrumb']} — {m['title']}")
