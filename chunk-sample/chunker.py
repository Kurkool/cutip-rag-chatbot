"""
Structure-aware chunker สำหรับประกาศจุฬาลงกรณ์มหาวิทยาลัย
กลยุทธ์:
  - ใช้ "ข้อ" เป็น semantic unit หลัก (1 ข้อ = 1 chunk โดยปกติ)
  - แนบ breadcrumb (หมวด > ส่วน > ข้อ) เข้าไปในตัว text เพื่อให้ embedding จับ context
  - เก็บ metadata แยกไว้สำหรับ filter ตอน retrieval (หมวด, ส่วน, เลขข้อ, หน้า, tags)
  - ถ้าข้อไหนยาวเกิน threshold (> MAX_CHARS) → split เป็น sub-chunks
    แต่ยังคง breadcrumb และเลขข้อเดิม เพื่อให้ re-ranker หรือ context expansion รวมกลับได้
"""

import json
import re
from document_data import DOC_META, CLAUSES

# -------- ค่าคงที่ --------
# ใช้ character count แทน token count เพื่อความเรียบง่าย
# (rule of thumb: 1 token ภาษาไทย ≈ 2-3 characters ใน tokenizer ของ multilingual models)
MAX_CHARS = 1800       # ประมาณ 600-900 tokens (safe สำหรับ embedding models ส่วนใหญ่ที่ context 512-8192)
SOFT_MIN_CHARS = 200   # chunk ที่สั้นมากจะพยายาม merge กับเพื่อน (ยกเว้นเป็นข้อสั้นตัวเดียวก็ปล่อย)


def build_breadcrumb(clause: dict) -> str:
    """สร้าง breadcrumb เช่น 'หมวด 2 ค่าตอบแทน... > ส่วนที่ 1 ค่าตอบแทน > ข้อ 9'"""
    parts = []
    if clause.get("chapter") == "transitional":
        parts.append("บทเฉพาะกาล")
    elif clause.get("chapter") == "annex":
        parts.append(clause.get("chapter_name", "บัญชีแนบท้าย"))
    elif clause.get("chapter"):
        ch_name = clause.get("chapter_name", "")
        parts.append(f"หมวด {clause['chapter']} {ch_name}".strip())

    if clause.get("section"):
        sec_name = clause.get("section_name", "")
        parts.append(f"ส่วนที่ {clause['section']} {sec_name}".strip())

    item = clause.get("item", "")
    if item and not item.startswith("annex") and item != "preamble":
        parts.append(f"ข้อ {item}")
    elif item == "preamble":
        parts.append("บทนำประกาศ")

    return " > ".join(parts) if parts else "ประกาศ"


def split_long_content(content: str, max_chars: int) -> list[str]:
    """
    ถ้า content ยาวเกินไป แตกตามอนุบัญญัติ (๑)(๒)(ก)(ข) ก่อน
    ถ้ายังยาวเกิน ค่อยตัดตามย่อหน้า / ประโยค
    """
    if len(content) <= max_chars:
        return [content]

    # 1) ลองแยกตามอนุบัญญัติระดับบน: "(1) ...", "(2) ..." (รวมตัวเลขไทย-อารบิก)
    # pattern: ขึ้นบรรทัดใหม่ด้วย "(<digit/ไทย>)"
    parts = re.split(r'(?m)^(?=\(\d+\)|\([๑-๙]+\))', content)
    parts = [p.strip() for p in parts if p.strip()]

    # ถ้ามีมากกว่า 1 ชิ้น → group ชิ้นเล็กๆ เข้าด้วยกันจนใกล้ max_chars
    if len(parts) > 1:
        merged = []
        buf = ""
        for p in parts:
            if len(buf) + len(p) + 1 <= max_chars:
                buf = (buf + "\n" + p) if buf else p
            else:
                if buf:
                    merged.append(buf)
                # ถ้าตัวเดียวยาวเกิน max_chars ก็ต้อง recursive ตัดย่อยอีก
                if len(p) > max_chars:
                    merged.extend(_split_by_paragraphs(p, max_chars))
                else:
                    buf = p
        if buf:
            merged.append(buf)
        return merged

    # 2) ถ้าไม่มีอนุบัญญัติ → ตัดตามย่อหน้า
    return _split_by_paragraphs(content, max_chars)


def _split_by_paragraphs(text: str, max_chars: int) -> list[str]:
    paragraphs = text.split("\n")
    chunks, buf = [], ""
    for para in paragraphs:
        if len(buf) + len(para) + 1 <= max_chars:
            buf = (buf + "\n" + para) if buf else para
        else:
            if buf:
                chunks.append(buf)
            if len(para) > max_chars:
                # fallback: hard cut
                for i in range(0, len(para), max_chars):
                    chunks.append(para[i:i + max_chars])
                buf = ""
            else:
                buf = para
    if buf:
        chunks.append(buf)
    return chunks


def extract_tags(clause: dict) -> list[str]:
    """ดึง tag คร่าวๆ จากเนื้อหาและหัวข้อ เพื่อช่วย retrieval"""
    text = (clause.get("title", "") + " " + clause.get("content", "")).lower()
    tag_rules = {
        "ค่าเบี้ยประชุม": ["เบี้ยประชุม"],
        "ค่าตอบแทน": ["ค่าตอบแทน"],
        "ปฏิบัติงานนอกเวลา": ["นอกเวลา", "ปฏิบัติงานนอกเวลา"],
        "เดินทางในประเทศ": ["ในประเทศ", "ปริมณฑล", "กรุงเทพ"],
        "เดินทางต่างประเทศ": ["ต่างประเทศ", "กลุ่มที่"],
        "ฝึกอบรม": ["ฝึกอบรม", "วิทยากร", "อบรม"],
        "นิสิต": ["นิสิต", "วิทยานิพนธ์"],
        "การสอบ": ["สอบ", "กระดาษคำตอบ"],
        "กรรมการสภามหาวิทยาลัย": ["สภามหาวิทยาลัย", "นายกสภา"],
        "ตำแหน่งวิชาการ": ["ศาสตราจารย์", "รองศาสตราจารย์", "ผู้ช่วยศาสตราจารย์"],
        "ที่พัก": ["ที่พัก", "ค่าห้องพัก"],
        "สวัสดิการ": ["งานศพ", "พวงหรีด"],
    }
    tags = []
    for tag, keywords in tag_rules.items():
        if any(kw.lower() in text for kw in keywords):
            tags.append(tag)
    return tags


def count_baht_values(content: str) -> int:
    """นับจำนวนอัตราเงิน (เลข + 'บาท') ใน chunk — ใช้ประเมินว่า chunk นี้ 'information-dense' แค่ไหน"""
    # จับทั้งเลขอารบิกและเลขไทย
    return len(re.findall(r'[\d๐-๙,]+\s*บาท', content))


def chunk_document() -> list[dict]:
    """Main: แปลง CLAUSES → list ของ chunks พร้อม metadata"""
    chunks = []
    for clause in CLAUSES:
        breadcrumb = build_breadcrumb(clause)
        title = clause.get("title", "")
        content = clause.get("content", "")

        # แตก content ถ้ายาวเกิน
        parts = split_long_content(content, MAX_CHARS)
        total_parts = len(parts)

        for i, part in enumerate(parts, 1):
            # สร้าง chunk text ที่มี breadcrumb นำหน้า (เพื่อให้ embedding ได้ context)
            header = f"[{breadcrumb}] {title}"
            if total_parts > 1:
                header += f"  (ส่วนที่ {i}/{total_parts})"

            chunk_text = f"{header}\n\n{part}"

            # สร้าง chunk_id
            chapter_id = clause.get("chapter") or "0"
            section_id = clause.get("section") or "0"
            item_id = clause.get("item")
            suffix = f"-p{i}" if total_parts > 1 else ""
            chunk_id = f"chula-2563-c{chapter_id}-s{section_id}-i{item_id}{suffix}"

            chunks.append({
                "chunk_id": chunk_id,
                "text": chunk_text,         # ข้อความที่จะส่งเข้า embedding model
                "metadata": {
                    "doc_title": DOC_META["title"],
                    "doc_year_be": DOC_META["year_be"],
                    "doc_year_ce": DOC_META["year_ce"],
                    "chapter": clause.get("chapter"),
                    "chapter_name": clause.get("chapter_name"),
                    "section": clause.get("section"),
                    "section_name": clause.get("section_name"),
                    "item_number": clause.get("item"),
                    "title": title,
                    "breadcrumb": breadcrumb,
                    "page": clause.get("page"),
                    "part_index": i,
                    "part_total": total_parts,
                    "char_count": len(chunk_text),
                    "baht_mentions": count_baht_values(part),
                    "tags": extract_tags(clause),
                },
            })
    return chunks


def summarize(chunks: list[dict]) -> dict:
    """คำนวณสถิติของผลลัพธ์"""
    sizes = [c["metadata"]["char_count"] for c in chunks]
    chapters = {}
    for c in chunks:
        ch = c["metadata"]["chapter"] or "preamble"
        chapters[ch] = chapters.get(ch, 0) + 1
    return {
        "total_chunks": len(chunks),
        "min_chars": min(sizes),
        "max_chars": max(sizes),
        "avg_chars": round(sum(sizes) / len(sizes), 1),
        "chunks_per_chapter": chapters,
        "total_baht_mentions": sum(c["metadata"]["baht_mentions"] for c in chunks),
    }


if __name__ == "__main__":
    chunks = chunk_document()
    stats = summarize(chunks)

    # บันทึกเป็น JSON (รูปแบบที่นำเข้า embedding pipeline ได้ทันที)
    with open("/home/claude/chunks.json", "w", encoding="utf-8") as f:
        json.dump({
            "document": DOC_META,
            "chunking_config": {
                "strategy": "structure-aware (by ข้อ with breadcrumb)",
                "max_chars": MAX_CHARS,
            },
            "stats": stats,
            "chunks": chunks,
        }, f, ensure_ascii=False, indent=2)

    # บันทึกเฉพาะ text + metadata ในรูป JSONL (format ยอดนิยมสำหรับ embedding)
    with open("/home/claude/chunks.jsonl", "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    # พิมพ์สถิติ
    print("=" * 60)
    print("สถิติผลลัพธ์ chunking")
    print("=" * 60)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print()
    print("=" * 60)
    print("ตัวอย่าง chunk (3 ตัวแรก)")
    print("=" * 60)
    for c in chunks[:3]:
        print(f"\n── chunk_id: {c['chunk_id']} ──")
        print(f"char_count: {c['metadata']['char_count']}  |  baht_mentions: {c['metadata']['baht_mentions']}")
        print(f"tags: {c['metadata']['tags']}")
        print(f"breadcrumb: {c['metadata']['breadcrumb']}")
        print("--- text ---")
        print(c["text"][:500] + ("..." if len(c["text"]) > 500 else ""))

    print()
    print("=" * 60)
    print("ตัวอย่างที่ถูก split (ข้อ 11 ที่มีอนุบัญญัติ 18 รายการ)")
    print("=" * 60)
    split_chunks = [c for c in chunks if c["metadata"]["part_total"] > 1]
    if split_chunks:
        for c in split_chunks[:4]:
            print(f"\n── {c['chunk_id']} ({c['metadata']['part_index']}/{c['metadata']['part_total']}) ──")
            print(f"char_count: {c['metadata']['char_count']}  baht_mentions: {c['metadata']['baht_mentions']}")
            print(c["text"][:300] + "...")
    else:
        print("(ไม่มี chunk ไหนถูก split — ทุกข้ออยู่ในขนาดที่กำหนด)")
