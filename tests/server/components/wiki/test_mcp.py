"""MCP protocol tests for `supernote.server.components.wiki.mcp`."""

from __future__ import annotations

from typing import Any

import httpx2
import pytest

from supernote.client.wiki import WikiClient
from supernote.models.base import ErrorCode
from supernote.server.components.wiki.service import WIKI_SERVICE_KEY
from supernote.server.config import ServerConfig
from tests.server.components.conftest import call_mcp_tool, mcp_session

_EXPECTED_WIKI_TOOLS = {
    "get_wiki_index",
    "list_wiki_pages",
    "read_wiki_page",
    "search_wiki",
    "upsert_wiki_page",
    "list_wiki_lint_issues",
    "resolve_wiki_lint_issue",
    "get_wiki_status",
}


@pytest.fixture
def mcp_enabled() -> bool:
    """Enable the embedded MCP Streamable HTTP server for protocol tests."""
    return True


@pytest.fixture
def server_config(server_config: ServerConfig) -> ServerConfig:
    """Enable the opt-in wiki component for MCP protocol tests."""
    server_config.wiki = {"enabled": True}
    return server_config


async def test_wiki_mcp_registers_all_eight_tools_and_requires_auth(
    mcp_url: str,
    auth_headers: dict[str, str],
) -> None:
    """Verify all eight wiki tools are exposed over MCP and unauthenticated requests are rejected."""
    async with httpx2.AsyncClient() as http_client:
        resp = await http_client.post(
            mcp_url,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert resp.status_code == 401

    async with mcp_session(mcp_url, auth_headers) as session:
        tools = await session.list_tools()
        assert _EXPECTED_WIKI_TOOLS.issubset({t.name for t in tools.tools})


async def test_wiki_mcp_crud_index_list_search_and_lint_resolution(
    client: Any,
    mcp_url: str,
    auth_headers: dict[str, str],
    test_user_id: int,
) -> None:
    """Verify full wiki CRUD, index, search, lint, and status flows over MCP."""
    async with mcp_session(mcp_url, auth_headers) as session:
        upserted = await call_mcp_tool(
            session,
            "upsert_wiki_page",
            {
                "slug": "projects/mcp-test",
                "title": "MCP Test",
                "body_md": "Linked to [[entities/missing]].",
                "page_kind": "project",
                "summary": "Created by MCP agent",
            },
        )
        assert upserted["success"] is True
        assert upserted["page"]["last_author_kind"] == "agent"

        index = await call_mcp_tool(session, "get_wiki_index")
        assert [e["slug"] for e in index["entries"]] == ["projects/mcp-test"]

        listed = await call_mcp_tool(
            session, "list_wiki_pages", {"page_kind": "project"}
        )
        assert listed["success"] is True
        assert [p["slug"] for p in listed["pages"]] == ["projects/mcp-test"]

        read = await call_mcp_tool(
            session, "read_wiki_page", {"slug": "projects/mcp-test"}
        )
        assert read["success"] is True
        assert read["page"]["title"] == "MCP Test"

        search = await call_mcp_tool(session, "search_wiki", {"query": "mcp"})
        assert len(search["hits"]) == 1

        # Trigger structural lint so list/resolve lint tools have a real issue.
        await client.app[WIKI_SERVICE_KEY].run_structural_lint(test_user_id)
        lint_list = await call_mcp_tool(
            session, "list_wiki_lint_issues", {"status": "open"}
        )
        assert lint_list["success"] is True
        assert len(lint_list["issues"]) >= 1

        issue_id = lint_list["issues"][0]["issue_id"]
        resolved = await call_mcp_tool(
            session,
            "resolve_wiki_lint_issue",
            {"issue_id": issue_id, "status": "dismissed"},
        )
        assert resolved["success"] is True
        assert resolved["issue"]["status"] == "dismissed"

        status = await call_mcp_tool(session, "get_wiki_status")
        assert status["success"] is True
        assert status["status"]["page_count"] == 1


async def test_wiki_mcp_error_paths_and_policy_enforcement(
    mcp_url: str,
    auth_headers: dict[str, str],
    wiki_client: WikiClient,
) -> None:
    """Verify policy enforcement, optimistic concurrency, and validation errors over MCP."""
    # Seed a user-owned protected_prose page through the public HTTP API.
    await wiki_client.upsert_page(
        slug="projects/human-owned",
        title="Human Owned",
        body_md="Do not overwrite",
    )

    async with mcp_session(mcp_url, auth_headers) as session:
        # Policy violation -> 403 FORBIDDEN.
        forbidden = await call_mcp_tool(
            session,
            "upsert_wiki_page",
            {
                "slug": "projects/human-owned",
                "title": "Human Owned",
                "body_md": "Agent overwrite",
            },
        )
        assert forbidden["success"] is False
        assert forbidden["errorCode"] == ErrorCode.FORBIDDEN.value

        # Optimistic concurrency conflict -> 409 CONFLICT.
        await call_mcp_tool(
            session,
            "upsert_wiki_page",
            {"slug": "projects/v1", "title": "V1", "body_md": "Body"},
        )
        conflict = await call_mcp_tool(
            session,
            "upsert_wiki_page",
            {
                "slug": "projects/v1",
                "title": "V1",
                "body_md": "Stale",
                "expected_version": 99,
            },
        )
        assert conflict["success"] is False
        assert conflict["errorCode"] == ErrorCode.CONFLICT.value

        # Missing page -> 404 NOT_FOUND.
        missing = await call_mcp_tool(
            session, "read_wiki_page", {"slug": "projects/does-not-exist"}
        )
        assert missing["success"] is False
        assert missing["errorCode"] == ErrorCode.NOT_FOUND.value

        # Blank title, malformed source_refs, and invalid enum filters -> 400 BAD_REQUEST.
        blank_title = await call_mcp_tool(
            session,
            "upsert_wiki_page",
            {"slug": "projects/empty", "title": "   ", "body_md": "Body"},
        )
        assert blank_title["errorCode"] == ErrorCode.BAD_REQUEST.value

        bad_refs = await call_mcp_tool(
            session,
            "upsert_wiki_page",
            {
                "slug": "projects/v1",
                "title": "V1",
                "body_md": "Body",
                "source_refs": [{"invalid": "ref"}],
            },
        )
        assert bad_refs["errorCode"] == ErrorCode.BAD_REQUEST.value

        bad_kind = await call_mcp_tool(
            session, "list_wiki_pages", {"page_kind": "bogus"}
        )
        assert bad_kind["errorCode"] == ErrorCode.BAD_REQUEST.value

        bad_status = await call_mcp_tool(
            session, "list_wiki_lint_issues", {"status": "bogus"}
        )
        assert bad_status["errorCode"] == ErrorCode.BAD_REQUEST.value

        bad_slug = await call_mcp_tool(session, "read_wiki_page", {"slug": "../escape"})
        assert bad_slug["errorCode"] == ErrorCode.BAD_REQUEST.value

        bad_resolve_status = await call_mcp_tool(
            session,
            "resolve_wiki_lint_issue",
            {"issue_id": 1, "status": "bogus"},
        )
        assert bad_resolve_status["errorCode"] == ErrorCode.BAD_REQUEST.value

        missing_issue = await call_mcp_tool(
            session,
            "resolve_wiki_lint_issue",
            {"issue_id": 999999, "status": "resolved"},
        )
        assert missing_issue["errorCode"] == ErrorCode.NOT_FOUND.value
