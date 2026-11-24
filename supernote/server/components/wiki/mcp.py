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
    VALID_PAGE_KINDS,
    WikiConflictError,
    WikiNotFoundError,
    WikiPolicyError,
    WikiSourceRefDTO,
    WikiUpsertInput,
)
from .service import WIKI_SERVICE_KEY, WikiService

__all__ = ["async_setup_mcp"]

_AUTH_ERROR_MSG = "Authentication failed. Please set a valid token in meta."
_VALID_LINT_STATUS_FILTERS: frozenset[str] = frozenset(
    {"open", "resolved", "dismissed", "all"}
)


async def async_setup_mcp(core: ServerCore, registrar: McpRegistrar) -> None:
    """Register the eight wiki MCP tools onto `registrar`."""
    wiki_service: WikiService = core.app[WIKI_SERVICE_KEY]

    async def get_wiki_index(ctx: Context, limit: int = 100) -> dict[str, Any]:
        """Return a compact index of active wiki pages (slug, title, kind, summary).

        Start here for a low-token overview of the compiled wiki (omits full
        Markdown bodies) to orient or pick specific slugs to fetch with
        `read_wiki_page`.

        Args:
            limit: Maximum number of index entries to return (`1..500`, default `100`).
        """
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
        """List active wiki pages for the authenticated user.

        Use when paginating full page payloads or filtering by `page_kind`.
        Prefer `get_wiki_index` for lightweight discovery.

        Args:
            page_kind: Optional category filter (`project`, `entity`, `topic`,
                `source_digest`, `index`, or `log`).
            limit: Maximum number of pages to return (`1..500`, default `50`).
            offset: Pagination offset (default `0`).
        """
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()
        if page_kind is not None and page_kind not in VALID_PAGE_KINDS:
            return create_error_response(
                f"Unsupported page_kind: {page_kind!r}", ErrorCode.BAD_REQUEST
            ).to_dict()
        pages = await wiki_service.list_pages(
            user_id, page_kind=page_kind, limit=limit, offset=offset
        )
        return {"success": True, "pages": [p.to_dict() for p in pages]}

    async def read_wiki_page(ctx: Context, slug: str) -> dict[str, Any]:
        """Read a single wiki page by slug, including backlinks and source refs.

        Use after `get_wiki_index` or `search_wiki` to inspect full Markdown
        prose, provenance citations, and the current `version` (needed for
        optimistic concurrency before calling `upsert_wiki_page`).

        Args:
            slug: Canonical plural-prefixed page slug (e.g. ``projects/q3-plan``,
                ``entities/alice``).
        """
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
        """Search wiki pages by keyword or alias, returning 1-hop links and source refs.

        Use first when answering questions about a topic, person, or project
        from compiled knowledge; fall back to notebook chunk search or
        transcripts when finer source detail is needed.

        Args:
            query: Space-separated keywords or aliases to match against page
                titles, aliases, summaries, and bodies.
            top_k: Maximum number of ranked hits to return (`1..50`, default `10`).
        """
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
        """Create or update a wiki page as an external MCP agent (respects edit_policy).

        Use to persist synthesized knowledge compiled from notebooks or tasks.
        Read an existing page first to pass its `version` as `expected_version`;
        pages edited by the user (`protected_prose`) or `locked` reject agent
        writes with `403`.

        Args:
            slug: Canonical plural-prefixed slug (e.g. ``projects/q3-plan``,
                ``entities/alice``); lowercase `[a-z0-9._-/]`, max 191 chars.
            title: Human-readable page heading.
            body_md: Markdown body; supports ``[[slug]]`` and ``[[slug|label]]``
                wikilinks for cross-page graph links and backlinks.
            page_kind: Page category (`project`, `entity`, `topic`,
                `source_digest`, `index`, or `log`; default `topic`).
            summary: Optional one-line summary for index and search snippets.
            aliases: Optional alternate names or abbreviations for search and
                entity resolution.
            source_refs: Optional provenance citations, each a dict with
                ``source_type`` (`note_page` or `schedule_task`), ``source_key``
                (``{file_id}:{page_id}`` or ``{task_id}``), and optional
                ``file_id`` (int or null).
            expected_version: Optional optimistic-concurrency guard (`0` for a
                new or revived page, or the current `version` for an update).
                Returns `409` on version mismatch and `403` if the page has
                `protected_prose` or `locked` edit policy.
            change_summary: Optional short note recorded on the revision row.
        """
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()
        raw_refs = source_refs or []
        if any(not isinstance(r, dict) for r in raw_refs):
            return create_error_response(
                "Invalid source_refs: each entry must be an object",
                ErrorCode.BAD_REQUEST,
            ).to_dict()
        raw_aliases = aliases or []
        if any(not isinstance(a, str) for a in raw_aliases):
            return create_error_response(
                "Invalid aliases: each entry must be a string",
                ErrorCode.BAD_REQUEST,
            ).to_dict()
        try:
            refs = [WikiSourceRefDTO.from_dict(r) for r in raw_refs]
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
        """List wiki health (lint) issues needing review or cleanup.

        Lint issues are wiki knowledge-graph problems—not code-style errors—such
        as structural defects (`broken_link`, `orphan_page`, `stale_source`) or
        semantic findings (`contradiction`, `duplicate_entity`). Use during a
        maintenance pass or when `get_wiki_status` reports open issues.

        Args:
            status: Filter by issue status (`open`, `resolved`, `dismissed`, or
                `all`; default `open`).
        """
        _ = ctx
        if (user_id := get_authenticated_user_id()) is None:
            return create_error_response(
                _AUTH_ERROR_MSG, ErrorCode.UNAUTHORIZED
            ).to_dict()
        if status not in _VALID_LINT_STATUS_FILTERS:
            return create_error_response(
                f"Unsupported lint status filter: {status!r}", ErrorCode.BAD_REQUEST
            ).to_dict()
        issues = await wiki_service.list_lint_issues(
            user_id, status=None if status == "all" else status
        )
        return {"success": True, "issues": [i.to_dict() for i in issues]}

    async def resolve_wiki_lint_issue(
        ctx: Context, issue_id: int, status: str = "resolved"
    ) -> dict[str, Any]:
        """Mark a wiki health (lint) issue as resolved or dismissed.

        Use after fixing the underlying wiki graph or content problem (e.g.
        reconciling a contradiction or updating a broken link) with
        `upsert_wiki_page`, or to dismiss a false positive.

        Args:
            issue_id: Numeric ID of the lint issue from `list_wiki_lint_issues`.
            status: Target status (`resolved` or `dismissed`; default `resolved`).
        """
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
        """Return per-user wiki inventory, cursor, and open lint summary.

        Use to check whether the wiki is populated, see how current it is with
        the event stream, or check for open lint issues before querying or
        running maintenance.
        """
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
