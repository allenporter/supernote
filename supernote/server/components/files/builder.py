"""Pure-Python e-ink document builder converting Markdown to EPUB 3 and PDF.

Generates distraction-free, e-ink-friendly `.epub` and `.pdf` documents from
Markdown without requiring native browser or LaTeX dependencies:

- **EPUB 3** (`build_epub`): packages well-formed XHTML, an e-ink stylesheet,
  and an auto-generated heading table of contents (`nav.xhtml`) into a valid
  EPUB 3 archive using stdlib `zipfile`.
- **PDF** (`build_pdf`): walks the same normalized XHTML tree and renders
  paginated flowables with `reportlab` sized for e-ink tablets.
"""

from __future__ import annotations

import datetime
import html as html_lib
import io
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from html.parser import HTMLParser
from xml.sax.saxutils import escape as xml_escape

import markdown2
from reportlab.lib import colors
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle, StyleSheet1, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

__all__ = [
    "BuiltDocument",
    "DocumentFormat",
    "build_document",
    "build_epub",
    "build_pdf",
    "sanitize_filename",
]

_EPUB_MEDIA_TYPE = "application/epub+zip"
_PDF_MEDIA_TYPE = "application/pdf"
_PDF_MARGIN = 14 * mm
_PDF_CONTENT_WIDTH = A5[0] - (2 * _PDF_MARGIN)
_PDF_MAX_CODE_LINE_CHARS = 65
_MAX_FILENAME_STEM_LEN = 120
_SAFE_FILENAME_RE = re.compile(r"[^\w\s.\-()]+", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")
_VOID_HTML_TAGS = frozenset({"br", "hr", "img"})
_ALLOWED_TAGS = frozenset(
    {
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "br",
        "hr",
        "strong",
        "b",
        "em",
        "i",
        "s",
        "del",
        "code",
        "pre",
        "blockquote",
        "ul",
        "ol",
        "li",
        "a",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "div",
        "span",
    }
)
_SAFE_LINK_SCHEMES = ("http://", "https://", "mailto:")

_EINK_CSS = """\
body {
  font-family: Georgia, "Times New Roman", serif;
  color: #000000;
  background-color: #ffffff;
  line-height: 1.55;
  margin: 1.2em;
}
h1, h2, h3, h4, h5, h6 {
  font-family: -apple-system, Helvetica, Arial, sans-serif;
  line-height: 1.25;
  margin-top: 1.2em;
  margin-bottom: 0.4em;
  page-break-after: avoid;
}
h1 { font-size: 1.6em; border-bottom: 1px solid #444444; padding-bottom: 0.2em; }
h2 { font-size: 1.3em; }
h3 { font-size: 1.1em; }
p { margin: 0.6em 0; }
blockquote {
  margin: 0.8em 0;
  padding: 0.2em 0.9em;
  border-left: 3px solid #555555;
  color: #222222;
}
pre {
  font-family: "Courier New", Courier, monospace;
  font-size: 0.85em;
  background-color: #f2f2f2;
  padding: 0.6em 0.8em;
  white-space: pre-wrap;
  word-wrap: break-word;
}
code {
  font-family: "Courier New", Courier, monospace;
  font-size: 0.9em;
}
table {
  border-collapse: collapse;
  width: 100%;
  margin: 0.8em 0;
}
th, td {
  border: 1px solid #555555;
  padding: 0.35em 0.5em;
  text-align: left;
}
th { background-color: #eaeaea; font-weight: bold; }
hr { border: none; border-top: 1px solid #666666; margin: 1.2em 0; }
a { color: #000000; text-decoration: underline; }
"""


class DocumentFormat(StrEnum):
    """Supported output formats for the e-ink Markdown document builder."""

    EPUB = "epub"
    PDF = "pdf"


@dataclass(frozen=True)
class BuiltDocument:
    """Rendered document bytes paired with a sanitized filename and MIME type."""

    content: bytes
    """Raw binary bytes of the generated `.epub` or `.pdf` document."""

    file_name: str
    """Sanitized single-segment filename including extension (e.g. `Brief.epub`)."""

    media_type: str
    """MIME media type (`application/epub+zip` or `application/pdf`)."""


def sanitize_filename(title: str, extension: str) -> str:
    """Convert a document title into a safe single-segment filename with `extension`."""
    cleaned = _SAFE_FILENAME_RE.sub("", title.strip())
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip(" .")
    if not cleaned:
        cleaned = "Untitled"
    stem = cleaned[:_MAX_FILENAME_STEM_LEN].rstrip(" .")
    if not stem:
        stem = "Untitled"
    ext = extension.lstrip(".").lower()
    return f"{stem}.{ext}"


class _HtmlToXhtmlTreeBuilder(HTMLParser):
    """Parse HTML fragments into a strictly well-formed, sanitized `ElementTree`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = ET.Element("div")
        self._stack: list[ET.Element] = [self.root]
        self._pre_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in _ALLOWED_TAGS:
            return
        # Flatten syntax-highlighter spans inside <pre> into plain text for clean e-ink output.
        if self._pre_depth > 0 and tag in ("span", "code"):
            return
        clean_attrs: dict[str, str] = {}
        if tag == "a":
            for key, val in attrs:
                if (
                    key.lower() == "href"
                    and val
                    and val.strip().lower().startswith(_SAFE_LINK_SCHEMES)
                ):
                    clean_attrs["href"] = val.strip()
        elem = ET.SubElement(self._stack[-1], tag, clean_attrs)
        if tag not in _VOID_HTML_TAGS:
            self._stack.append(elem)
            if tag == "pre":
                self._pre_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag not in _ALLOWED_TAGS or tag in _VOID_HTML_TAGS:
            return
        if self._pre_depth > 0 and tag in ("span", "code"):
            return
        for idx in range(len(self._stack) - 1, 0, -1):
            if self._stack[idx].tag == tag:
                if tag == "pre":
                    self._pre_depth = max(0, self._pre_depth - 1)
                del self._stack[idx:]
                break

    def handle_data(self, data: str) -> None:
        parent = self._stack[-1]
        if len(parent) == 0:
            parent.text = (parent.text or "") + data
        else:
            last = parent[-1]
            last.tail = (last.tail or "") + data


def _markdown_to_xhtml_tree(markdown: str) -> ET.Element:
    """Convert Markdown text into a sanitized, well-formed XHTML `<div>` element."""
    raw_html = markdown2.markdown(
        markdown,
        extras=["fenced-code-blocks", "tables", "strike", "cuddled-lists"],
        safe_mode="escape",
    )
    builder = _HtmlToXhtmlTreeBuilder()
    builder.feed(str(raw_html))
    builder.close()
    return builder.root


def _assign_heading_ids(body: ET.Element) -> list[tuple[str, str]]:
    """Assign anchor IDs to `h1`–`h3` elements and return `(anchor_id, text)` pairs."""
    toc: list[tuple[str, str]] = []
    for elem in body.iter():
        if elem.tag in ("h1", "h2", "h3"):
            heading_text = "".join(elem.itertext()).strip()
            if not heading_text:
                continue
            anchor = f"sec-{len(toc) + 1}"
            elem.set("id", anchor)
            toc.append((anchor, heading_text))
    return toc


def build_epub(title: str, markdown: str, *, author: str | None = None) -> bytes:
    """Build a valid EPUB 3 archive from Markdown text."""
    doc_title = title.strip() or "Untitled"
    doc_author = (author or "Supernote").strip() or "Supernote"
    book_id = f"urn:uuid:{uuid.uuid4()}"
    modified = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    body_tree = _markdown_to_xhtml_tree(markdown)
    toc_entries = _assign_heading_ids(body_tree)
    body_xhtml = ET.tostring(body_tree, encoding="unicode", method="xml")

    escaped_title = html_lib.escape(doc_title)
    escaped_author = html_lib.escape(doc_author)

    content_xhtml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">\n'
        "<head>\n"
        f"  <title>{escaped_title}</title>\n"
        '  <link rel="stylesheet" type="text/css" href="style.css"/>\n'
        "</head>\n"
        "<body>\n"
        f"  <h1>{escaped_title}</h1>\n"
        f"  {body_xhtml}\n"
        "</body>\n"
        "</html>\n"
    )

    if toc_entries:
        nav_items = "\n".join(
            f'      <li><a href="content.xhtml#{anchor}">{html_lib.escape(text)}</a></li>'
            for anchor, text in toc_entries
        )
    else:
        nav_items = f'      <li><a href="content.xhtml">{escaped_title}</a></li>'

    nav_xhtml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en">\n'
        "<head>\n"
        f"  <title>{escaped_title}</title>\n"
        "</head>\n"
        "<body>\n"
        '  <nav epub:type="toc" id="toc">\n'
        "    <h1>Contents</h1>\n"
        "    <ol>\n"
        f"{nav_items}\n"
        "    </ol>\n"
        "  </nav>\n"
        "</body>\n"
        "</html>\n"
    )

    container_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        "  <rootfiles>\n"
        '    <rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/>\n'
        "  </rootfiles>\n"
        "</container>\n"
    )

    content_opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" '
        'unique-identifier="bookid" version="3.0">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="bookid">{book_id}</dc:identifier>\n'
        f"    <dc:title>{escaped_title}</dc:title>\n"
        f"    <dc:creator>{escaped_author}</dc:creator>\n"
        "    <dc:language>en</dc:language>\n"
        f'    <meta property="dcterms:modified">{modified}</meta>\n'
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" '
        'properties="nav"/>\n'
        '    <item id="content" href="content.xhtml" '
        'media-type="application/xhtml+xml"/>\n'
        '    <item id="css" href="style.css" media-type="text/css"/>\n'
        "  </manifest>\n"
        "  <spine>\n"
        '    <itemref idref="content"/>\n'
        "  </spine>\n"
        "</package>\n"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # EPUB 3 requires `mimetype` as the first entry, stored uncompressed.
        zf.writestr("mimetype", _EPUB_MEDIA_TYPE, compress_type=zipfile.ZIP_STORED)
        zf.writestr(
            "META-INF/container.xml", container_xml, compress_type=zipfile.ZIP_DEFLATED
        )
        zf.writestr(
            "OEBPS/content.opf", content_opf, compress_type=zipfile.ZIP_DEFLATED
        )
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/style.css", _EINK_CSS, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr(
            "OEBPS/content.xhtml", content_xhtml, compress_type=zipfile.ZIP_DEFLATED
        )
    return buf.getvalue()


def _inline_to_rml(elem: ET.Element) -> str:
    """Serialize an XHTML element's inline children into ReportLab Paragraph markup."""
    parts: list[str] = []
    if elem.text:
        parts.append(xml_escape(elem.text))
    for child in elem:
        inner = _inline_to_rml(child)
        tag = child.tag
        if tag in ("strong", "b"):
            parts.append(f"<b>{inner}</b>")
        elif tag in ("em", "i"):
            parts.append(f"<i>{inner}</i>")
        elif tag in ("s", "del"):
            parts.append(f"<strike>{inner}</strike>")
        elif tag == "code":
            parts.append(f'<font name="Courier">{inner}</font>')
        elif tag == "br":
            parts.append("<br/>")
        elif tag == "a" and (href := child.get("href")):
            safe_href = xml_escape(href, {'"': "&quot;"})
            parts.append(f'<u><a href="{safe_href}">{inner}</a></u>')
        else:
            parts.append(inner)
        if child.tail:
            parts.append(xml_escape(child.tail))
    return "".join(parts)


def _pdf_styles() -> dict[str, ParagraphStyle]:
    """Create clean e-ink paragraph styles for ReportLab PDF generation."""
    base: StyleSheet1 = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "EinkTitle",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            spaceAfter=10,
            textColor=colors.black,
        ),
        "h1": ParagraphStyle(
            "EinkH1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            spaceBefore=10,
            spaceAfter=5,
            textColor=colors.black,
        ),
        "h2": ParagraphStyle(
            "EinkH2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            spaceBefore=8,
            spaceAfter=4,
            textColor=colors.black,
        ),
        "h3": ParagraphStyle(
            "EinkH3",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=14,
            spaceBefore=6,
            spaceAfter=3,
            textColor=colors.black,
        ),
        "body": ParagraphStyle(
            "EinkBody",
            parent=base["Normal"],
            fontName="Times-Roman",
            fontSize=10,
            leading=14.5,
            spaceAfter=6,
            textColor=colors.black,
        ),
        "quote": ParagraphStyle(
            "EinkQuote",
            parent=base["Normal"],
            fontName="Times-Italic",
            fontSize=9.5,
            leading=13.5,
            leftIndent=14,
            spaceAfter=6,
            textColor=colors.HexColor("#222222"),
        ),
        "list_item": ParagraphStyle(
            "EinkListItem",
            parent=base["Normal"],
            fontName="Times-Roman",
            fontSize=10,
            leading=14,
            leftIndent=14,
            firstLineIndent=-8,
            spaceAfter=3,
            textColor=colors.black,
        ),
        "code": ParagraphStyle(
            "EinkCode",
            parent=base["Code"],
            fontName="Courier",
            fontSize=8.5,
            leading=11.5,
            leftIndent=8,
            spaceBefore=4,
            spaceAfter=6,
            backColor=colors.HexColor("#F2F2F2"),
            textColor=colors.black,
        ),
    }


def _append_pdf_flowables(
    container: ET.Element,
    flowables: list[Flowable],
    styles: dict[str, ParagraphStyle],
) -> None:
    """Recursively convert XHTML block elements into ReportLab flowables."""
    for elem in container:
        tag = elem.tag
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            style_key = tag if tag in styles else "h3"
            flowables.append(Paragraph(_inline_to_rml(elem), styles[style_key]))
        elif tag == "p":
            flowables.append(Paragraph(_inline_to_rml(elem), styles["body"]))
        elif tag == "blockquote":
            text = _inline_to_rml(elem).strip()
            if text:
                flowables.append(Paragraph(text, styles["quote"]))
        elif tag in ("ul", "ol"):
            for idx, item in enumerate(elem.findall("li"), start=1):
                prefix = f"{idx}. " if tag == "ol" else "• "
                flowables.append(
                    Paragraph(f"{prefix}{_inline_to_rml(item)}", styles["list_item"])
                )
            flowables.append(Spacer(1, 3))
        elif tag == "pre":
            code_text = "".join(elem.itertext()).rstrip("\n")
            flowables.append(
                Preformatted(
                    code_text, styles["code"], maxLineLength=_PDF_MAX_CODE_LINE_CHARS
                )
            )
        elif tag == "hr":
            flowables.append(
                HRFlowable(
                    width="100%",
                    thickness=0.6,
                    color=colors.HexColor("#666666"),
                    spaceBefore=6,
                    spaceAfter=6,
                )
            )
        elif tag == "table":
            rows: list[list[Paragraph]] = []
            for tr in elem.iter("tr"):
                row = [
                    Paragraph(_inline_to_rml(cell), styles["body"])
                    for cell in tr
                    if cell.tag in ("th", "td")
                ]
                if row:
                    rows.append(row)
            if rows:
                num_cols = max(len(r) for r in rows)
                col_widths = [_PDF_CONTENT_WIDTH / num_cols] * num_cols
                table = Table(rows, colWidths=col_widths, hAlign="LEFT")
                table.setStyle(
                    TableStyle(
                        [
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#555555")),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAEAEA")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ]
                    )
                )
                flowables.append(table)
                flowables.append(Spacer(1, 6))
        elif tag == "div":
            _append_pdf_flowables(elem, flowables, styles)


def build_pdf(title: str, markdown: str, *, author: str | None = None) -> bytes:
    """Build an e-ink-friendly A5 PDF document from Markdown text."""
    doc_title = title.strip() or "Untitled"
    doc_author = (author or "Supernote").strip() or "Supernote"
    body_tree = _markdown_to_xhtml_tree(markdown)
    styles = _pdf_styles()

    flowables: list[Flowable] = [
        Paragraph(xml_escape(doc_title), styles["title"]),
        HRFlowable(
            width="100%",
            thickness=0.8,
            color=colors.HexColor("#444444"),
            spaceAfter=8,
        ),
    ]
    _append_pdf_flowables(body_tree, flowables, styles)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A5,
        leftMargin=_PDF_MARGIN,
        rightMargin=_PDF_MARGIN,
        topMargin=_PDF_MARGIN,
        bottomMargin=_PDF_MARGIN,
        title=doc_title,
        author=doc_author,
    )
    doc.build(flowables)
    return buf.getvalue()


def build_document(
    title: str,
    markdown: str,
    *,
    fmt: DocumentFormat = DocumentFormat.EPUB,
    author: str | None = None,
) -> BuiltDocument:
    """Render Markdown into an e-ink-formatted `.epub` or `.pdf` `BuiltDocument`."""
    if fmt == DocumentFormat.EPUB:
        return BuiltDocument(
            content=build_epub(title, markdown, author=author),
            file_name=sanitize_filename(title, "epub"),
            media_type=_EPUB_MEDIA_TYPE,
        )
    if fmt == DocumentFormat.PDF:
        return BuiltDocument(
            content=build_pdf(title, markdown, author=author),
            file_name=sanitize_filename(title, "pdf"),
            media_type=_PDF_MEDIA_TYPE,
        )
    raise ValueError(f"Unsupported document format: {fmt!r}")
