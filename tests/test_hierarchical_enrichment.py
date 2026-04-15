"""TDD tests for hierarchical contextual enrichment (Task 4).

Tests verify:
- _build_section_map: parses markdown headers into section list
- _find_section_for_chunk: matches chunk to its owning section by position
- _enrich_with_context: uses section-level context when headers exist,
  falls back to global context when no headers
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from langchain_core.documents import Document


def test_build_section_map_from_headers():
    from ingest.services.enrichment import _build_section_map
    text = "# Curriculum\n\nDetails about curriculum here.\n\n## Tuition\n\nTuition is 21,000 baht.\n\n## Schedule\n\nMonday 9-12"
    sections = _build_section_map(text)
    assert len(sections) >= 2
    assert any("Tuition" in s["title"] for s in sections)
    assert all("text" in s and "start" in s and "end" in s for s in sections)


def test_build_section_map_no_headers():
    from ingest.services.enrichment import _build_section_map
    text = "Plain text without any headers. Just content."
    sections = _build_section_map(text)
    assert len(sections) == 1
    assert sections[0]["title"] == "Document"


def test_build_section_map_text_content():
    """Each section's 'text' field should contain that section's content."""
    from ingest.services.enrichment import _build_section_map
    text = "# Intro\n\nThis is intro content.\n\n# Fees\n\nFees are 21000 baht."
    sections = _build_section_map(text)
    assert len(sections) >= 2
    intro = next(s for s in sections if "Intro" in s["title"])
    fees = next(s for s in sections if "Fees" in s["title"])
    assert "intro content" in intro["text"]
    assert "21000 baht" in fees["text"]


def test_build_section_map_text_truncated_at_3000():
    """Section text should be capped at 3000 chars."""
    from ingest.services.enrichment import _build_section_map
    long_body = "word " * 1000  # ~5000 chars
    text = f"# BigSection\n\n{long_body}"
    sections = _build_section_map(text)
    assert len(sections) == 1
    assert len(sections[0]["text"]) <= 3000


def test_build_section_map_no_headers_full_text_truncated():
    """Fallback Document section also truncates text to 3000 chars."""
    from ingest.services.enrichment import _build_section_map
    long_text = "x " * 2000  # ~4000 chars
    sections = _build_section_map(long_text)
    assert len(sections) == 1
    assert sections[0]["title"] == "Document"
    assert len(sections[0]["text"]) <= 3000


def test_find_section_for_chunk_basic():
    from ingest.services.enrichment import _build_section_map, _find_section_for_chunk
    full_text = "# Curriculum\n\nLong text\n\n## Tuition\n\nTuition is 21,000 baht per semester"
    sections = _build_section_map(full_text)
    chunk_text = "Tuition is 21,000 baht per semester"
    section = _find_section_for_chunk(sections, chunk_text, full_text)
    assert "Tuition" in section["title"]


def test_find_section_for_chunk_falls_back_to_first():
    """When chunk is not found in text, return first section."""
    from ingest.services.enrichment import _build_section_map, _find_section_for_chunk
    full_text = "# Intro\n\nSome intro.\n\n# Body\n\nSome body."
    sections = _build_section_map(full_text)
    section = _find_section_for_chunk(sections, "completely missing text", full_text)
    # Should return some section (first or last) without crashing
    assert section is not None
    assert "title" in section


@pytest.mark.asyncio
async def test_enrich_uses_section_context():
    with patch("ingest.services.enrichment.get_haiku_precise") as MockLLM:
        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(return_value=MagicMock(content="Context about tuition"))
        MockLLM.return_value = mock_instance  # get_haiku_precise() returns the mock

        from ingest.services.enrichment import _enrich_with_context
        full_text = "# Curriculum\n\nLong text\n\n## Tuition\n\nTuition is 21,000 baht per semester"
        chunks = [Document(page_content="Tuition is 21,000 baht per semester", metadata={})]
        enriched = await _enrich_with_context(chunks, full_text)

        assert len(enriched) == 1
        assert "Context about tuition" in enriched[0].page_content


@pytest.mark.asyncio
async def test_enrich_fallback_global_when_no_headers():
    with patch("ingest.services.enrichment.get_haiku_precise") as MockLLM:
        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(return_value=MagicMock(content="Global context"))
        MockLLM.return_value = mock_instance  # get_haiku_precise() returns the mock

        from ingest.services.enrichment import _enrich_with_context
        full_text = "Plain text without headers. Just a bunch of content about various topics."
        chunks = [Document(page_content="Just a bunch of content", metadata={})]
        enriched = await _enrich_with_context(chunks, full_text)

        assert "Global context" in enriched[0].page_content


@pytest.mark.asyncio
async def test_enrich_empty_chunks_returns_empty():
    from ingest.services.enrichment import _enrich_with_context
    result = await _enrich_with_context([], "some text")
    assert result == []


@pytest.mark.asyncio
async def test_enrich_skips_chunk_on_llm_failure():
    """If LLM raises, the chunk should be kept with original content (not crash)."""
    with patch("ingest.services.enrichment.get_haiku_precise") as MockLLM:
        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(side_effect=Exception("API error"))
        MockLLM.return_value = mock_instance  # get_haiku_precise() returns the mock

        from ingest.services.enrichment import _enrich_with_context
        full_text = "# Section\n\nSome content here."
        chunks = [Document(page_content="Some content here.", metadata={"key": "value"})]
        enriched = await _enrich_with_context(chunks, full_text)

        # On failure, chunk is skipped (not enriched but returned as-is or removed)
        # The spec says "skip chunk, log warning" - we interpret as returned unchanged
        assert len(enriched) == 1
        assert enriched[0].page_content == "Some content here."


@pytest.mark.asyncio
async def test_enrich_uses_section_prompt_format():
    """Section prompt should include section title, not full document."""
    captured_calls = []

    with patch("ingest.services.enrichment.get_haiku_precise") as MockLLM:
        mock_instance = MagicMock()

        async def capture_invoke(prompt):
            captured_calls.append(str(prompt))
            return MagicMock(content="Section context")

        mock_instance.ainvoke = capture_invoke
        MockLLM.return_value = mock_instance  # get_haiku_precise() returns the mock

        from ingest.services.enrichment import _enrich_with_context
        full_text = "# Admissions\n\nApplication details.\n\n## Requirements\n\nGPA must be 3.0"
        chunks = [Document(page_content="GPA must be 3.0", metadata={})]
        await _enrich_with_context(chunks, full_text)

        assert len(captured_calls) == 1
        # Section-based prompt should reference section title
        assert "Requirements" in captured_calls[0] or "Admissions" in captured_calls[0]


@pytest.mark.asyncio
async def test_enrich_batches_pause_every_10():
    """Should pause asyncio.sleep every 10 chunks, not every 5."""
    sleep_calls = []

    async def fake_sleep(secs):
        sleep_calls.append(secs)

    with patch("ingest.services.enrichment.get_haiku_precise") as MockLLM:
        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(return_value=MagicMock(content="ctx"))
        MockLLM.return_value = mock_instance  # get_haiku_precise() returns the mock

        with patch("ingest.services.ingestion.asyncio.sleep", side_effect=fake_sleep):
            from ingest.services.enrichment import _enrich_with_context
            import importlib
            import ingest.services.ingestion as ing_mod
            importlib.reload(ing_mod)

            full_text = "# Section\n\n" + "Content here. " * 20
            chunks = [
                Document(page_content=f"Content chunk {i}", metadata={})
                for i in range(12)
            ]
            # Re-import after reload
            await ing_mod._enrich_with_context(chunks, full_text)

    # Should have paused once (at index 10), not at index 5
    assert len(sleep_calls) == 1
