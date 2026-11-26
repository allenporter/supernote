"""HTTP platform routes for the LLM Wiki component (`/api/extended/wiki/*`)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from aiohttp import web
from mashumaro.mixins.json import DataClassJSONMixin

from supernote.models.wiki import (
    WikiCompileMode,
    WikiCompileResponseVO,
    WikiDeleteResponseVO,
    WikiLintIssueResponseVO,
    WikiLintListVO,
    WikiPageListVO,
    WikiPageResponseVO,
    WikiRevisionsResponseVO,
    WikiSearchResponseVO,
    WikiStatusResponseVO,
)
from supernote.server.ai.base import AIError
from supernote.server.components.http import HttpRegistrar, parse_json_dto
from supernote.server.core import ServerCore
from supernote.server.exceptions import InvalidInputError
from supernote.server.keys import (
    REQUEST_ACTOR_KEY,
    REQUEST_USER_KEY,
    USER_SERVICE_KEY,
)
from supernote.server.routes.decorators import interactive_session_only
from supernote.server.services.user import UserService

from .compiler import WIKI_COMPILER_KEY, WikiCompileResult, WikiCompilerWorker
from .export import WIKI_EXPORT_SERVICE_KEY, WikiExportService
from .models import (
    VALID_PAGE_KINDS,
    WikiConflictError,
    WikiNotFoundError,
    WikiPolicyError,
    WikiSourceRefDTO,
    WikiUpsertInput,
)
from .service import WIKI_SERVICE_KEY, WikiService

__all__ = [
    "WikiCompileRequestDTO",
    "WikiResolveLintRequestDTO",
    "WikiUpsertRequestDTO",
    "async_setup_http",
    "routes",
]

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()

_VALID_LINT_STATUS_FILTERS: frozenset[str] = frozenset(
    {"open", "resolved", "dismissed", "all"}
)


@dataclass
class WikiUpsertRequestDTO(DataClassJSONMixin):
    """Request body for `PUT /api/extended/wiki/pages/{slug}`."""

    title: str
    body_md: str = ""
    page_kind: str = "topic"
    summary: str = ""
    aliases: list[str] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    source_refs: list[WikiSourceRefDTO] = field(default_factory=list)
    change_summary: str = ""
    expected_version: int | None = None
    edit_policy: str | None = None

    def __post_init__(self) -> None:
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("title is required")
        if self.expected_version is not None and self.expected_version < 0:
            raise ValueError("expected_version must be >= 0")


@dataclass
class WikiCompileRequestDTO(DataClassJSONMixin):
    """Optional request body for `POST /api/extended/wiki/compile`."""

    mode: WikiCompileMode = WikiCompileMode.INCREMENTAL
    max_files: int | None = None

    def __post_init__(self) -> None:
        if self.max_files is not None and (self.max_files < 1 or self.max_files > 20):
            raise ValueError("max_files must be between 1 and 20")


@dataclass
class WikiResolveLintRequestDTO(DataClassJSONMixin):
    """Optional request body for `POST /api/extended/wiki/lint/{issue_id}/resolve`."""

    status: str = "resolved"


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


def _compile_result_response(
    mode: WikiCompileMode, res: WikiCompileResult
) -> web.Response:
    return web.json_response(
        WikiCompileResponseVO(
            mode=mode,
            events_processed=res.events_processed,
            pages_updated=res.pages_updated,
            skipped_policy_pages=res.skipped_policy_pages,
            lint_issues_open=res.lint_issues_open,
            status=res.status,
            files_processed=res.files_processed,
            updated_pages=res.updated_pages,
            remaining_files=res.remaining_files,
        ).to_dict()
    )


@routes.get("/api/extended/wiki/pages")
async def handle_list_wiki_pages(request: web.Request) -> web.Response:
    """List active wiki pages for the authenticated user."""
    if (user_id := await _resolve_user_id(request)) is None:
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
    if page_kind is not None and page_kind not in VALID_PAGE_KINDS:
        return web.json_response(
            {"error": f"Unsupported page_kind: {page_kind!r}"}, status=400
        )

    service: WikiService = request.app[WIKI_SERVICE_KEY]
    pages = await service.list_pages(
        user_id, page_kind=page_kind, limit=limit, offset=offset
    )
    return web.json_response(WikiPageListVO(pages=pages).to_dict())


@routes.get("/api/extended/wiki/pages/{slug:.+}")
async def handle_get_wiki_page(request: web.Request) -> web.Response:
    """Fetch a single active wiki page by slug."""
    if (user_id := await _resolve_user_id(request)) is None:
        return web.json_response({"error": "User not found"}, status=404)

    service: WikiService = request.app[WIKI_SERVICE_KEY]
    try:
        page = await service.get_page(user_id, request.match_info["slug"])
    except ValueError as err:
        return web.json_response({"error": str(err)}, status=400)
    if page is None:
        return web.json_response({"error": "Wiki page not found"}, status=404)
    return web.json_response(WikiPageResponseVO(page=page).to_dict())


@routes.put("/api/extended/wiki/pages/{slug:.+}")
async def handle_put_wiki_page(request: web.Request) -> web.Response:
    """Create or update a wiki page with optimistic concurrency."""
    if (user_id := await _resolve_user_id(request)) is None:
        return web.json_response({"error": "User not found"}, status=404)

    try:
        req_dto = await parse_json_dto(request, WikiUpsertRequestDTO)
    except InvalidInputError as err:
        return web.json_response({"error": err.message}, status=err.status_code)

    actor = request[REQUEST_ACTOR_KEY]
    author_kind = (
        "user" if (actor == "user:web" or actor.startswith("device:")) else "agent"
    )

    service: WikiService = request.app[WIKI_SERVICE_KEY]
    try:
        page = await service.upsert_page(
            user_id,
            WikiUpsertInput(
                slug=request.match_info["slug"],
                title=req_dto.title,
                body_md=req_dto.body_md,
                page_kind=req_dto.page_kind,
                summary=req_dto.summary,
                claims=list(req_dto.claims),
                aliases=list(req_dto.aliases),
                source_refs=list(req_dto.source_refs),
                author_kind=author_kind,
                author_ref=str(actor),
                change_summary=req_dto.change_summary,
                expected_version=req_dto.expected_version,
                edit_policy=req_dto.edit_policy,
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

    return web.json_response(WikiPageResponseVO(page=page).to_dict())


@routes.delete("/api/extended/wiki/pages/{slug:.+}")
@interactive_session_only
async def handle_delete_wiki_page(request: web.Request) -> web.Response:
    """Soft-delete a wiki page tombstone."""
    if (user_id := await _resolve_user_id(request)) is None:
        return web.json_response({"error": "User not found"}, status=404)

    service: WikiService = request.app[WIKI_SERVICE_KEY]
    try:
        await service.delete_page(user_id, request.match_info["slug"])
    except ValueError as err:
        return web.json_response({"error": str(err)}, status=400)
    except WikiNotFoundError as err:
        return web.json_response({"error": str(err)}, status=404)
    return web.json_response(WikiDeleteResponseVO(deleted=True).to_dict())


@routes.get("/api/extended/wiki/revisions/{slug:.+}")
async def handle_list_wiki_revisions(request: web.Request) -> web.Response:
    """List immutable revision snapshots for a wiki slug."""
    if (user_id := await _resolve_user_id(request)) is None:
        return web.json_response({"error": "User not found"}, status=404)

    service: WikiService = request.app[WIKI_SERVICE_KEY]
    try:
        revisions = await service.list_revisions(user_id, request.match_info["slug"])
    except ValueError as err:
        return web.json_response({"error": str(err)}, status=400)
    except WikiNotFoundError as err:
        return web.json_response({"error": str(err)}, status=404)
    return web.json_response(WikiRevisionsResponseVO(revisions=revisions).to_dict())


@routes.get("/api/extended/wiki/search")
async def handle_search_wiki(request: web.Request) -> web.Response:
    """Search active wiki pages with 1-hop neighbor links and source refs."""
    if (user_id := await _resolve_user_id(request)) is None:
        return web.json_response({"error": "User not found"}, status=404)

    query = request.query.get("q", "").strip()
    try:
        top_k = _parse_int_param(request.query.get("top_k"), 10, min_val=1, max_val=50)
    except ValueError as err:
        return web.json_response({"error": str(err)}, status=400)

    service: WikiService = request.app[WIKI_SERVICE_KEY]
    hits = await service.search_pages(user_id, query, top_k=top_k)
    return web.json_response(WikiSearchResponseVO(hits=hits).to_dict())


@routes.get("/api/extended/wiki/status")
async def handle_wiki_status(request: web.Request) -> web.Response:
    """Return wiki inventory counts, cursor status, and open lint count."""
    if (user_id := await _resolve_user_id(request)) is None:
        return web.json_response({"error": "User not found"}, status=404)

    service: WikiService = request.app[WIKI_SERVICE_KEY]
    status = await service.get_status(user_id)
    compiler: WikiCompilerWorker | None = request.app.get(WIKI_COMPILER_KEY)
    if compiler is not None:
        in_flight = compiler.in_flight_backfill_pages(user_id)
        if in_flight > 0:
            status.backfill_remaining_pages = max(
                0, status.backfill_remaining_pages - in_flight
            )
    return web.json_response(WikiStatusResponseVO(status=status).to_dict())


@routes.post("/api/extended/wiki/compile")
@interactive_session_only
async def handle_wiki_compile(request: web.Request) -> web.Response:
    """Trigger incremental compile, historical backfill, or semantic lint."""
    if (user_id := await _resolve_user_id(request)) is None:
        return web.json_response({"error": "User not found"}, status=404)

    try:
        req_dto = await parse_json_dto(request, WikiCompileRequestDTO, allow_empty=True)
    except InvalidInputError as err:
        return web.json_response({"error": err.message}, status=err.status_code)

    compiler: WikiCompilerWorker = request.app[WIKI_COMPILER_KEY]
    try:
        if req_dto.mode is WikiCompileMode.INCREMENTAL:
            res = await compiler.compile_user_delta(user_id)
            return _compile_result_response(req_dto.mode, res)
        if req_dto.mode is WikiCompileMode.BACKFILL:
            if compiler.is_backfill_running(user_id):
                return web.json_response(
                    {
                        "error": "Background backfill is already running; stop it before running a manual batch."
                    },
                    status=409,
                )
            res = await compiler.run_backfill(
                user_id,
                max_files=req_dto.max_files if req_dto.max_files is not None else 5,
            )
            return _compile_result_response(req_dto.mode, res)
        if req_dto.mode is WikiCompileMode.BACKFILL_START:
            res = await compiler.start_backfill_job(
                user_id,
                max_files_per_turn=(
                    req_dto.max_files if req_dto.max_files is not None else 1
                ),
            )
            return _compile_result_response(req_dto.mode, res)
        if req_dto.mode is WikiCompileMode.BACKFILL_STOP:
            res = await compiler.stop_backfill_job(user_id)
            return _compile_result_response(req_dto.mode, res)
        if req_dto.mode is WikiCompileMode.BACKFILL_RESET:
            try:
                res = await compiler.reset_backfill(user_id)
            except ValueError as err:
                return web.json_response({"error": str(err)}, status=409)
            return _compile_result_response(req_dto.mode, res)
        issues = await compiler.run_semantic_lint(user_id)
        return web.json_response(
            WikiCompileResponseVO(mode=req_dto.mode, issues=issues).to_dict()
        )
    except (AIError, ValueError, TypeError, LookupError) as err:
        return web.json_response({"error": str(err)}, status=502)


@routes.get("/api/extended/wiki/lint")
async def handle_list_wiki_lint(request: web.Request) -> web.Response:
    """List wiki lint issues for the authenticated user."""
    if (user_id := await _resolve_user_id(request)) is None:
        return web.json_response({"error": "User not found"}, status=404)

    status_filter = request.query.get("status", "open")
    if status_filter not in _VALID_LINT_STATUS_FILTERS:
        return web.json_response(
            {"error": f"Unsupported lint status filter: {status_filter!r}"}, status=400
        )

    service: WikiService = request.app[WIKI_SERVICE_KEY]
    issues = await service.list_lint_issues(
        user_id, status=None if status_filter == "all" else status_filter
    )
    return web.json_response(WikiLintListVO(issues=issues).to_dict())


@routes.post("/api/extended/wiki/lint/{issue_id}/resolve")
async def handle_resolve_wiki_lint(request: web.Request) -> web.Response:
    """Resolve or dismiss a wiki lint issue."""
    if (user_id := await _resolve_user_id(request)) is None:
        return web.json_response({"error": "User not found"}, status=404)

    try:
        issue_id = int(request.match_info["issue_id"])
    except ValueError:
        return web.json_response({"error": "Invalid issue_id"}, status=400)

    try:
        req_dto = await parse_json_dto(
            request, WikiResolveLintRequestDTO, allow_empty=True
        )
    except InvalidInputError as err:
        return web.json_response({"error": err.message}, status=err.status_code)

    service: WikiService = request.app[WIKI_SERVICE_KEY]
    try:
        issue = await service.resolve_lint_issue(
            user_id, issue_id, status=req_dto.status
        )
    except ValueError as err:
        return web.json_response({"error": str(err)}, status=400)
    except WikiNotFoundError as err:
        return web.json_response({"error": str(err)}, status=404)
    return web.json_response(WikiLintIssueResponseVO(issue=issue).to_dict())


@routes.get("/api/extended/wiki/export.zip")
async def handle_export_wiki_zip(request: web.Request) -> web.Response:
    """Stream an Obsidian-compatible `.zip` vault of all active wiki pages."""
    if (user_id := await _resolve_user_id(request)) is None:
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
    if (user_id := await _resolve_user_id(request)) is None:
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
