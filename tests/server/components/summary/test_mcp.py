"""MCP protocol tests for `supernote.server.components.summary.mcp`."""

from __future__ import annotations

import pytest

from supernote.server.db.models.summary import SummaryDO, SummaryTranscriptDO
from supernote.server.db.session import DatabaseSessionManager
from tests.server.components.conftest import call_mcp_tool, mcp_session


@pytest.fixture
def mcp_enabled() -> bool:
    """Enable the embedded MCP Streamable HTTP server for protocol tests."""
    return True


async def test_mcp_list_digests_returns_handwriting_transcript_and_filters(
    mcp_url: str,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """`list_digests` returns unified `DigestListVO` entries and filters by file and category."""
    async with session_manager.session() as session:
        d1 = SummaryDO(
            user_id=test_user_id,
            file_id=5001,
            parent_unique_identifier="cat-books",
            name="Chapter 1",
            unique_identifier="mcp-digest-1",
            content="Highlighted passage from book",
            comment_str="Great point",
            source_path="/Document/Book.pdf",
            handwrite_inner_name="hw1.mark",
            handwrite_md5="md5_current",
            tags="reading, notes",
            is_summary_group=False,
            is_deleted=False,
        )
        d2 = SummaryDO(
            user_id=test_user_id,
            file_id=5002,
            parent_unique_identifier="cat-ai",
            name="Chapter 2",
            unique_identifier="mcp-digest-2",
            content="Second passage",
            handwrite_inner_name="hw2.mark",
            handwrite_md5="md5_v2",
            is_summary_group=False,
            is_deleted=False,
        )
        other_user = SummaryDO(
            user_id=test_user_id + 1,
            file_id=5001,
            unique_identifier="mcp-digest-other",
            content="Private other user digest",
            is_summary_group=False,
            is_deleted=False,
        )
        session.add_all([d1, d2, other_user])
        await session.flush()
        d1_id = int(d1.id)
        d2_id = int(d2.id)
        session.add_all(
            [
                SummaryTranscriptDO(
                    user_id=test_user_id,
                    summary_id=d1_id,
                    handwrite_md5="md5_current",
                    text_content="Follow up on flux capacitor.",
                    model_id="fake-ocr-v1",
                ),
                SummaryTranscriptDO(
                    user_id=test_user_id,
                    summary_id=d2_id,
                    handwrite_md5="md5_v1",
                    text_content="Stale text",
                    model_id="fake-ocr-v1",
                ),
            ]
        )
        await session.commit()

    async with mcp_session(mcp_url, auth_headers) as session:
        all_resp = await call_mcp_tool(session, "list_digests", {})
        assert all_resp["success"] is True
        assert all_resp["total"] == 2
        assert all_resp["limit"] == 50
        assert all_resp["offset"] == 0
        by_id = {d["id"]: d for d in all_resp["digests"]}
        assert by_id[str(d1_id)]["categoryId"] == "cat-books"
        assert by_id[str(d1_id)]["content"] == "Highlighted passage from book"
        assert by_id[str(d1_id)]["comment"] == "Great point"
        assert by_id[str(d1_id)]["tags"] == ["reading", "notes"]
        assert by_id[str(d1_id)]["sourcePath"] == "/Document/Book.pdf"
        assert by_id[str(d1_id)]["handwriting"]["md5"] == "md5_current"
        assert (
            by_id[str(d1_id)]["handwriting"]["transcript"]
            == "Follow up on flux capacitor."
        )
        assert by_id[str(d1_id)]["handwriting"]["modelId"] == "fake-ocr-v1"
        assert by_id[str(d2_id)]["handwriting"]["md5"] == "md5_v2"
        assert "transcript" not in by_id[str(d2_id)]["handwriting"]

        by_file = await call_mcp_tool(session, "list_digests", {"file_id": "5001"})
        assert by_file["success"] is True
        assert by_file["total"] == 1
        assert by_file["digests"][0]["id"] == str(d1_id)

        by_category = await call_mcp_tool(
            session, "list_digests", {"category_id": "cat-ai"}
        )
        assert by_category["success"] is True
        assert by_category["total"] == 1
        assert by_category["digests"][0]["id"] == str(d2_id)

        paged = await call_mcp_tool(session, "list_digests", {"limit": 1, "offset": 1})
        assert paged["success"] is True
        assert paged["total"] == 2
        assert paged["limit"] == 1
        assert paged["offset"] == 1
        assert len(paged["digests"]) == 1


async def test_mcp_list_digests_invalid_file_id_returns_error(
    mcp_url: str,
    auth_headers: dict[str, str],
) -> None:
    """`list_digests` returns a structured BAD_REQUEST error on non-numeric file_id."""
    async with mcp_session(mcp_url, auth_headers) as session:
        resp = await call_mcp_tool(session, "list_digests", {"file_id": "not-a-number"})
        assert resp["success"] is False
        assert "Invalid file_id" in resp["errorMsg"]
