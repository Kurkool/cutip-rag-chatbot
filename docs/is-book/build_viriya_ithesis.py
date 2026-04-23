"""
Build VIRIYA IS manuscript into the iThesis Next Gen template.

Strategy: open VIRIYA-iThesis.docx (iThesis-generated template) as base, find the
empty placeholder section between "คำอธิบายสัญลักษณ์" and "บรรณานุกรม", and inject
chapter content there using iThesis Heading styles. Also fill bibliography +
appendices from markdown.

User should still fill cover/approval/abstract/acknowledgement via the iThesis
add-in UI in Word (those have specific form-linked fields that the add-in
populates from student metadata).

Run from cutip-rag-chatbot/ dir:
    .venv/Scripts/python.exe docs/is-book/build_viriya_ithesis.py
"""
from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


BASE = Path(__file__).parent
MANUSCRIPT = BASE / "manuscript"
TEMPLATE = BASE / "VIRIYA-iThesis.docx"
import sys as _sys
OUT_PRIMARY = BASE / "VIRIYA-IS-ithesis.docx"
OUT_FALLBACK = BASE / "VIRIYA-IS-ithesis-v2.docx"
try:
    # If primary is open in Word, writing will fail — use fallback
    _test = open(OUT_PRIMARY, "a+b")
    _test.close()
    OUT = OUT_PRIMARY
except (PermissionError, OSError):
    OUT = OUT_FALLBACK
    print(f"(PRIMARY {OUT_PRIMARY.name} locked — saving to {OUT.name} instead)", file=_sys.stderr)

# Order of chapter files to insert
CHAPTER_FILES = [
    "ch01-introduction.md",
    "ch02-literature-review.md",
    "ch03-methodology.md",
    "ch04-results.md",
    "ch05-business-feasibility.md",
    "ch06-financial-feasibility.md",
    "ch07-conclusion.md",
]


def find_insertion_point(doc):
    """Locate the <w:p> element right after "คำอธิบายสัญลักษณ์ (ถ้ามี)" section ends,
    which is where chapters should be inserted.

    Returns the <w:p> element to insert BEFORE.
    """
    body = doc.element.body
    state = "searching"  # searching -> found_abbrev -> found_sect_break_after_abbrev -> insert_here
    for child in list(body.iterchildren()):
        if child.tag != qn("w:p"):
            continue
        # Find style
        pPr = child.find(qn("w:pPr"))
        if pPr is None:
            continue
        pStyle = pPr.find(qn("w:pStyle"))
        style = pStyle.get(qn("w:val")) if pStyle is not None else None
        # Find text
        text = "".join(t.text or "" for t in child.iter(qn("w:t")))
        has_sect_break = pPr.find(qn("w:sectPr")) is not None

        if state == "searching" and style == "iThesisIndex1" and "คำอธิบายสัญลักษณ์" in text:
            state = "found_abbrev"
            continue

        if state == "found_abbrev" and has_sect_break:
            state = "after_abbrev_sect"
            continue

        if state == "after_abbrev_sect":
            # Next paragraph should be where chapters start (currently empty)
            # We insert BEFORE the bibliography paragraph
            if style == "iThesisIndex1" and "บรรณานุกรม" in text:
                return child
    return None


def create_heading_para(doc, text: str, level: int):
    """Create a heading paragraph element with Word's built-in Heading style."""
    para = doc.add_paragraph(text, style=f"Heading {level}")
    # Remove from end of doc (we'll move it into body manually)
    p_element = para._element
    p_element.getparent().remove(p_element)
    return p_element


def create_normal_para(doc, text: str, bold: bool = False):
    para = doc.add_paragraph()
    run = para.add_run(text)
    if bold:
        run.bold = True
    p_element = para._element
    p_element.getparent().remove(p_element)
    return p_element


def create_bullet_para(doc, text: str):
    # iThesis template lacks "List Bullet" — use "List Paragraph" + manual bullet char
    para = doc.add_paragraph(f"•  {text}", style="List Paragraph")
    p_element = para._element
    p_element.getparent().remove(p_element)
    return p_element


def create_number_para(doc, text: str, num: int = 1):
    # iThesis template lacks "List Number" — use "List Paragraph" + manual numbering
    para = doc.add_paragraph(f"{num}.  {text}", style="List Paragraph")
    p_element = para._element
    p_element.getparent().remove(p_element)
    return p_element


def create_table_from_rows(doc, rows: list[list[str]]):
    n_cols = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=n_cols)
    table.style = "Table Grid"
    for r_idx, row in enumerate(rows):
        for c_idx in range(n_cols):
            cell = table.cell(r_idx, c_idx)
            cell.text = row[c_idx] if c_idx < len(row) else ""
            if r_idx == 0:
                for p in cell.paragraphs:
                    for run in p.runs:
                        run.bold = True
    tbl_element = table._element
    tbl_element.getparent().remove(tbl_element)
    return tbl_element


def parse_markdown_table(lines: list[str], start_idx: int) -> tuple[list[list[str]], int]:
    rows = []
    i = start_idx
    while i < len(lines) and lines[i].lstrip().startswith("|"):
        row_raw = lines[i].strip()
        if re.match(r"^\|[\s\-:|]+\|?$", row_raw):
            i += 1
            continue
        cells = [c.strip() for c in row_raw.strip("|").split("|")]
        rows.append(cells)
        i += 1
    return rows, i


def parse_markdown_to_elements(doc, content: str) -> list:
    """Parse markdown and return a list of OxmlElement to insert."""
    elements = []
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Skip HTML comments and tags
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            i += 1
            continue
        if stripped.startswith("<") and stripped.endswith(">"):
            i += 1
            continue

        # Horizontal rule → skip (we rely on heading-based section breaks)
        if stripped == "---":
            i += 1
            continue

        # Headings
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            elements.append(create_heading_para(doc, text, min(level, 9)))
            i += 1
            continue

        # Tables
        if stripped.startswith("|"):
            rows, next_i = parse_markdown_table(lines, i)
            if rows:
                elements.append(create_table_from_rows(doc, rows))
            i = next_i
            continue

        # Bullet list
        if re.match(r"^[-*]\s+", stripped):
            content_text = re.sub(r"^[-*]\s+", "", stripped)
            # Strip markdown bold
            content_text = re.sub(r"\*\*([^*]+)\*\*", r"\1", content_text)
            elements.append(create_bullet_para(doc, content_text))
            i += 1
            continue

        # Numbered list
        m_num = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if m_num:
            num = int(m_num.group(1))
            content_text = m_num.group(2)
            content_text = re.sub(r"\*\*([^*]+)\*\*", r"\1", content_text)
            elements.append(create_number_para(doc, content_text, num=num))
            i += 1
            continue

        # Blockquote
        if stripped.startswith(">"):
            content_text = re.sub(r"^>\s*", "", stripped)
            elements.append(create_normal_para(doc, content_text))
            i += 1
            continue

        # Regular paragraph — may span multiple lines
        para_lines = [stripped]
        j = i + 1
        while j < len(lines):
            nxt = lines[j].strip()
            if not nxt:
                break
            if re.match(r"^#{1,6}\s", nxt):
                break
            if nxt.startswith("|"):
                break
            if nxt == "---":
                break
            if re.match(r"^[-*]\s", nxt) or re.match(r"^\d+\.\s", nxt):
                break
            para_lines.append(nxt)
            j += 1
        merged = " ".join(para_lines)
        # Strip markdown bold notation (iThesis styles control formatting)
        merged = re.sub(r"\*\*([^*]+)\*\*", r"\1", merged)
        # Strip inline code markers
        merged = re.sub(r"`([^`]+)`", r"\1", merged)
        elements.append(create_normal_para(doc, merged))
        i = j

    return elements


def main():
    if not TEMPLATE.exists():
        raise SystemExit(f"Template not found: {TEMPLATE}")

    # Open iThesis template as base
    doc = Document(str(TEMPLATE))

    # Find insertion point (before "บรรณานุกรม" paragraph)
    insertion_point = find_insertion_point(doc)
    if insertion_point is None:
        raise SystemExit("Could not locate insertion point (before บรรณานุกรม). Template structure may have changed.")
    print("Insertion point located.")

    # Build list of elements to insert before bibliography
    elements_to_insert = []

    # Chapters 1-7
    for filename in CHAPTER_FILES:
        path = MANUSCRIPT / filename
        if not path.exists():
            print(f"  WARN: missing {filename}")
            continue
        print(f"  processing {filename}...")
        with path.open(encoding="utf-8") as f:
            content = f.read()
        chapter_elements = parse_markdown_to_elements(doc, content)
        elements_to_insert.extend(chapter_elements)

    # Insert all chapter elements before "บรรณานุกรม" paragraph
    parent = insertion_point.getparent()
    for elem in elements_to_insert:
        parent.insert(list(parent).index(insertion_point), elem)

    # Save
    doc.save(str(OUT))
    print(f"\nSaved: {OUT}")
    print(f"File size: {OUT.stat().st_size:,} bytes")
    print("\nNext steps for user:")
    print("  1. Open VIRIYA-IS-ithesis.docx in Word")
    print("  2. Let iThesis add-in refresh automatically (it detects template)")
    print("  3. Fill cover page / approval / abstract TH / abstract EN / กิตติกรรม")
    print("     via iThesis add-in UI (forms are linked to student metadata)")
    print("  4. Press F9 on TOC to refresh (chapters auto-populate)")
    print("  5. Manually paste manuscript/backmatter.md content into:")
    print("     - บรรณานุกรม section (or use EndNote Update Citations)")
    print("     - ภาคผนวก ก/ข/ค sections")
    print("     - ประวัติผู้เขียน at end")


if __name__ == "__main__":
    main()
