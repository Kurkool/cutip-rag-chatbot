# Ingest v2 Text-Only Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a text-only branch to `opus_parse_and_chunk` that drops the PDF `document` content block when content is already OCR'd, unifying two input sources (pure-scan PDFs after Haiku OCR, `.ocr.docx` files from `scripts/ocr_pdf_via_opus.py`) into one downstream path to Opus 4.7. Preserves smart chunking (`page`, `section_path`, `has_table`). Backward compatible — text-layer PDFs and non-OCR'd DOCX/XLSX/PPTX untouched.

**Architecture:** Both OCR'd sources normalize to `ocr_sidecar: dict[int, str]`. A new helper `_read_ocr_docx_as_pages` parses `.ocr.docx` into that dict (splitting on `หน้า N` level-2 headings); the existing `ocr_pdf_pages` already produces that shape for pure-scan PDFs. `ingest_v2` routes `.ocr.docx` through the new helper and skips `ensure_pdf`. `opus_parse_and_chunk` gains a `pdf_bytes: bytes | None` signature and branches on `ocr_sidecar is not None`: text-only sends one `text` block with page-delineated OCR content; the original path (document block + text block) is unchanged for text-layer PDFs.

**Tech Stack:** Python 3.11, python-docx 1.1+, pymupdf, langchain-anthropic + langchain-core (Opus 4.7 via ChatAnthropic), pytest + pytest-asyncio.

**Spec:** [`docs/superpowers/specs/2026-04-22-ingest-v2-text-only-path-design.md`](../specs/2026-04-22-ingest-v2-text-only-path-design.md)

**Branch:** `feat/ingest-robustness` (continuation — spec already committed as `58dc7a6` + `43b3455`)

---

## File Map

| File | Change |
|---|---|
| `ingest/services/ingestion_v2.py` | Modify `OCR_PROMPT` constant (align with standalone script); add `_read_ocr_docx_as_pages`; add `_format_pages_for_text_only`; modify `opus_parse_and_chunk` (signature + text-only branch); modify `ingest_v2` (`.ocr.docx` branch before `ensure_pdf`). |
| `ingest/services/_v2_prompts.py` | Add `USER_PROMPT_TEMPLATE_TEXT_ONLY` constant. |
| `tests/test_ingestion_v2.py` | Add 9 new tests across tasks 1, 2, 3, 5, 6. |

---

## Task 1: Add `_read_ocr_docx_as_pages` helper

**Why:** Parse `.ocr.docx` into the same `dict[int, str]` shape that `ocr_pdf_pages` already produces for pure-scan PDFs. Downstream `opus_parse_and_chunk` can then treat both sources identically.

**Files:**
- Modify: `cutip-rag-chatbot/ingest/services/ingestion_v2.py` (add helper near `ocr_pdf_pages`)
- Test: `cutip-rag-chatbot/tests/test_ingestion_v2.py` (add 3 tests)

- [ ] **Step 1: Write failing test — happy path (page headings split correctly)**

Append to `tests/test_ingestion_v2.py`:

```python
def test_read_ocr_docx_as_pages_splits_on_page_headings():
    """Docx with 'หน้า N' level-2 headings → pages keyed by N with joined paragraph text."""
    import io
    from docx import Document as DocxDocument

    docx = DocxDocument()
    docx.add_heading("doc title", level=1)            # ignored (level 1)
    docx.add_heading("หน้า 1", level=2)
    docx.add_paragraph("first para of page 1")
    docx.add_paragraph("second para of page 1")
    docx.add_heading("หน้า 2", level=2)
    docx.add_paragraph("only para of page 2")
    buf = io.BytesIO()
    docx.save(buf)

    result = ingestion_v2._read_ocr_docx_as_pages(buf.getvalue())

    assert result == {
        1: "first para of page 1\nsecond para of page 1",
        2: "only para of page 2",
    }
```

- [ ] **Step 2: Run test to verify it fails (no function yet)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py::test_read_ocr_docx_as_pages_splits_on_page_headings -v`
Expected: FAIL with `AttributeError: module 'ingest.services.ingestion_v2' has no attribute '_read_ocr_docx_as_pages'`

- [ ] **Step 3: Write failing test — fallback when no page markers**

Append:

```python
def test_read_ocr_docx_as_pages_fallback_single_page_when_no_markers():
    """Docx without any 'หน้า N' heading → all paragraphs join into page 1."""
    import io
    from docx import Document as DocxDocument

    docx = DocxDocument()
    docx.add_paragraph("alpha")
    docx.add_paragraph("beta")
    docx.add_paragraph("gamma")
    buf = io.BytesIO()
    docx.save(buf)

    result = ingestion_v2._read_ocr_docx_as_pages(buf.getvalue())

    assert result == {1: "alpha\nbeta\ngamma"}
```

- [ ] **Step 4: Write failing test — corrupt bytes raise ValueError**

Append:

```python
def test_read_ocr_docx_as_pages_raises_on_corrupt_bytes():
    """python-docx's PackageNotFoundError is wrapped in ValueError for callers."""
    with pytest.raises(ValueError, match="not a valid .ocr.docx"):
        ingestion_v2._read_ocr_docx_as_pages(b"this is not a zip file")
```

- [ ] **Step 5: Run all 3 tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k "test_read_ocr_docx_as_pages" -v`
Expected: 3 FAILs — all with `AttributeError`.

- [ ] **Step 6: Implement `_read_ocr_docx_as_pages` in `ingest/services/ingestion_v2.py`**

Locate the section after `ocr_pdf_pages` (around line 125) and add:

```python
import io
import re

_OCR_DOCX_PAGE_HEADING_RE = re.compile(r"^หน้า\s+(\d+)\s*$")


def _read_ocr_docx_as_pages(file_bytes: bytes) -> dict[int, str]:
    """Parse a .ocr.docx (produced by ``scripts/ocr_pdf_via_opus.py``) into
    ``{1-based page: joined text}`` matching ``ocr_pdf_pages``'s shape.

    The script writes: level-1 heading (doc title, ignored) → level-2
    ``หน้า N`` heading opening each page → paragraphs with OCR'd text.
    This parser walks paragraphs in document order; a Heading 2 matching
    ``r'^หน้า\\s+(\\d+)$'`` opens a new page bucket, subsequent non-heading
    paragraphs accumulate into it joined by ``\\n``.

    Fallback: if no page markers are found (hand-edited or tool-produced
    docx), return ``{1: <all paragraphs joined>}`` so ingest proceeds as
    single-page rather than fails outright.

    Raises ``ValueError`` when python-docx cannot open the bytes (wraps
    ``docx.opc.exceptions.PackageNotFoundError`` so callers see a stable
    exception type).
    """
    from docx import Document as DocxDocument
    from docx.opc.exceptions import PackageNotFoundError

    try:
        doc = DocxDocument(io.BytesIO(file_bytes))
    except PackageNotFoundError as exc:
        raise ValueError(f"not a valid .ocr.docx: {exc}") from exc

    pages: dict[int, list[str]] = {}
    current_page: int | None = None

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style_name = (para.style.name or "") if para.style else ""
        if style_name == "Heading 2":
            m = _OCR_DOCX_PAGE_HEADING_RE.match(text)
            if m:
                current_page = int(m.group(1))
                pages.setdefault(current_page, [])
                continue
            # Other level-2 headings (unexpected) — fall through as content
            # on the currently open page, if any.
        if current_page is None:
            continue
        pages[current_page].append(text)

    if not pages:
        # No page markers — collect all non-empty paragraphs into page 1.
        joined = "\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())
        return {1: joined}

    return {p: "\n".join(lines) for p, lines in pages.items()}
```

- [ ] **Step 7: Run the 3 tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k "test_read_ocr_docx_as_pages" -v`
Expected: 3 PASS.

- [ ] **Step 8: Run the full ingestion_v2 test module to catch regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -v`
Expected: all previous tests still pass (25+ pass total, no failures).

- [ ] **Step 9: Commit**

```bash
git add ingest/services/ingestion_v2.py tests/test_ingestion_v2.py
git commit -m "feat(ingest-v2): add _read_ocr_docx_as_pages helper

Parses .ocr.docx produced by scripts/ocr_pdf_via_opus.py into the same
{page: text} dict shape as ocr_pdf_pages. Splits on level-2 'หน้า N'
headings; falls back to single-page when no markers exist; wraps
python-docx PackageNotFoundError in ValueError for a stable exception
contract.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Add `_format_pages_for_text_only` helper

**Why:** Render `ocr_sidecar: dict[int, str]` as a single string for the text-only Opus prompt. Uses `### Page N` page markers (matching existing `format_ocr_sidecar` convention so chunk `page` field attribution is consistent). Distinct from `format_ocr_sidecar` because text-only has no "treat rendered image as ground truth" preamble — the text IS the ground truth.

**Files:**
- Modify: `cutip-rag-chatbot/ingest/services/ingestion_v2.py`
- Test: `cutip-rag-chatbot/tests/test_ingestion_v2.py`

- [ ] **Step 1: Write failing test — empty dict returns placeholder**

Append to `tests/test_ingestion_v2.py`:

```python
def test_format_pages_for_text_only_empty_returns_placeholder():
    result = ingestion_v2._format_pages_for_text_only({})
    assert result == "(empty document)"
```

- [ ] **Step 2: Write failing test — populated dict has `### Page N` markers**

Append:

```python
def test_format_pages_for_text_only_has_page_markers_and_content():
    result = ingestion_v2._format_pages_for_text_only({
        1: "alpha text",
        2: "beta text",
    })
    # Page markers use "### Page N" (matches format_ocr_sidecar convention).
    assert "### Page 1" in result
    assert "### Page 2" in result
    # Content preserved in order.
    i1 = result.index("alpha text")
    i2 = result.index("beta text")
    assert i1 < i2
```

- [ ] **Step 3: Run both tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k "test_format_pages_for_text_only" -v`
Expected: 2 FAILs with `AttributeError: module 'ingest.services.ingestion_v2' has no attribute '_format_pages_for_text_only'`

- [ ] **Step 4: Implement `_format_pages_for_text_only`**

Add to `ingest/services/ingestion_v2.py` immediately after `_read_ocr_docx_as_pages`:

```python
def _format_pages_for_text_only(ocr_sidecar: dict[int, str]) -> str:
    """Render per-page OCR text for the text-only Opus prompt (no PDF block).

    Distinct from ``format_ocr_sidecar`` (in ``_v2_prompts``) which treats
    the rendered PDF image as ground truth and OCR as assistive. Here the
    text IS the ground truth — Opus has no image to cross-check. Page
    markers use ``### Page N`` to match ``format_ocr_sidecar``'s convention
    so chunk ``page`` attribution is consistent regardless of which path
    produced the text.
    """
    if not ocr_sidecar:
        return "(empty document)"
    lines: list[str] = []
    for page_num in sorted(ocr_sidecar.keys()):
        text = ocr_sidecar[page_num]
        lines.append(f"### Page {page_num}")
        lines.append(text if text else "(no text extracted on this page)")
        lines.append("")
    return "\n".join(lines).rstrip()
```

- [ ] **Step 5: Run both tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k "test_format_pages_for_text_only" -v`
Expected: 2 PASS.

- [ ] **Step 6: Commit**

```bash
git add ingest/services/ingestion_v2.py tests/test_ingestion_v2.py
git commit -m "feat(ingest-v2): add _format_pages_for_text_only helper

Renders ocr_sidecar dict as a single prompt string with '### Page N'
markers (matching format_ocr_sidecar's convention) for use in the
text-only Opus branch where there is no PDF image to cross-check. Empty
dict returns a placeholder so the prompt template substitution never
produces a blank block.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Add `USER_PROMPT_TEMPLATE_TEXT_ONLY` to prompts module

**Why:** The existing `USER_PROMPT_TEMPLATE` says "Parse the attached PDF" — wrong for text-only path. A parallel template tells Opus there is no PDF attached and the text block is authoritative.

**Files:**
- Modify: `cutip-rag-chatbot/ingest/services/_v2_prompts.py`
- Test: `cutip-rag-chatbot/tests/test_ingestion_v2.py`

- [ ] **Step 1: Write failing test — template has the right placeholders**

Append to `tests/test_ingestion_v2.py`:

```python
def test_user_prompt_template_text_only_has_required_placeholders():
    from ingest.services._v2_prompts import USER_PROMPT_TEMPLATE_TEXT_ONLY
    assert "{filename}" in USER_PROMPT_TEMPLATE_TEXT_ONLY
    assert "{sidecar_block}" in USER_PROMPT_TEMPLATE_TEXT_ONLY
    assert "{page_text_block}" in USER_PROMPT_TEMPLATE_TEXT_ONLY
    # Must NOT tell Opus to parse an attached PDF (there is no PDF block).
    assert "attached PDF" not in USER_PROMPT_TEMPLATE_TEXT_ONLY
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py::test_user_prompt_template_text_only_has_required_placeholders -v`
Expected: FAIL with `ImportError: cannot import name 'USER_PROMPT_TEMPLATE_TEXT_ONLY'`

- [ ] **Step 3: Add the template constant**

In `ingest/services/_v2_prompts.py`, add immediately after `USER_PROMPT_TEMPLATE` (around line 36):

```python
USER_PROMPT_TEMPLATE_TEXT_ONLY = """Document filename: {filename}

The document below has been pre-OCR'd; no PDF is attached. Use the text as the sole source of truth and produce chunks via the `record_chunks` tool.

Page boundaries are marked with `### Page N` — use them to set each chunk's `page` field.

Hyperlink sidecar (URIs hidden in PDF annotations, not visible on the rendered page):
{sidecar_block}

{page_text_block}
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py::test_user_prompt_template_text_only_has_required_placeholders -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ingest/services/_v2_prompts.py tests/test_ingestion_v2.py
git commit -m "feat(ingest-v2): add USER_PROMPT_TEMPLATE_TEXT_ONLY

Parallel to USER_PROMPT_TEMPLATE but for the text-only Opus path where no
PDF document block is attached. Tells Opus the text is authoritative and
explains the '### Page N' marker convention for chunk.page attribution.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Align `OCR_PROMPT` constant with standalone script

**Why:** The in-pipeline Haiku 4.5 OCR (`ocr_pdf_pages`) currently asks for "โครงสร้าง ... ตาราง" but doesn't specify output format. The standalone `scripts/ocr_pdf_via_opus.py` uses markdown pipe format for tables, which is what Opus chunker expects downstream for `has_table=true` detection. Without this alignment, pure-scan PDFs going through C1 would lose table structure under the text-only path.

**Files:**
- Modify: `cutip-rag-chatbot/ingest/services/ingestion_v2.py` (constant around line 54–59)

No tests — prompt string content is brittle to test directly; end-to-end ingest on the `.ocr.docx` sample and a pure-scan PDF will validate `has_table` propagation.

- [ ] **Step 1: Update `OCR_PROMPT`**

In `ingest/services/ingestion_v2.py`, replace:

```python
OCR_PROMPT = (
    "สกัดข้อความทั้งหมดที่มองเห็นจากภาพสแกนหน้านี้ "
    "คงรูปโครงสร้าง (หัวข้อ ย่อหน้า รายการหัวข้อ ตาราง) เท่าที่ทำได้. "
    "ไม่ต้องใส่คำอธิบายใด ๆ ให้คืนเฉพาะข้อความเท่านั้น. "
    "ถ้ามีภาษาอังกฤษปนให้คงไว้ตามต้นฉบับ."
)
```

with:

```python
OCR_PROMPT = (
    "สกัดข้อความทั้งหมดที่มองเห็นจากภาพสแกนหน้านี้ "
    "คงรูปโครงสร้าง (หัวข้อ ย่อหน้า รายการหัวข้อ ตาราง) เท่าที่ทำได้ "
    "- หัวข้อให้ขึ้นบรรทัดใหม่ "
    "- ตารางให้ใช้ pipe markdown | col1 | col2 | "
    "- ไม่ต้องใส่คำอธิบายใด ๆ หรือบอกว่าเป็นภาพอะไร ให้คืนเฉพาะข้อความ "
    "- ถ้ามีภาษาอังกฤษปนให้คงไว้ตามต้นฉบับ"
)
```

- [ ] **Step 2: Run the full ingestion_v2 test module to verify no regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -v`
Expected: all tests still pass.

- [ ] **Step 3: Commit**

```bash
git add ingest/services/ingestion_v2.py
git commit -m "refactor(ingest-v2): align OCR_PROMPT with standalone ocr script

Haiku in-pipeline OCR now uses the same prompt style as
scripts/ocr_pdf_via_opus.py — explicit pipe-markdown table format and an
instruction not to describe what the image is. Ensures tables survive
the upcoming text-only path with structure preserved so Opus chunker
can detect has_table=true.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Branch `opus_parse_and_chunk` on `ocr_sidecar`

**Why:** Core change. When `ocr_sidecar is not None`, send ONE `text` content block (no `document` block). The existing path (document block + text block) stays for text-layer PDFs where `ocr_sidecar is None`.

**Files:**
- Modify: `cutip-rag-chatbot/ingest/services/ingestion_v2.py` (lines 240–329, function `opus_parse_and_chunk`)
- Test: `cutip-rag-chatbot/tests/test_ingestion_v2.py`

**Note:** Existing test `test_opus_parse_and_chunk_injects_ocr_sidecar` (line ~401) tests the ocr_sidecar-populated path. Under the new design, that path no longer sends a `document` block. The existing assertions (`"hello from page 1" in t`, `"### Page 1" in t`) stay valid — `### Page 1` format is preserved via `_format_pages_for_text_only`. No update to that test needed.

- [ ] **Step 1: Write failing test — text-only path omits document block**

Append to `tests/test_ingestion_v2.py`:

```python
@pytest.mark.asyncio
async def test_opus_parse_and_chunk_text_only_omits_document_block(
    monkeypatch, pure_scan_pdf_bytes
):
    """With ocr_sidecar populated, the human message must have ONE text block and NO document block."""
    from unittest.mock import AsyncMock, MagicMock

    captured: dict = {}
    fake_llm = MagicMock()

    async def fake_ainvoke(messages):
        captured["content"] = messages[1].content
        return MagicMock(tool_calls=[{"args": {"chunks": []}}])

    fake_llm.ainvoke = AsyncMock(side_effect=fake_ainvoke)
    fake_llm.bind_tools = MagicMock(return_value=fake_llm)

    ingestion_v2._get_opus_llm.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_opus_llm", lambda: fake_llm)

    await ingestion_v2.opus_parse_and_chunk(
        pdf_bytes=pure_scan_pdf_bytes,
        hyperlinks=[],
        filename="x.pdf",
        ocr_sidecar={1: "only page"},
    )

    blocks = captured["content"]
    block_types = [b.get("type") for b in blocks]
    assert block_types == ["text"], f"expected ['text'], got {block_types}"
    assert "only page" in blocks[0]["text"]
    assert "### Page 1" in blocks[0]["text"]
```

- [ ] **Step 2: Write failing test — text-only accepts `pdf_bytes=None`**

Append:

```python
@pytest.mark.asyncio
async def test_opus_parse_and_chunk_text_only_accepts_none_pdf_bytes(
    monkeypatch,
):
    """For .ocr.docx (no PDF at all), pdf_bytes=None must not crash the text-only path."""
    from unittest.mock import AsyncMock, MagicMock

    captured: dict = {}
    fake_llm = MagicMock()

    async def fake_ainvoke(messages):
        captured["content"] = messages[1].content
        return MagicMock(tool_calls=[{"args": {"chunks": []}}])

    fake_llm.ainvoke = AsyncMock(side_effect=fake_ainvoke)
    fake_llm.bind_tools = MagicMock(return_value=fake_llm)

    ingestion_v2._get_opus_llm.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_opus_llm", lambda: fake_llm)

    chunks = await ingestion_v2.opus_parse_and_chunk(
        pdf_bytes=None,
        hyperlinks=[],
        filename="y.ocr.docx",
        ocr_sidecar={1: "aaa", 2: "bbb"},
    )

    # Confirms no exception, content is text-only.
    assert chunks == []
    block_types = [b.get("type") for b in captured["content"]]
    assert block_types == ["text"]
    assert "aaa" in captured["content"][0]["text"]
    assert "bbb" in captured["content"][0]["text"]
```

- [ ] **Step 3: Write failing test — PDF path (ocr_sidecar=None) keeps document block**

Append:

```python
@pytest.mark.asyncio
async def test_opus_parse_and_chunk_pdf_path_keeps_document_block(
    monkeypatch, pure_scan_pdf_bytes
):
    """Regression guard: text-layer PDF path still sends document + text blocks."""
    from unittest.mock import AsyncMock, MagicMock

    captured: dict = {}
    fake_llm = MagicMock()

    async def fake_ainvoke(messages):
        captured["content"] = messages[1].content
        return MagicMock(tool_calls=[{"args": {"chunks": []}}])

    fake_llm.ainvoke = AsyncMock(side_effect=fake_ainvoke)
    fake_llm.bind_tools = MagicMock(return_value=fake_llm)

    ingestion_v2._get_opus_llm.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_opus_llm", lambda: fake_llm)

    await ingestion_v2.opus_parse_and_chunk(
        pdf_bytes=pure_scan_pdf_bytes,
        hyperlinks=[],
        filename="x.pdf",
        ocr_sidecar=None,
    )

    block_types = [b.get("type") for b in captured["content"]]
    assert block_types == ["document", "text"], f"expected document+text, got {block_types}"
```

- [ ] **Step 4: Run the 3 new tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k "text_only_omits or text_only_accepts or pdf_path_keeps" -v`
Expected: 3 FAILs.

- [ ] **Step 5: Replace `opus_parse_and_chunk` implementation**

In `ingest/services/ingestion_v2.py`, locate the function (starts around line 240). Replace the full function body with:

```python
async def opus_parse_and_chunk(
    pdf_bytes: bytes | None,
    hyperlinks: list[dict],
    filename: str,
    ocr_sidecar: dict[int, str] | None = None,
) -> list[Document]:
    """Send PDF + sidecar (or text-only content) to Opus 4.7 with auto tool use, return chunks.

    Two content-block shapes:

    1. **Text-only path** (``ocr_sidecar is not None``): single ``text`` block
       with filename, hyperlink sidecar, and page-delineated OCR text. No
       PDF ``document`` block. Used for pure-scan PDFs (Haiku OCR output)
       and ``.ocr.docx`` files (paragraph extraction). Empirically Opus
       silent-fails on the document-block path for long dense Thai legal
       scans; text-only keeps the smart-chunking contract without the
       failure mode.

    2. **PDF path** (``ocr_sidecar is None``): legacy shape — ``document``
       block (base64 PDF) + ``text`` block (filename + hyperlink sidecar +
       empty OCR sidecar placeholder). Used for text-layer PDFs where
       Anthropic's internal PDF processing is reliable. Unchanged.

    Both paths use ``tool_choice={"type": "auto"}`` + ``record_chunks``
    tool schema (see :func:`_get_opus_llm` docstring for why forced
    tool_choice is not used).

    Returns a list of LangChain ``Document`` objects with metadata
    ``{page, section_path, has_table}``. Empty / refusal / malformed
    responses return ``[]``.
    """
    from ingest.services._v2_prompts import (
        USER_PROMPT_TEMPLATE_TEXT_ONLY,
    )

    sidecar_block = format_sidecar(hyperlinks)

    if ocr_sidecar is not None:
        # Text-only path: no document block.
        page_text_block = _format_pages_for_text_only(ocr_sidecar)
        user_text = USER_PROMPT_TEMPLATE_TEXT_ONLY.format(
            filename=filename,
            sidecar_block=sidecar_block,
            page_text_block=page_text_block,
        )
        human_content: list[dict] = [{"type": "text", "text": user_text}]
    else:
        # Legacy PDF path: document block + text block.
        if pdf_bytes is None:
            raise ValueError(
                "opus_parse_and_chunk: pdf_bytes cannot be None when ocr_sidecar is None"
            )
        pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
        ocr_block = format_ocr_sidecar({})  # always empty on this path
        user_text = USER_PROMPT_TEMPLATE.format(
            filename=filename,
            sidecar_block=sidecar_block,
            ocr_block=ocr_block,
        )
        human_content = [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": pdf_b64,
                },
            },
            {"type": "text", "text": user_text},
        ]

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=human_content),
    ]

    llm = _get_opus_llm().bind_tools(
        [CHUNK_TOOL_SCHEMA],
        tool_choice={"type": "auto"},
    )
    response = await llm.ainvoke(messages)

    tool_calls = getattr(response, "tool_calls", None) or []
    if not tool_calls:
        logger.warning(
            "opus_parse_and_chunk(%s): no tool_call in response — returning []",
            filename,
        )
        return []

    raw_chunks = tool_calls[0].get("args", {}).get("chunks", [])
    cleaned: list[Document] = []
    for c in raw_chunks:
        text = (c.get("text") or "").strip()
        if not text:
            continue
        if _looks_like_refusal(text):
            logger.warning(
                "opus_parse_and_chunk(%s): dropping refusal-pattern chunk on page %s",
                filename, c.get("page", "?"),
            )
            continue
        cleaned.append(Document(
            page_content=text,
            metadata={
                "page": int(c.get("page", 1)),
                "section_path": c.get("section_path", ""),
                "has_table": bool(c.get("has_table", False)),
            },
        ))
    return cleaned
```

Also ensure the import at the top of `ingestion_v2.py` still includes what we need — the existing imports already have `from ingest.services._v2_prompts import ... format_ocr_sidecar`. Verify:

```bash
grep -n "from ingest.services._v2_prompts" ingest/services/ingestion_v2.py
```

Expected output shows the existing import block. No change needed there (we add a local import for `USER_PROMPT_TEMPLATE_TEXT_ONLY` inside the function to keep the diff tight).

- [ ] **Step 6: Run the 3 new tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k "text_only_omits or text_only_accepts or pdf_path_keeps" -v`
Expected: 3 PASS.

- [ ] **Step 7: Run the full ingestion_v2 test module to catch regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -v`
Expected: all tests pass. Pay attention to `test_opus_parse_and_chunk_injects_ocr_sidecar` and `test_opus_parse_and_chunk_without_ocr_sidecar_uses_placeholder` — both should still pass unchanged.

- [ ] **Step 8: Commit**

```bash
git add ingest/services/ingestion_v2.py tests/test_ingestion_v2.py
git commit -m "feat(ingest-v2): branch opus_parse_and_chunk on ocr_sidecar

When ocr_sidecar is populated (pure-scan PDF post-Haiku OCR, or .ocr.docx),
send a single text content block with page-delineated OCR content — no PDF
document block. Empirically Opus silent-fails on the document-block path
for long dense Thai legal scans even with an OCR sidecar; text-only keeps
smart-chunking intact without triggering the failure mode.

Signature change: pdf_bytes is now Optional[bytes]. Callers passing None
MUST also pass ocr_sidecar (guarded with ValueError).

Text-layer PDFs (ocr_sidecar=None) take the legacy document-block path
unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Add `.ocr.docx` branch to `ingest_v2`

**Why:** Route `.ocr.docx` files past `ensure_pdf` (LibreOffice conversion) and `extract_page_text` (text-layer detection) — those are irrelevant when we already have clean text from the docx.

**Files:**
- Modify: `cutip-rag-chatbot/ingest/services/ingestion_v2.py` (function `ingest_v2`, lines ~332–393)
- Test: `cutip-rag-chatbot/tests/test_ingestion_v2.py`

- [ ] **Step 1: Write failing test — `.ocr.docx` skips LibreOffice + extract_hyperlinks**

Append to `tests/test_ingestion_v2.py`:

```python
@pytest.mark.asyncio
async def test_ingest_v2_ocr_docx_skips_libreoffice_and_hyperlinks(
    monkeypatch,
):
    """Filename ending in .ocr.docx → read docx paragraphs, skip ensure_pdf + extract_hyperlinks."""
    import io
    from docx import Document as DocxDocument
    from unittest.mock import AsyncMock

    # Build a minimal .ocr.docx with 2 pages.
    docx = DocxDocument()
    docx.add_heading("title", level=1)
    docx.add_heading("หน้า 1", level=2)
    docx.add_paragraph("page one body")
    docx.add_heading("หน้า 2", level=2)
    docx.add_paragraph("page two body")
    buf = io.BytesIO()
    docx.save(buf)
    docx_bytes = buf.getvalue()

    captured: dict = {"ensure_pdf_called": False, "hyperlinks_called": False}

    def fake_ensure_pdf(blob, fn):
        captured["ensure_pdf_called"] = True
        return b""

    def fake_extract_hyperlinks(pdf):
        captured["hyperlinks_called"] = True
        return []

    async def fake_opus(pdf_bytes, hyperlinks, filename, ocr_sidecar=None):
        captured["opus_pdf_bytes"] = pdf_bytes
        captured["opus_hyperlinks"] = hyperlinks
        captured["opus_ocr_sidecar"] = ocr_sidecar
        return []

    async def fake_upsert(chunks, namespace, extra_metadata):
        return len(chunks)

    monkeypatch.setattr(ingestion_v2, "ensure_pdf", fake_ensure_pdf)
    monkeypatch.setattr(ingestion_v2, "extract_hyperlinks", fake_extract_hyperlinks)
    monkeypatch.setattr(ingestion_v2, "opus_parse_and_chunk", fake_opus)

    import ingest.services.ingest_helpers as v1_mod
    monkeypatch.setattr(v1_mod, "_upsert", fake_upsert)

    result = await ingestion_v2.ingest_v2(
        file_bytes=docx_bytes,
        filename="ประกาศ.ocr.docx",
        namespace="ns-test",
        tenant_id="t",
    )

    assert result == 0
    assert captured["ensure_pdf_called"] is False
    assert captured["hyperlinks_called"] is False
    assert captured["opus_pdf_bytes"] is None
    assert captured["opus_hyperlinks"] == []
    assert captured["opus_ocr_sidecar"] == {
        1: "page one body",
        2: "page two body",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py::test_ingest_v2_ocr_docx_skips_libreoffice_and_hyperlinks -v`
Expected: FAIL — either `ensure_pdf` was called (assertion fails) or LibreOffice import blows up depending on how the fake was set up.

- [ ] **Step 3: Modify `ingest_v2` to add the `.ocr.docx` branch**

In `ingest/services/ingestion_v2.py`, replace the body of `ingest_v2` (roughly lines 356–393) with:

```python
async def ingest_v2(
    file_bytes: bytes,
    filename: str,
    namespace: str,
    tenant_id: str,
    doc_category: str = "general",
    url: str = "",
    download_link: str = "",
    drive_file_id: str = "",
) -> int:
    """v2 universal ingestion entrypoint.

    Pipeline:
      1. Route by filename:
         - ``.ocr.docx`` → ``_read_ocr_docx_as_pages`` → text-only Opus path
         - other → ``ensure_pdf`` + pure-scan detection → OCR or not → Opus
      2. ``opus_parse_and_chunk`` returns chunks with page/section_path/has_table
      3. ``_upsert`` (reused from v1) — Cohere embed, Pinecone atomic swap,
         BM25 cross-process invalidation

    ``drive_file_id`` (optional) stores the Drive file ID in chunk metadata
    so admin delete can remove the Drive file by ID even after rename —
    name-based lookup breaks when users rename files in Drive after ingest.
    """
    from ingest.services.ingest_helpers import _build_metadata, _upsert

    pdf_bytes: bytes | None
    hyperlinks: list[dict]
    ocr_sidecar: dict[int, str] | None

    if filename.lower().endswith(".ocr.docx"):
        # OCR'd content already — skip LibreOffice + PDF path entirely.
        ocr_sidecar = _read_ocr_docx_as_pages(file_bytes)
        pdf_bytes = None
        hyperlinks = []
        logger.info(
            "ingest_v2(%s): .ocr.docx detected — %d pages, %d total chars, skipping LibreOffice + PDF path",
            filename, len(ocr_sidecar), sum(len(t) for t in ocr_sidecar.values()),
        )
    else:
        pdf_bytes = ensure_pdf(file_bytes, filename)
        page_text = extract_page_text(pdf_bytes)
        total_text_chars = sum(len(t) for t in page_text.values())
        if total_text_chars <= PURE_SCAN_TEXT_THRESHOLD:
            logger.info(
                "ingest_v2(%s): pure-scan detected (0 text chars across %d pages), running OCR",
                filename, len(page_text),
            )
            ocr_sidecar = await ocr_pdf_pages(pdf_bytes, filename)
        else:
            logger.debug(
                "ingest_v2(%s): text-layer PDF (%d chars across %d pages), OCR skipped",
                filename, total_text_chars, len(page_text),
            )
            ocr_sidecar = None
        hyperlinks = extract_hyperlinks(pdf_bytes)

    chunks = await opus_parse_and_chunk(
        pdf_bytes, hyperlinks, filename, ocr_sidecar=ocr_sidecar,
    )

    if not chunks:
        logger.warning("ingest_v2(%s): Opus returned 0 chunks — nothing upserted", filename)
        return 0

    metadata = _build_metadata(
        tenant_id=tenant_id,
        source_type="pdf",  # v2 universalizes to pdf
        source_filename=filename,
        doc_category=doc_category,
        url=url,
        download_link=download_link,
        drive_file_id=drive_file_id,
    )
    return await _upsert(chunks, namespace, metadata)
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py::test_ingest_v2_ocr_docx_skips_libreoffice_and_hyperlinks -v`
Expected: PASS.

- [ ] **Step 5: Run the full ingestion_v2 test module**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -v`
Expected: all tests pass. Pay particular attention to `test_ingest_v2_orchestrates_pipeline`, `test_ingest_v2_pure_scan_triggers_ocr_path`, `test_ingest_v2_text_layer_skips_ocr` — all non-`.ocr.docx` paths should behave as before.

- [ ] **Step 6: Commit**

```bash
git add ingest/services/ingestion_v2.py tests/test_ingestion_v2.py
git commit -m "feat(ingest-v2): route .ocr.docx through text-only Opus path

When filename ends with '.ocr.docx', skip ensure_pdf (LibreOffice) and
extract_hyperlinks. Read docx paragraphs via _read_ocr_docx_as_pages and
pass the resulting {page: text} dict as ocr_sidecar to opus_parse_and_chunk,
which takes its text-only branch. Closes the .ocr.docx silent-fail mode
observed 2026-04-21: LibreOffice-converted PDFs with Courier-declared Thai
runs triggered Opus zero-chunk responses.

Text-layer PDFs, non-OCR'd DOCX/XLSX/PPTX, and pure-scan PDFs
unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Full test suite + end-to-end verification

**Why:** Catch any unexpected regressions across the 237-test suite, confirm lint, and prepare a smoke-test checklist for post-deploy.

**Files:** no code changes.

- [ ] **Step 1: Run the full backend test suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all tests pass (previously 237 pre-branch, now ~246 with the 9 new tests added across tasks 1, 2, 3, 5, 6; actual count may differ by a few if any prior test is removed).

If failures: stop and diagnose. Do NOT deploy with red tests.

- [ ] **Step 2: Run mypy / pyflakes if the project uses them**

Check for a lint/type config:

```bash
ls pyproject.toml setup.cfg 2>/dev/null | xargs grep -l "ruff\|mypy\|pyflakes" 2>/dev/null
```

If a config exists, run the configured checker (exact command depends on tool). If no config → skip this step.

- [ ] **Step 3: Verify no stale imports / dead code remain**

Run: `.venv/Scripts/python.exe -c "from ingest.services import ingestion_v2; print(ingestion_v2._read_ocr_docx_as_pages, ingestion_v2._format_pages_for_text_only, ingestion_v2.opus_parse_and_chunk, ingestion_v2.ingest_v2)"`
Expected: 4 `<function ...>` reprs with no import errors.

- [ ] **Step 4: Write deploy smoke-test notes to the spec's Testing section**

This is documentation only. Manually in the Post-deploy smoke test section of the spec file, confirm the existing integration test instructions are still accurate. No code change expected.

- [ ] **Step 5: Summary commit (if anything changed in steps 1–4)**

If any cleanup was needed based on test output, commit those cleanups. If nothing changed, skip this step — the plan is complete as of Task 6.

- [ ] **Step 6: Push guidance for user**

Inform the user: the feature branch `feat/ingest-robustness` now has spec + implementation + tests for the text-only path. User pushes to remote themselves (per CLAUDE.md convention). After push, deploy:

```bash
cd cutip-rag-chatbot/
cp ingest/Dockerfile Dockerfile
gcloud run deploy cutip-ingest-worker --source=. --region=asia-southeast1 --project=cutip-rag --quiet --timeout=3600 --set-secrets "PINECONE_API_KEY=PINECONE_API_KEY:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,COHERE_API_KEY=COHERE_API_KEY:latest,ADMIN_API_KEY=ADMIN_API_KEY:latest"
git checkout Dockerfile
```

Then smoke-test:

1. Re-upload `ประกาศจุฬาฯ…2563.ocr.docx` to Drive (if removed earlier).
2. Trigger Smart Scan from admin portal.
3. Watch Cloud Run logs: `gcloud logging read 'resource.labels.service_name="cutip-ingest-worker"' --project=cutip-rag --freshness=10m --limit=50`.
4. Expected log: `.ocr.docx detected — N pages, … skipping LibreOffice + PDF path` then `_upsert` completes with >0 chunks.
5. Query one fact from the document in admin-portal chat — expect the chunk to be retrieved.

If Opus still returns 0 chunks on the text-only path: the hypothesis is wrong; escalate to a separate spec to split the document into half-page batches (noted in spec's error-handling table).

---

## Self-review notes

**Spec coverage check:**
- ✅ Goal 1 (text-only path) → Tasks 2, 3, 5
- ✅ Goal 2 (unify two sources) → Tasks 1, 6 (plus Task 5 for the shared downstream branch)
- ✅ Goal 3 (preserve Opus as smart chunker) → Task 5's branch reuses the same `record_chunks` tool schema
- ✅ Goal 4 (OCR_PROMPT alignment) → Task 4
- ✅ Goal 5 (backward compat) → Task 5's regression test + Task 6 only branches on filename suffix
- ✅ Component `_read_ocr_docx_as_pages` → Task 1
- ✅ Component modified `ingest_v2` → Task 6
- ✅ Component modified `opus_parse_and_chunk` → Task 5
- ✅ Component `_format_pages_for_text_only` → Task 2
- ✅ Component `USER_PROMPT_TEMPLATE_TEXT_ONLY` → Task 3
- ✅ Component modified `OCR_PROMPT` → Task 4
- ✅ All 9 tests from spec mapped to task steps

**Placeholder scan:** No TBDs, no "similar to", no "handle edge cases" without specifics, no uncoded test descriptions. Every step has concrete code or exact commands.

**Type consistency:**
- `_read_ocr_docx_as_pages(file_bytes: bytes) -> dict[int, str]` — used identically in Tasks 1 (definition) and 6 (call site).
- `_format_pages_for_text_only(ocr_sidecar: dict[int, str]) -> str` — used identically in Tasks 2 (definition) and 5 (call site via `opus_parse_and_chunk`).
- `opus_parse_and_chunk(pdf_bytes: bytes | None, hyperlinks: list[dict], filename: str, ocr_sidecar: dict[int, str] | None = None) -> list[Document]` — consistent across Tasks 5 (signature change) and 6 (call site passes `None` for `.ocr.docx`).
- `USER_PROMPT_TEMPLATE_TEXT_ONLY` placeholders `{filename}`, `{sidecar_block}`, `{page_text_block}` — consistent between Task 3 (definition) and Task 5 (`.format(...)` call).
