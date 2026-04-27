# Ingest v2 Image-Blocks + JSON-Fence Implementation Plan (Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the failing tool_call-based chunking pipeline with image blocks (for pure-scan PDFs) plus free-form JSON-in-markdown-fence output, and remove the now-obsolete `.ocr.docx` / text-only / Haiku-pre-OCR machinery added by prior features on this branch.

**Architecture:** `ingest_v2` detects text-layer presence and dispatches `opus_parse_and_chunk` with `mode="document"` (text-layer PDFs keep the existing `document` content block) or `mode="images"` (pure-scan PDFs → pymupdf rasterise per page → Anthropic `image` content blocks). Opus emits text containing one `\`\`\`json` fence; we parse it via a small helper. No `bind_tools`, no `tool_choice`. Adaptive thinking stays.

**Tech Stack:** Python 3.11, pymupdf, langchain-anthropic + langchain-core (Opus 4.7 via ChatAnthropic), pytest + pytest-asyncio.

**Spec:** [`docs/superpowers/specs/2026-04-22-ingest-v2-image-blocks-design.md`](../specs/2026-04-22-ingest-v2-image-blocks-design.md)

**Branch:** `feat/ingest-robustness` (continuation — spec committed at `5847f31`)

---

## File Map

| File | Change |
|---|---|
| `ingest/services/ingestion_v2.py` | Add `_extract_json_from_fence`, `_text_from_response`, `_pdf_to_image_blocks`. Modify `opus_parse_and_chunk` (drop `bind_tools`, add `mode` param, parse JSON fence). Modify `ingest_v2` (drop `.ocr.docx` branch + Haiku pre-OCR call; add text-layer→mode routing). Delete `OCR_*` constants, `OCR_PROMPT`, `_get_ocr_client`, `ocr_pdf_pages`, `_OCR_DOCX_PAGE_HEADING_RE`, `_read_ocr_docx_as_pages`, `_format_pages_for_text_only`, `PURE_SCAN_TEXT_THRESHOLD`. Clean unused imports (`zipfile`, possibly `re`). |
| `ingest/services/_v2_prompts.py` | Modify `SYSTEM_PROMPT` (JSON-fence directive + escape hatch). Modify `USER_PROMPT_TEMPLATE` (drop `{ocr_block}` placeholder). Delete `CHUNK_TOOL_SCHEMA`, `format_ocr_sidecar`, `USER_PROMPT_TEMPLATE_TEXT_ONLY`. |
| `tests/test_ingestion_v2.py` | Add 16 new tests across Tasks 1–6. Delete ~14 obsolete tests across the same tasks. |

---

## Task 1: Add `_extract_json_from_fence` helper

**Why:** Parse the JSON object from Opus's free-form text response. Tolerates a leading `\`\`\`json` markdown fence as well as bare JSON with surrounding prose. Returns `None` on parse failure so the caller can log + treat as 0 chunks.

**Files:**
- Modify: `cutip-rag-chatbot/ingest/services/ingestion_v2.py` (add helper + module-level regex)
- Test: `cutip-rag-chatbot/tests/test_ingestion_v2.py` (add 4 tests)

- [ ] **Step 1: Write failing test — basic fence**

Append to `tests/test_ingestion_v2.py`:

```python
def test_extract_json_from_fence_parses_basic_fence():
    text = """some chatter
```json
{"chunks": [{"text": "a", "page": 1}]}
```
trailing prose"""
    result = ingestion_v2._extract_json_from_fence(text)
    assert result == {"chunks": [{"text": "a", "page": 1}]}
```

- [ ] **Step 2: Write failing test — bare JSON with prose**

Append:

```python
def test_extract_json_from_fence_parses_bare_json_with_prose():
    text = 'Here is the result: {"chunks": [{"text": "alpha", "page": 1}]} done.'
    result = ingestion_v2._extract_json_from_fence(text)
    assert result == {"chunks": [{"text": "alpha", "page": 1}]}
```

- [ ] **Step 3: Write failing test — malformed returns None**

Append:

```python
def test_extract_json_from_fence_returns_none_on_malformed():
    text = "```json\nthis is not json at all\n```"
    assert ingestion_v2._extract_json_from_fence(text) is None
```

- [ ] **Step 4: Write failing test — empty returns None**

Append:

```python
def test_extract_json_from_fence_returns_none_on_empty():
    assert ingestion_v2._extract_json_from_fence("") is None
    assert ingestion_v2._extract_json_from_fence(None) is None
```

- [ ] **Step 5: Run all 4 tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k "test_extract_json_from_fence" -v`
Expected: 4 FAILs with `AttributeError: module 'ingest.services.ingestion_v2' has no attribute '_extract_json_from_fence'`.

- [ ] **Step 6: Implement `_extract_json_from_fence`**

In `ingest/services/ingestion_v2.py`, add an `import json` at module level if missing, then add the regex constant near the existing `_OCR_DOCX_PAGE_HEADING_RE` (top of file, after the existing `re` import) and the helper function.

Add module-level constant (next to other regex constants, top of file):

```python
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
```

Add `import json` to the existing top-level imports if not already present.

Add the helper function (place above the existing `_get_ocr_client` so all module-level functions sit before the LRU-cached factories):

```python
def _extract_json_from_fence(text):
    """Extract a JSON object from a markdown fence, tolerating extra prose.

    Opus 4.7 reliably outputs JSON inside a ``\`\`\`json … \`\`\``` fence when
    the system prompt asks for it. We accept either a fenced code block or
    bare JSON with extra text by finding the outermost ``{ … }`` span.

    Returns ``None`` on parse failure or empty input — caller logs and treats
    as 0 chunks.
    """
    if not text:
        return None
    m = _JSON_FENCE_RE.search(text)
    candidate = m.group(1) if m else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(candidate[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None
```

- [ ] **Step 7: Run the 4 tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k "test_extract_json_from_fence" -v`
Expected: 4 PASS.

- [ ] **Step 8: Run the full ingestion_v2 test module to catch regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -v`
Expected: all previously-passing tests still pass.

- [ ] **Step 9: Commit**

```bash
git add ingest/services/ingestion_v2.py tests/test_ingestion_v2.py
git commit -m "feat(ingest-v2): add _extract_json_from_fence helper

Parses JSON inside a markdown ```json fence; falls back to bare-JSON-with-
prose extraction by locating the outermost { ... } span. Returns None on
parse failure or empty input.

Used by the upcoming Opus parse-and-chunk rewrite that drops the tool_call
output schema in favour of free-form text + JSON fence (the architecture
that mirrors what claude.ai produces internally).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Add `_text_from_response` helper

**Why:** Opus 4.7 with adaptive thinking returns `response.content` as a list of typed blocks (`thinking`, `text`, sometimes others), not a string. The existing `chat/services/agent.py` already extracts text blocks explicitly (CLAUDE.md gotcha #1) — replicate the same pattern as a small helper for `opus_parse_and_chunk`.

**Files:**
- Modify: `cutip-rag-chatbot/ingest/services/ingestion_v2.py`
- Test: `cutip-rag-chatbot/tests/test_ingestion_v2.py`

- [ ] **Step 1: Write failing test — string content**

Append to `tests/test_ingestion_v2.py`:

```python
def test_text_from_response_handles_string_content():
    from unittest.mock import MagicMock
    fake = MagicMock()
    fake.content = "hello world"
    assert ingestion_v2._text_from_response(fake) == "hello world"
```

- [ ] **Step 2: Write failing test — list content with thinking block**

Append:

```python
def test_text_from_response_concatenates_text_blocks_only():
    from unittest.mock import MagicMock
    fake = MagicMock()
    fake.content = [
        {"type": "thinking", "thinking": "internal monologue"},  # ignored
        {"type": "text", "text": "first"},
        {"type": "text", "text": "second"},
    ]
    assert ingestion_v2._text_from_response(fake) == "first\nsecond"
```

- [ ] **Step 3: Run both tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k "test_text_from_response" -v`
Expected: 2 FAILs with `AttributeError`.

- [ ] **Step 4: Implement `_text_from_response`**

Add to `ingest/services/ingestion_v2.py`, immediately after `_extract_json_from_fence`:

```python
def _text_from_response(response):
    """Return the concatenated text-block content from a langchain AIMessage.

    Opus 4.7 with adaptive thinking returns ``content`` as a list of typed
    blocks (``thinking``, ``text``, …). Plain string content is also handled
    for compatibility with simpler responses (and tests).
    """
    content = response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
        return "\n".join(parts)
    return str(content or "")
```

- [ ] **Step 5: Run both tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k "test_text_from_response" -v`
Expected: 2 PASS.

- [ ] **Step 6: Commit**

```bash
git add ingest/services/ingestion_v2.py tests/test_ingestion_v2.py
git commit -m "feat(ingest-v2): add _text_from_response helper

Concatenates text-block content from a langchain AIMessage. Opus 4.7 with
adaptive thinking returns content as a list of typed blocks (thinking,
text, ...) per CLAUDE.md gotcha #1; plain string content is also accepted.

Used by the upcoming opus_parse_and_chunk rewrite to extract the JSON-fence
text from the model's response.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Add `_pdf_to_image_blocks` helper

**Why:** Render every PDF page as a PNG and wrap as Anthropic `image` content blocks. Used by `opus_parse_and_chunk` when the PDF has no text layer — bypasses Anthropic's `document` block path that empirically silent-fails on long pure-scan Thai legal PDFs.

**Files:**
- Modify: `cutip-rag-chatbot/ingest/services/ingestion_v2.py`
- Test: `cutip-rag-chatbot/tests/test_ingestion_v2.py`

- [ ] **Step 1: Write failing test — N-page PDF returns N image blocks**

Append to `tests/test_ingestion_v2.py`:

```python
def test_pdf_to_image_blocks_returns_image_block_per_page():
    """3-page PDF → 3 image blocks, each base64 PNG with media_type=image/png."""
    import pymupdf

    doc = pymupdf.open()
    for _ in range(3):
        page = doc.new_page()
        page.insert_text((72, 72), "hello")
    pdf_bytes = doc.tobytes()
    doc.close()

    blocks = ingestion_v2._pdf_to_image_blocks(pdf_bytes)

    assert len(blocks) == 3
    for b in blocks:
        assert b["type"] == "image"
        assert b["source"]["type"] == "base64"
        assert b["source"]["media_type"] == "image/png"
        assert isinstance(b["source"]["data"], str)
        assert len(b["source"]["data"]) > 0
```

- [ ] **Step 2: Write failing test — over 100 pages raises**

Append:

```python
def test_pdf_to_image_blocks_raises_on_over_100_pages():
    """Anthropic limit is 100 image blocks per request; surface a clear error."""
    import pymupdf
    import pytest

    doc = pymupdf.open()
    for _ in range(101):
        doc.new_page()
    pdf_bytes = doc.tobytes()
    doc.close()

    with pytest.raises(ValueError, match="exceeds Anthropic's 100-image limit"):
        ingestion_v2._pdf_to_image_blocks(pdf_bytes)
```

- [ ] **Step 3: Run both tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k "test_pdf_to_image_blocks" -v`
Expected: 2 FAILs with `AttributeError`.

- [ ] **Step 4: Implement `_pdf_to_image_blocks`**

Add to `ingest/services/ingestion_v2.py`, immediately after `_text_from_response`:

```python
def _pdf_to_image_blocks(pdf_bytes, dpi=150):
    """Rasterise every PDF page to PNG and wrap as Anthropic image content blocks.

    Used by ``opus_parse_and_chunk`` when the PDF has no text layer.
    Mirrors what claude.ai does internally for PDF uploads — Anthropic's PDF
    ``document`` block path is unreliable on long pure-scan Thai legal docs
    (silent ``chunks=[]`` even with an OCR sidecar). Sending pre-rendered
    images bypasses that path.

    DPI 150 balances OCR fidelity against payload size: a 24-page Thai legal
    scan at 150 DPI is ~36K input tokens vs ~5K for the document block.

    Anthropic limits a single request to 100 image blocks. This function
    raises ``ValueError`` if the PDF exceeds that.
    """
    import pymupdf
    blocks = []
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        if doc.page_count > 100:
            raise ValueError(
                f"_pdf_to_image_blocks: {doc.page_count} pages exceeds "
                f"Anthropic's 100-image limit"
            )
        for page in doc:
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            png = pix.tobytes("png")
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.standard_b64encode(png).decode("utf-8"),
                },
            })
    finally:
        doc.close()
    return blocks
```

- [ ] **Step 5: Run both tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k "test_pdf_to_image_blocks" -v`
Expected: 2 PASS.

- [ ] **Step 6: Run the full module to catch regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -v`
Expected: all previously-passing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add ingest/services/ingestion_v2.py tests/test_ingestion_v2.py
git commit -m "feat(ingest-v2): add _pdf_to_image_blocks helper

Rasterises every PDF page to PNG @ 150 DPI and wraps as Anthropic image
content blocks. Replaces the document-block path for pure-scan PDFs in the
upcoming opus_parse_and_chunk rewrite — Anthropic's internal PDF handling
empirically silent-fails on long pure-scan Thai legal docs even with OCR
sidecars; sending pre-rendered images mirrors what claude.ai does internally.

Raises ValueError when page count exceeds Anthropic's 100-image cap.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Update prompts + rewrite `opus_parse_and_chunk`

**Why:** Drop the `bind_tools` + `tool_choice` constraint that empirically lets Opus opt out of `record_chunks` and produce 0 chunks. Output is now a JSON-in-markdown-fence response. Branch on a new `mode` parameter to dispatch between `image` blocks (pure-scan) and `document` block (text-layer) content shapes. This task pairs with prompt changes because `USER_PROMPT_TEMPLATE` no longer carries the `{ocr_block}` placeholder.

**Files:**
- Modify: `cutip-rag-chatbot/ingest/services/_v2_prompts.py`
- Modify: `cutip-rag-chatbot/ingest/services/ingestion_v2.py`
- Test: `cutip-rag-chatbot/tests/test_ingestion_v2.py`

- [ ] **Step 1: Delete obsolete prompt-related tests**

In `tests/test_ingestion_v2.py`, locate and **delete** the following test function bodies entirely (they exercise the soon-to-be-removed tool-call output schema or `{ocr_block}` placeholder):

- `test_user_prompt_template_has_ocr_block_placeholder`
- `test_user_prompt_template_text_only_has_required_placeholders`
- `test_format_ocr_sidecar_empty_dict_returns_placeholder`
- `test_format_ocr_sidecar_populated_renders_per_page_sections`
- `test_opus_parse_and_chunk_happy_path`
- `test_opus_parse_and_chunk_filters_refusal_chunks`
- `test_opus_parse_and_chunk_returns_empty_when_no_tool_call`
- `test_opus_parse_and_chunk_injects_ocr_sidecar`
- `test_opus_parse_and_chunk_without_ocr_sidecar_uses_placeholder`
- `test_opus_parse_and_chunk_text_only_omits_document_block`
- `test_opus_parse_and_chunk_text_only_accepts_none_pdf_bytes`
- `test_opus_parse_and_chunk_pdf_path_keeps_document_block`

Each deletion is the entire `def test_…` block (including any `@pytest.mark.asyncio` decorator above it). Leave a single blank line between adjacent surviving tests.

- [ ] **Step 2: Add 6 new tests for the rewritten `opus_parse_and_chunk` + prompts**

Append to `tests/test_ingestion_v2.py`:

```python
def test_user_prompt_template_drops_ocr_block_placeholder():
    from ingest.services._v2_prompts import USER_PROMPT_TEMPLATE
    assert "{filename}" in USER_PROMPT_TEMPLATE
    assert "{sidecar_block}" in USER_PROMPT_TEMPLATE
    assert "{ocr_block}" not in USER_PROMPT_TEMPLATE


def test_system_prompt_instructs_json_fence_output():
    from ingest.services._v2_prompts import SYSTEM_PROMPT
    assert "```json" in SYSTEM_PROMPT
    # tool_call language must be gone
    assert "record_chunks" not in SYSTEM_PROMPT
    # escape hatch
    assert "[page" in SYSTEM_PROMPT and "unreadable]" in SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_opus_parse_and_chunk_images_mode_omits_document_block(
    monkeypatch, pure_scan_pdf_bytes
):
    """mode='images' → content blocks include image type and exclude document type."""
    from langchain_core.messages import AIMessage
    from unittest.mock import AsyncMock, MagicMock

    captured = {}

    async def fake_ainvoke(messages):
        captured["content"] = messages[1].content
        return AIMessage(content='```json\n{"chunks": []}\n```')

    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(side_effect=fake_ainvoke)

    ingestion_v2._get_opus_llm.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_opus_llm", lambda: fake_llm)

    await ingestion_v2.opus_parse_and_chunk(
        pdf_bytes=pure_scan_pdf_bytes,
        hyperlinks=[],
        filename="x.pdf",
        mode="images",
    )

    types = [b.get("type") for b in captured["content"]]
    assert "image" in types
    assert "document" not in types


@pytest.mark.asyncio
async def test_opus_parse_and_chunk_document_mode_includes_document_block(
    monkeypatch, tiny_text_pdf_bytes
):
    """mode='document' → content blocks include document + text."""
    from langchain_core.messages import AIMessage
    from unittest.mock import AsyncMock, MagicMock

    captured = {}

    async def fake_ainvoke(messages):
        captured["content"] = messages[1].content
        return AIMessage(content='```json\n{"chunks": []}\n```')

    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(side_effect=fake_ainvoke)

    ingestion_v2._get_opus_llm.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_opus_llm", lambda: fake_llm)

    await ingestion_v2.opus_parse_and_chunk(
        pdf_bytes=tiny_text_pdf_bytes,
        hyperlinks=[],
        filename="x.pdf",
        mode="document",
    )

    types = [b.get("type") for b in captured["content"]]
    assert types == ["document", "text"]


@pytest.mark.asyncio
async def test_opus_parse_and_chunk_returns_chunks_from_json_fence(
    monkeypatch, tiny_text_pdf_bytes
):
    """Chunks parsed from JSON fence are returned as Documents with metadata."""
    from langchain_core.messages import AIMessage
    from unittest.mock import AsyncMock, MagicMock

    payload = (
        '```json\n'
        '{"chunks": ['
        '{"text": "alpha", "page": 1, "section_path": "Intro", "has_table": false},'
        '{"text": "beta", "page": 2, "section_path": "", "has_table": true}'
        ']}\n'
        '```'
    )

    async def fake_ainvoke(messages):
        return AIMessage(content=payload)

    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(side_effect=fake_ainvoke)

    ingestion_v2._get_opus_llm.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_opus_llm", lambda: fake_llm)

    chunks = await ingestion_v2.opus_parse_and_chunk(
        pdf_bytes=tiny_text_pdf_bytes,
        hyperlinks=[],
        filename="x.pdf",
        mode="document",
    )

    assert len(chunks) == 2
    assert chunks[0].page_content == "alpha"
    assert chunks[0].metadata == {"page": 1, "section_path": "Intro", "has_table": False}
    assert chunks[1].metadata["has_table"] is True


@pytest.mark.asyncio
async def test_opus_parse_and_chunk_returns_empty_on_no_json_fence(
    monkeypatch, tiny_text_pdf_bytes
):
    """If Opus replies with prose (no JSON fence) we return [] and log a warning."""
    from langchain_core.messages import AIMessage
    from unittest.mock import AsyncMock, MagicMock

    async def fake_ainvoke(messages):
        return AIMessage(content="I cannot read this document clearly.")

    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(side_effect=fake_ainvoke)

    ingestion_v2._get_opus_llm.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_opus_llm", lambda: fake_llm)

    chunks = await ingestion_v2.opus_parse_and_chunk(
        pdf_bytes=tiny_text_pdf_bytes,
        hyperlinks=[],
        filename="x.pdf",
        mode="document",
    )

    assert chunks == []


@pytest.mark.asyncio
async def test_opus_parse_and_chunk_filters_unreadable_escape_hatch(
    monkeypatch, tiny_text_pdf_bytes
):
    """Chunks of the form [page N: unreadable] are filtered out."""
    from langchain_core.messages import AIMessage
    from unittest.mock import AsyncMock, MagicMock

    payload = (
        '```json\n{"chunks": ['
        '{"text": "[page 3: unreadable]", "page": 3, "section_path": "", "has_table": false},'
        '{"text": "real content", "page": 4, "section_path": "", "has_table": false}'
        ']}\n```'
    )

    async def fake_ainvoke(messages):
        return AIMessage(content=payload)

    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(side_effect=fake_ainvoke)

    ingestion_v2._get_opus_llm.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_opus_llm", lambda: fake_llm)

    chunks = await ingestion_v2.opus_parse_and_chunk(
        pdf_bytes=tiny_text_pdf_bytes,
        hyperlinks=[],
        filename="x.pdf",
        mode="document",
    )

    assert len(chunks) == 1
    assert chunks[0].page_content == "real content"


@pytest.mark.asyncio
async def test_opus_parse_and_chunk_invalid_mode_raises(tiny_text_pdf_bytes):
    import pytest
    with pytest.raises(ValueError, match="unknown mode"):
        await ingestion_v2.opus_parse_and_chunk(
            pdf_bytes=tiny_text_pdf_bytes,
            hyperlinks=[],
            filename="x.pdf",
            mode="bogus",
        )
```

- [ ] **Step 3: Run all 7 new tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k "test_user_prompt_template_drops_ocr_block_placeholder or test_system_prompt_instructs_json_fence_output or test_opus_parse_and_chunk_images_mode_omits_document_block or test_opus_parse_and_chunk_document_mode_includes_document_block or test_opus_parse_and_chunk_returns_chunks_from_json_fence or test_opus_parse_and_chunk_returns_empty_on_no_json_fence or test_opus_parse_and_chunk_filters_unreadable_escape_hatch or test_opus_parse_and_chunk_invalid_mode_raises" -v`
Expected: 7 FAILs (template assertions / signature mismatch / not yet refactored).

- [ ] **Step 4: Update `_v2_prompts.py` — system prompt + user template + remove obsolete names**

Open `ingest/services/_v2_prompts.py`. Replace its complete contents with:

```python
"""Opus 4.7 prompt templates for ingest v2.

Phase 1 architecture: Opus emits a free-form text response containing exactly one
``\`\`\`json`` markdown fence with ``{"chunks": [...]}``. No tool binding, no
schema enforcement at the model level — Python parses + validates after the call.
"""

SYSTEM_PROMPT = """You are a document-parsing tool for a Thai+English academic/administrative knowledge base.

Your job: split the provided document into self-contained, retrieval-ready chunks.

RULES
- Preserve Thai characters exactly. Never translate or transliterate.
- Each chunk: 300–1500 characters of substantive content.
- Each chunk must stand alone — a reader who sees only one chunk should understand what it is about.
- Annotate with `section_path` (e.g. `ขั้นตอนสอบวิทยานิพนธ์ > สอบโครงร่าง`) when the document has genuine hierarchy. Leave `section_path` as an empty string if hierarchy would be invented.
- Tables: emit as markdown tables. If a table spans multiple chunks, REPEAT the header row in every chunk so each is self-contained.
- Hyperlinks: the user message includes a sidecar list of `{page, text, uri}` entries — these are URLs that are hidden in PDF link annotations and NOT visible in the rendered page. Inline them as `[anchor](uri)` markdown in the chunk whose text contains the anchor. If the URL is already plainly visible in the text, do not duplicate it.
- Forms: capture field labels and checkbox state exactly (☑ checked, ☐ unchecked).
- Diagrams / signatures / stamps: describe briefly in square brackets, e.g. `[signature of ผู้อำนวยการหลักสูตร]`. Do not fabricate content.
- Slides: 1 slide = 1 chunk unless the slide is trivially short (then merge with neighbors).
- Page numbers: set `page` to the 1-based page index where each chunk starts.
- Do not include navigation furniture (page numbers alone, running headers, "Q&A" slide titles) as standalone chunks.
- If a single page is genuinely unreadable, emit one chunk with text "[page N: unreadable]" and continue with other pages. NEVER refuse the whole document.

OUTPUT FORMAT
Return ONE markdown json fence and nothing else. Exactly this shape:

```json
{
  "chunks": [
    {"text": "…", "section_path": "…", "page": 1, "has_table": false}
  ]
}
```

No prose before or after the fence. No explanation."""


USER_PROMPT_TEMPLATE = """Document filename: {filename}

Hyperlink sidecar (URIs hidden in PDF annotations, not visible on the rendered page):
{sidecar_block}

Parse the attached content and emit chunks via the JSON output specified in the system prompt."""


def format_sidecar(hyperlinks):
    """Render the hyperlink sidecar as a stable human+LLM-readable block."""
    if not hyperlinks:
        return "(no hidden hyperlinks on any page)"
    lines = []
    for h in hyperlinks:
        lines.append(f"- page {h['page']}: [{h['text']}]({h['uri']})")
    return "\n".join(lines)
```

This deletes `CHUNK_TOOL_SCHEMA`, `format_ocr_sidecar`, and `USER_PROMPT_TEMPLATE_TEXT_ONLY`. The two surviving exports (`SYSTEM_PROMPT`, `USER_PROMPT_TEMPLATE`, `format_sidecar`) keep their import-time names; consumers that imported the deleted names will fail at import time and must be fixed in this same task.

- [ ] **Step 5: Update `ingest/services/ingestion_v2.py` import block + rewrite `opus_parse_and_chunk`**

In `ingest/services/ingestion_v2.py`:

a. Replace the existing `_v2_prompts` import block to drop `CHUNK_TOOL_SCHEMA`, `format_ocr_sidecar`, and `USER_PROMPT_TEMPLATE_TEXT_ONLY` (the latter is imported lazily inside the current function — remove the lazy import too):

```python
from ingest.services._v2_prompts import (
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    format_sidecar,
)
```

b. Replace the entire body of `opus_parse_and_chunk` (which currently spans roughly the lines starting at `async def opus_parse_and_chunk` through its `return cleaned`) with:

```python
async def opus_parse_and_chunk(
    pdf_bytes,
    hyperlinks,
    filename,
    mode,
):
    """Send PDF (or rasterised page images) to Opus 4.7, parse JSON-fence response.

    No tool binding. The system prompt instructs Opus to emit one
    ``\`\`\`json`` fence containing ``{"chunks": [...]}``. We accept text output
    and parse the fence.

    ``mode`` selects the content shape:
    - ``"document"`` — text-layer PDF: ``[document_block, text_block]``
    - ``"images"``   — pure-scan PDF: ``[image_block, …, text_block]``

    Empty / refusal / [page N: unreadable] chunks are filtered out. Any failure
    to parse JSON returns ``[]`` (caller logs and treats as 0 chunks).
    """
    sidecar_block = format_sidecar(hyperlinks)
    user_text = USER_PROMPT_TEMPLATE.format(
        filename=filename,
        sidecar_block=sidecar_block,
    )

    if mode == "images":
        image_blocks = _pdf_to_image_blocks(pdf_bytes)
        human_content = [*image_blocks, {"type": "text", "text": user_text}]
    elif mode == "document":
        pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
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
    else:
        raise ValueError(f"opus_parse_and_chunk: unknown mode {mode!r}")

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=human_content),
    ]
    response = await _get_opus_llm().ainvoke(messages)

    meta = response.response_metadata or {}
    stop_reason = meta.get("stop_reason")
    usage = meta.get("usage", {}) or {}
    text = _text_from_response(response)
    logger.info(
        "opus_parse(%s mode=%s): stop=%s in_tok=%s out_tok=%s text_len=%d",
        filename, mode, stop_reason,
        usage.get("input_tokens"), usage.get("output_tokens"), len(text),
    )

    parsed = _extract_json_from_fence(text)
    if not parsed or "chunks" not in parsed:
        logger.warning(
            "opus_parse(%s): could not parse JSON. preview=%r",
            filename, text[:800],
        )
        return []

    raw_chunks = parsed.get("chunks") or []
    cleaned = []
    for c in raw_chunks:
        t = (c.get("text") or "").strip()
        if not t:
            continue
        if t.startswith("[page") and t.endswith("unreadable]"):
            continue
        if _looks_like_refusal(t):
            logger.warning(
                "opus_parse(%s): dropping refusal chunk on page %s",
                filename, c.get("page", "?"),
            )
            continue
        try:
            page = int(c.get("page", 1))
        except (TypeError, ValueError):
            page = 1
        cleaned.append(Document(
            page_content=t,
            metadata={
                "page": page,
                "section_path": c.get("section_path", "") or "",
                "has_table": bool(c.get("has_table", False)),
            },
        ))
    return cleaned
```

c. Update `_get_opus_llm()` docstring (function body unchanged). Replace its current docstring with:

```python
@lru_cache(maxsize=1)
def _get_opus_llm():
    """Return the Opus 4.7 LLM used for v2 parse+chunk (cached per process).

    Adaptive thinking is ENABLED. No tool binding — the system prompt
    instructs Opus to emit a ``\`\`\`json`` fence and we parse it in Python.
    Earlier iterations of this pipeline used ``bind_tools`` + ``tool_choice``
    but empirically Opus would opt out of the tool call on long Thai legal
    docs (silent ``chunks=[]``). Free-form text + JSON fence reliably
    produces parseable output.

    Cached so a batch audit (e.g. 14 PDFs) does not re-instantiate the
    HTTP-pooled client once per file. Tests monkeypatch this function
    directly — ``monkeypatch.setattr`` replaces the module attribute so
    the cached original is bypassed entirely during the test.
    """
    from langchain_anthropic import ChatAnthropic
    from shared.config import settings
    return ChatAnthropic(
        model=settings.OCR_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        max_tokens=32000,
        max_retries=3,
        thinking={"type": "adaptive"},
    )
```

- [ ] **Step 6: Run the 7 new prompt + opus_parse_and_chunk tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k "test_user_prompt_template_drops_ocr_block_placeholder or test_system_prompt_instructs_json_fence_output or test_opus_parse_and_chunk_images_mode_omits_document_block or test_opus_parse_and_chunk_document_mode_includes_document_block or test_opus_parse_and_chunk_returns_chunks_from_json_fence or test_opus_parse_and_chunk_returns_empty_on_no_json_fence or test_opus_parse_and_chunk_filters_unreadable_escape_hatch or test_opus_parse_and_chunk_invalid_mode_raises" -v`
Expected: 7 PASS.

- [ ] **Step 7: Run the full module to surface any orphaned tests still referencing removed names**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -v`
Expected: any failures here are tests that import `CHUNK_TOOL_SCHEMA`, `format_ocr_sidecar`, `USER_PROMPT_TEMPLATE_TEXT_ONLY`, or that exercise `ingest_v2`'s pre-flight Haiku OCR or `.ocr.docx` branch. Those will be cleaned up in Tasks 5 and 6 — record them now and continue. **Do not** delete the failing tests prematurely; they belong to upcoming tasks.

If any test failure references something that should already be working (e.g., the new helpers from Tasks 1–3, the test_extract_hyperlinks_* tests, or test_ensure_pdf_*), stop and investigate.

- [ ] **Step 8: Commit**

```bash
git add ingest/services/_v2_prompts.py ingest/services/ingestion_v2.py tests/test_ingestion_v2.py
git commit -m "feat(ingest-v2): rewrite opus_parse_and_chunk with mode + JSON fence

Drop bind_tools / tool_choice. Opus now emits a free-form text response
containing one ```json fence; we parse it in Python. Empirically this
prevents the silent chunks=[] failure mode where adaptive thinking lets
Opus opt out of a forced tool schema on long Thai legal documents.

opus_parse_and_chunk gains a mode parameter:
- mode='document' → existing PDF document block path (text-layer PDFs)
- mode='images'   → rasterised page image blocks (pure-scan PDFs)

_v2_prompts.py: SYSTEM_PROMPT switched to JSON-fence directive + 'page N
unreadable' escape hatch. USER_PROMPT_TEMPLATE drops {ocr_block}.
CHUNK_TOOL_SCHEMA, format_ocr_sidecar, USER_PROMPT_TEMPLATE_TEXT_ONLY
removed (no longer used).

Tests: 12 obsolete tool-call / sidecar tests deleted; 8 new tests added
covering JSON fence parsing, mode dispatch, and the unreadable escape hatch.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Rewrite `ingest_v2` for mode routing

**Why:** Replace the current `.ocr.docx` branch + Haiku pre-OCR pre-flight with simple text-layer detection that selects `mode="images"` or `mode="document"`. After this task, `ingest_v2` no longer references any of the OCR-related globals (`OCR_PROMPT`, `_get_ocr_client`, `ocr_pdf_pages`, `_read_ocr_docx_as_pages`, `_format_pages_for_text_only`, `PURE_SCAN_TEXT_THRESHOLD`); Task 6 will then physically delete those.

**Files:**
- Modify: `cutip-rag-chatbot/ingest/services/ingestion_v2.py` (function `ingest_v2`)
- Test: `cutip-rag-chatbot/tests/test_ingestion_v2.py`

- [ ] **Step 1: Delete obsolete `ingest_v2` tests**

In `tests/test_ingestion_v2.py`, locate and delete the entire body of:

- `test_ingest_v2_pure_scan_triggers_ocr_path`
- `test_ingest_v2_text_layer_skips_ocr`
- `test_ingest_v2_ocr_docx_skips_libreoffice_and_hyperlinks`

Each deletion is the entire `def test_…` block including its `@pytest.mark.asyncio` decorator.

**Note:** `test_ingest_v2_orchestrates_pipeline` stays but needs an update because the `fake_opus` signature changes from `(pdf, links, fn, ocr_sidecar=None)` to `(pdf, links, fn, mode)`.

- [ ] **Step 2: Adjust `test_ingest_v2_orchestrates_pipeline` to the new opus signature**

Locate `test_ingest_v2_orchestrates_pipeline` in `tests/test_ingestion_v2.py`. Its `fake_opus` definition currently reads roughly:

```python
async def fake_opus(pdf, links, fn, ocr_sidecar=None):
    calls["opus"] = (pdf, links, fn)
    return [Document(page_content="body", metadata={"page": 1, "section_path": "", "has_table": False})]
```

Replace that single `fake_opus` definition with:

```python
async def fake_opus(pdf, links, fn, mode):
    calls["opus"] = (pdf, links, fn, mode)
    return [Document(page_content="body", metadata={"page": 1, "section_path": "", "has_table": False})]
```

The surrounding test code (`monkeypatch.setattr(ingestion_v2, "opus_parse_and_chunk", fake_opus)`, the assertion `calls["opus"][2] == "form.docx"`, etc.) stays as-is. Add an additional assertion at the end of the test before the existing `assert meta[…]` block:

```python
    assert calls["opus"][3] == "document"  # tiny text content → document mode
```

This locks in that the orchestration test exercises the routing logic.

- [ ] **Step 3: Add 2 new mode-routing tests**

Append to `tests/test_ingestion_v2.py`:

```python
@pytest.mark.asyncio
async def test_ingest_v2_pure_scan_routes_to_images_mode(monkeypatch, pure_scan_pdf_bytes):
    """A PDF with empty text layer must dispatch opus_parse_and_chunk(mode='images')."""
    captured = {}

    async def fake_opus(pdf, links, fn, mode):
        captured["mode"] = mode
        return []

    monkeypatch.setattr(ingestion_v2, "opus_parse_and_chunk", fake_opus)

    await ingestion_v2.ingest_v2(
        file_bytes=pure_scan_pdf_bytes,
        filename="scan.pdf",
        namespace="ns-test",
        tenant_id="t",
    )

    assert captured["mode"] == "images"


@pytest.mark.asyncio
async def test_ingest_v2_text_layer_routes_to_document_mode(monkeypatch, tiny_text_pdf_bytes):
    """A PDF with non-empty text layer must dispatch opus_parse_and_chunk(mode='document')."""
    captured = {}

    async def fake_opus(pdf, links, fn, mode):
        captured["mode"] = mode
        return []

    monkeypatch.setattr(ingestion_v2, "opus_parse_and_chunk", fake_opus)

    await ingestion_v2.ingest_v2(
        file_bytes=tiny_text_pdf_bytes,
        filename="text.pdf",
        namespace="ns-test",
        tenant_id="t",
    )

    assert captured["mode"] == "document"
```

- [ ] **Step 4: Run the 2 new tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k "test_ingest_v2_pure_scan_routes_to_images_mode or test_ingest_v2_text_layer_routes_to_document_mode" -v`
Expected: 2 FAILs. The current `ingest_v2` calls `opus_parse_and_chunk(pdf, hyperlinks, filename, ocr_sidecar=…)`, so the `fake_opus` here will receive an unexpected keyword argument and raise `TypeError`.

- [ ] **Step 5: Rewrite `ingest_v2`**

In `ingest/services/ingestion_v2.py`, replace the entire body of `ingest_v2` (everything from `async def ingest_v2` through its final `return await _upsert(…)`) with:

```python
async def ingest_v2(
    file_bytes,
    filename,
    namespace,
    tenant_id,
    doc_category="general",
    url="",
    download_link="",
    drive_file_id="",
):
    """v2 universal ingestion entrypoint.

    Pipeline:
      1. ensure_pdf — normalize any supported format to PDF
      2. extract_page_text — detect text-layer; routes to either:
         - "document" mode: text-layer PDF → Anthropic document block
         - "images" mode:   pure-scan PDF → rasterised page image blocks
      3. opus_parse_and_chunk — free-form JSON fence response
      4. _upsert — Cohere embed, Pinecone atomic swap, BM25 invalidation

    ``drive_file_id`` (optional) stores the Drive file ID in chunk metadata
    so admin delete can remove the Drive file by ID even after rename.
    """
    from ingest.services.ingest_helpers import _build_metadata, _upsert

    pdf_bytes = ensure_pdf(file_bytes, filename)
    page_text = extract_page_text(pdf_bytes)
    total_text_chars = sum(len(t) for t in page_text.values())
    if total_text_chars <= 0:
        mode = "images"
        logger.info(
            "ingest_v2(%s): pure-scan detected (0 text chars across %d pages), using image blocks",
            filename, len(page_text),
        )
    else:
        mode = "document"
        logger.debug(
            "ingest_v2(%s): text-layer PDF (%d chars across %d pages), using document block",
            filename, total_text_chars, len(page_text),
        )
    hyperlinks = extract_hyperlinks(pdf_bytes)

    chunks = await opus_parse_and_chunk(pdf_bytes, hyperlinks, filename, mode=mode)
    if not chunks:
        logger.warning("ingest_v2(%s): Opus returned 0 chunks — nothing upserted", filename)
        return 0

    metadata = _build_metadata(
        tenant_id=tenant_id,
        source_type="pdf",
        source_filename=filename,
        doc_category=doc_category,
        url=url,
        download_link=download_link,
        drive_file_id=drive_file_id,
    )
    return await _upsert(chunks, namespace, metadata)
```

- [ ] **Step 6: Run the 2 new mode-routing tests + the orchestration test to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k "test_ingest_v2_pure_scan_routes_to_images_mode or test_ingest_v2_text_layer_routes_to_document_mode or test_ingest_v2_orchestrates_pipeline" -v`
Expected: 3 PASS.

- [ ] **Step 7: Run the full module — orphaned tests for OCR functions / `_read_ocr_docx_as_pages` / etc. will fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -v`
Expected: failures for tests that exercise removed-from-flow functions (`_get_ocr_client`, `ocr_pdf_pages`, `_read_ocr_docx_as_pages`, `_format_pages_for_text_only`). The functions still exist in the module (deletion is Task 6) — these tests still pass on the function bodies but should be removed because the functions themselves will be deleted next. Continue to Task 6.

- [ ] **Step 8: Commit**

```bash
git add ingest/services/ingestion_v2.py tests/test_ingestion_v2.py
git commit -m "feat(ingest-v2): route ingest_v2 by text-layer detection

Replace the .ocr.docx filename branch + pre-flight Haiku OCR call with a
simple text-layer detection that selects opus_parse_and_chunk(mode=…):
- 0 text chars → mode='images' (rasterised page image blocks)
- >0 text chars → mode='document' (Anthropic document block, existing path)

The Haiku pre-OCR helpers and .ocr.docx parser remain in the module for one
more commit so this change stays focused; Task 6 deletes them.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Delete obsolete code + tests

**Why:** After Task 5 nothing in `ingest_v2.py` references the old OCR/.ocr.docx machinery. Physically delete it now to keep the file lean and prevent future drift.

**Files:**
- Modify: `cutip-rag-chatbot/ingest/services/ingestion_v2.py`
- Test: `cutip-rag-chatbot/tests/test_ingestion_v2.py`

- [ ] **Step 1: Delete obsolete tests**

In `tests/test_ingestion_v2.py`, delete the following test function bodies entirely (each is one `def test_…` block, including its `@pytest.mark.asyncio` if present):

- `test_get_ocr_client_is_cached_async_anthropic`
- `test_ocr_pdf_pages_returns_per_page_dict`
- `test_ocr_pdf_pages_partial_failure_returns_empty_string`
- `test_ocr_pdf_pages_all_pages_fail_raises`
- `test_read_ocr_docx_as_pages_splits_on_page_headings`
- `test_read_ocr_docx_as_pages_fallback_single_page_when_no_markers`
- `test_read_ocr_docx_as_pages_raises_on_corrupt_bytes`
- `test_read_ocr_docx_as_pages_raises_on_zip_without_content_types`
- `test_format_pages_for_text_only_empty_returns_placeholder`
- `test_format_pages_for_text_only_has_page_markers_and_content`

- [ ] **Step 2: Delete obsolete code from `ingest_v2.py`**

In `ingest/services/ingestion_v2.py`, delete in this order:

a. The OCR-related constants block (after the existing `import` lines), including `OCR_MODEL`, `OCR_CONCURRENCY`, `OCR_DPI`, `OCR_MAX_TOKENS_PER_PAGE`, `PURE_SCAN_TEXT_THRESHOLD`.

b. The `OCR_PROMPT` constant.

c. The `_get_ocr_client` function (entire `@lru_cache` decorator + body).

d. The `ocr_pdf_pages` function (entire async def + body).

e. The `_OCR_DOCX_PAGE_HEADING_RE` regex constant.

f. The `_read_ocr_docx_as_pages` function (entire body).

g. The `_format_pages_for_text_only` function (entire body).

h. From the top-of-file import block, delete `import zipfile` if no remaining code references `zipfile` (run `grep -n zipfile ingest/services/ingestion_v2.py` before saving — should return zero matches after the deletions in g).

i. From the top-of-file import block, delete `import io` if no remaining code references `io` (same `grep` check — `_pdf_to_image_blocks` uses `base64`, not `io`, so this should be safe to remove).

j. Confirm `import re` stays — `_JSON_FENCE_RE` (added in Task 1) still uses it.

k. Confirm `import json` stays — `_extract_json_from_fence` uses it.

The remaining module-level shape after these deletions should be:

```python
# imports (base64, json, logging, os, re, functools.lru_cache, typing.Any, langchain_*, etc.)
# _JSON_FENCE_RE = ...
# def _extract_json_from_fence(text): ...
# def _text_from_response(response): ...
# def _pdf_to_image_blocks(pdf_bytes, dpi=150): ...
# @lru_cache def _get_opus_llm(): ...
# def ensure_pdf(file_bytes, filename) -> bytes: ...
# def extract_hyperlinks(pdf_bytes) -> list[dict]: ...
# def extract_page_text(pdf_bytes) -> dict[int, str]: ...
# async def opus_parse_and_chunk(pdf_bytes, hyperlinks, filename, mode): ...
# async def ingest_v2(...): ...
```

- [ ] **Step 3: Run the full module to verify no regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -v`
Expected: all surviving tests pass. The total count should now be roughly 24-26 tests (was 35 at end of prior feature minus the ~14 deleted across Tasks 4–6, plus the ~16 new ones from Tasks 1–5).

If any test fails with `AttributeError: module has no attribute '<deleted name>'`, that test was missed in the deletion lists for Task 4 / 5 / 6 — delete that test too and re-run.

- [ ] **Step 4: Run the full backend test suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all tests pass. (Was 280 before this branch; counts will differ — the absolute number is less important than zero failures.)

- [ ] **Step 5: Verify imports are clean**

Run: `.venv/Scripts/python.exe -c "from ingest.services import ingestion_v2; print(ingestion_v2._extract_json_from_fence); print(ingestion_v2._text_from_response); print(ingestion_v2._pdf_to_image_blocks); print(ingestion_v2.opus_parse_and_chunk); print(ingestion_v2.ingest_v2)"`
Expected: 5 `<function …>` reprs, no errors.

Run: `.venv/Scripts/python.exe -c "from ingest.services import ingestion_v2; print(hasattr(ingestion_v2, '_get_ocr_client'), hasattr(ingestion_v2, 'ocr_pdf_pages'), hasattr(ingestion_v2, '_read_ocr_docx_as_pages'), hasattr(ingestion_v2, '_format_pages_for_text_only'))"`
Expected: `False False False False`.

- [ ] **Step 6: Commit**

```bash
git add ingest/services/ingestion_v2.py tests/test_ingestion_v2.py
git commit -m "refactor(ingest-v2): delete obsolete OCR + .ocr.docx machinery

After the image-blocks + JSON-fence rewrite (prior commits in this Phase 1
sequence), the C1 Haiku pre-OCR helpers and the .ocr.docx text-only branch
are dead code. Delete them and their tests.

Removed from ingest/services/ingestion_v2.py:
- OCR_MODEL, OCR_CONCURRENCY, OCR_DPI, OCR_MAX_TOKENS_PER_PAGE,
  PURE_SCAN_TEXT_THRESHOLD constants
- OCR_PROMPT constant
- _get_ocr_client()
- ocr_pdf_pages()
- _OCR_DOCX_PAGE_HEADING_RE regex
- _read_ocr_docx_as_pages()
- _format_pages_for_text_only()
- import zipfile (no longer used)
- import io (no longer used)

Removed from tests/test_ingestion_v2.py:
- test_get_ocr_client_is_cached_async_anthropic
- test_ocr_pdf_pages_* (3 tests)
- test_read_ocr_docx_as_pages_* (4 tests)
- test_format_pages_for_text_only_* (2 tests)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Final verification + deploy smoke notes

**Why:** Run the full test suite and prepare a smoke-test checklist for post-deploy.

**Files:** no code changes.

- [ ] **Step 1: Run the full backend test suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all tests pass.

If any failures: stop and diagnose. Do NOT deploy with red tests.

- [ ] **Step 2: Verify all new helpers + entrypoints load cleanly**

Run: `.venv/Scripts/python.exe -c "from ingest.services import ingestion_v2; from ingest.services._v2_prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE, format_sidecar; assert '\`\`\`json' in SYSTEM_PROMPT; assert '{ocr_block}' not in USER_PROMPT_TEMPLATE; print('OK')"`
Expected: prints `OK`.

- [ ] **Step 3: Confirm git state is clean**

Run: `git status --short`
Expected: at most pre-existing untracked files (e.g. `chunk-sample/` if not gitignored). No tracked-file modifications.

- [ ] **Step 4: Push to origin (the user does this themselves per CLAUDE.md)**

Inform the user: implementation is complete on `feat/ingest-robustness`. They push to remote themselves and deploy:

```bash
cd cutip-rag-chatbot/
cp ingest/Dockerfile Dockerfile
gcloud run deploy cutip-ingest-worker --source=. --region=asia-southeast1 --project=cutip-rag --quiet --timeout=3600 --set-secrets "PINECONE_API_KEY=PINECONE_API_KEY:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,COHERE_API_KEY=COHERE_API_KEY:latest,ADMIN_API_KEY=ADMIN_API_KEY:latest"
git checkout Dockerfile
```

- [ ] **Step 5: Post-deploy smoke test**

After deployment, the user runs the following to verify the new pipeline:

1. **Pure-scan PDF smoke:** Upload `ประกาศจุฬาฯ…2563.pdf` (the original scan, not `.ocr.docx`) to the tenant's Drive folder. Trigger Smart Scan. Watch logs:
   ```bash
   gcloud logging read 'resource.labels.service_name="cutip-ingest-worker"' --project=cutip-rag --freshness=10m --limit=50 --format='value(timestamp,textPayload)' --order=asc
   ```
   Expected log lines, in order:
   - `ingest_v2(…2563.pdf): pure-scan detected (0 text chars across 24 pages), using image blocks`
   - `opus_parse(…2563.pdf mode=images): stop=… in_tok=… out_tok=… text_len=…`
   - Then either upsert success (chunks > 0) or, if Opus still struggles, `opus_parse(…): could not parse JSON. preview=…` — at which point the JSON preview tells us exactly what Opus emitted and we iterate from there.

2. **Text-layer PDF regression:** Upload `slide.pdf` (or use an already-Drive-resident text-layer PDF). Trigger Smart Scan. Expect `using document block` log line and chunks upserted.

3. **Chat probe (if smoke 1 succeeded):** Run a chat query through `/api/chat` against the tenant — e.g. `"ค่าเบี้ยประชุมกรรมการสภามหาวิทยาลัย"` — and confirm a relevant chunk from `…2563.pdf` is retrieved with `[หมวด …](anchor)` markdown intact (or whatever section_path Opus produced).

4. **Failure path (if smoke 1 still returns 0 chunks):** The C2 cooldown takes over after 3 consecutive failures (existing behaviour); the user can also delete the file from Drive to stop further attempts.

---

## Self-review notes

**Spec coverage check:**
- ✅ Goal "drop tool binding entirely" → Tasks 4 (rewrite opus_parse_and_chunk without bind_tools)
- ✅ Goal "pure-scan PDFs send rasterised page images" → Task 3 (helper) + Task 4 (mode='images' branch)
- ✅ Goal "text-layer PDFs keep document block" → Task 4 (mode='document' branch) + Task 5 (routing)
- ✅ Goal "remove dead branches" → Tasks 4, 5, 6 across the three files
- ✅ Goal "backward compatibility for non-failing flows" → Task 4's `test_opus_parse_and_chunk_document_mode_includes_document_block` + Task 5's `test_ingest_v2_text_layer_routes_to_document_mode` + the adjusted `test_ingest_v2_orchestrates_pipeline`
- ✅ All 16 tests from spec are mapped to task steps

**Placeholder scan:** No TBDs / TODOs / "similar to" / un-coded test descriptions. Every code step has concrete code or exact commands.

**Type / signature consistency:**
- `_extract_json_from_fence(text)` — used in Tasks 1 (definition) and 4 (call site)
- `_text_from_response(response)` — used in Tasks 2 (definition) and 4 (call site)
- `_pdf_to_image_blocks(pdf_bytes, dpi=150)` — used in Tasks 3 (definition) and 4 (call site)
- `opus_parse_and_chunk(pdf_bytes, hyperlinks, filename, mode)` — Tasks 4 (rewrite) and 5 (caller)
- `ingest_v2(file_bytes, filename, namespace, tenant_id, …)` — Task 5; signature unchanged from prior, only body rewritten

All names match across tasks.
