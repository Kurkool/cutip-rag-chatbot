import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from langchain_core.documents import Document


def test_reciprocal_rank_fusion():
    from services.search import reciprocal_rank_fusion
    doc_a = Document(page_content="A content here for matching", metadata={})
    doc_b = Document(page_content="B content here for matching", metadata={})
    doc_c = Document(page_content="C content here for matching", metadata={})

    vector = [doc_a, doc_b]
    bm25 = [doc_c, doc_a]
    merged = reciprocal_rank_fusion(vector, bm25, k=60)

    # doc_a appears in both → highest score
    assert merged[0].page_content.startswith("A")
    assert len(merged) == 3


@pytest.mark.asyncio
async def test_decompose_simple_query():
    with patch("services.search._get_haiku") as mock_haiku:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(
            content='{"type": "simple", "query": "ค่าเทอม"}'
        ))
        mock_haiku.return_value = mock_llm

        from services.search import _decompose_query
        result = await _decompose_query("ค่าเทอม")
        assert result == ["ค่าเทอม"]


@pytest.mark.asyncio
async def test_decompose_complex_query():
    with patch("services.search._get_haiku") as mock_haiku:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(
            content='{"type": "complex", "sub_queries": ["ค่าเทอม 4 ปี", "ค่าเทอม 5 ปี"]}'
        ))
        mock_haiku.return_value = mock_llm

        from services.search import _decompose_query
        result = await _decompose_query("เปรียบเทียบค่าเทอม 4 ปี กับ 5 ปี")
        assert len(result) == 2
        assert "4 ปี" in result[0]


@pytest.mark.asyncio
async def test_generate_query_variants():
    with patch("services.search._get_haiku") as mock_haiku:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(
            content='["tuition fee", "ค่าใช้จ่ายการศึกษา"]'
        ))
        mock_haiku.return_value = mock_llm

        from services.search import _generate_query_variants
        result = await _generate_query_variants("ค่าเทอม")
        assert len(result) == 3  # original + 2 variants
        assert result[0] == "ค่าเทอม"


@pytest.mark.asyncio
async def test_search_with_sources_returns_tuple():
    with (
        patch("services.search._decompose_query", new_callable=AsyncMock) as mock_d,
        patch("services.search._generate_query_variants", new_callable=AsyncMock) as mock_v,
        patch("services.search._hybrid_search") as mock_h,
        patch("services.search.rerank_with_scores") as mock_r,
    ):
        mock_d.return_value = ["ค่าเทอม"]
        mock_v.return_value = ["ค่าเทอม", "tuition", "ค่าใช้จ่าย"]
        doc = Document(page_content="ค่าเทอม 21,000 บาท", metadata={"source_filename": "test.pdf", "download_link": "http://example.com"})
        mock_h.return_value = [doc]
        mock_r.return_value = [(doc, 0.85)]

        from services.search import search_with_sources
        text, sources = await search_with_sources("ค่าเทอม", "ns")

        assert "[HIGH CONFIDENCE]" in text
        assert len(sources) == 1
        assert sources[0]["filename"] == "test.pdf"
        assert sources[0]["confidence"] == "HIGH"


def test_hybrid_search_vector_only():
    """When BM25 has no matching docs, return vector results."""
    with (
        patch("services.search.get_vectorstore") as mock_vs,
        patch("services.search.get_bm25_index") as mock_bm25,
    ):
        doc = Document(page_content="Test result", metadata={})
        mock_store = MagicMock()
        mock_store.similarity_search.return_value = [doc]
        mock_vs.return_value = mock_store
        # BM25 has docs but no matches for this query
        mock_bm25_idx = MagicMock()
        mock_bm25_idx.documents = [doc]  # non-empty so no bootstrap
        mock_bm25_idx.search.return_value = []  # no BM25 matches
        mock_bm25.return_value = mock_bm25_idx

        from services.search import _hybrid_search
        results = _hybrid_search("query", "ns")
        assert len(results) == 1
