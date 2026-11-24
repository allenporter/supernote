"""Tests for `supernote.server.components.wiki.mcp` MCP tools."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

from mcp.server.auth.middleware.auth_context import AuthenticatedUser, auth_context_var

from supernote.models.base import ErrorCode
from supernote.server.components.mcp import McpRegistrar
from supernote.server.components.oauth.models import MCPScope, SupernoteAccessToken
from supernote.server.components.wiki.mcp import async_setup_mcp
from supernote.server.components.wiki.models import WikiUpsertInput
from supernote.server.components.wiki.service import WIKI_SERVICE_KEY
from supernote.server.core import ServerCore
from tests.server.components.conftest import LoadComponents


@contextmanager
def _as_mcp_user(user_id: int = 1, actor: str = "oauth:claude") -> Generator[None]:
    token = SupernoteAccessToken(
        token="tok",
        client_id="claude",
        scopes=[MCPScope.ALL],
        user_id=user_id,
        actor=actor,
    )
    reset = auth_context_var.set(AuthenticatedUser(token))
    try:
        yield
    finally:
        auth_context_var.reset(reset)


async def _setup_wiki_mcp_tools(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> dict[str, Any]:
    await load_components("wiki", configs={"wiki": {"enabled": True}})
    registrar = McpRegistrar()
    await async_setup_mcp(component_core, registrar)
    return registrar._tools


async def test_wiki_mcp_registers_all_eight_tools_and_requires_auth(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    tools = await _setup_wiki_mcp_tools(component_core, load_components)
    assert set(tools) == {
        "get_wiki_index",
        "list_wiki_pages",
        "read_wiki_page",
        "search_wiki",
        "upsert_wiki_page",
        "list_wiki_lint_issues",
        "resolve_wiki_lint_issue",
        "get_wiki_status",
    }
    unauth = await tools["get_wiki_index"](MagicMock())
    assert unauth["success"] is False
    assert unauth["errorCode"] == ErrorCode.UNAUTHORIZED.value


async def test_wiki_mcp_crud_index_list_search_and_lint_resolution(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    tools = await _setup_wiki_mcp_tools(component_core, load_components)
    ctx = MagicMock()

    with _as_mcp_user():
        upserted = await tools["upsert_wiki_page"](
            ctx,
            slug="projects/mcp-test",
            title="MCP Test",
            body_md="Linked to [[entities/missing]].",
            page_kind="project",
            summary="Created by MCP agent",
        )
        assert upserted["success"] is True
        assert upserted["page"]["last_author_kind"] == "agent"

        index = await tools["get_wiki_index"](ctx)
        assert [e["slug"] for e in index["entries"]] == ["projects/mcp-test"]

        listed = await tools["list_wiki_pages"](ctx, page_kind="project")
        assert listed["success"] is True
        assert [p["slug"] for p in listed["pages"]] == ["projects/mcp-test"]

        read = await tools["read_wiki_page"](ctx, slug="projects/mcp-test")
        assert read["success"] is True
        assert read["page"]["title"] == "MCP Test"

        search = await tools["search_wiki"](ctx, query="mcp")
        assert len(search["hits"]) == 1

        # Trigger structural lint so list/resolve lint tools have a real issue.
        await component_core.app[WIKI_SERVICE_KEY].run_structural_lint(1)
        lint_list = await tools["list_wiki_lint_issues"](ctx, status="open")
        assert lint_list["success"] is True
        assert len(lint_list["issues"]) >= 1

        issue_id = lint_list["issues"][0]["issue_id"]
        resolved = await tools["resolve_wiki_lint_issue"](
            ctx, issue_id=issue_id, status="dismissed"
        )
        assert resolved["success"] is True
        assert resolved["issue"]["status"] == "dismissed"

        status = await tools["get_wiki_status"](ctx)
        assert status["success"] is True
        assert status["status"]["page_count"] == 1


async def test_wiki_mcp_error_paths_and_policy_enforcement(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    tools = await _setup_wiki_mcp_tools(component_core, load_components)
    ctx = MagicMock()

    # Seed a user-owned protected_prose page.
    await component_core.app[WIKI_SERVICE_KEY].upsert_page(
        1,
        WikiUpsertInput(
            slug="projects/human-owned",
            title="Human Owned",
            body_md="Do not overwrite",
            author_kind="user",
        ),
    )

    with _as_mcp_user():
        # Policy violation -> 403 FORBIDDEN.
        forbidden = await tools["upsert_wiki_page"](
            ctx,
            slug="projects/human-owned",
            title="Human Owned",
            body_md="Agent overwrite",
        )
        assert forbidden["success"] is False
        assert forbidden["errorCode"] == ErrorCode.FORBIDDEN.value

        # Optimistic concurrency conflict -> 409 CONFLICT.
        await tools["upsert_wiki_page"](
            ctx, slug="projects/v1", title="V1", body_md="Body"
        )
        conflict = await tools["upsert_wiki_page"](
            ctx,
            slug="projects/v1",
            title="V1",
            body_md="Stale",
            expected_version=99,
        )
        assert conflict["success"] is False
        assert conflict["errorCode"] == ErrorCode.CONFLICT.value

        # Missing page -> 404 NOT_FOUND.
        missing = await tools["read_wiki_page"](ctx, slug="projects/does-not-exist")
        assert missing["success"] is False
        assert missing["errorCode"] == ErrorCode.NOT_FOUND.value

        # Blank title, non-dict source_refs, and invalid enum filters -> 400 BAD_REQUEST.
        blank_title = await tools["upsert_wiki_page"](
            ctx, slug="projects/empty", title="   ", body_md="Body"
        )
        assert blank_title["errorCode"] == ErrorCode.BAD_REQUEST.value

        bad_refs = await tools["upsert_wiki_page"](
            ctx,
            slug="projects/v1",
            title="V1",
            body_md="Body",
            source_refs=["note_page:1:p1"],  # type: ignore[list-item]
        )
        assert bad_refs["errorCode"] == ErrorCode.BAD_REQUEST.value

        bad_kind = await tools["list_wiki_pages"](ctx, page_kind="bogus")
        assert bad_kind["errorCode"] == ErrorCode.BAD_REQUEST.value

        bad_status = await tools["list_wiki_lint_issues"](ctx, status="bogus")
        assert bad_status["errorCode"] == ErrorCode.BAD_REQUEST.value
