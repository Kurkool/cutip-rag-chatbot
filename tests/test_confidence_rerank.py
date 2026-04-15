import pytest
from unittest.mock import patch, MagicMock
from langchain_core.documents import Document


def test_rerank_with_scores_returns_tuples():
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
        results = rerank_with_scores("query", docs, top_k=2)
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
    assert "No relevant documents" in result


def test_rerank_with_scores_empty():
    from chat.services.reranker import rerank_with_scores
    assert rerank_with_scores("query", [], top_k=5) == []
