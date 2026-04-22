"""Ad-hoc PDF diagnostic for ingest 0-chunk debugging.

Prints page count, encryption, per-page text-layer length, embedded image
resolution, and rendered image preview path. Tells scan vs text-layer vs
hybrid, and shows what resolution Opus will see.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import pymupdf

pdf_path = Path(sys.argv[1])
out_png = pdf_path.with_suffix(".page1.png")

print(f"path   : {pdf_path}")
print(f"size   : {pdf_path.stat().st_size:,} bytes ({pdf_path.stat().st_size / 1_048_576:.2f} MB)")

doc = pymupdf.open(pdf_path)
print(f"encrypt: {doc.is_encrypted}")
print(f"pages  : {doc.page_count}")
print(f"meta   : {doc.metadata}")
print()

total_text = 0
print(f"{'page':>4}  {'text':>5}  {'images':>6}  {'img_wxh':>12}  {'img_bytes':>10}  {'cspace':>10}")
for i, page in enumerate(doc):
    txt = page.get_text("text") or ""
    imgs = page.get_images(full=True)
    total_text += len(txt)
    if imgs:
        xref = imgs[0][0]
        img_info = doc.extract_image(xref)
        w, h = img_info.get("width"), img_info.get("height")
        nbytes = len(img_info.get("image", b""))
        cspace = img_info.get("colorspace")
        cs_name = {1: "gray", 3: "rgb", 4: "cmyk"}.get(cspace, f"cs={cspace}")
        print(f"{i + 1:>4}  {len(txt):>5}  {len(imgs):>6}  {w}x{h:<6}  {nbytes:>10,}  {cs_name:>10}")
    else:
        print(f"{i + 1:>4}  {len(txt):>5}  {len(imgs):>6}  {'—':>12}  {'—':>10}  {'—':>10}")
print()
print(f"TOTAL text chars across all pages: {total_text:,}")

doc[0].get_pixmap(dpi=150).save(out_png)
print(f"page 1 rendered -> {out_png}")
doc.close()
