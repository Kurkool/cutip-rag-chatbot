"""TDD tests for table-aware chunking (_fix_table_boundaries).

Tests are written BEFORE the implementation — they should all fail initially.
"""
import pytest
from langchain_core.documents import Document
from services.ingestion import _fix_table_boundaries


def test_incomplete_table_merged_with_next_chunk():
    chunks = [
        Document(page_content="Some text\n| Col1 | Col2 |\n| --- | --- |\n| A | B", metadata={}),
        Document(page_content="| C | D |\n| E | F |\n\nMore text after table", metadata={}),
    ]
    fixed = _fix_table_boundaries(chunks)
    assert any("| A | B" in c.page_content and "| C | D |" in c.page_content for c in fixed)


def test_complete_table_not_merged():
    chunks = [
        Document(page_content="| Col1 | Col2 |\n| --- | --- |\n| A | B |", metadata={}),
        Document(page_content="Separate text chunk", metadata={}),
    ]
    fixed = _fix_table_boundaries(chunks)
    assert len(fixed) == 2


def test_has_table_metadata_added():
    chunks = [
        Document(page_content="| Col1 | Col2 |\n| --- | --- |\n| A | B |", metadata={}),
        Document(page_content="No table here", metadata={}),
    ]
    fixed = _fix_table_boundaries(chunks)
    table_chunk = [c for c in fixed if "Col1" in c.page_content][0]
    text_chunk = [c for c in fixed if "No table" in c.page_content][0]
    assert table_chunk.metadata.get("has_table") is True
    assert text_chunk.metadata.get("has_table") is not True


def test_large_table_split_at_row_boundary():
    rows = "| A long value here padding | Another long value here padding |\n" * 60
    table = "| Col1 | Col2 |\n| --- | --- |\n" + rows
    chunks = [Document(page_content=table, metadata={})]
    fixed = _fix_table_boundaries(chunks)
    assert len(fixed) >= 2
    for chunk in fixed:
        assert "| Col1 | Col2 |" in chunk.page_content
