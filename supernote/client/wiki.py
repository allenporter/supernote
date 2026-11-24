"""Client for the Supernote Private Cloud LLM Wiki API (`/api/extended/wiki/*`)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from supernote.models.wiki import (
    WikiCompileResponseVO,
    WikiDeleteResponseVO,
    WikiLintIssueDTO,
    WikiLintIssueResponseVO,
    WikiLintListVO,
    WikiPageDTO,
    WikiPageListVO,
    WikiPageResponseVO,
    WikiRevisionDTO,
    WikiRevisionsResponseVO,
    WikiSearchHitDTO,
    WikiSearchResponseVO,
    WikiSourceRefDTO,
    WikiStatusDTO,
    WikiStatusResponseVO,
)

from .client import Client
from .exceptions import ApiException

__all__ = ["WikiClient"]


def _encode_slug(slug: str) -> str:
    """Validate and percent-encode a wiki slug for safe URL path interpolation."""
    cleaned = slug.strip().strip("/")
    if not cleaned:
        raise ValueError("Wiki slug must be non-empty")
    segments = cleaned.split("/")
    for seg in segments:
        if seg in ("", ".", ".."):
            raise ValueError(f"Invalid wiki slug segment {seg!r} in {slug!r}")
    return "/".join(quote(seg, safe="") for seg in segments)


class WikiClient:
    """Typed client for per-user LLM Wiki CRUD, search, lint, compile, and export."""

    def __init__(self, client: Client) -> None:
        self._client = client

    async def list_pages(
        self,
        *,
        page_kind: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WikiPageDTO]:
        """List active wiki pages (`GET /api/extended/wiki/pages`)."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if page_kind is not None:
            params["page_kind"] = page_kind
        vo = await self._client.get_json(
            "/api/extended/wiki/pages", WikiPageListVO, params=params
        )
        return vo.pages

    async def get_page(self, slug: str) -> WikiPageDTO:
        """Fetch a single wiki page by slug (`GET /api/extended/wiki/pages/{slug}`)."""
        vo = await self._client.get_json(
            f"/api/extended/wiki/pages/{_encode_slug(slug)}", WikiPageResponseVO
        )
        if vo.page is None:
            raise ApiException("Server returned empty wiki page payload")
        return vo.page

    async def upsert_page(
        self,
        slug: str,
        *,
        title: str,
        body_md: str = "",
        page_kind: str = "topic",
        summary: str = "",
        aliases: list[str] | None = None,
        claims: list[dict[str, Any]] | None = None,
        source_refs: list[WikiSourceRefDTO] | None = None,
        change_summary: str = "",
        expected_version: int | None = None,
        edit_policy: str | None = None,
    ) -> WikiPageDTO:
        """Create or update a wiki page (`PUT /api/extended/wiki/pages/{slug}`)."""
        payload: dict[str, Any] = {
            "title": title,
            "body_md": body_md,
            "page_kind": page_kind,
            "summary": summary,
            "change_summary": change_summary,
        }
        if aliases is not None:
            payload["aliases"] = aliases
        if claims is not None:
            payload["claims"] = claims
        if source_refs is not None:
            payload["source_refs"] = [r.to_dict() for r in source_refs]
        if expected_version is not None:
            payload["expected_version"] = expected_version
        if edit_policy is not None:
            payload["edit_policy"] = edit_policy
        vo = await self._client.put_json(
            f"/api/extended/wiki/pages/{_encode_slug(slug)}",
            WikiPageResponseVO,
            json=payload,
        )
        if vo.page is None:
            raise ApiException("Server returned empty wiki page payload")
        return vo.page

    async def delete_page(self, slug: str) -> bool:
        """Soft-delete a wiki page (`DELETE /api/extended/wiki/pages/{slug}`)."""
        vo = await self._client.delete_json(
            f"/api/extended/wiki/pages/{_encode_slug(slug)}", WikiDeleteResponseVO
        )
        return vo.deleted

    async def list_revisions(self, slug: str) -> list[WikiRevisionDTO]:
        """List immutable revisions (`GET /api/extended/wiki/revisions/{slug}`)."""
        vo = await self._client.get_json(
            f"/api/extended/wiki/revisions/{_encode_slug(slug)}",
            WikiRevisionsResponseVO,
        )
        return vo.revisions

    async def search(self, query: str, *, top_k: int = 10) -> list[WikiSearchHitDTO]:
        """Search wiki pages (`GET /api/extended/wiki/search`)."""
        vo = await self._client.get_json(
            "/api/extended/wiki/search",
            WikiSearchResponseVO,
            params={"q": query, "top_k": top_k},
        )
        return vo.hits

    async def get_status(self) -> WikiStatusDTO:
        """Fetch wiki status (`GET /api/extended/wiki/status`)."""
        vo = await self._client.get_json(
            "/api/extended/wiki/status", WikiStatusResponseVO
        )
        if vo.status is None:
            raise ApiException("Server returned empty wiki status payload")
        return vo.status

    async def compile(
        self,
        *,
        mode: str = "incremental",
        max_files: int | None = None,
    ) -> WikiCompileResponseVO:
        """Trigger incremental compile, backfill, or lint (`POST /api/extended/wiki/compile`)."""
        payload: dict[str, Any] = {"mode": mode}
        if max_files is not None:
            payload["max_files"] = max_files
        return await self._client.post_json(
            "/api/extended/wiki/compile", WikiCompileResponseVO, json=payload
        )

    async def list_lint_issues(self, *, status: str = "open") -> list[WikiLintIssueDTO]:
        """List wiki lint issues (`GET /api/extended/wiki/lint`)."""
        vo = await self._client.get_json(
            "/api/extended/wiki/lint",
            WikiLintListVO,
            params={"status": status},
        )
        return vo.issues

    async def resolve_lint_issue(
        self, issue_id: int, *, status: str = "resolved"
    ) -> WikiLintIssueDTO:
        """Resolve or dismiss a lint issue (`POST /api/extended/wiki/lint/{issue_id}/resolve`)."""
        vo = await self._client.post_json(
            f"/api/extended/wiki/lint/{issue_id}/resolve",
            WikiLintIssueResponseVO,
            json={"status": status},
        )
        if vo.issue is None:
            raise ApiException("Server returned empty wiki lint issue payload")
        return vo.issue

    async def export_markdown(self, slug: str) -> str:
        """Export one wiki page as Obsidian Markdown (`GET /api/extended/wiki/export/{slug}.md`)."""
        raw = await self._client.get_content(
            f"/api/extended/wiki/export/{_encode_slug(slug)}.md"
        )
        return raw.decode("utf-8")

    async def export_zip(self) -> bytes:
        """Export the full wiki vault as ZIP bytes (`GET /api/extended/wiki/export.zip`)."""
        return await self._client.get_content("/api/extended/wiki/export.zip")
