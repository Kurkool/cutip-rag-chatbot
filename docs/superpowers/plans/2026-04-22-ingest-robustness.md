# Ingest Robustness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pre-flight OCR fallback for pure-scan PDFs (C1) and Firestore-backed failure tracking (C2) to `cutip-ingest-worker`, eliminating the silent 0-chunk failure mode and the hourly scan-all Opus hammer.

**Architecture:** C1 detects zero text-layer PDFs via `pymupdf`, runs per-page Haiku 4.5 vision OCR through the raw `anthropic.AsyncAnthropic` SDK, and passes the result as a new sidecar block into the existing `opus_parse_and_chunk` flow. C2 persists failure state in a new Firestore collection `ingest_failures` keyed by `{tenant_id}__{drive_file_id}`; `_process_gdrive_folder` skips files at `MAX_CONSECUTIVE_FAILURES` until Drive `modifiedTime` advances, records on 0-chunk/exception, and clears on success (or on the existing SKIP-up-to-date branch, opportunistically).

**Tech Stack:** Python 3.11, FastAPI, pymupdf, `anthropic` SDK (raw), `google-cloud-firestore`, `pytest` + `pytest-asyncio`.

**Spec:** `docs/superpowers/specs/2026-04-22-ingest-robustness-design.md`

---

## File Structure

**New files:**
- `shared/services/ingest_failures.py` — async Firestore wrapper for `ingest_failures` collection (record / clear / get / list). One responsibility, ~120 LOC.
- `tests/test_ingest_failures.py` — unit tests for the wrapper.

**Modified files:**
- `ingest/services/ingestion_v2.py` — add `extract_page_text`, `_get_ocr_client`, `ocr_pdf_pages`, extend `opus_parse_and_chunk` with `ocr_sidecar` kwarg, orchestrate pre-flight in `ingest_v2`.
- `ingest/services/_v2_prompts.py` — add `format_ocr_sidecar`, extend `USER_PROMPT_TEMPLATE` with `{ocr_block}` placeholder.
- `ingest/routers/ingestion.py` — modify `_process_gdrive_folder`: parallel state fetch, cooldown branch, failure bookkeeping around `ingest_v2` call.
- `tests/conftest.py` — add `tiny_text_pdf_bytes` + `pure_scan_pdf_bytes` fixtures; add `ingest_failures` dict to `FakeFirestore`.
- `tests/test_ingestion_v2.py` — add tests for `extract_page_text`, `ocr_pdf_pages`, `format_ocr_sidecar`, `opus_parse_and_chunk` sidecar, `ingest_v2` orchestration.
- `tests/test_ingestion_router.py` — add tests for parallel fetch, cooldown skip / unblock, failure bookkeeping, SKIP-up-to-date opportunistic clear, ordering.
- `CLAUDE.md` — add gotcha #18 (pure-scan PDF handling + scan-all cooldown).

---

## Task 1: Fixtures for text-layer and pure-scan PDFs

**Files:**
- Modify: `tests/conftest.py`

Fixtures are needed by Tasks 2 and 8. Keep them at module scope (session-wide is overkill for byte strings this small) so tests that mutate never touch each other.

- [ ] **Step 1: Write the fixtures**

Append to `tests/conftest.py` (before the `@pytest.fixture` for `FakeFirestore`):

```python
# ──────────────────────────────────────
# PDF byte fixtures for ingestion tests
# ──────────────────────────────────────

@pytest.fixture
def tiny_text_pdf_bytes() -> bytes:
    """One-page PDF with a text layer. Used to verify NON-pure-scan flow."""
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "hello world")
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def pure_scan_pdf_bytes() -> bytes:
    """Two-page PDF with embedded images only (no text layer at all)."""
    import pymupdf
    doc = pymupdf.open()
    # Build a 1x1 white PNG for the embedded image (tiny — content is not what's tested).
    import io, struct, zlib
    def _tiny_png() -> bytes:
        header = b"\x89PNG\r\n\x1a\n"
        ihdr = b"IHDR" + struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        ihdr_chunk = struct.pack(">I", 13) + ihdr + struct.pack(">I", zlib.crc32(ihdr))
        raw = b"\x00\xff\xff\xff"
        comp = zlib.compress(raw)
        idat = b"IDAT" + comp
        idat_chunk = struct.pack(">I", len(comp)) + idat + struct.pack(">I", zlib.crc32(idat))
        iend = b"IEND"
        iend_chunk = struct.pack(">I", 0) + iend + struct.pack(">I", zlib.crc32(iend))
        return header + ihdr_chunk + idat_chunk + iend_chunk
    for _ in range(2):
        page = doc.new_page()
        page.insert_image(pymupdf.Rect(0, 0, 100, 100), stream=_tiny_png())
    data = doc.tobytes()
    doc.close()
    return data
```

- [ ] **Step 2: Add `ingest_failures` to `FakeFirestore`**

Find the `FakeFirestore` class (around line 68). Add to `__init__`:

```python
        self.ingest_failures: dict[str, dict] = {}
```

And to `reset()`:

```python
        self.ingest_failures.clear()
```

- [ ] **Step 3: Sanity-check fixtures load and open**

Add a smoke test at the bottom of `tests/conftest.py` (or a new minimal `tests/test_conftest_fixtures.py` — either works; inline is fine for single-file sanity):

```python
def test_tiny_text_pdf_bytes_fixture_opens(tiny_text_pdf_bytes):
    import pymupdf
    doc = pymupdf.open(stream=tiny_text_pdf_bytes, filetype="pdf")
    assert doc.page_count == 1
    assert "hello" in doc[0].get_text("text")
    doc.close()


def test_pure_scan_pdf_bytes_fixture_has_no_text(pure_scan_pdf_bytes):
    import pymupdf
    doc = pymupdf.open(stream=pure_scan_pdf_bytes, filetype="pdf")
    assert doc.page_count == 2
    for page in doc:
        assert page.get_text("text").strip() == ""
        assert len(page.get_images(full=False)) == 1
    doc.close()
```

- [ ] **Step 4: Run sanity tests**

```bash
.venv/Scripts/python.exe -m pytest tests/test_conftest_fixtures.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/test_conftest_fixtures.py
git commit -m "test(fixtures): add tiny-text and pure-scan PDF byte fixtures + FakeFirestore.ingest_failures"
```

---

## Task 2: `extract_page_text` function

**Files:**
- Modify: `ingest/services/ingestion_v2.py`
- Modify: `tests/test_ingestion_v2.py`

Pure pymupdf; extracts per-page text layer into a dict. Used by `ingest_v2` to decide pure-scan vs not.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ingestion_v2.py`:

```python
def test_extract_page_text_returns_per_page_dict(tiny_text_pdf_bytes):
    result = ingestion_v2.extract_page_text(tiny_text_pdf_bytes)
    assert set(result.keys()) == {1}
    assert "hello" in result[1]


def test_extract_page_text_pure_scan_returns_all_empty(pure_scan_pdf_bytes):
    result = ingestion_v2.extract_page_text(pure_scan_pdf_bytes)
    assert set(result.keys()) == {1, 2}
    assert all(v == "" for v in result.values())
    assert sum(len(v) for v in result.values()) == 0
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py::test_extract_page_text_returns_per_page_dict -v
```

Expected: FAIL with `AttributeError: module 'ingest.services.ingestion_v2' has no attribute 'extract_page_text'`.

- [ ] **Step 3: Implement**

Add to `ingest/services/ingestion_v2.py` after `extract_hyperlinks`:

```python
def extract_page_text(pdf_bytes: bytes) -> dict[int, str]:
    """Return {1-based page index: extracted text layer} for the PDF.

    Used by ``ingest_v2`` to detect pure-scan PDFs (all values empty). Also
    exposes per-page text so future work can feed hybrid PDFs' native text
    to Opus as an OCR-equivalent sidecar without triggering the LLM path.
    """
    import pymupdf

    out: dict[int, str] = {}
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        for i, page in enumerate(doc):
            out[i + 1] = page.get_text("text") or ""
    finally:
        doc.close()
    return out
```

- [ ] **Step 4: Run tests**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py::test_extract_page_text_returns_per_page_dict tests/test_ingestion_v2.py::test_extract_page_text_pure_scan_returns_all_empty -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add ingest/services/ingestion_v2.py tests/test_ingestion_v2.py
git commit -m "feat(ingest-v2): add extract_page_text for per-page text-layer inspection"
```

---

## Task 3: `_get_ocr_client` factory

**Files:**
- Modify: `ingest/services/ingestion_v2.py`
- Modify: `tests/test_ingestion_v2.py`

Monkeypatchable factory that returns a cached `anthropic.AsyncAnthropic` instance. Mirrors the `_get_opus_llm` convention so tests can swap the client without touching the caching layer.

- [ ] **Step 1: Write failing test**

Append to `tests/test_ingestion_v2.py`:

```python
def test_get_ocr_client_is_cached_async_anthropic():
    from anthropic import AsyncAnthropic

    # Clear the cache from any prior test run so we verify caching in isolation.
    ingestion_v2._get_ocr_client.cache_clear()

    c1 = ingestion_v2._get_ocr_client()
    c2 = ingestion_v2._get_ocr_client()

    assert isinstance(c1, AsyncAnthropic)
    assert c1 is c2  # lru_cache returns the same instance
```

- [ ] **Step 2: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py::test_get_ocr_client_is_cached_async_anthropic -v
```

Expected: FAIL with `AttributeError: ... has no attribute '_get_ocr_client'`.

- [ ] **Step 3: Implement**

Add module-level constants + factory to `ingest/services/ingestion_v2.py` near the top (just below existing imports, above `_get_opus_llm`):

```python
# OCR fallback constants (used when ingest_v2 detects a pure-scan PDF)
OCR_MODEL = "claude-haiku-4-5-20251001"
OCR_CONCURRENCY = 4
OCR_DPI = 200
OCR_MAX_TOKENS_PER_PAGE = 4096
PURE_SCAN_TEXT_THRESHOLD = 0


@lru_cache(maxsize=1)
def _get_ocr_client():
    """Cached raw AsyncAnthropic client for per-page vision OCR.

    Intentionally uses the raw anthropic SDK rather than langchain_anthropic:
    the OCR call is a single image + text block with no tool use, and raw
    SDK has cleaner async semantics and direct access to response bodies for
    debugging. Tests monkeypatch this function (or its return value) — the
    cache is small so a cache_clear() in a fixture is cheap.
    """
    from anthropic import AsyncAnthropic
    from shared.config import settings
    return AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY, max_retries=3)
```

Also confirm `from anthropic import AsyncAnthropic` is NOT already at the top — if it is, the inside-function import can be removed. Imports inside factory keep module load fast for test collection.

- [ ] **Step 4: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py::test_get_ocr_client_is_cached_async_anthropic -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ingest/services/ingestion_v2.py tests/test_ingestion_v2.py
git commit -m "feat(ingest-v2): add _get_ocr_client factory (Haiku 4.5, raw AsyncAnthropic)"
```

---

## Task 4: `ocr_pdf_pages` success path

**Files:**
- Modify: `ingest/services/ingestion_v2.py`
- Modify: `tests/test_ingestion_v2.py`

Per-page vision OCR with concurrency limit. This task covers the happy path only; failures handled in Task 5.

- [ ] **Step 1: Write failing test**

Append to `tests/test_ingestion_v2.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_ocr_pdf_pages_returns_per_page_dict(pure_scan_pdf_bytes, monkeypatch):
    """Mock anthropic client returns scripted text per page → dict[int,str]."""
    from unittest.mock import AsyncMock, MagicMock

    class FakeContentBlock:
        def __init__(self, text):
            self.type = "text"
            self.text = text

    call_count = {"n": 0}

    async def fake_create(**kwargs):
        call_count["n"] += 1
        resp = MagicMock()
        resp.content = [FakeContentBlock(f"page {call_count['n']} ocr text")]
        return resp

    fake_client = MagicMock()
    fake_client.messages = MagicMock()
    fake_client.messages.create = AsyncMock(side_effect=fake_create)

    ingestion_v2._get_ocr_client.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_ocr_client", lambda: fake_client)

    result = await ingestion_v2.ocr_pdf_pages(pure_scan_pdf_bytes, "test.pdf")

    assert set(result.keys()) == {1, 2}
    assert "ocr text" in result[1]
    assert "ocr text" in result[2]
    assert call_count["n"] == 2  # one call per page
```

- [ ] **Step 2: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py::test_ocr_pdf_pages_returns_per_page_dict -v
```

Expected: FAIL (attribute error).

- [ ] **Step 3: Implement**

Add to `ingest/services/ingestion_v2.py` after `_get_ocr_client`:

```python
OCR_PROMPT = (
    "สกัดข้อความทั้งหมดที่มองเห็นจากภาพสแกนหน้านี้ "
    "คงรูปโครงสร้าง (หัวข้อ ย่อหน้า รายการหัวข้อ ตาราง) เท่าที่ทำได้. "
    "ไม่ต้องใส่คำอธิบายใด ๆ ให้คืนเฉพาะข้อความเท่านั้น. "
    "ถ้ามีภาษาอังกฤษปนให้คงไว้ตามต้นฉบับ."
)


async def ocr_pdf_pages(pdf_bytes: bytes, filename: str) -> dict[int, str]:
    """Per-page vision OCR using Haiku 4.5, parallelized up to OCR_CONCURRENCY.

    Returns ``{1-based page: text}``. A per-page exception yields an empty
    string for that page (partial OCR is better than total fail). If every
    page raises, the function raises ``RuntimeError``.
    """
    import asyncio
    import base64
    import pymupdf

    client = _get_ocr_client()
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    n_pages = doc.page_count
    # Render page images up front so the async tasks don't fight over the pymupdf handle.
    page_pngs: dict[int, bytes] = {}
    try:
        for i, page in enumerate(doc):
            page_pngs[i + 1] = page.get_pixmap(dpi=OCR_DPI).tobytes("png")
    finally:
        doc.close()

    sem = asyncio.Semaphore(OCR_CONCURRENCY)

    async def _one(page_num: int) -> tuple[int, str | BaseException]:
        async with sem:
            try:
                b64 = base64.standard_b64encode(page_pngs[page_num]).decode("ascii")
                resp = await client.messages.create(
                    model=OCR_MODEL,
                    max_tokens=OCR_MAX_TOKENS_PER_PAGE,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                            {"type": "text", "text": OCR_PROMPT},
                        ],
                    }],
                )
                text_parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
                return page_num, "\n".join(text_parts).strip()
            except BaseException as exc:
                return page_num, exc

    results = await asyncio.gather(*[_one(p) for p in range(1, n_pages + 1)])

    out: dict[int, str] = {}
    n_failed = 0
    for page_num, payload in results:
        if isinstance(payload, BaseException):
            logger.warning("ocr_pdf_pages(%s): page %d failed: %r", filename, page_num, payload)
            out[page_num] = ""
            n_failed += 1
        else:
            out[page_num] = payload

    if n_failed == n_pages:
        raise RuntimeError(f"OCR failed for all pages of {filename!r}")

    logger.info(
        "ocr_pdf_pages(%s): OCR complete — %d pages, %d chars total, %d failed",
        filename, n_pages, sum(len(v) for v in out.values()), n_failed,
    )
    return out
```

- [ ] **Step 4: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py::test_ocr_pdf_pages_returns_per_page_dict -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ingest/services/ingestion_v2.py tests/test_ingestion_v2.py
git commit -m "feat(ingest-v2): add ocr_pdf_pages (Haiku 4.5 vision, async, success path)"
```

---

## Task 5: `ocr_pdf_pages` partial-failure and all-fail paths

**Files:**
- Modify: `tests/test_ingestion_v2.py`

No implementation change — verifies the try/except branches of the function from Task 4.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ingestion_v2.py`:

```python
@pytest.mark.asyncio
async def test_ocr_pdf_pages_partial_failure_returns_empty_string(pure_scan_pdf_bytes, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    class FakeContentBlock:
        def __init__(self, text):
            self.type = "text"
            self.text = text

    # First call raises; second succeeds. MagicMock's side_effect iterates.
    call_count = {"n": 0}

    async def fake_create(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated rate limit")
        resp = MagicMock()
        resp.content = [FakeContentBlock("page two ok")]
        return resp

    fake_client = MagicMock()
    fake_client.messages = MagicMock()
    fake_client.messages.create = AsyncMock(side_effect=fake_create)

    ingestion_v2._get_ocr_client.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_ocr_client", lambda: fake_client)

    result = await ingestion_v2.ocr_pdf_pages(pure_scan_pdf_bytes, "test.pdf")

    # One page failed → empty string at that key, no raise.
    assert "" in result.values()
    assert any("page two" in v for v in result.values())


@pytest.mark.asyncio
async def test_ocr_pdf_pages_all_pages_fail_raises(pure_scan_pdf_bytes, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    async def fake_create(**kwargs):
        raise RuntimeError("every call fails")

    fake_client = MagicMock()
    fake_client.messages = MagicMock()
    fake_client.messages.create = AsyncMock(side_effect=fake_create)

    ingestion_v2._get_ocr_client.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_ocr_client", lambda: fake_client)

    with pytest.raises(RuntimeError, match="OCR failed for all pages"):
        await ingestion_v2.ocr_pdf_pages(pure_scan_pdf_bytes, "test.pdf")
```

- [ ] **Step 2: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py::test_ocr_pdf_pages_partial_failure_returns_empty_string tests/test_ingestion_v2.py::test_ocr_pdf_pages_all_pages_fail_raises -v
```

Expected: 2 passed (the Task-4 implementation already handles both cases).

- [ ] **Step 3: Commit**

```bash
git add tests/test_ingestion_v2.py
git commit -m "test(ingest-v2): cover ocr_pdf_pages partial and total failure paths"
```

---

## Task 6: `format_ocr_sidecar` + `USER_PROMPT_TEMPLATE` extension

**Files:**
- Modify: `ingest/services/_v2_prompts.py`
- Modify: `tests/test_ingestion_v2.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ingestion_v2.py`:

```python
def test_format_ocr_sidecar_empty_dict_returns_placeholder():
    from ingest.services._v2_prompts import format_ocr_sidecar
    assert format_ocr_sidecar({}) == "(no OCR sidecar — document text layer sufficient)"


def test_format_ocr_sidecar_populated_renders_per_page_sections():
    from ingest.services._v2_prompts import format_ocr_sidecar
    out = format_ocr_sidecar({1: "page one text", 2: "page two\nmore text"})
    assert "### Page 1" in out
    assert "page one text" in out
    assert "### Page 2" in out
    assert "page two\nmore text" in out


def test_user_prompt_template_has_ocr_block_placeholder():
    from ingest.services._v2_prompts import USER_PROMPT_TEMPLATE
    assert "{ocr_block}" in USER_PROMPT_TEMPLATE
```

- [ ] **Step 2: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k "format_ocr_sidecar or ocr_block_placeholder" -v
```

Expected: FAIL (ImportError + substring missing).

- [ ] **Step 3: Implement**

Append to `ingest/services/_v2_prompts.py`:

```python
def format_ocr_sidecar(ocr_text: dict[int, str]) -> str:
    """Render per-page OCR text as a stable markdown block for Opus.

    Opus is told (via the user prompt) to treat the rendered PDF image as
    ground truth and the OCR text as assistive — OCR may miss Thai tone
    marks or confuse digits, and Opus should correct obvious errors by
    looking at the image. Empty input returns a placeholder string so the
    prompt template substitution never leaves a blank line dangling.
    """
    if not ocr_text or all(not v for v in ocr_text.values()):
        return "(no OCR sidecar — document text layer sufficient)"
    lines = [
        "OCR was run on every page because the PDF has no extractable text layer.",
        "Treat the rendered image as ground truth and correct obvious OCR errors",
        "(mis-segmented Thai tone marks, digit/letter confusion, etc.).",
        "",
    ]
    for page_num in sorted(ocr_text.keys()):
        text = ocr_text[page_num]
        lines.append(f"### Page {page_num}")
        lines.append(text if text else "(OCR failed for this page — rely on vision only)")
        lines.append("")
    return "\n".join(lines).rstrip()
```

Then modify `USER_PROMPT_TEMPLATE` (replace the existing constant):

```python
USER_PROMPT_TEMPLATE = """Document filename: {filename}

Hyperlink sidecar (URIs hidden in PDF annotations, not visible on the rendered page):
{sidecar_block}

OCR sidecar:
{ocr_block}

Parse the attached PDF and emit chunks via the `record_chunks` tool."""
```

- [ ] **Step 4: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k "format_ocr_sidecar or ocr_block_placeholder" -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add ingest/services/_v2_prompts.py tests/test_ingestion_v2.py
git commit -m "feat(ingest-v2): add format_ocr_sidecar + {ocr_block} placeholder in user prompt"
```

---

## Task 7: `opus_parse_and_chunk` — `ocr_sidecar` kwarg wiring

**Files:**
- Modify: `ingest/services/ingestion_v2.py`
- Modify: `tests/test_ingestion_v2.py`

Extend the existing function's signature so that when `ocr_sidecar` is provided, the formatted OCR block replaces the `{ocr_block}` placeholder in the user message.

- [ ] **Step 1: Write failing test**

Append to `tests/test_ingestion_v2.py`:

```python
@pytest.mark.asyncio
async def test_opus_parse_and_chunk_injects_ocr_sidecar(monkeypatch, pure_scan_pdf_bytes):
    """When ocr_sidecar is provided, the user message must contain the formatted OCR block."""
    from unittest.mock import AsyncMock, MagicMock

    captured: dict = {}

    fake_llm = MagicMock()

    async def fake_ainvoke(messages):
        # Capture the human message content for assertion.
        human = messages[1]
        captured["content"] = human.content
        return MagicMock(tool_calls=[{"args": {"chunks": []}}])

    fake_llm.ainvoke = AsyncMock(side_effect=fake_ainvoke)
    fake_llm.bind_tools = MagicMock(return_value=fake_llm)

    ingestion_v2._get_opus_llm.cache_clear()
    monkeypatch.setattr(ingestion_v2, "_get_opus_llm", lambda: fake_llm)

    await ingestion_v2.opus_parse_and_chunk(
        pdf_bytes=pure_scan_pdf_bytes,
        hyperlinks=[],
        filename="x.pdf",
        ocr_sidecar={1: "hello from page 1", 2: "hello from page 2"},
    )

    # Find the text content block in the human message.
    text_blocks = [b["text"] for b in captured["content"] if b.get("type") == "text"]
    assert any("hello from page 1" in t for t in text_blocks)
    assert any("### Page 1" in t for t in text_blocks)


@pytest.mark.asyncio
async def test_opus_parse_and_chunk_without_ocr_sidecar_uses_placeholder(monkeypatch, pure_scan_pdf_bytes):
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

    text_blocks = [b["text"] for b in captured["content"] if b.get("type") == "text"]
    assert any("no OCR sidecar" in t for t in text_blocks)
```

- [ ] **Step 2: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k opus_parse_and_chunk -v
```

Expected: FAIL — existing function doesn't accept `ocr_sidecar` kwarg.

- [ ] **Step 3: Implement**

Edit `opus_parse_and_chunk` in `ingest/services/ingestion_v2.py`. Three concrete changes:

**3a. Update the import block at the top** (adds `format_ocr_sidecar`):

```python
from ingest.services._v2_prompts import (
    CHUNK_TOOL_SCHEMA,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    format_sidecar,
    format_ocr_sidecar,  # NEW
)
```

**3b. Add the new kwarg to the function signature** (add `ocr_sidecar: dict[int, str] | None = None,`):

```python
async def opus_parse_and_chunk(
    pdf_bytes: bytes,
    hyperlinks: list[dict],
    filename: str,
    ocr_sidecar: dict[int, str] | None = None,
) -> list[Document]:
```

Also extend the docstring: add one paragraph noting "When `ocr_sidecar` is provided (pure-scan path), per-page OCR text is injected into the user prompt via `{ocr_block}` alongside the hyperlink sidecar. The PDF document block is still sent so Opus can cross-check vision against OCR."

**3c. Insert one line and extend the format call.** Locate the existing:

```python
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    sidecar_block = format_sidecar(hyperlinks)
    user_text = USER_PROMPT_TEMPLATE.format(
        filename=filename,
        sidecar_block=sidecar_block,
    )
```

Change to:

```python
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    sidecar_block = format_sidecar(hyperlinks)
    ocr_block = format_ocr_sidecar(ocr_sidecar or {})  # NEW
    user_text = USER_PROMPT_TEMPLATE.format(
        filename=filename,
        sidecar_block=sidecar_block,
        ocr_block=ocr_block,  # NEW
    )
```

All other lines (message construction, `bind_tools`, `ainvoke`, tool_calls parsing, chunk cleanup) remain untouched.

- [ ] **Step 4: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k opus_parse_and_chunk -v
```

Expected: PASS for the two new tests + no regression on existing `test_opus_parse_and_chunk_*` tests.

- [ ] **Step 5: Commit**

```bash
git add ingest/services/ingestion_v2.py tests/test_ingestion_v2.py
git commit -m "feat(ingest-v2): opus_parse_and_chunk accepts ocr_sidecar kwarg"
```

---

## Task 8: `ingest_v2` orchestration — pre-flight pure-scan detection

**Files:**
- Modify: `ingest/services/ingestion_v2.py`
- Modify: `tests/test_ingestion_v2.py`

Wire `extract_page_text` → `ocr_pdf_pages` into the existing `ingest_v2` flow. When the PDF has zero text across all pages, call OCR and pass the result as `ocr_sidecar` to `opus_parse_and_chunk`. Otherwise, unchanged.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ingestion_v2.py`:

```python
@pytest.mark.asyncio
async def test_ingest_v2_pure_scan_triggers_ocr_path(monkeypatch, pure_scan_pdf_bytes):
    """Pure-scan PDF must trigger ocr_pdf_pages and pass its output downstream."""
    from unittest.mock import AsyncMock

    captured: dict = {}

    async def fake_ocr(pdf_bytes, filename):
        captured["ocr_called"] = True
        captured["filename"] = filename
        return {1: "ocr p1", 2: "ocr p2"}

    async def fake_opus(pdf_bytes, hyperlinks, filename, ocr_sidecar=None):
        captured["ocr_sidecar_arg"] = ocr_sidecar
        return []  # 0 chunks — we're not exercising the upsert here

    monkeypatch.setattr(ingestion_v2, "ocr_pdf_pages", fake_ocr)
    monkeypatch.setattr(ingestion_v2, "opus_parse_and_chunk", fake_opus)

    result = await ingestion_v2.ingest_v2(
        file_bytes=pure_scan_pdf_bytes,
        filename="scan.pdf",
        namespace="ns-test",
        tenant_id="tenant_x",
    )

    assert result == 0
    assert captured.get("ocr_called") is True
    assert captured["ocr_sidecar_arg"] == {1: "ocr p1", 2: "ocr p2"}


@pytest.mark.asyncio
async def test_ingest_v2_text_layer_skips_ocr(monkeypatch, tiny_text_pdf_bytes):
    """Text-layer PDF must NOT trigger ocr_pdf_pages."""
    from unittest.mock import AsyncMock

    captured: dict = {}

    async def fake_ocr(pdf_bytes, filename):
        captured["ocr_called"] = True
        return {}

    async def fake_opus(pdf_bytes, hyperlinks, filename, ocr_sidecar=None):
        captured["ocr_sidecar_arg"] = ocr_sidecar
        return []

    monkeypatch.setattr(ingestion_v2, "ocr_pdf_pages", fake_ocr)
    monkeypatch.setattr(ingestion_v2, "opus_parse_and_chunk", fake_opus)

    await ingestion_v2.ingest_v2(
        file_bytes=tiny_text_pdf_bytes,
        filename="text.pdf",
        namespace="ns-test",
        tenant_id="tenant_x",
    )

    assert captured.get("ocr_called") is not True
    assert captured["ocr_sidecar_arg"] is None
```

- [ ] **Step 2: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k ingest_v2_pure_scan -v
.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -k ingest_v2_text_layer -v
```

Expected: FAIL (pre-flight branch not wired yet → opus called with `ocr_sidecar=None` even for pure-scan).

- [ ] **Step 3: Implement**

Edit `ingest_v2` in `ingest/services/ingestion_v2.py`. Replace the body between `pdf_bytes = ensure_pdf(...)` and the `chunks = await opus_parse_and_chunk(...)` line with:

```python
    pdf_bytes = ensure_pdf(file_bytes, filename)

    page_text = extract_page_text(pdf_bytes)
    ocr_sidecar: dict[int, str] | None = None
    if sum(len(t) for t in page_text.values()) <= PURE_SCAN_TEXT_THRESHOLD:
        logger.info(
            "ingest_v2(%s): pure-scan detected (0 text chars across %d pages), running OCR",
            filename, len(page_text),
        )
        ocr_sidecar = await ocr_pdf_pages(pdf_bytes, filename)

    hyperlinks = extract_hyperlinks(pdf_bytes)
    chunks = await opus_parse_and_chunk(
        pdf_bytes, hyperlinks, filename, ocr_sidecar=ocr_sidecar,
    )
```

- [ ] **Step 4: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingestion_v2.py -v
```

Expected: every `ingest_v2` test passes — new ones + all 11 original tests.

- [ ] **Step 5: Commit**

```bash
git add ingest/services/ingestion_v2.py tests/test_ingestion_v2.py
git commit -m "feat(ingest-v2): pre-flight pure-scan detection triggers OCR fallback"
```

---

## Task 9: `ingest_failures` — `record_failure` (create + increment)

**Files:**
- Create: `shared/services/ingest_failures.py`
- Create: `tests/test_ingest_failures.py`

This task scaffolds the new module with the first function and its tests. Subsequent tasks add clear/get/list/resilience.

- [ ] **Step 1: Write failing tests (new file)**

Create `tests/test_ingest_failures.py`:

```python
"""Tests for shared.services.ingest_failures (Firestore collection wrapper)."""
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_record_failure_creates_doc_on_first_call(monkeypatch):
    """First call writes a new doc with fail_count=1 and first_failed_at set."""
    from shared.services import ingest_failures as ifs

    fake_doc_ref = MagicMock()
    fake_col = MagicMock()
    fake_col.document = MagicMock(return_value=fake_doc_ref)
    fake_client = MagicMock()
    fake_client.collection = MagicMock(return_value=fake_col)

    ifs._get_client.cache_clear()
    monkeypatch.setattr(ifs, "_get_client", lambda: fake_client)

    await ifs.record_failure(
        tenant_id="tenant_a",
        drive_file_id="abc123",
        filename="x.pdf",
        drive_modified=1700000000.0,
        error="test error",
    )

    fake_client.collection.assert_called_with("ingest_failures")
    fake_col.document.assert_called_with("tenant_a__abc123")
    # .set called with merge=True
    assert fake_doc_ref.set.called
    args, kwargs = fake_doc_ref.set.call_args
    payload = args[0]
    assert payload["tenant_id"] == "tenant_a"
    assert payload["drive_file_id"] == "abc123"
    assert payload["filename"] == "x.pdf"
    assert payload["last_drive_modified"] == 1700000000.0
    assert "test error" in payload["last_error_short"]
    # Use merge=True so first_failed_at not clobbered on subsequent calls
    assert kwargs.get("merge") is True


@pytest.mark.asyncio
async def test_record_failure_uses_firestore_increment_for_fail_count(monkeypatch):
    from google.cloud import firestore
    from shared.services import ingest_failures as ifs

    fake_doc_ref = MagicMock()
    fake_col = MagicMock(document=MagicMock(return_value=fake_doc_ref))
    fake_client = MagicMock(collection=MagicMock(return_value=fake_col))
    ifs._get_client.cache_clear()
    monkeypatch.setattr(ifs, "_get_client", lambda: fake_client)

    await ifs.record_failure(
        tenant_id="t", drive_file_id="d", filename="x.pdf",
        drive_modified=1.0, error="e",
    )

    payload = fake_doc_ref.set.call_args[0][0]
    assert isinstance(payload["fail_count"], firestore.Increment)
```

- [ ] **Step 2: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingest_failures.py -v
```

Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Create the module**

Create `shared/services/ingest_failures.py`:

```python
"""Firestore-backed ingest failure tracking for scan-all cooldown.

Keeps a per-file fail counter in collection ``ingest_failures`` keyed by
``{tenant_id}__{drive_file_id}``. ``_process_gdrive_folder`` checks the
counter against MAX_CONSECUTIVE_FAILURES before attempting ingest and
clears the record on success, so a single broken file cannot hammer the
Opus API indefinitely.

All functions are async and non-blocking — Firestore SDK is sync, so
every operation is wrapped in ``asyncio.to_thread``. On Firestore
unavailability the functions log a warning and degrade gracefully (reads
return empty, writes silently no-op) so an outage never takes down the
scan path.
"""
from __future__ import annotations

import asyncio
import logging
import time
from functools import lru_cache
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

COLLECTION = "ingest_failures"
MAX_CONSECUTIVE_FAILURES = 3

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_client() -> firestore.Client:
    """Cached Firestore client. Tests monkeypatch this function."""
    from shared.config import settings
    return firestore.Client(project=settings.GOOGLE_CLOUD_PROJECT or None)


def _doc_id(tenant_id: str, drive_file_id: str) -> str:
    return f"{tenant_id}__{drive_file_id}"


def _short_error(error: Exception | str) -> str:
    if isinstance(error, Exception):
        msg = f"{type(error).__name__}: {error}"
    else:
        msg = str(error)
    return msg[:200]


def _record_failure_sync(tenant_id, drive_file_id, filename, drive_modified, error) -> None:
    now = time.time()
    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "drive_file_id": drive_file_id,
        "filename": filename,
        "fail_count": firestore.Increment(1),
        "last_failed_at": now,
        "first_failed_at": now,  # merge=True → written only if missing
        "last_drive_modified": drive_modified,
        "last_error_short": _short_error(error),
    }
    _get_client().collection(COLLECTION).document(_doc_id(tenant_id, drive_file_id)).set(
        payload, merge=True,
    )


async def record_failure(
    tenant_id: str,
    drive_file_id: str,
    filename: str,
    drive_modified: float,
    error: Exception | str,
) -> None:
    """Record a failure for (tenant_id, drive_file_id).

    Increments ``fail_count`` on every call (server-atomic via
    ``firestore.Increment``). ``first_failed_at`` is set on the initial
    write and preserved thereafter via ``merge=True``.
    """
    try:
        await asyncio.to_thread(
            _record_failure_sync,
            tenant_id, drive_file_id, filename, drive_modified, error,
        )
        logger.info(
            "ingest_failures.record_failure: tenant=%s drive_id=%s error=%s",
            tenant_id, drive_file_id, _short_error(error),
        )
    except Exception as exc:
        logger.warning(
            "ingest_failures.record_failure: Firestore unavailable — state not persisted (tenant=%s drive_id=%s): %r",
            tenant_id, drive_file_id, exc,
        )
```

- [ ] **Step 4: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingest_failures.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add shared/services/ingest_failures.py tests/test_ingest_failures.py
git commit -m "feat(ingest-failures): add record_failure with atomic increment + merge"
```

---

## Task 10: `ingest_failures` — `get_failure`, `clear_failure`, `list_failures`

**Files:**
- Modify: `shared/services/ingest_failures.py`
- Modify: `tests/test_ingest_failures.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ingest_failures.py`:

```python
@pytest.mark.asyncio
async def test_get_failure_returns_none_when_missing(monkeypatch):
    from shared.services import ingest_failures as ifs

    fake_snap = MagicMock(exists=False)
    fake_doc_ref = MagicMock(get=MagicMock(return_value=fake_snap))
    fake_col = MagicMock(document=MagicMock(return_value=fake_doc_ref))
    fake_client = MagicMock(collection=MagicMock(return_value=fake_col))
    ifs._get_client.cache_clear()
    monkeypatch.setattr(ifs, "_get_client", lambda: fake_client)

    assert await ifs.get_failure("t", "d") is None


@pytest.mark.asyncio
async def test_get_failure_returns_doc_data_when_present(monkeypatch):
    from shared.services import ingest_failures as ifs

    fake_snap = MagicMock(exists=True)
    fake_snap.to_dict.return_value = {"tenant_id": "t", "drive_file_id": "d", "fail_count": 2}
    fake_doc_ref = MagicMock(get=MagicMock(return_value=fake_snap))
    fake_col = MagicMock(document=MagicMock(return_value=fake_doc_ref))
    fake_client = MagicMock(collection=MagicMock(return_value=fake_col))
    ifs._get_client.cache_clear()
    monkeypatch.setattr(ifs, "_get_client", lambda: fake_client)

    out = await ifs.get_failure("t", "d")
    assert out == {"tenant_id": "t", "drive_file_id": "d", "fail_count": 2}


@pytest.mark.asyncio
async def test_clear_failure_calls_delete(monkeypatch):
    from shared.services import ingest_failures as ifs

    fake_doc_ref = MagicMock()
    fake_col = MagicMock(document=MagicMock(return_value=fake_doc_ref))
    fake_client = MagicMock(collection=MagicMock(return_value=fake_col))
    ifs._get_client.cache_clear()
    monkeypatch.setattr(ifs, "_get_client", lambda: fake_client)

    await ifs.clear_failure("t", "d")
    fake_col.document.assert_called_with("t__d")
    assert fake_doc_ref.delete.called


@pytest.mark.asyncio
async def test_list_failures_returns_dict_keyed_by_drive_id(monkeypatch):
    from shared.services import ingest_failures as ifs

    def _snap(drive_id, fail_count):
        s = MagicMock()
        s.to_dict.return_value = {"drive_file_id": drive_id, "fail_count": fail_count}
        return s

    fake_query = MagicMock()
    fake_query.stream = MagicMock(return_value=[_snap("d1", 1), _snap("d2", 3)])
    fake_col = MagicMock()
    fake_col.where = MagicMock(return_value=fake_query)
    fake_client = MagicMock(collection=MagicMock(return_value=fake_col))
    ifs._get_client.cache_clear()
    monkeypatch.setattr(ifs, "_get_client", lambda: fake_client)

    out = await ifs.list_failures("tenant_a")

    assert set(out.keys()) == {"d1", "d2"}
    assert out["d1"]["fail_count"] == 1
    assert out["d2"]["fail_count"] == 3
```

- [ ] **Step 2: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingest_failures.py -v
```

Expected: 4 new tests FAIL (functions missing).

- [ ] **Step 3: Implement**

Append to `shared/services/ingest_failures.py`:

```python
def _get_failure_sync(tenant_id: str, drive_file_id: str) -> dict[str, Any] | None:
    snap = _get_client().collection(COLLECTION).document(_doc_id(tenant_id, drive_file_id)).get()
    if not snap.exists:
        return None
    return snap.to_dict()


async def get_failure(tenant_id: str, drive_file_id: str) -> dict[str, Any] | None:
    """Return the failure doc dict, or None if no failure recorded."""
    try:
        return await asyncio.to_thread(_get_failure_sync, tenant_id, drive_file_id)
    except Exception as exc:
        logger.warning(
            "ingest_failures.get_failure: Firestore unavailable (tenant=%s drive_id=%s): %r",
            tenant_id, drive_file_id, exc,
        )
        return None


def _clear_failure_sync(tenant_id: str, drive_file_id: str) -> None:
    _get_client().collection(COLLECTION).document(_doc_id(tenant_id, drive_file_id)).delete()


async def clear_failure(tenant_id: str, drive_file_id: str) -> None:
    """Delete the failure doc if present. Ignores 'not found'."""
    try:
        await asyncio.to_thread(_clear_failure_sync, tenant_id, drive_file_id)
        logger.info(
            "ingest_failures.clear_failure: tenant=%s drive_id=%s",
            tenant_id, drive_file_id,
        )
    except Exception as exc:
        logger.warning(
            "ingest_failures.clear_failure: Firestore unavailable (tenant=%s drive_id=%s): %r",
            tenant_id, drive_file_id, exc,
        )


def _list_failures_sync(tenant_id: str) -> dict[str, dict[str, Any]]:
    query = (
        _get_client()
        .collection(COLLECTION)
        .where(filter=FieldFilter("tenant_id", "==", tenant_id))
    )
    out: dict[str, dict[str, Any]] = {}
    for snap in query.stream():
        data = snap.to_dict() or {}
        drive_id = data.get("drive_file_id", "")
        if drive_id:
            out[drive_id] = data
    return out


async def list_failures(tenant_id: str) -> dict[str, dict[str, Any]]:
    """Return {drive_file_id: failure_doc} for all failures of this tenant.

    Intended for one-round-trip use in the scan loop.
    """
    try:
        return await asyncio.to_thread(_list_failures_sync, tenant_id)
    except Exception as exc:
        logger.warning(
            "ingest_failures.list_failures: Firestore unavailable (tenant=%s): %r",
            tenant_id, exc,
        )
        return {}
```

- [ ] **Step 4: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingest_failures.py -v
```

Expected: 6 passed total.

- [ ] **Step 5: Commit**

```bash
git add shared/services/ingest_failures.py tests/test_ingest_failures.py
git commit -m "feat(ingest-failures): add get, clear, list_failures + Firestore-outage resilience"
```

---

## Task 11: Firestore-outage resilience tests (belt-and-braces)

**Files:**
- Modify: `tests/test_ingest_failures.py`

The Task-9 and Task-10 impls already wrap every op in try/except. These tests verify that behavior explicitly so future refactors don't silently break it.

- [ ] **Step 1: Write tests**

Append to `tests/test_ingest_failures.py`:

```python
@pytest.mark.asyncio
async def test_record_failure_firestore_outage_logs_and_does_not_raise(monkeypatch, caplog):
    from shared.services import ingest_failures as ifs

    def boom(*a, **kw):
        raise RuntimeError("Firestore unavailable")

    monkeypatch.setattr(ifs, "_record_failure_sync", boom)

    with caplog.at_level("WARNING", logger="shared.services.ingest_failures"):
        await ifs.record_failure(
            tenant_id="t", drive_file_id="d", filename="x.pdf",
            drive_modified=1.0, error="e",
        )

    assert any("Firestore unavailable" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_list_failures_firestore_outage_returns_empty_dict(monkeypatch):
    from shared.services import ingest_failures as ifs

    def boom(*a, **kw):
        raise RuntimeError("down")

    monkeypatch.setattr(ifs, "_list_failures_sync", boom)

    out = await ifs.list_failures("t")
    assert out == {}


@pytest.mark.asyncio
async def test_clear_failure_firestore_outage_does_not_raise(monkeypatch):
    from shared.services import ingest_failures as ifs

    def boom(*a, **kw):
        raise RuntimeError("down")

    monkeypatch.setattr(ifs, "_clear_failure_sync", boom)

    # should not raise
    await ifs.clear_failure("t", "d")
```

- [ ] **Step 2: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingest_failures.py -v
```

Expected: 9 passed (3 new + 6 existing).

- [ ] **Step 3: Commit**

```bash
git add tests/test_ingest_failures.py
git commit -m "test(ingest-failures): verify Firestore-outage resilience for all 3 writes"
```

---

## Task 12: `_process_gdrive_folder` — parallel state fetch + cooldown branch

**Files:**
- Modify: `ingest/routers/ingestion.py`
- Modify: `tests/test_ingestion_router.py`

Fetch `drive_state`, `legacy_filenames`, and `ingest_failures.list_failures(tenant_id)` in a single `asyncio.gather`. Then add the cooldown branch per the spec's ordering (SKIP up-to-date → LEGACY → COOLDOWN → RENAME → OVERWRITE/NEW).

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ingestion_router.py` (check for an existing fixture pattern; if the file already uses `ingestion_v2.ingest_v2` monkeypatching, reuse that style):

```python
import pytest


@pytest.mark.asyncio
async def test_scan_fail_cooldown_blocks_at_threshold(monkeypatch):
    """fail_count >= MAX + drive_modified <= last_drive_modified → skip without calling ingest_v2."""
    from ingest.routers import ingestion as router_mod
    from shared.services import ingest_failures as ifs

    monkeypatch.setattr(router_mod, "_get_existing_filenames", lambda ns: set())

    async def fake_list_failures(tenant_id):
        return {
            "drive_file_abc": {
                "fail_count": 3,
                "last_drive_modified": 2000.0,
            }
        }
    monkeypatch.setattr(ifs, "list_failures", fake_list_failures)

    def fake_get_state(ns):
        return {}  # no prior Pinecone entry
    monkeypatch.setattr("shared.services.vectorstore.get_existing_drive_state", fake_get_state)

    def fake_list_files(folder_id):
        return [{"id": "drive_file_abc", "name": "broken.pdf", "modifiedTime": "1970-01-01T00:33:20.000Z"}]
    monkeypatch.setattr("shared.services.gdrive.list_files", fake_list_files)

    ingest_called = {"n": 0}

    async def fake_ingest_v2(**kw):
        ingest_called["n"] += 1
        return 5
    monkeypatch.setattr("ingest.services.ingestion_v2.ingest_v2", fake_ingest_v2)

    tenant = {"tenant_id": "t", "pinecone_namespace": "ns-t"}
    result = await router_mod._process_gdrive_folder(
        tenant, folder_id="F", doc_category="general", skip_existing=True,
    )

    assert ingest_called["n"] == 0
    assert any("cooldown" in s["reason"].lower() for s in result.skipped)


@pytest.mark.asyncio
async def test_scan_fail_cooldown_unblocks_on_drive_modified_advance(monkeypatch):
    """drive_modified > last_drive_modified → cooldown lifts → ingest_v2 runs."""
    from ingest.routers import ingestion as router_mod
    from shared.services import ingest_failures as ifs

    monkeypatch.setattr(router_mod, "_get_existing_filenames", lambda ns: set())

    async def fake_list_failures(tenant_id):
        return {
            "drive_file_abc": {
                "fail_count": 3,
                "last_drive_modified": 1000.0,
            }
        }
    monkeypatch.setattr(ifs, "list_failures", fake_list_failures)
    monkeypatch.setattr("shared.services.vectorstore.get_existing_drive_state", lambda ns: {})
    monkeypatch.setattr(
        "shared.services.gdrive.list_files",
        lambda fid: [{"id": "drive_file_abc", "name": "fixed.pdf", "modifiedTime": "2020-01-01T00:00:00.000Z"}],
    )
    monkeypatch.setattr("shared.services.gdrive.download_file", lambda fid: b"%PDF-1.4\n%%EOF")

    ingest_called = {"n": 0}
    async def fake_ingest_v2(**kw):
        ingest_called["n"] += 1
        return 5
    monkeypatch.setattr("ingest.services.ingestion_v2.ingest_v2", fake_ingest_v2)

    async def noop(*a, **kw): return None
    monkeypatch.setattr(ifs, "record_failure", noop)
    monkeypatch.setattr(ifs, "clear_failure", noop)

    tenant = {"tenant_id": "t", "pinecone_namespace": "ns-t"}
    await router_mod._process_gdrive_folder(
        tenant, folder_id="F", doc_category="general", skip_existing=True,
    )

    assert ingest_called["n"] == 1


@pytest.mark.asyncio
async def test_scan_fail_count_below_threshold_ingests(monkeypatch):
    """fail_count < MAX → ingest attempted."""
    from ingest.routers import ingestion as router_mod
    from shared.services import ingest_failures as ifs

    monkeypatch.setattr(router_mod, "_get_existing_filenames", lambda ns: set())

    async def fake_list_failures(tenant_id):
        return {"drive_file_abc": {"fail_count": 2, "last_drive_modified": 9999.0}}
    monkeypatch.setattr(ifs, "list_failures", fake_list_failures)
    monkeypatch.setattr("shared.services.vectorstore.get_existing_drive_state", lambda ns: {})
    monkeypatch.setattr(
        "shared.services.gdrive.list_files",
        lambda fid: [{"id": "drive_file_abc", "name": "f.pdf", "modifiedTime": "1970-01-01T00:00:00.000Z"}],
    )
    monkeypatch.setattr("shared.services.gdrive.download_file", lambda fid: b"%PDF-1.4\n%%EOF")

    ingest_called = {"n": 0}
    async def fake_ingest_v2(**kw):
        ingest_called["n"] += 1
        return 7
    monkeypatch.setattr("ingest.services.ingestion_v2.ingest_v2", fake_ingest_v2)
    async def noop(*a, **kw): return None
    monkeypatch.setattr(ifs, "record_failure", noop)
    monkeypatch.setattr(ifs, "clear_failure", noop)

    tenant = {"tenant_id": "t", "pinecone_namespace": "ns-t"}
    await router_mod._process_gdrive_folder(
        tenant, folder_id="F", doc_category="general", skip_existing=True,
    )

    assert ingest_called["n"] == 1
```

- [ ] **Step 2: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingestion_router.py -k "fail_cooldown or below_threshold" -v
```

Expected: FAIL — router doesn't call `list_failures` yet; cooldown branch doesn't exist.

- [ ] **Step 3: Implement**

Edit `ingest/routers/ingestion.py`:

3a. Add import at top:

```python
from shared.services import ingest_failures
```

3b. Inside `_process_gdrive_folder`, replace the parallel state fetch block (currently just the `if skip_existing:` → `get_existing_drive_state` / `_get_existing_filenames` lines ~333-338) with:

```python
    # Build existing state from Pinecone + failures from Firestore (parallel when skip_existing)
    if skip_existing:
        drive_state, legacy_filenames, failures = await asyncio.gather(
            asyncio.to_thread(get_existing_drive_state, namespace),
            asyncio.to_thread(_get_existing_filenames, namespace),
            ingest_failures.list_failures(tenant_id),
        )
        state_filenames = {v["filename"] for v in drive_state.values()}
        legacy_only = legacy_filenames - state_filenames
    else:
        drive_state, legacy_only, failures = {}, set(), {}
```

3c. Inside the per-file loop, insert the cooldown check after the existing entry/legacy checks and before the fall-through to ingest. Replace the block (currently starting at `if skip_existing:` inside the loop, ~350-370) with:

```python
        stale_filename_to_delete: str | None = None

        if skip_existing:
            entry = drive_state.get(drive_id)

            # 1. SKIP up-to-date — opportunistic clear of any stale failure doc.
            if entry is not None and entry["filename"] == filename and drive_modified <= entry["ingest_ts"]:
                await ingest_failures.clear_failure(tenant_id, drive_id)
                skipped.append({"filename": filename, "reason": "up to date"})
                continue

            # 2. LEGACY (no drive_file_id yet) — preserve existing behavior.
            if entry is None and filename in legacy_only:
                skipped.append({"filename": filename, "reason": "legacy, no drive_file_id"})
                continue

            # 3. FAIL_COOLDOWN — stop hammer before any expensive work.
            fail_rec = failures.get(drive_id)
            if (fail_rec
                    and fail_rec.get("fail_count", 0) >= ingest_failures.MAX_CONSECUTIVE_FAILURES
                    and drive_modified <= fail_rec.get("last_drive_modified", 0.0)):
                skipped.append({
                    "filename": filename,
                    "reason": (
                        f"cooldown: {fail_rec.get('fail_count', '?')} consecutive failures — "
                        "edit the file in Drive to retry"
                    ),
                })
                logger.info(
                    "scan-all: FAIL_COOLDOWN skip tenant=%s drive_id=%s filename=%r fail_count=%s",
                    tenant_id, drive_id, filename, fail_rec.get("fail_count"),
                )
                continue

            # 4. RENAME — mark old chunks for deletion, fall through to ingest.
            if entry is not None and entry["filename"] != filename:
                stale_filename_to_delete = entry["filename"]
                logger.info(
                    "Drive rename detected (tenant=%s): %r → %r",
                    tenant_id, entry["filename"], filename,
                )

            # else: OVERWRITE (entry + newer mtime) — fall through.
            # else: NEW (no entry, no legacy) — fall through.
```

- [ ] **Step 4: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingestion_router.py -k "fail_cooldown or below_threshold" -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add ingest/routers/ingestion.py tests/test_ingestion_router.py
git commit -m "feat(scan-all): parallel state fetch + FAIL_COOLDOWN branch in _process_gdrive_folder"
```

---

## Task 13: Failure bookkeeping — record on 0-chunk/exception, clear on success

**Files:**
- Modify: `ingest/routers/ingestion.py`
- Modify: `tests/test_ingestion_router.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ingestion_router.py`:

```python
@pytest.mark.asyncio
async def test_scan_records_failure_on_zero_chunks(monkeypatch):
    from ingest.routers import ingestion as router_mod
    from shared.services import ingest_failures as ifs

    monkeypatch.setattr(router_mod, "_get_existing_filenames", lambda ns: set())
    async def empty_failures(tid): return {}
    monkeypatch.setattr(ifs, "list_failures", empty_failures)
    monkeypatch.setattr("shared.services.vectorstore.get_existing_drive_state", lambda ns: {})
    monkeypatch.setattr(
        "shared.services.gdrive.list_files",
        lambda fid: [{"id": "d", "name": "f.pdf", "modifiedTime": "2020-01-01T00:00:00.000Z"}],
    )
    monkeypatch.setattr("shared.services.gdrive.download_file", lambda fid: b"%PDF-1.4\n%%EOF")
    async def zero(**kw): return 0
    monkeypatch.setattr("ingest.services.ingestion_v2.ingest_v2", zero)

    record_calls: list = []
    async def capture(**kw): record_calls.append(kw)
    monkeypatch.setattr(ifs, "record_failure", capture)
    async def noop(*a, **kw): return None
    monkeypatch.setattr(ifs, "clear_failure", noop)

    tenant = {"tenant_id": "t", "pinecone_namespace": "ns-t"}
    result = await router_mod._process_gdrive_folder(
        tenant, folder_id="F", doc_category="general", skip_existing=True,
    )

    assert len(record_calls) == 1
    assert record_calls[0]["drive_file_id"] == "d"
    assert any(s["reason"] == "0 chunks produced" for s in result.skipped)


@pytest.mark.asyncio
async def test_scan_records_failure_on_exception(monkeypatch):
    from ingest.routers import ingestion as router_mod
    from shared.services import ingest_failures as ifs

    monkeypatch.setattr(router_mod, "_get_existing_filenames", lambda ns: set())
    async def empty_failures(tid): return {}
    monkeypatch.setattr(ifs, "list_failures", empty_failures)
    monkeypatch.setattr("shared.services.vectorstore.get_existing_drive_state", lambda ns: {})
    monkeypatch.setattr(
        "shared.services.gdrive.list_files",
        lambda fid: [{"id": "d", "name": "f.pdf", "modifiedTime": "2020-01-01T00:00:00.000Z"}],
    )
    monkeypatch.setattr("shared.services.gdrive.download_file", lambda fid: b"%PDF-1.4\n%%EOF")
    async def boom(**kw): raise RuntimeError("opus exploded")
    monkeypatch.setattr("ingest.services.ingestion_v2.ingest_v2", boom)

    record_calls: list = []
    async def capture(**kw): record_calls.append(kw)
    monkeypatch.setattr(ifs, "record_failure", capture)
    async def noop(*a, **kw): return None
    monkeypatch.setattr(ifs, "clear_failure", noop)

    tenant = {"tenant_id": "t", "pinecone_namespace": "ns-t"}
    result = await router_mod._process_gdrive_folder(
        tenant, folder_id="F", doc_category="general", skip_existing=True,
    )

    assert len(record_calls) == 1
    assert isinstance(record_calls[0]["error"], RuntimeError)
    assert len(result.errors) == 1


@pytest.mark.asyncio
async def test_scan_clears_failure_on_successful_ingest(monkeypatch):
    from ingest.routers import ingestion as router_mod
    from shared.services import ingest_failures as ifs

    monkeypatch.setattr(router_mod, "_get_existing_filenames", lambda ns: set())
    async def empty_failures(tid): return {}
    monkeypatch.setattr(ifs, "list_failures", empty_failures)
    monkeypatch.setattr("shared.services.vectorstore.get_existing_drive_state", lambda ns: {})
    monkeypatch.setattr(
        "shared.services.gdrive.list_files",
        lambda fid: [{"id": "d", "name": "f.pdf", "modifiedTime": "2020-01-01T00:00:00.000Z"}],
    )
    monkeypatch.setattr("shared.services.gdrive.download_file", lambda fid: b"%PDF-1.4\n%%EOF")
    async def good(**kw): return 7
    monkeypatch.setattr("ingest.services.ingestion_v2.ingest_v2", good)

    clear_calls: list = []
    async def capture(*a, **kw): clear_calls.append((a, kw))
    monkeypatch.setattr(ifs, "clear_failure", capture)
    async def noop(*a, **kw): return None
    monkeypatch.setattr(ifs, "record_failure", noop)

    tenant = {"tenant_id": "t", "pinecone_namespace": "ns-t"}
    await router_mod._process_gdrive_folder(
        tenant, folder_id="F", doc_category="general", skip_existing=True,
    )

    # One clear call after successful ingest
    assert len(clear_calls) == 1


@pytest.mark.asyncio
async def test_scan_skip_up_to_date_also_clears_failure(monkeypatch):
    """A stale failure doc is cleared opportunistically when we SKIP (file is fine)."""
    from ingest.routers import ingestion as router_mod
    from shared.services import ingest_failures as ifs

    monkeypatch.setattr(router_mod, "_get_existing_filenames", lambda ns: set())
    # A failure doc exists even though Pinecone says the file is fine.
    async def fake_failures(tid):
        return {"d": {"fail_count": 3, "last_drive_modified": 1.0}}
    monkeypatch.setattr(ifs, "list_failures", fake_failures)

    # Pinecone says the file is ingested and current.
    def fake_state(ns):
        return {"d": {"filename": "f.pdf", "ingest_ts": 9999999999.0}}
    monkeypatch.setattr("shared.services.vectorstore.get_existing_drive_state", fake_state)
    monkeypatch.setattr(
        "shared.services.gdrive.list_files",
        lambda fid: [{"id": "d", "name": "f.pdf", "modifiedTime": "2020-01-01T00:00:00.000Z"}],
    )

    clear_calls: list = []
    async def capture(*a, **kw): clear_calls.append((a, kw))
    monkeypatch.setattr(ifs, "clear_failure", capture)
    async def noop(*a, **kw): return None
    monkeypatch.setattr(ifs, "record_failure", noop)

    ingest_called = {"n": 0}
    async def should_not_run(**kw):
        ingest_called["n"] += 1
        return 5
    monkeypatch.setattr("ingest.services.ingestion_v2.ingest_v2", should_not_run)

    tenant = {"tenant_id": "t", "pinecone_namespace": "ns-t"}
    result = await router_mod._process_gdrive_folder(
        tenant, folder_id="F", doc_category="general", skip_existing=True,
    )

    assert ingest_called["n"] == 0  # SKIP up-to-date wins
    assert len(clear_calls) == 1  # stale doc got cleared
    assert any(s["reason"] == "up to date" for s in result.skipped)
```

- [ ] **Step 2: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingestion_router.py -k "records_failure or clears_failure or skip_up_to_date" -v
```

Expected: 4 FAIL — bookkeeping not wired yet.

- [ ] **Step 3: Implement**

Edit the ingest try/except in `_process_gdrive_folder` (around the `try: ...ingestion_v2.ingest_v2...` block, ~371-393). Replace with:

```python
        try:
            # RENAME cleanup first so dangling chunks don't linger
            if stale_filename_to_delete:
                await asyncio.to_thread(
                    delete_vectors_by_filename, namespace, stale_filename_to_delete,
                )

            file_bytes = download_file(drive_id)
            drive_link = f"https://drive.google.com/file/d/{drive_id}/view"
            chunks = await ingestion_v2.ingest_v2(
                file_bytes=file_bytes, filename=filename, namespace=namespace,
                tenant_id=tenant_id, doc_category=doc_category,
                download_link=drive_link, drive_file_id=drive_id,
            )

            if chunks == 0:
                await ingest_failures.record_failure(
                    tenant_id=tenant_id, drive_file_id=drive_id, filename=filename,
                    drive_modified=drive_modified, error="ingest returned 0 chunks",
                )
                skipped.append({"filename": filename, "reason": "0 chunks produced"})
            else:
                await ingest_failures.clear_failure(tenant_id, drive_id)
                ingested.append({"filename": filename, "chunks": chunks})
                logger.info("Ingested '%s' (%d chunks) for tenant %s", filename, chunks, tenant_id)

            await asyncio.sleep(3)

        except ValueError as exc:
            # Unsupported-extension / user-input issues — not pipeline failures.
            skipped.append({"filename": filename, "reason": str(exc)})
        except Exception as exc:
            logger.exception("Failed to ingest '%s'", filename)
            await ingest_failures.record_failure(
                tenant_id=tenant_id, drive_file_id=drive_id, filename=filename,
                drive_modified=drive_modified, error=exc,
            )
            errors.append({"filename": filename, "error": "ingestion failed"})
```

- [ ] **Step 4: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ingestion_router.py -v
```

Expected: all router tests pass — existing + the 7 new ones (3 from Task 12, 4 from Task 13).

- [ ] **Step 5: Commit**

```bash
git add ingest/routers/ingestion.py tests/test_ingestion_router.py
git commit -m "feat(scan-all): record failure on 0-chunk/exception, clear on success"
```

---

## Task 14: Full regression run

**Files:**
- None modified; this is a verification gate.

Confirms nothing drifted in adjacent tests (scan_all.py, tenants, super_god, etc.).

- [ ] **Step 1: Run full test suite**

```bash
.venv/Scripts/python.exe -m pytest tests/ -q
```

Expected: all green. If any adjacent test fails, check monkeypatches — a common failure mode is that `test_scan_all.py` patched `_process_gdrive_folder` at the old signature; verify those mocks.

- [ ] **Step 2: If any failure, read the trace + fix inline; otherwise proceed.**

- [ ] **Step 3: Commit the test-suite-green state (only if fixes were needed above)**

```bash
git add -p  # stage only what you fixed
git commit -m "test: adapt ingest router tests to ingest_failures wiring"
```

If no adjacent fixes needed → skip commit.

---

## Task 15: CLAUDE.md gotcha #18

**Files:**
- Modify: `CLAUDE.md`

Record the new invariants so future cross-machine sessions don't re-discover.

- [ ] **Step 1: Add the entry**

Open `CLAUDE.md`. In the "Critical gotchas (cross-machine)" section (numbered list), append as #18:

```markdown
18. **Pure-scan PDFs need OCR, scan-all cools down on consecutive failures.** `ingest_v2` pre-flight-detects zero-text-layer PDFs (`extract_page_text` → all pages empty) and triggers per-page Haiku 4.5 vision OCR (`ocr_pdf_pages`) whose output becomes an `{ocr_block}` sidecar in the Opus user prompt. Separately, the `scan-all` state machine in `_process_gdrive_folder` consults `shared/services/ingest_failures.py` — after `MAX_CONSECUTIVE_FAILURES` (currently 3) consecutive 0-chunk or exception outcomes for the same `drive_file_id`, subsequent scans skip the file until Drive `modifiedTime` advances. Ingest failures live in Firestore collection `ingest_failures` keyed by `{tenant_id}__{drive_file_id}`. Operational: `.ocr.docx` sidecar workaround from `scripts/ocr_pdf_via_opus.py` is now unnecessary for Drive-synced files.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(CLAUDE.md): add gotcha #18 (pure-scan OCR + scan-all cooldown)"
```

---

## Task 16: Deploy to Cloud Run + smoke test

**Files:**
- None (operational task).

**Prerequisites:**
- All previous tasks merged (commits can be local; user pushes themselves per project convention).
- `gcloud` authenticated for project `cutip-rag`.

- [ ] **Step 1: Build + deploy ingest-worker (Windows quirks from CLAUDE.md)**

```bash
cd cutip-rag-chatbot/
cp ingest/Dockerfile Dockerfile
gcloud run deploy cutip-ingest-worker --source=. --region=asia-southeast1 --project=cutip-rag --timeout=3600 --quiet
git checkout Dockerfile
```

Expected: new revision `cutip-ingest-worker-000XX-yyy` deployed, status "True".

- [ ] **Step 2: Smoke — re-ingest the historical pure-scan PDF via audit namespace**

Use the `.pdf` still in `sample-doc/cutip-doc/` (not the `.ocr.docx` workaround). Upload it to Drive manually (Drive UI, folder `1duGSSJxj9g-A2dxNTLROnjBPn7V08aMk`), or use an existing test file known to be pure-scan.

Then trigger:

```bash
curl -X POST "https://cutip-ingest-worker-secaaxwrgq-as.a.run.app/api/tenants/cutip_01/ingest/v2/gdrive/file?namespace_override=cutip_v2_audit" \
  -H "X-API-Key: $(gcloud secrets versions access latest --secret=ADMIN_API_KEY)" \
  -H "Content-Type: application/json" \
  -d '{"folder_id": "1duGSSJxj9g-A2dxNTLROnjBPn7V08aMk", "filename": "ประกาศจุฬาลงกรณ์มหาวิทยาลัยเรื่อง การกำหนดเกณฑ์และอัตราการจ่ายเงินประเภทต่างๆ พ.ศ. 2563.pdf", "doc_category": "general"}'
```

- [ ] **Step 3: Verify Cloud Run log shows OCR pathway fired and chunks produced**

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="cutip-ingest-worker" AND (textPayload:"pure-scan detected" OR textPayload:"ocr_pdf_pages" OR textPayload:"Ingested")' --limit=20 --freshness=10m --format="value(timestamp,textPayload)"
```

Expected log lines (in order):
- `ingest_v2(ประกาศจุฬาฯ...pdf): pure-scan detected (0 text chars across 24 pages), running OCR`
- `ocr_pdf_pages(ประกาศจุฬาฯ...pdf): OCR complete — 24 pages, NNNNN chars total, 0 failed`
- `Ingested 'ประกาศจุฬาฯ...pdf' (N chunks) for tenant cutip_01` with `N > 0`

- [ ] **Step 4: Verify no regression on the 19 existing files**

Wait for the next hourly `scan-all` tick (or trigger manually with `curl -X POST` against the super_admin-gated endpoint), then:

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="cutip-ingest-worker" AND textPayload:"scan-all"' --limit=5 --freshness=90m --format="value(textPayload)"
```

Expected: `scan-all tenant=cutip_01 total=19 ingested=0 skipped=19 errors=0` (all SKIP up-to-date).

- [ ] **Step 5: Verify Firestore is clean**

```bash
gcloud firestore databases query "SELECT * FROM ingest_failures" --project=cutip-rag --database='(default)' 2>&1 | head -20
```

Or browse in the Firebase console. Expected: empty collection (or any historical residue cleared on the SKIP-up-to-date path).

- [ ] **Step 6: Rollback if needed**

If any of the above fails:

```bash
gcloud run services update-traffic cutip-ingest-worker --to-revisions=cutip-ingest-worker-00027-wgm=100 --region=asia-southeast1
```

And file a follow-up issue describing the regression.

- [ ] **Step 7: Mark plan complete**

No commit required here. Update internal tracking / close the task list.

---

## Appendix — OCR prompt text (single source)

The `OCR_PROMPT` constant in `ingest/services/ingestion_v2.py` is the canonical wording and also matches what `scripts/ocr_pdf_via_opus.py` uses. If one drifts, update both — or better, extract into `_v2_prompts.py` as a follow-up.

```
สกัดข้อความทั้งหมดที่มองเห็นจากภาพสแกนหน้านี้
คงรูปโครงสร้าง (หัวข้อ ย่อหน้า รายการหัวข้อ ตาราง) เท่าที่ทำได้.
ไม่ต้องใส่คำอธิบายใด ๆ ให้คืนเฉพาะข้อความเท่านั้น.
ถ้ามีภาษาอังกฤษปนให้คงไว้ตามต้นฉบับ.
```
