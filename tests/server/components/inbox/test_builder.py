"""Unit tests for `supernote.server.components.inbox.builder`."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile

import pytest

from supernote.server.components.inbox.builder import (
    DocumentFormat,
    build_document,
    build_epub,
    build_pdf,
    sanitize_filename,
)

_SAMPLE_MARKDOWN = """\
## Overview & Goals

A paragraph with **bold**, *italic*, `inline_code`, ~~old~~, and
[example](https://example.com/path?a=1&b=2).

> Quoted insight with *emphasis* & <script>alert(1)</script>

- First bullet
- Second bullet

1. Step one
2. Step two

---

```python
def greet(name: str) -> str:
    return f"hello {name} & friends <3"
```

| Metric | Value |
| :--- | :--- |
| Latency | `12ms` |
"""


@pytest.mark.parametrize(
    ("title", "ext", "expected"),
    [
        ("Research Brief", "epub", "Research Brief.epub"),
        ("  Scaling: Laws / 2026?  ", "pdf", "Scaling Laws 2026.pdf"),
        ("...", "epub", "Untitled.epub"),
        ("", "pdf", "Untitled.pdf"),
        ("A" * 200, "epub", f"{'A' * 120}.epub"),
    ],
)
def test_sanitize_filename(title: str, ext: str, expected: str) -> None:
    """Titles normalize into safe, bounded single-segment filenames."""
    assert sanitize_filename(title, ext) == expected


def test_build_epub_produces_valid_epub3_archive() -> None:
    """`build_epub` creates a spec-compliant EPUB 3 zip with uncompressed mimetype and valid XML."""
    epub_bytes = build_epub("My Brief & Notes", _SAMPLE_MARKDOWN, author="Ada")

    with zipfile.ZipFile(io.BytesIO(epub_bytes), "r") as zf:
        names = zf.namelist()
        assert names[0] == "mimetype"
        mimetype_info = zf.getinfo("mimetype")
        assert mimetype_info.compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == b"application/epub+zip"

        expected_entries = {
            "META-INF/container.xml",
            "OEBPS/content.opf",
            "OEBPS/nav.xhtml",
            "OEBPS/style.css",
            "OEBPS/content.xhtml",
        }
        assert expected_entries.issubset(set(names))

        # Every XML/XHTML file parses cleanly under strict XML parsing
        for xml_path in (
            "META-INF/container.xml",
            "OEBPS/content.opf",
            "OEBPS/nav.xhtml",
            "OEBPS/content.xhtml",
        ):
            ET.fromstring(zf.read(xml_path))

        content_text = zf.read("OEBPS/content.xhtml").decode("utf-8")
        assert "My Brief &amp; Notes" in content_text
        assert "https://example.com/path?a=1&amp;b=2" in content_text
        assert "<script>" not in content_text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in content_text

        nav_text = zf.read("OEBPS/nav.xhtml").decode("utf-8")
        assert "Overview &amp; Goals" in nav_text

        opf_text = zf.read("OEBPS/content.opf").decode("utf-8")
        assert "<dc:creator>Ada</dc:creator>" in opf_text


def test_build_epub_strips_javascript_links() -> None:
    """Unsafe link schemes like `javascript:` are stripped from generated XHTML."""
    epub_bytes = build_epub("Safety", "[click](javascript:alert(1))")
    with zipfile.ZipFile(io.BytesIO(epub_bytes), "r") as zf:
        content_text = zf.read("OEBPS/content.xhtml").decode("utf-8")
        assert "javascript:" not in content_text


def test_build_pdf_produces_valid_pdf_document() -> None:
    """`build_pdf` renders rich Markdown into a non-empty PDF byte stream."""
    pdf_bytes = build_pdf("My Brief & Notes", _SAMPLE_MARKDOWN, author="Ada")
    assert pdf_bytes.startswith(b"%PDF-")
    assert b"%%EOF" in pdf_bytes
    assert len(pdf_bytes) > 1000


def test_build_document_dispatches_epub_and_pdf() -> None:
    """`build_document` returns `BuiltDocument` with matching filename and MIME type."""
    epub_doc = build_document("Daily Brief", "# Hi\n\nBody.", fmt=DocumentFormat.EPUB)
    assert epub_doc.file_name == "Daily Brief.epub"
    assert epub_doc.media_type == "application/epub+zip"
    assert zipfile.is_zipfile(io.BytesIO(epub_doc.content))

    pdf_doc = build_document("Daily Brief", "# Hi\n\nBody.", fmt=DocumentFormat.PDF)
    assert pdf_doc.file_name == "Daily Brief.pdf"
    assert pdf_doc.media_type == "application/pdf"
    assert pdf_doc.content.startswith(b"%PDF-")


def test_builders_strip_illegal_xml_control_characters() -> None:
    """ASCII control characters forbidden in XML 1.0 are stripped from EPUB and PDF."""
    dirty_md = "Line with\x00null and\x0cform-feed and\x07bell."
    epub_bytes = build_epub("Title\x00Bad", dirty_md, author="Ada\x0c")
    with zipfile.ZipFile(io.BytesIO(epub_bytes), "r") as zf:
        for xml_path in (
            "OEBPS/content.opf",
            "OEBPS/nav.xhtml",
            "OEBPS/content.xhtml",
        ):
            ET.fromstring(zf.read(xml_path))
        content = zf.read("OEBPS/content.xhtml").decode("utf-8")
        assert "\x00" not in content
        assert "\x0c" not in content
        assert "\x07" not in content

    pdf_bytes = build_pdf("Title\x00Bad", dirty_md, author="Ada\x0c")
    assert pdf_bytes.startswith(b"%PDF-")


def test_build_pdf_handles_ragged_tables_nested_lists_and_multi_paragraph_quotes() -> (
    None
):
    """Ragged tables, nested lists, and multi-paragraph blockquotes render without crashing."""
    edge_md = """\
> First quoted paragraph.
>
> Second quoted paragraph.

- Parent bullet
  - Nested bullet A
  - Nested bullet B
- Next parent

| A | B | C |
| - | - | - |
| 1 | 2 |
| 3 | 4 | 5 |
"""
    pdf_bytes = build_pdf("Edge Cases", edge_md)
    assert pdf_bytes.startswith(b"%PDF-")
    assert b"%%EOF" in pdf_bytes
