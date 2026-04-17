import pytest
from unittest.mock import patch, MagicMock
from langchain_core.documents import Document


@pytest.mark.asyncio
async def test_rerank_with_scores_returns_tuples():
    with patch("chat.services.reranker._get_client") as mock_client:
        mock_response = MagicMock()
        mock_response.results = [
            MagicMock(index=0, relevance_score=0.85),
            MagicMock(index=1, relevance_score=0.45),
        ]
        mock_client.return_value.rerank.return_value = mock_response

        from chat.services.reranker import rerank_with_scores
        docs = [
            Document(page_content="High relevance", metadata={}),
            Document(page_content="Medium relevance", metadata={}),
        ]
        results = await rerank_with_scores("query", docs, top_k=2)
        assert len(results) == 2
        assert results[0][1] == 0.85
        assert results[1][1] == 0.45


def test_format_with_confidence_high():
    from chat.services.reranker import format_with_confidence
    scored = [(Document(page_content="Content", metadata={"source_filename": "a.pdf"}), 0.85)]
    result = format_with_confidence(scored)
    assert "[HIGH CONFIDENCE]" in result
    assert "a.pdf" in result


def test_format_with_confidence_medium():
    from chat.services.reranker import format_with_confidence
    scored = [(Document(page_content="Content", metadata={"source_filename": "b.pdf"}), 0.45)]
    result = format_with_confidence(scored)
    assert "[MEDIUM" in result


def test_format_with_confidence_filters_low():
    from chat.services.reranker import format_with_confidence
    scored = [
        (Document(page_content="High", metadata={"source_filename": "a.pdf"}), 0.85),
        (Document(page_content="Low", metadata={"source_filename": "c.pdf"}), 0.15),
    ]
    result = format_with_confidence(scored)
    assert "High" in result
    assert "Low" not in result


def test_format_with_confidence_all_low():
    from chat.services.reranker import format_with_confidence
    scored = [(Document(page_content="Low", metadata={}), 0.1)]
    result = format_with_confidence(scored)
    # Marker signals the agent to refuse honestly; content varies but always
    # starts with NO_RESULTS: so the LLM can pattern-match it.
    assert result.startswith("NO_RESULTS:")
    assert "fabricate" in result.lower()


def test_fmt_page_strips_pinecone_float_roundtrip():
    """Regression (2026-04-17): Pinecone stores numeric metadata as doubles,
    so page=1 ingested comes back as 1.0 → users saw "(p.1.0)" in LINE
    replies. Whole-number floats must display as integers.
    """
    from chat.services.reranker import _fmt_page
    assert _fmt_page(1.0) == "1"
    assert _fmt_page(42.0) == "42"
    assert _fmt_page("3.0") == "3"
    # Non-integer floats (rare but possible) keep their precision
    assert _fmt_page(1.5) == "1.5"
    # Empty / N/A / None → empty string (caller-safe)
    assert _fmt_page("") == ""
    assert _fmt_page(None) == ""
    assert _fmt_page("N/A") == ""
    # Already-int ints stay intact
    assert _fmt_page(7) == "7"
    # Non-numeric falls through
    assert _fmt_page("cover") == "cover"


def test_fmt_page_rejects_pathological_values():
    """Hardening against metadata drift: bool (int subclass), NaN, infinity,
    and unreasonable magnitudes must not leak to users as "page 0" etc.
    """
    import math
    from chat.services.reranker import _fmt_page
    # bool → empty (True/False are int subclass; "page 0" looks like a real page)
    assert _fmt_page(True) == ""
    assert _fmt_page(False) == ""
    # NaN / Inf → empty
    assert _fmt_page(float("nan")) == ""
    assert _fmt_page(float("inf")) == ""
    assert _fmt_page(float("-inf")) == ""
    # Sentinel < 1 or > 10000 → empty (no real document has those pages)
    assert _fmt_page(0) == ""
    assert _fmt_page(-5) == ""
    assert _fmt_page(10001) == ""
    assert _fmt_page(1e20) == ""


def test_format_with_confidence_empty_filename_no_broken_markdown():
    """Regression: empty source_filename (metadata drift) was emitting
    `INLINE_LINK: [](url)` — LINE renders as zero-width broken link.
    """
    from chat.services.reranker import format_with_confidence
    scored = [(
        Document(
            page_content="Content",
            metadata={
                "source_filename": "",  # empty, not missing
                "download_link": "https://example.com/a.pdf",
            },
        ),
        0.85,
    )]
    result = format_with_confidence(scored)
    assert "[](https://example.com/a.pdf)" not in result
    assert "[unknown](https://example.com/a.pdf)" in result


def test_format_with_confidence_integer_page_no_trailing_zero():
    """format_with_confidence must render whole-number pages without .0."""
    from chat.services.reranker import format_with_confidence
    scored = [(
        Document(
            page_content="Some content",
            metadata={"source_filename": "syllabus.pdf", "page": 1.0},
        ),
        0.85,
    )]
    result = format_with_confidence(scored)
    assert "(page 1)" in result
    assert "(page 1.0)" not in result


@pytest.mark.asyncio
async def test_rerank_with_scores_empty():
    from chat.services.reranker import rerank_with_scores
    assert await rerank_with_scores("query", [], top_k=5) == []
