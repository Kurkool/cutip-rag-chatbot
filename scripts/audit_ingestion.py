"""Honest audit: compare source PDFs against ingested Pinecone chunks.

For each PDF in sample-doc/cutip-doc/:
  1. Extract raw text with PyMuPDF (ground truth)
  2. Fetch all Pinecone chunks for the same filename
  3. Detect:
     - Vision error messages polluting chunks (indicates failed OCR)
     - Thai names present in source but missing from chunks (dropped content)
     - Total chunk text size vs. source size (coverage ratio)
"""
import os
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import fitz
from pinecone import Pinecone

SAMPLE_DIR = Path(r"C:\Users\USER\PycharmProjects\TIP-RAG\sample-doc\cutip-doc")

# Phrases Haiku Vision emits when it fails/refuses OCR. Any chunk containing
# these is garbage content, not real document text.
VISION_ERROR_PATTERNS = [
    "Ensure the image is clear",
    "Could you please",
    "Re-upload the document",
    "no visible text",
    "convert to Markdown",
    "readable document",
    "file loaded correctly",
]

# Thai-name-candidate pattern: นาย/นางสาว/นาง followed by Thai chars
THAI_NAME_RE = re.compile(r"(?:นาย|นางสาว|นาง)\s*([ก-๙]+(?:\s+[ก-๙]+)?)")


def extract_pdf_text(path: Path) -> str:
    doc = fitz.open(str(path))
    text = "\n".join(p.get_text("text") for p in doc)
    doc.close()
    return text


def fetch_pinecone_chunks(pc: Pinecone, filename: str) -> list[dict]:
    idx = pc.Index("university-rag")
    all_ids = []
    for page in idx.list(namespace="cutip_01"):
        all_ids.extend(page)
    chunks = []
    for i in range(0, len(all_ids), 50):
        batch = idx.fetch(ids=all_ids[i : i + 50], namespace="cutip_01")
        for v in batch.vectors.values():
            meta = v.metadata or {}
            if meta.get("source_filename") == filename:
                chunks.append({
                    "text": str(meta.get("text", "")),
                    "page": meta.get("page"),
                })
    return chunks


def count_vision_errors(chunks: list[dict]) -> int:
    n = 0
    for c in chunks:
        t = c["text"]
        if any(p in t for p in VISION_ERROR_PATTERNS):
            n += 1
    return n


def audit_pdf(pc: Pinecone, path: Path) -> dict:
    src_text = extract_pdf_text(path)
    src_names = set(m.group(0) for m in THAI_NAME_RE.finditer(src_text))
    chunks = fetch_pinecone_chunks(pc, path.name)
    chunk_text = "\n".join(c["text"] for c in chunks)
    dropped = [n for n in src_names if n not in chunk_text]
    return {
        "file": path.name,
        "src_chars": len(src_text),
        "chunk_chars": len(chunk_text),
        "coverage_pct": round(100 * len(chunk_text) / max(1, len(src_text)), 1),
        "n_chunks": len(chunks),
        "vision_error_chunks": count_vision_errors(chunks),
        "src_names": len(src_names),
        "dropped_names": dropped[:5],
        "n_dropped_names": len(dropped),
    }


def main():
    key = subprocess.check_output(
        ["gcloud", "secrets", "versions", "access", "latest", "--secret=PINECONE_API_KEY"],
        shell=True,
    ).decode().strip()
    pc = Pinecone(api_key=key)
    pdfs = sorted(SAMPLE_DIR.glob("*.pdf"))
    print(f"Auditing {len(pdfs)} PDFs...\n")
    for p in pdfs:
        r = audit_pdf(pc, p)
        print(f"{r['file']}")
        print(
            f"  src={r['src_chars']} chunks={r['chunk_chars']} "
            f"coverage={r['coverage_pct']}%  "
            f"vision_err_chunks={r['vision_error_chunks']}/{r['n_chunks']}  "
            f"dropped_names={r['n_dropped_names']}/{r['src_names']}"
        )
        if r["dropped_names"]:
            print(f"  examples of dropped: {r['dropped_names']}")
        print()


if __name__ == "__main__":
    main()
