"""Unit tests for `supernote.server.components.summary.markdown_export`."""

from supernote.models.extended import DigestHandwritingVO, DigestVO
from supernote.server.components.summary.markdown_export import format_digests_markdown


def test_format_digests_markdown_empty_and_blank_only_digests() -> None:
    """Empty input or digests with no renderable fields emit the empty placeholder."""
    assert format_digests_markdown([]) == "# Digests\n\n_No digests found._\n"
    assert (
        format_digests_markdown(
            [DigestVO(id=1, source_path="Document/Empty.pdf", content="   ")],
            title="Reading",
        )
        == "# Reading\n\n_No digests found._\n"
    )


def test_format_digests_markdown_groups_by_source_and_renders_all_fields() -> None:
    """Digests are grouped by normalized source path with comments, transcripts, and metadata."""
    digests = [
        DigestVO(
            id=1,
            content="Simplicity is prerequisite for reliability.",
            comment="First line\n\nSecond line",
            author="Edsger Dijkstra",
            source_path="/Document/Papers/Reliability.pdf",
            tags=["classic", " systems ", ""],
            handwriting=DigestHandwritingVO(
                md5="m1",
                transcript="Keep state machines minimal",
                model_id="gemini-2.5-flash",
                update_time=1700000000000,
            ),
            update_time=1700000000000,
        ),
        DigestVO(
            id=2,
            content="Second highlight from same paper.",
            source_path="Document/Papers/Reliability.pdf",
            creation_time=1700000000000,
        ),
        DigestVO(
            id=3,
            content="Standalone note",
        ),
    ]

    result = format_digests_markdown(digests, title="My Digests")
    expected = (
        "# My Digests\n\n"
        "## Reliability.pdf\n\n"
        "Source: `Document/Papers/Reliability.pdf`\n\n"
        "Simplicity is prerequisite for reliability.\n\n"
        "> First line\n"
        ">\n"
        "> Second line\n\n"
        "**Handwritten annotation:**\n\n"
        "Keep state machines minimal\n\n"
        "_Edsger Dijkstra · #classic #systems · 2023-11-14_\n\n"
        "---\n\n"
        "Second highlight from same paper.\n\n"
        "_2023-11-14_\n\n"
        "## Standalone Digests\n\n"
        "Standalone note\n"
    )
    assert result == expected


def test_format_digests_markdown_handles_out_of_range_timestamps_and_backticks() -> (
    None
):
    """Out-of-range timestamps are ignored and backticks/newlines in paths are safely fenced."""
    digest = DigestVO(
        id=10,
        content="Edge case excerpt",
        source_path="Document/`weird`\nfile.pdf",
        author="Ada\nLovelace",
        update_time=10**20,
    )
    result = format_digests_markdown([digest], title="Line1\nLine2")
    assert result == (
        "# Line1 Line2\n\n"
        "## `weird` file.pdf\n\n"
        "Source: ``Document/`weird` file.pdf``\n\n"
        "Edge case excerpt\n\n"
        "_Ada Lovelace_\n"
    )
