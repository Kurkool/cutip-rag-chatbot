"""Quick assessment of HSM sample docs — ingestion-readiness check.

For each PDF:
- PyMuPDF text layer size (digital vs scanned)
- Table count per page
- Language mix (Thai % / English %)
- Pages with low text (likely-scanned)
- Quick OCR-complexity red flags
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import fitz

DOC_DIR = Path(r"C:\Users\USER\PycharmProjects\TIP-RAG\sample-doc\hsm-doc")


def pct_thai(text: str) -> float:
    if not text:
        return 0.0
    thai = sum(1 for c in text if "\u0e00" <= c <= "\u0e7f")
    latin = sum(1 for c in text if c.isalpha() and not ("\u0e00" <= c <= "\u0e7f"))
    total = thai + latin
    return 100 * thai / total if total else 0.0


def assess(path: Path) -> dict:
    doc = fitz.open(str(path))
    pages = []
    total_text = 0
    total_tables = 0
    low_text_pages = 0
    flags = []
    for i, page in enumerate(doc):
        txt = page.get_text("text")
        tables = list(page.find_tables().tables)
        pages.append({"n": i + 1, "chars": len(txt), "tables": len(tables)})
        total_text += len(txt)
        total_tables += len(tables)
        if len(txt) < 100:
            low_text_pages += 1
        # Check for checkboxes (common in forms)
        if "☐" in txt or "☑" in txt or "□" in txt:
            flags.append(f"p{i+1}:checkboxes")
        # Has images that might be diagrams/flowcharts
        img_list = page.get_images()
        if len(img_list) > 2:
            flags.append(f"p{i+1}:images({len(img_list)})")
    all_text = "\n".join(page.get_text("text") for page in doc)
    thai_pct = pct_thai(all_text)
    doc.close()
    return {
        "file": path.name,
        "size_kb": path.stat().st_size // 1024,
        "pages": len(pages),
        "total_chars": total_text,
        "avg_chars_per_page": total_text // max(1, len(pages)),
        "total_tables": total_tables,
        "low_text_pages": low_text_pages,
        "thai_pct": round(thai_pct, 1),
        "flags": flags[:5],
    }


def main():
    pdfs = sorted(DOC_DIR.glob("*.pdf"))
    print(f"Assessing {len(pdfs)} HSM docs:\n")
    total_pages = 0
    total_vision_needed = 0
    for p in pdfs:
        r = assess(p)
        total_pages += r["pages"]
        total_vision_needed += r["low_text_pages"]
        name = r["file"][:55]
        print(
            f"{name:55s}  {r['pages']:2d}pg  "
            f"{r['avg_chars_per_page']:5d}c/pg  "
            f"tables={r['total_tables']:2d}  "
            f"thai={r['thai_pct']:4.1f}%  "
            f"low_text_pg={r['low_text_pages']}"
        )
        if r["flags"]:
            print(f"{'':55s}  flags: {', '.join(r['flags'])}")
    print(
        f"\nTotal: {len(pdfs)} docs, {total_pages} pages, "
        f"~{total_vision_needed} pages need Vision OCR"
    )


if __name__ == "__main__":
    main()
