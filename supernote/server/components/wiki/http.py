"""HTTP platform routes for the LLM Wiki component (`/api/extended/wiki/*`)."""

from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import web
from mashumaro.exceptions import InvalidFieldValue, MissingField

from supernote.server.ai.base import AIError
from supernote.server.components.http import HttpRegistrar
from supernote.server.core import ServerCore
from supernote.server.keys import (
    REQUEST_ACTOR_KEY,
    REQUEST_USER_KEY,
    USER_SERVICE_KEY,
)
from supernote.server.routes.decorators import interactive_session_only
from supernote.server.services.user import UserService

from .compiler import WIKI_COMPILER_KEY, WikiCompilerWorker
from .export import WIKI_EXPORT_SERVICE_KEY, WikiExportService
from .models import (
    WikiConflictError,
    WikiNotFoundError,
    WikiPolicyError,
    WikiSourceRefDTO,
    WikiUpsertInput,
)
from .service import WIKI_SERVICE_KEY, WikiService

__all__ = [
    "async_setup_http",
    "routes",
]

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


async def _resolve_user_id(request: web.Request) -> int | None:
    user_service: UserService = request.app[USER_SERVICE_KEY]
    return await user_service.get_user_id(request[REQUEST_USER_KEY])


def _parse_int_param(
    raw: str | None, default: int, *, min_val: int, max_val: int
) -> int:
    if raw is None or not raw.strip():
        return default
    val = int(raw)
    if val < min_val or val > max_val:
        raise ValueError(f"Parameter out of range [{min_val}, {max_val}]")
    return val


@routes.get("/api/extended/wiki/pages")
async def handle_list_wiki_pages(request: web.Request) -> web.Response:
    """List active wiki pages for the authenticated user."""
    user_id = await _resolve_user_id(request)
    if user_id is None:
        return web.json_response({"error": "User not found"}, status=404)

    try:
        limit = _parse_int_param(
            request.query.get("limit"), 100, min_val=1, max_val=500
        )
        offset = _parse_int_param(
            request.query.get("offset"), 0, min_val=0, max_val=100_000
        )
    except ValueError as err:
        return web.json_response({"error": str(err)}, status=400)

    page_kind = request.query.get("page_kind") or None
    service: WikiService = request.app[WIKI_SERVICE_KEY]
    pages = await service.list_pages(
        user_id, page_kind=page_kind, limit=limit, offset=offset
    )
    return web.json_response({"pages": [p.to_dict() for p in pages]})


@routes.get("/api/extended/wiki/pages/{slug:.+}")
async def handle_get_wiki_page(request: web.Request) -> web.Response:
    """Fetch a single active wiki page by slug."""
    user_id = await _resolve_user_id(request)
    if user_id is None:
        return web.json_response({"error": "User not found"}, status=404)

    service: WikiService = request.app[WIKI_SERVICE_KEY]
    try:
        page = await service.get_page(user_id, request.match_info["slug"])
    except ValueError as err:
        return web.json_response({"error": str(err)}, status=400)
    if page is None:
        return web.json_response({"error": "Wiki page not found"}, status=404)
    return web.json_response({"page": page.to_dict()})


@routes.put("/api/extended/wiki/pages/{slug:.+}")
async def handle_put_wiki_page(request: web.Request) -> web.Response:
    """Create or update a wiki page with optimistic concurrency."""
    user_id = await _resolve_user_id(request)
    if user_id is None:
        return web.json_response({"error": "User not found"}, status=404)

    try:
        body: dict[str, Any] = await request.json()
    except (json.JSONDecodeError, ValueError):
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response(
            {"error": "Request body must be a JSON object"}, status=400
        )

    title = str(body.get("title", "")).strip()
    if not title:
        return web.json_response({"error": "title is required"}, status=400)

    for field_name in ("source_refs", "claims", "aliases"):
        val = body.get(field_name)
        if val is not None and not isinstance(val, list):
            return web.json_response(
                {"error": f"{field_name} must be a list"}, status=400
            )

    try:
        source_refs = [
            WikiSourceRefDTO.from_dict(r)
            for r in (body.get("source_refs") or [])
            if isinstance(r, dict)
        ]
    except (MissingField, InvalidFieldValue, ValueError, TypeError) as err:
        return web.json_response({"error": f"Invalid source_refs: {err}"}, status=400)

    actor = request[REQUEST_ACTOR_KEY]
    author_kind = (
        "user" if (actor == "user:web" or actor.startswith("device:")) else "agent"
    )
    expected_version = body.get("expected_version")
    if expected_version is not None:
        if isinstance(expected_version, bool):
            return web.json_response(
                {"error": "expected_version must be an integer"}, status=400
            )
        try:
            expected_version = int(expected_version)
        except (TypeError, ValueError):
            return web.json_response(
                {"error": "expected_version must be an integer"}, status=400
            )

    service: WikiService = request.app[WIKI_SERVICE_KEY]
    try:
        page = await service.upsert_page(
            user_id,
            WikiUpsertInput(
                slug=request.match_info["slug"],
                title=title,
                body_md=str(body.get("body_md", "")),
                page_kind=str(body.get("page_kind", "topic")),
                summary=str(body.get("summary", "")),
                claims=[c for c in (body.get("claims") or []) if isinstance(c, dict)],
                aliases=[
                    str(a) for a in (body.get("aliases") or []) if isinstance(a, str)
                ],
                source_refs=source_refs,
                author_kind=author_kind,
                author_ref=str(actor),
                change_summary=str(body.get("change_summary", "")),
                expected_version=expected_version,
                edit_policy=(
                    str(body["edit_policy"])
                    if body.get("edit_policy") is not None
                    else None
                ),
            ),
        )
    except ValueError as err:
        return web.json_response({"error": str(err)}, status=400)
    except WikiConflictError as err:
        return web.json_response(
            {"error": str(err), "expected": err.expected, "actual": err.actual},
            status=409,
        )
    except WikiPolicyError as err:
        return web.json_response({"error": str(err)}, status=403)

    return web.json_response({"page": page.to_dict()})


@routes.delete("/api/extended/wiki/pages/{slug:.+}")
@interactive_session_only
async def handle_delete_wiki_page(request: web.Request) -> web.Response:
    """Soft-delete a wiki page tombstone."""
    user_id = await _resolve_user_id(request)
    if user_id is None:
        return web.json_response({"error": "User not found"}, status=404)

    service: WikiService = request.app[WIKI_SERVICE_KEY]
    try:
        await service.delete_page(user_id, request.match_info["slug"])
    except ValueError as err:
        return web.json_response({"error": str(err)}, status=400)
    except WikiNotFoundError as err:
        return web.json_response({"error": str(err)}, status=404)
    return web.json_response({"deleted": True})


@routes.get("/api/extended/wiki/revisions/{slug:.+}")
async def handle_list_wiki_revisions(request: web.Request) -> web.Response:
    """List immutable revision snapshots for a wiki slug."""
    user_id = await _resolve_user_id(request)
    if user_id is None:
        return web.json_response({"error": "User not found"}, status=404)

    service: WikiService = request.app[WIKI_SERVICE_KEY]
    try:
        revisions = await service.list_revisions(user_id, request.match_info["slug"])
    except ValueError as err:
        return web.json_response({"error": str(err)}, status=400)
    except WikiNotFoundError as err:
        return web.json_response({"error": str(err)}, status=404)
    return web.json_response({"revisions": [r.to_dict() for r in revisions]})


@routes.get("/api/extended/wiki/search")
async def handle_search_wiki(request: web.Request) -> web.Response:
    """Search active wiki pages with 1-hop neighbor links and source refs."""
    user_id = await _resolve_user_id(request)
    if user_id is None:
        return web.json_response({"error": "User not found"}, status=404)

    query = request.query.get("q", "").strip()
    try:
        top_k = _parse_int_param(request.query.get("top_k"), 10, min_val=1, max_val=50)
    except ValueError as err:
        return web.json_response({"error": str(err)}, status=400)

    service: WikiService = request.app[WIKI_SERVICE_KEY]
    hits = await service.search_pages(user_id, query, top_k=top_k)
    return web.json_response({"hits": [h.to_dict() for h in hits]})


@routes.get("/api/extended/wiki/status")
async def handle_wiki_status(request: web.Request) -> web.Response:
    """Return wiki inventory counts, cursor status, and open lint count."""
    user_id = await _resolve_user_id(request)
    if user_id is None:
        return web.json_response({"error": "User not found"}, status=404)

    service: WikiService = request.app[WIKI_SERVICE_KEY]
    status = await service.get_status(user_id)
    return web.json_response({"status": status.to_dict()})


@routes.post("/api/extended/wiki/compile")
async def handle_wiki_compile(request: web.Request) -> web.Response:
    """Trigger incremental compile, historical backfill, or semantic lint."""
    user_id = await _resolve_user_id(request)
    if user_id is None:
        return web.json_response({"error": "User not found"}, status=404)

    body: dict[str, Any] = {}
    if request.can_read_body:
        try:
            raw = await request.json()
            if isinstance(raw, dict):
                body = raw
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "Invalid JSON body"}, status=400)

    mode = str(body.get("mode", "incremental"))
    compiler: WikiCompilerWorker = request.app[WIKI_COMPILER_KEY]
    try:
        if mode == "incremental":
            res = await compiler.compile_user_delta(user_id)
            return web.json_response(
                {
                    "mode": mode,
                    "events_processed": res.events_processed,
                    "pages_updated": res.pages_updated,
                    "skipped_policy_pages": res.skipped_policy_pages,
                    "lint_issues_open": res.lint_issues_open,
                    "status": res.status,
                }
            )
        if mode == "backfill":
            raw_max = body.get("max_files")
            if raw_max is None:
                max_files = 5
            elif isinstance(raw_max, bool):
                return web.json_response(
                    {"error": "max_files must be an integer"}, status=400
                )
            else:
                try:
                    max_files = int(raw_max)
                except (TypeError, ValueError):
                    return web.json_response(
                        {"error": "max_files must be an integer"}, status=400
                    )
            res = await compiler.run_backfill(user_id, max_files=max_files)
            return web.json_response(
                {
                    "mode": mode,
                    "events_processed": res.events_processed,
                    "pages_updated": res.pages_updated,
                    "skipped_policy_pages": res.skipped_policy_pages,
                    "lint_issues_open": res.lint_issues_open,
                    "status": res.status,
                }
            )
        if mode == "lint":
            issues = await compiler.run_semantic_lint(user_id)
            return web.json_response(
                {"mode": mode, "issues": [i.to_dict() for i in issues]}
            )
    except AIError as err:
        return web.json_response({"error": str(err)}, status=502)

    return web.json_response(
        {"error": f"Unsupported compile mode: {mode!r}"}, status=400
    )


@routes.get("/api/extended/wiki/lint")
async def handle_list_wiki_lint(request: web.Request) -> web.Response:
    """List wiki lint issues for the authenticated user."""
    user_id = await _resolve_user_id(request)
    if user_id is None:
        return web.json_response({"error": "User not found"}, status=404)

    status_filter = request.query.get("status", "open")
    service: WikiService = request.app[WIKI_SERVICE_KEY]
    issues = await service.list_lint_issues(
        user_id, status=None if status_filter == "all" else status_filter
    )
    return web.json_response({"issues": [i.to_dict() for i in issues]})


@routes.post("/api/extended/wiki/lint/{issue_id}/resolve")
async def handle_resolve_wiki_lint(request: web.Request) -> web.Response:
    """Resolve or dismiss a wiki lint issue."""
    user_id = await _resolve_user_id(request)
    if user_id is None:
        return web.json_response({"error": "User not found"}, status=404)

    try:
        issue_id = int(request.match_info["issue_id"])
    except ValueError:
        return web.json_response({"error": "Invalid issue_id"}, status=400)

    status = "resolved"
    if request.can_read_body:
        try:
            body = await request.json()
            if isinstance(body, dict) and body.get("status") is not None:
                status = str(body["status"])
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "Invalid JSON body"}, status=400)

    service: WikiService = request.app[WIKI_SERVICE_KEY]
    try:
        issue = await service.resolve_lint_issue(user_id, issue_id, status=status)
    except ValueError as err:
        return web.json_response({"error": str(err)}, status=400)
    except WikiNotFoundError as err:
        return web.json_response({"error": str(err)}, status=404)
    return web.json_response({"issue": issue.to_dict()})


@routes.get("/api/extended/wiki/export.zip")
async def handle_export_wiki_zip(request: web.Request) -> web.Response:
    """Stream an Obsidian-compatible `.zip` vault of all active wiki pages."""
    user_id = await _resolve_user_id(request)
    if user_id is None:
        return web.json_response({"error": "User not found"}, status=404)

    exporter: WikiExportService = request.app[WIKI_EXPORT_SERVICE_KEY]
    raw_zip = await exporter.export_vault_zip(user_id)
    return web.Response(
        body=raw_zip,
        content_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="supernote-wiki.zip"'},
    )


@routes.get("/api/extended/wiki/export/{slug:.+}.md")
async def handle_export_wiki_markdown(request: web.Request) -> web.Response:
    """Export one active wiki page as Obsidian-compatible Markdown."""
    user_id = await _resolve_user_id(request)
    if user_id is None:
        return web.json_response({"error": "User not found"}, status=404)

    exporter: WikiExportService = request.app[WIKI_EXPORT_SERVICE_KEY]
    try:
        markdown = await exporter.export_page_markdown(
            user_id, request.match_info["slug"]
        )
    except ValueError as err:
        return web.json_response({"error": str(err)}, status=400)
    except WikiNotFoundError as err:
        return web.json_response({"error": str(err)}, status=404)
    return web.Response(text=markdown, content_type="text/markdown", charset="utf-8")


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Register `/api/extended/wiki/*` routes on `registrar.router`."""
    _ = core
    registrar.router.add_routes(routes)
