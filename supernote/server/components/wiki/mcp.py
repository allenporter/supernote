"""MCP platform setup exposing LLM Wiki read, search, write, and lint tools."""

from __future__ import annotations

from typing import Any

from mashumaro.exceptions import InvalidFieldValue, MissingField
from mcp.server.mcpserver import Context

from supernote.models.base import ErrorCode, create_error_response
from supernote.server.components.mcp import (
    McpRegistrar,
    get_authenticated_actor,
    get_authenticated_user_id,
)
from supernote.server.core import ServerCore

from .models import (
    WikiConflictError,
    WikiNotFoundError,
    WikiPolicyError,
    WikiSourceRefDTO,
    WikiUpsertInput,
)
from .service import WIKI_SERVICE_KEY, WikiService

__all__ = ["async_setup_mcp"]

_AUTH_ERROR_MSG = "Authentication failed. Please set a valid token in meta."


async def async_setup_mcp(core: ServerCore, registrar: McpRegistrar) -> None:
    """Register the eight wiki MCP tools onto `registrar`."""
    wiki_service: WikiService = core.app[WIKI_SERVICE_KEY]

    async def get_wiki_index(ctx: Context, limit: int = 100) -> dict[str, Any]:
        """Return a compact index of active wiki pages (slug, title, kind, summary)."""
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()
        pages = await wiki_service.list_pages(user_id, limit=limit)
        return {
            "success": True,
            "entries": [
                {
                    "slug": p.slug,
                    "title": p.title,
                    "page_kind": p.page_kind,
                    "summary": p.summary,
                    "version": p.version,
                    "update_time": p.update_time,
                }
                for p in pages
            ],
        }

    async def list_wiki_pages(
        ctx: Context,
        page_kind: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List active wiki pages for the authenticated user."""
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()
        pages = await wiki_service.list_pages(
            user_id, page_kind=page_kind, limit=limit, offset=offset
        )
        return {"success": True, "pages": [p.to_dict() for p in pages]}

    async def read_wiki_page(ctx: Context, slug: str) -> dict[str, Any]:
        """Read a single wiki page by slug, including backlinks and source refs."""
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()
        try:
            page = await wiki_service.get_page(user_id, slug)
        except ValueError as err:
            return create_error_response(str(err), ErrorCode.BAD_REQUEST).to_dict()
        if page is None:
            return create_error_response(
                f"Wiki page {slug!r} not found", ErrorCode.NOT_FOUND
            ).to_dict()
        return {"success": True, "page": page.to_dict()}

    async def search_wiki(ctx: Context, query: str, top_k: int = 10) -> dict[str, Any]:
        """Search wiki pages by keyword or alias, returning 1-hop links and source refs."""
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()
        hits = await wiki_service.search_pages(user_id, query, top_k=top_k)
        return {"success": True, "hits": [h.to_dict() for h in hits]}

    async def upsert_wiki_page(
        ctx: Context,
        slug: str,
        title: str,
        body_md: str,
        page_kind: str = "topic",
        summary: str = "",
        aliases: list[str] | None = None,
        source_refs: list[dict[str, Any]] | None = None,
        expected_version: int | None = None,
        change_summary: str = "",
    ) -> dict[str, Any]:
        """Create or update a wiki page as an external MCP agent (respects edit_policy)."""
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()
        try:
            refs = [
                WikiSourceRefDTO.from_dict(r)
                for r in (source_refs or [])
                if isinstance(r, dict)
            ]
        except (MissingField, InvalidFieldValue, ValueError, TypeError) as err:
            return create_error_response(
                f"Invalid source_refs: {err}", ErrorCode.BAD_REQUEST
            ).to_dict()
        try:
            page = await wiki_service.upsert_page(
                user_id,
                WikiUpsertInput(
                    slug=slug,
                    title=title,
                    body_md=body_md,
                    page_kind=page_kind,
                    summary=summary,
                    aliases=list(aliases or []),
                    source_refs=refs,
                    author_kind="agent",
                    author_ref=get_authenticated_actor(),
                    change_summary=change_summary,
                    expected_version=expected_version,
                ),
            )
        except ValueError as err:
            return create_error_response(str(err), ErrorCode.BAD_REQUEST).to_dict()
        except WikiConflictError as err:
            return create_error_response(str(err), ErrorCode.CONFLICT).to_dict()
        except WikiPolicyError as err:
            return create_error_response(str(err), ErrorCode.FORBIDDEN).to_dict()
        return {"success": True, "page": page.to_dict()}

    async def list_wiki_lint_issues(
        ctx: Context, status: str = "open"
    ) -> dict[str, Any]:
        """List structural and semantic wiki lint issues."""
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()
        issues = await wiki_service.list_lint_issues(
            user_id, status=None if status == "all" else status
        )
        return {"success": True, "issues": [i.to_dict() for i in issues]}

    async def resolve_wiki_lint_issue(
        ctx: Context, issue_id: int, status: str = "resolved"
    ) -> dict[str, Any]:
        """Resolve or dismiss a wiki lint issue."""
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()
        try:
            issue = await wiki_service.resolve_lint_issue(
                user_id, issue_id, status=status
            )
        except ValueError as err:
            return create_error_response(str(err), ErrorCode.BAD_REQUEST).to_dict()
        except WikiNotFoundError as err:
            return create_error_response(str(err), ErrorCode.NOT_FOUND).to_dict()
        return {"success": True, "issue": issue.to_dict()}

    async def get_wiki_status(ctx: Context) -> dict[str, Any]:
        """Return per-user wiki inventory, cursor, and open lint summary."""
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()
        status = await wiki_service.get_status(user_id)
        return {"success": True, "status": status.to_dict()}

    for tool_fn in (
        get_wiki_index,
        list_wiki_pages,
        read_wiki_page,
        search_wiki,
        upsert_wiki_page,
        list_wiki_lint_issues,
        resolve_wiki_lint_issue,
        get_wiki_status,
    ):
        registrar.add_tool(tool_fn)
