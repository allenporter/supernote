"""Tests for `supernote.server.components.wiki.mcp` MCP tools."""

from __future__ import annotations

from unittest.mock import MagicMock

from mcp.server.auth.middleware.auth_context import AuthenticatedUser, auth_context_var

from supernote.server.components.ai import AiComponent
from supernote.server.components.events import EventsComponent
from supernote.server.components.mcp import McpRegistrar
from supernote.server.components.oauth.models import MCPScope, SupernoteAccessToken
from supernote.server.components.wiki import WikiComponent
from supernote.server.components.wiki.mcp import async_setup_mcp
from supernote.server.core import ComponentLoader, ServerCore


async def test_wiki_mcp_tools_end_to_end(component_core: ServerCore) -> None:
    loader = ComponentLoader()
    loader.register(AiComponent())
    loader.register(EventsComponent())
    loader.register(WikiComponent())
    await loader.async_setup_all(component_core, {"wiki": {"enabled": True}})

    registrar = McpRegistrar()
    await async_setup_mcp(component_core, registrar)
    assert set(registrar.tool_names) == {
        "get_wiki_index",
        "list_wiki_pages",
        "read_wiki_page",
        "search_wiki",
        "upsert_wiki_page",
        "list_wiki_lint_issues",
        "resolve_wiki_lint_issue",
        "get_wiki_status",
    }

    tools = registrar._tools
    ctx = MagicMock()

    # Unauthenticated call fails cleanly.
    unauth = await tools["get_wiki_index"](ctx)
    assert unauth["success"] is False

    token = SupernoteAccessToken(
        token="tok",
        client_id="claude",
        scopes=[MCPScope.ALL],
        user_id=1,
        actor="oauth:claude",
    )
    reset = auth_context_var.set(AuthenticatedUser(token))
    try:
        upserted = await tools["upsert_wiki_page"](
            ctx,
            slug="projects/mcp-test",
            title="MCP Test",
            body_md="Linked to [[entities/alice]].",
            page_kind="project",
            summary="Created by MCP agent",
        )
        assert upserted["success"] is True
        assert upserted["page"]["last_author_kind"] == "agent"

        index = await tools["get_wiki_index"](ctx)
        assert index["success"] is True
        assert [e["slug"] for e in index["entries"]] == ["projects/mcp-test"]

        read = await tools["read_wiki_page"](ctx, slug="projects/mcp-test")
        assert read["success"] is True
        assert read["page"]["title"] == "MCP Test"

        search = await tools["search_wiki"](ctx, query="mcp")
        assert search["success"] is True
        assert len(search["hits"]) == 1

        status = await tools["get_wiki_status"](ctx)
        assert status["success"] is True
        assert status["status"]["page_count"] == 1
    finally:
        auth_context_var.reset(reset)

    await loader.async_stop_all(component_core)
