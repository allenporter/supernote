"""Obsidian-compatible Markdown and ZIP vault export service (`WikiExportService`)."""

from __future__ import annotations

import io
import zipfile
from typing import Any

import yaml
from aiohttp import web

from .models import WikiNotFoundError, WikiPageDTO, normalize_slug
from .service import WikiService

__all__ = [
    "WIKI_EXPORT_SERVICE_KEY",
    "WikiExportService",
    "render_page_markdown",
]

_EXPORT_BATCH_SIZE = 200


def render_page_markdown(page: WikiPageDTO) -> str:
    """Render a `WikiPageDTO` as Obsidian-compatible Markdown with YAML frontmatter."""
    frontmatter: dict[str, Any] = {
        "wiki_id": page.page_id,
        "slug": page.slug,
        "title": page.title,
        "page_kind": page.page_kind,
        "version": page.version,
        "edit_policy": page.edit_policy,
        "updated_at": page.update_time,
    }
    if page.aliases:
        frontmatter["aliases"] = list(page.aliases)
    if page.source_refs:
        frontmatter["sources"] = [
            f"{ref.source_type}:{ref.source_key}" for ref in page.source_refs
        ]
    header = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    body = page.body_md.rstrip()
    return f"---\n{header}\n---\n\n{body}\n" if body else f"---\n{header}\n---\n"


class WikiExportService:
    """Streams per-user Obsidian Markdown and `.zip` vaults directly from `WikiService`."""

    def __init__(self, wiki_service: WikiService) -> None:
        self._wiki_service = wiki_service

    async def export_page_markdown(self, user_id: int, slug: str) -> str:
        """Export one active wiki page as Obsidian-compatible Markdown."""
        page = await self._wiki_service.get_page(user_id, slug)
        if page is None:
            raise WikiNotFoundError(f"Wiki page {slug!r} not found")
        return render_page_markdown(page)

    async def export_vault_zip(self, user_id: int) -> bytes:
        """Build an in-memory `.zip` archive of all active wiki pages for `user_id`."""
        pages: list[WikiPageDTO] = []
        offset = 0
        while True:
            batch = await self._wiki_service.list_pages(
                user_id, limit=_EXPORT_BATCH_SIZE, offset=offset
            )
            pages.extend(batch)
            if len(batch) < _EXPORT_BATCH_SIZE:
                break
            offset += len(batch)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for page in sorted(pages, key=lambda p: p.slug):
                safe_slug = normalize_slug(page.slug)
                zf.writestr(f"{safe_slug}.md", render_page_markdown(page))
        return buf.getvalue()


WIKI_EXPORT_SERVICE_KEY: web.AppKey[WikiExportService] = web.AppKey(
    "wiki_export_service"
)
