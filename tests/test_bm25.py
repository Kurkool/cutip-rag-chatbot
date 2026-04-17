import pytest
from langchain_core.documents import Document
from chat.services.bm25 import BM25Index, get_bm25_index, invalidate_bm25_cache


def test_bm25_search_finds_exact_keyword():
    docs = [
        Document(page_content="วิชา 2110101 คณิตศาสตร์วิศวกรรม", metadata={"source_filename": "a.pdf"}),
        Document(page_content="ค่าเทอม 21,000 บาทต่อเทอม", metadata={"source_filename": "b.pdf"}),
        Document(page_content="ตารางเรียนวันจันทร์ 9:00-12:00", metadata={"source_filename": "c.pdf"}),
    ]
    idx = BM25Index(docs)
    results = idx.search("2110101", k=2)
    assert len(results) >= 1
    assert "2110101" in results[0].page_content


def test_bm25_search_returns_empty_for_no_match():
    docs = [Document(page_content="ค่าเทอม 21,000 บาท", metadata={})]
    idx = BM25Index(docs)
    results = idx.search("nonexistent_term_xyz", k=5)
    assert results == []


def test_bm25_empty_index():
    idx = BM25Index([])
    results = idx.search("anything", k=5)
    assert results == []


def test_bm25_cache_and_invalidation():
    docs = [Document(page_content="test content here", metadata={})]
    idx1 = get_bm25_index("test_ns", docs)
    idx2 = get_bm25_index("test_ns")
    assert idx1 is idx2

    invalidate_bm25_cache("test_ns")
    idx3 = get_bm25_index("test_ns", docs)
    assert idx3 is not idx1


def test_bm25_search_ranks_by_relevance():
    docs = [
        Document(page_content="วิชา 2110101 คณิตศาสตร์", metadata={}),
        Document(page_content="วิชา 2110201 ฟิสิกส์ วิชา 2110101", metadata={}),
        Document(page_content="ค่าเทอม ไม่เกี่ยวกับวิชา", metadata={}),
    ]
    idx = BM25Index(docs)
    results = idx.search("วิชา 2110101", k=3)
    # Doc mentioning 2110101 twice should rank higher or equal
    assert len(results) >= 2
    assert "2110101" in results[0].page_content


def test_bm25_filename_boosts_cross_language_match():
    # Query in English, content in Thai, only the filename contains the
    # English cue. Without filename tokenization the query misses the file.
    # Corpus padded with unrelated docs so BM25 IDF is non-degenerate.
    docs = [
        Document(
            page_content="ขั้นตอนการสอบวิทยานิพนธ์และการเตรียมเอกสาร",
            metadata={"source_filename": "slide.pdf"},
        ),
        Document(
            page_content="ทุนการศึกษาสำหรับนิสิตปริญญาโทและเอก",
            metadata={"source_filename": "ทุนการศึกษา.docx"},
        ),
        Document(
            page_content="ตารางเรียนภาคปลาย",
            metadata={"source_filename": "schedule.xlsx"},
        ),
        Document(
            page_content="ประกาศกรรมการสอบ",
            metadata={"source_filename": "announce.pdf"},
        ),
    ]
    idx = BM25Index(docs)
    results = idx.search("slide presentation", k=2)
    assert len(results) >= 1
    assert results[0].metadata["source_filename"] == "slide.pdf"


def test_bm25_filename_extension_stripped():
    # Extension tokens (pdf/docx/xlsx) should NOT create spurious matches
    # for queries that mention an extension word. Only content-level
    # mentions should match.
    docs = [
        Document(
            page_content="เนื้อหาเกี่ยวกับการวิจัย",
            metadata={"source_filename": "research.pdf"},
        ),
        Document(
            page_content="pdf เป็นรูปแบบเอกสารที่ใช้บ่อย",
            metadata={"source_filename": "formats.docx"},
        ),
        Document(
            page_content="เอกสารประกอบการเรียน",
            metadata={"source_filename": "materials.docx"},
        ),
        Document(
            page_content="ตารางเรียน",
            metadata={"source_filename": "schedule.xlsx"},
        ),
    ]
    idx = BM25Index(docs)
    results = idx.search("pdf", k=4)
    # Only content-level mention of 'pdf' should match. The stripped
    # extensions must not leak 'pdf' into token streams.
    assert len(results) == 1
    assert results[0].metadata["source_filename"] == "formats.docx"
