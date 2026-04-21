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
