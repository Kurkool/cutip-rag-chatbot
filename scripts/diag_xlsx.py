"""Diagnose why ตารางเรียน XLSX dropped from 70% (v1) to 21% (v2) coverage.

Dump v2 chunks + v1 chunks + raw source cells side-by-side.
No API cost — Pinecone + local file only.
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
from pinecone import Pinecone

SAMPLE_DIR = Path(r"C:\Users\USER\PycharmProjects\TIP-RAG\sample-doc\cutip-doc")
TARGET = "ตารางเรียน ปี 2568 ปโท และ ปเอก CU-TIP.xlsx"


def fetch_chunks_for_file(pc: Pinecone, namespace: str, filename: str):
    idx = pc.Index("university-rag")
    ids = []
    for page in idx.list(namespace=namespace):
        ids.extend(page)
    out = []
    for i in range(0, len(ids), 50):
        batch = idx.fetch(ids=ids[i:i + 50], namespace=namespace)
        for vid, v in batch.vectors.items():
            meta = v.metadata or {}
            if meta.get("source_filename") == filename:
                out.append({
                    "id": vid,
                    "text": str(meta.get("text", "")),
                    "page": meta.get("page"),
                    "section_path": meta.get("section_path", ""),
                    "has_table": meta.get("has_table"),
                })
    out.sort(key=lambda c: (c.get("page") or 0, c["id"]))
    return out


def dump_source(path: Path):
    xls = pd.ExcelFile(str(path))
    print(f"\n--- SOURCE: {path.name} ---")
    print(f"Sheets: {xls.sheet_names}")
    for sheet in xls.sheet_names:
        df = xls.parse(sheet, header=None)
        print(f"\n  Sheet '{sheet}': {len(df)} rows × {len(df.columns)} cols")
        # full cell dump (non-null)
        for ridx, row in df.iterrows():
            cells = [str(c) for c in row if pd.notna(c)]
            if cells:
                print(f"    [row {ridx:3d}] {' | '.join(cells)[:200]}")


def main():
    key = subprocess.check_output(
        ["gcloud", "secrets", "versions", "access", "latest", "--secret=PINECONE_API_KEY"],
        shell=True,
    ).decode().strip()
    pc = Pinecone(api_key=key)

    src_path = SAMPLE_DIR / TARGET
    if not src_path.exists():
        print(f"Source file not found: {src_path}")
        return

    print("=" * 120)
    print(f"DIAGNOSING: {TARGET}")
    print("=" * 120)

    # 1. Dump raw source cells
    dump_source(src_path)

    # 2. Fetch v2 chunks
    print("\n" + "=" * 120)
    print("V2 CHUNKS (cutip_v2_audit)")
    print("=" * 120)
    v2 = fetch_chunks_for_file(pc, "cutip_v2_audit", TARGET)
    for i, c in enumerate(v2, 1):
        print(f"\n[v2 chunk {i}/{len(v2)}]  page={c['page']}  section='{c['section_path'][:60]}'  has_table={c['has_table']}  len={len(c['text'])}")
        print("  " + c["text"].replace("\n", "\n  ")[:1500])
        if len(c["text"]) > 1500:
            print("  ... [TRUNCATED]")

    # 3. Fetch v1 chunks
    print("\n" + "=" * 120)
    print("V1 CHUNKS (cutip_01)")
    print("=" * 120)
    v1 = fetch_chunks_for_file(pc, "cutip_01", TARGET)
    for i, c in enumerate(v1, 1):
        print(f"\n[v1 chunk {i}/{len(v1)}]  page={c['page']}  has_table={c['has_table']}  len={len(c['text'])}")
        print("  " + c["text"].replace("\n", "\n  ")[:1500])
        if len(c["text"]) > 1500:
            print("  ... [TRUNCATED]")

    # 4. What's in v1 but NOT in v2 (content diff heuristic)
    print("\n" + "=" * 120)
    print("CONTENT IN V1 BUT MISSING FROM V2 (substring heuristic)")
    print("=" * 120)
    v1_merged = "\n".join(c["text"] for c in v1)
    v2_merged = "\n".join(c["text"] for c in v2)
    # find distinct lines in v1 not in v2
    v1_lines = {l.strip() for l in v1_merged.split("\n") if len(l.strip()) > 10}
    missing_in_v2 = [l for l in v1_lines if l not in v2_merged]
    print(f"Lines in v1 (>10 chars) not found in v2: {len(missing_in_v2)}/{len(v1_lines)}")
    for l in missing_in_v2[:40]:
        print(f"  - {l[:180]}")

    # 5. Coverage stats
    print("\n" + "=" * 120)
    print("SUMMARY")
    print("=" * 120)
    src_text = ""
    xls = pd.ExcelFile(str(src_path))
    for sheet in xls.sheet_names:
        df = xls.parse(sheet, header=None)
        for _, row in df.iterrows():
            for cell in row:
                if pd.notna(cell):
                    src_text += str(cell) + "\n"
    print(f"source chars:          {len(src_text)}")
    print(f"v1 chunks: {len(v1):3d}  merged chars: {len(v1_merged):5d}  ratio: {100*len(v1_merged)/max(1,len(src_text)):.1f}%")
    print(f"v2 chunks: {len(v2):3d}  merged chars: {len(v2_merged):5d}  ratio: {100*len(v2_merged)/max(1,len(src_text)):.1f}%")


if __name__ == "__main__":
    main()
