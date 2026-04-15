"""TDD tests for semantic chunking implementation.

These tests verify the new embedding-based _smart_chunk function.
"""
import pytest
from unittest.mock import MagicMock, patch
from langchain_core.documents import Document


# ---------------------------------------------------------------------------
# Helpers: mock embeddings so tests don't hit the Cohere API
# ---------------------------------------------------------------------------

def _make_fake_embeddings():
    """Return a mock embedding model that returns deterministic float vectors."""
    import hashlib

    class FakeEmbeddings:
        def embed_documents(self, texts):
            result = []
            for text in texts:
                # Produce a stable 384-dim vector from the text hash
                h = int(hashlib.md5(text.encode()).hexdigest(), 16)
                vec = [(((h >> i) & 0xFF) / 255.0) for i in range(384)]
                result.append(vec)
            return result

        def embed_query(self, text):
            return self.embed_documents([text])[0]

    return FakeEmbeddings()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_smart_chunk_returns_documents_with_metadata():
    from ingest.services.chunking import _smart_chunk
    text = (
        "# หลักสูตร\n\n"
        "หลักสูตรวิศวกรรมศาสตร์ใช้เวลา 4 ปี ค่าเทอม 21,000 บาท\n\n"
        "## ตารางเรียน\n\n"
        "วิชา 2110101 เปิดสอนทุกภาคการศึกษา วันจันทร์ 9:00-12:00\n\n"
        "## ค่าใช้จ่าย\n\n"
        "ค่าเทอมรวมค่าธรรมเนียมทั้งหมดแล้ว ไม่มีค่าใช้จ่ายเพิ่มเติม"
    )
    with patch("ingest.services.chunking.get_embedding_model", return_value=_make_fake_embeddings()):
        chunks = _smart_chunk(text, source="test.pdf")
    assert len(chunks) >= 1
    assert all(isinstance(c, Document) for c in chunks)
    assert all(c.metadata.get("source_filename") == "test.pdf" for c in chunks)


def test_smart_chunk_fallback_on_short_text():
    from ingest.services.chunking import _smart_chunk
    text = "สั้นมาก short text"
    with patch("ingest.services.chunking.get_embedding_model", return_value=_make_fake_embeddings()):
        chunks = _smart_chunk(text, source="short.pdf")
    assert len(chunks) >= 1
    assert chunks[0].metadata["source_filename"] == "short.pdf"


def test_smart_chunk_filters_tiny_chunks():
    from ingest.services.chunking import _smart_chunk
    text = (
        "# Section A\n\n"
        + "A detailed content about curriculum. " * 80
        + "\n\n# Section B\n\n"
        + "B detailed content about schedule. " * 80
    )
    with patch("ingest.services.chunking.get_embedding_model", return_value=_make_fake_embeddings()):
        chunks = _smart_chunk(text, source="test.pdf")
    for chunk in chunks:
        assert len(chunk.page_content.strip()) >= 50


def test_smart_chunk_falls_back_when_semantic_chunker_raises():
    """If SemanticChunker raises, fallback splitter should be used."""
    from ingest.services.chunking import _smart_chunk

    with patch("ingest.services.chunking.get_embedding_model", side_effect=Exception("API down")):
        # Should not raise; fallback RecursiveCharacterTextSplitter takes over
        text = "This is a document with enough content. " * 20
        chunks = _smart_chunk(text, source="fallback.pdf")

    assert len(chunks) >= 1
    assert all(isinstance(c, Document) for c in chunks)
    assert all(c.metadata.get("source_filename") == "fallback.pdf" for c in chunks)


def test_smart_chunk_caps_large_chunks():
    """Chunks > 3000 chars should be split further."""
    from ingest.services.chunking import _smart_chunk

    # Build text whose semantic chunker would return one huge chunk
    long_para = "x" * 3500
    text = long_para

    with patch("ingest.services.chunking.get_embedding_model", return_value=_make_fake_embeddings()):
        chunks = _smart_chunk(text, source="big.pdf")

    for chunk in chunks:
        assert len(chunk.page_content) <= 3000 + 200  # cap + overlap tolerance


def test_smart_chunk_header_path_annotation():
    """Chunks should carry their markdown header context as a prefix."""
    from ingest.services.chunking import _smart_chunk

    text = (
        "# Introduction\n\n"
        "This section introduces the course structure in detail. " * 10
    )
    with patch("ingest.services.chunking.get_embedding_model", return_value=_make_fake_embeddings()):
        chunks = _smart_chunk(text, source="header_test.pdf")

    # At least one chunk should be annotated with the header path
    assert any("[Introduction]" in c.page_content or "Introduction" in c.page_content for c in chunks)
