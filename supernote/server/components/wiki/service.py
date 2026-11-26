"""Transport-free domain service for per-user LLM Wiki storage, search, and lint."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Collection, Sequence

from aiohttp import web
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.models.wiki import WikiSourceType
from supernote.server.db.models.wiki import (
    WikiAliasDO,
    WikiCheckpointDO,
    WikiLinkDO,
    WikiLintIssueDO,
    WikiPageDO,
    WikiRevisionDO,
    WikiSourceRefDO,
)
from supernote.server.db.session import DatabaseSessionManager

from .models import (
    VALID_AUTHOR_KINDS,
    VALID_EDIT_POLICIES,
    VALID_PAGE_KINDS,
    WikiConflictError,
    WikiLintIssueDTO,
    WikiNotFoundError,
    WikiPageDTO,
    WikiPolicyError,
    WikiRevisionDTO,
    WikiSearchHitDTO,
    WikiSourceRefDTO,
    WikiStatusDTO,
    WikiUpsertInput,
    extract_wikilinks,
    normalize_alias,
    normalize_slug,
)
from .source_service import WikiSourceService

__all__ = [
    "WIKI_SERVICE_KEY",
    "WikiService",
]

_MAX_DEDUP_KEY_LEN = 191


def _now_ms() -> int:
    return int(time.time() * 1000)


def _make_dedup_key(raw_key: str) -> str:
    """Return a deterministic lint dedup key bounded to `VARCHAR(191)`."""
    if len(raw_key) <= _MAX_DEDUP_KEY_LEN:
        return raw_key
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:32]
    prefix = raw_key[: _MAX_DEDUP_KEY_LEN - len(digest) - 1]
    return f"{prefix}:{digest}"


class WikiService:
    """Multi-user CRUD, graph indexing, lexical search, and structural lint for `f_wiki_*`."""

    def __init__(
        self,
        session_manager: DatabaseSessionManager,
        source_service: WikiSourceService | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._source_service = source_service or WikiSourceService(session_manager)

    async def upsert_page(self, user_id: int, data: WikiUpsertInput) -> WikiPageDTO:
        """Create, update, or revive a wiki page atomically with revision and graph updates."""
        slug = normalize_slug(data.slug)
        if not data.title.strip():
            raise ValueError("Wiki page title must be non-empty")
        if data.author_kind not in VALID_AUTHOR_KINDS:
            raise ValueError(f"Unsupported author_kind: {data.author_kind!r}")
        if data.page_kind not in VALID_PAGE_KINDS:
            raise ValueError(f"Unsupported page_kind: {data.page_kind!r}")
        if data.edit_policy is not None and data.edit_policy not in VALID_EDIT_POLICIES:
            raise ValueError(f"Unsupported edit_policy: {data.edit_policy!r}")
        if data.author_kind != "user" and data.edit_policy is not None:
            raise WikiPolicyError(
                f"Non-user author {data.author_kind!r} cannot set edit_policy"
            )

        now = _now_ms()
        default_policy = "protected_prose" if data.author_kind == "user" else "auto"
        async with self._session_manager.session() as session:
            existing = (
                await session.execute(
                    select(WikiPageDO).where(
                        WikiPageDO.user_id == user_id,
                        WikiPageDO.slug == slug,
                    )
                )
            ).scalar_one_or_none()

            if existing is None:
                if data.expected_version is not None and data.expected_version != 0:
                    raise WikiConflictError(slug, data.expected_version, 0)
                page = WikiPageDO(
                    user_id=user_id,
                    slug=slug,
                    title=data.title.strip()[:255],
                    page_kind=data.page_kind,
                    summary=data.summary[:512],
                    body_md=data.body_md,
                    claims_json=list(data.claims),
                    edit_policy=data.edit_policy or default_policy,
                    last_author_kind=data.author_kind,
                    version=1,
                    is_deleted=False,
                    create_time=now,
                    update_time=now,
                )
                session.add(page)
                await session.flush()
            elif existing.is_deleted:
                # Tombstone revival: treat as a fresh creation for expected_version and policy.
                if data.expected_version is not None and data.expected_version != 0:
                    raise WikiConflictError(slug, data.expected_version, 0)
                page = existing
                page.title = data.title.strip()[:255]
                page.page_kind = data.page_kind
                page.summary = data.summary[:512]
                page.body_md = data.body_md
                page.claims_json = list(data.claims)
                page.edit_policy = data.edit_policy or default_policy
                page.last_author_kind = data.author_kind
                page.is_deleted = False
                page.version += 1
                page.update_time = now
            else:
                if (
                    data.expected_version is not None
                    and data.expected_version != existing.version
                ):
                    raise WikiConflictError(
                        slug, data.expected_version, existing.version
                    )
                if data.author_kind != "user":
                    if existing.edit_policy == "locked":
                        raise WikiPolicyError(f"Wiki page {slug!r} is locked")
                    if existing.edit_policy == "protected_prose":
                        raise WikiPolicyError(
                            f"Wiki page {slug!r} has protected_prose policy"
                        )
                page = existing
                page.title = data.title.strip()[:255]
                page.page_kind = data.page_kind
                page.summary = data.summary[:512]
                page.body_md = data.body_md
                page.claims_json = list(data.claims)
                page.last_author_kind = data.author_kind
                page.version += 1
                page.update_time = now
                if data.edit_policy is not None and data.author_kind == "user":
                    page.edit_policy = data.edit_policy
                elif data.author_kind == "user" and page.edit_policy == "auto":
                    page.edit_policy = "protected_prose"

            session.add(
                WikiRevisionDO(
                    user_id=user_id,
                    page_id=page.page_id,
                    revision_no=page.version,
                    title=page.title,
                    body_md=page.body_md,
                    claims_json=list(page.claims_json),
                    author_kind=data.author_kind,
                    author_ref=data.author_ref[:128] if data.author_ref else None,
                    change_summary=data.change_summary[:512],
                    source_event_seq=data.source_event_seq,
                    create_time=now,
                )
            )

            await self._sync_links(session, user_id, page, now)
            await self._sync_aliases(session, user_id, page.page_id, data, now)
            await self._sync_source_refs(
                session, user_id, page.page_id, data.source_refs, now
            )
            await session.commit()
            return (await self._hydrate_pages(session, user_id, [page]))[0]

    async def get_page(self, user_id: int, slug: str) -> WikiPageDTO | None:
        """Return an active wiki page with aliases, links, backlinks, and source refs."""
        canonical = normalize_slug(slug)
        async with self._session_manager.session() as session:
            page = (
                await session.execute(
                    select(WikiPageDO).where(
                        WikiPageDO.user_id == user_id,
                        WikiPageDO.slug == canonical,
                        WikiPageDO.is_deleted.is_(False),
                    )
                )
            ).scalar_one_or_none()
            if page is None:
                return None
            hydrated = (await self._hydrate_pages(session, user_id, [page]))[0]
        if hydrated.source_refs:
            meta_map = await self._source_service.resolve_source_metadata(
                user_id, hydrated.source_refs
            )
            for ref in hydrated.source_refs:
                if meta := meta_map.get((ref.source_type, ref.source_key)):
                    ref.file_name = meta.file_name
                    ref.page_index = meta.page_index
                    ref.task_title = meta.task_title
        return hydrated

    async def list_pages(
        self,
        user_id: int,
        *,
        page_kind: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WikiPageDTO]:
        """List active wiki pages for a user ordered by most recently updated."""
        stmt = select(WikiPageDO).where(
            WikiPageDO.user_id == user_id,
            WikiPageDO.is_deleted.is_(False),
        )
        if page_kind is not None:
            stmt = stmt.where(WikiPageDO.page_kind == page_kind)
        stmt = (
            stmt.order_by(WikiPageDO.update_time.desc(), WikiPageDO.slug.asc())
            .limit(max(1, min(limit, 500)))
            .offset(max(0, offset))
        )
        async with self._session_manager.session() as session:
            rows = list((await session.execute(stmt)).scalars().all())
            return await self._hydrate_pages(session, user_id, rows)

    async def delete_page(self, user_id: int, slug: str) -> None:
        """Soft-delete a wiki page tombstone, clearing links, aliases, and source refs."""
        canonical = normalize_slug(slug)
        now = _now_ms()
        async with self._session_manager.session() as session:
            page = (
                await session.execute(
                    select(WikiPageDO).where(
                        WikiPageDO.user_id == user_id,
                        WikiPageDO.slug == canonical,
                        WikiPageDO.is_deleted.is_(False),
                    )
                )
            ).scalar_one_or_none()
            if page is None:
                raise WikiNotFoundError(f"Wiki page {canonical!r} not found")

            page.is_deleted = True
            page.version += 1
            page.update_time = now
            await session.execute(
                delete(WikiLinkDO).where(
                    WikiLinkDO.user_id == user_id,
                    WikiLinkDO.from_page_id == page.page_id,
                )
            )
            await session.execute(
                update(WikiLinkDO)
                .where(
                    WikiLinkDO.user_id == user_id,
                    WikiLinkDO.target_page_id == page.page_id,
                )
                .values(target_page_id=None, update_time=now)
            )
            await session.execute(
                delete(WikiAliasDO).where(
                    WikiAliasDO.user_id == user_id,
                    WikiAliasDO.page_id == page.page_id,
                )
            )
            await session.execute(
                delete(WikiSourceRefDO).where(
                    WikiSourceRefDO.user_id == user_id,
                    WikiSourceRefDO.page_id == page.page_id,
                )
            )
            await session.commit()

        if canonical != "index":
            existing_index = await self.get_page(user_id, "index")
            if existing_index is not None and existing_index.edit_policy == "auto":
                await self.sync_index_page(user_id)

    async def list_revisions(
        self, user_id: int, slug: str, *, limit: int = 50
    ) -> list[WikiRevisionDTO]:
        """Return immutable revisions for a slug in descending revision order."""
        canonical = normalize_slug(slug)
        async with self._session_manager.session() as session:
            page = (
                await session.execute(
                    select(WikiPageDO).where(
                        WikiPageDO.user_id == user_id,
                        WikiPageDO.slug == canonical,
                    )
                )
            ).scalar_one_or_none()
            if page is None:
                raise WikiNotFoundError(f"Wiki page {canonical!r} not found")
            rows = (
                (
                    await session.execute(
                        select(WikiRevisionDO)
                        .where(
                            WikiRevisionDO.user_id == user_id,
                            WikiRevisionDO.page_id == page.page_id,
                        )
                        .order_by(WikiRevisionDO.revision_no.desc())
                        .limit(max(1, min(limit, 200)))
                    )
                )
                .scalars()
                .all()
            )
            return [
                WikiRevisionDTO(
                    revision_id=r.revision_id,
                    page_id=r.page_id,
                    revision_no=r.revision_no,
                    title=r.title,
                    body_md=r.body_md,
                    claims=list(r.claims_json),
                    author_kind=r.author_kind,
                    author_ref=r.author_ref,
                    change_summary=r.change_summary,
                    source_event_seq=r.source_event_seq,
                    create_time=r.create_time,
                )
                for r in rows
            ]

    async def search_pages(
        self, user_id: int, query: str, *, top_k: int = 10
    ) -> list[WikiSearchHitDTO]:
        """Pure-ORM lexical and alias search returning ranked hits with 1-hop links and source refs."""
        tokens = [t for t in query.lower().split() if t]
        if not tokens:
            return []

        async with self._session_manager.session() as session:
            pages = (
                (
                    await session.execute(
                        select(WikiPageDO).where(
                            WikiPageDO.user_id == user_id,
                            WikiPageDO.is_deleted.is_(False),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not pages:
                return []

            aliases_by_page: dict[int, list[str]] = {}
            for alias_row in (
                (
                    await session.execute(
                        select(WikiAliasDO).where(WikiAliasDO.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            ):
                aliases_by_page.setdefault(alias_row.page_id, []).append(
                    alias_row.normalized_alias
                )

            scored: list[tuple[float, WikiPageDO]] = []
            for page in pages:
                score = _score_page(page, aliases_by_page.get(page.page_id, ()), tokens)
                if score > 0:
                    scored.append((score, page))

            scored.sort(key=lambda item: (-item[0], -item[1].update_time, item[1].slug))
            top_items = scored[: max(1, min(top_k, 50))]
            if not top_items:
                return []

            page_ids = [p.page_id for _, p in top_items]
            links = (
                (
                    await session.execute(
                        select(WikiLinkDO).where(
                            WikiLinkDO.user_id == user_id,
                            WikiLinkDO.from_page_id.in_(page_ids),
                        )
                    )
                )
                .scalars()
                .all()
            )
            neighbors_by_page: dict[int, list[str]] = {}
            for link in links:
                neighbors_by_page.setdefault(link.from_page_id, []).append(
                    link.target_slug
                )

            refs = (
                (
                    await session.execute(
                        select(WikiSourceRefDO).where(
                            WikiSourceRefDO.user_id == user_id,
                            WikiSourceRefDO.page_id.in_(page_ids),
                        )
                    )
                )
                .scalars()
                .all()
            )
            refs_by_page: dict[int, list[WikiSourceRefDTO]] = {}
            for ref in refs:
                refs_by_page.setdefault(ref.page_id, []).append(
                    WikiSourceRefDTO(
                        source_type=WikiSourceType(ref.source_type),
                        source_key=ref.source_key,
                        file_id=ref.file_id,
                        last_event_seq=ref.last_event_seq,
                        is_source_deleted=ref.is_source_deleted,
                    )
                )

            return [
                WikiSearchHitDTO(
                    slug=page.slug,
                    title=page.title,
                    page_kind=page.page_kind,
                    summary=page.summary,
                    score=score,
                    neighbor_slugs=sorted(set(neighbors_by_page.get(page.page_id, []))),
                    source_refs=refs_by_page.get(page.page_id, []),
                )
                for score, page in top_items
            ]

    async def run_structural_lint(self, user_id: int) -> list[WikiLintIssueDTO]:
        """Run zero-LLM SQL structural lint (broken links, orphan pages, stale sources)."""
        now = _now_ms()
        async with self._session_manager.session() as session:
            active_pages = (
                (
                    await session.execute(
                        select(WikiPageDO).where(
                            WikiPageDO.user_id == user_id,
                            WikiPageDO.is_deleted.is_(False),
                        )
                    )
                )
                .scalars()
                .all()
            )
            page_by_id = {p.page_id: p for p in active_pages}
            all_links = (
                (
                    await session.execute(
                        select(WikiLinkDO).where(WikiLinkDO.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
            deleted_refs = (
                (
                    await session.execute(
                        select(WikiSourceRefDO).where(
                            WikiSourceRefDO.user_id == user_id,
                            WikiSourceRefDO.is_source_deleted.is_(True),
                        )
                    )
                )
                .scalars()
                .all()
            )

            desired: dict[str, tuple[str, str, int | None, str]] = {}
            inbound_targets: set[int] = set()
            for link in all_links:
                if (
                    link.target_page_id is not None
                    and link.from_page_id != link.target_page_id
                    and link.from_page_id in page_by_id
                    and page_by_id[link.from_page_id].page_kind not in ("index", "log")
                ):
                    inbound_targets.add(link.target_page_id)
                elif link.target_page_id is None and link.from_page_id in page_by_id:
                    dedup_key = _make_dedup_key(
                        f"broken_link:{link.from_page_id}:{link.target_slug}"
                    )
                    desired[dedup_key] = (
                        "broken_link",
                        "warn",
                        link.from_page_id,
                        f"Page {page_by_id[link.from_page_id].slug!r} links to missing page {link.target_slug!r}.",
                    )

            for page in active_pages:
                if page.page_kind in ("index", "log"):
                    continue
                if page.page_id not in inbound_targets:
                    dedup_key = _make_dedup_key(f"orphan_page:{page.page_id}")
                    desired[dedup_key] = (
                        "orphan_page",
                        "info",
                        page.page_id,
                        f"Page {page.slug!r} has no inbound wikilinks.",
                    )

            for ref in deleted_refs:
                if ref.page_id in page_by_id:
                    dedup_key = _make_dedup_key(
                        f"stale_source:{ref.page_id}:{ref.source_type}:{ref.source_key}"
                    )
                    desired[dedup_key] = (
                        "stale_source",
                        "warn",
                        ref.page_id,
                        f"Page {page_by_id[ref.page_id].slug!r} cites deleted {ref.source_type} {ref.source_key!r}.",
                    )

            existing_issues = (
                (
                    await session.execute(
                        select(WikiLintIssueDO).where(
                            WikiLintIssueDO.user_id == user_id,
                            WikiLintIssueDO.issue_type.in_(
                                ("broken_link", "orphan_page", "stale_source")
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            existing_by_key = {issue.dedup_key: issue for issue in existing_issues}

            for key, (issue_type, severity, page_id, desc) in desired.items():
                if existing := existing_by_key.get(key):
                    existing.description = desc
                    existing.severity = severity
                    if existing.status == "resolved":
                        existing.status = "open"
                    existing.update_time = now
                else:
                    session.add(
                        WikiLintIssueDO(
                            user_id=user_id,
                            dedup_key=key,
                            issue_type=issue_type,
                            severity=severity,
                            page_id=page_id,
                            description=desc,
                            status="open",
                            create_time=now,
                            update_time=now,
                        )
                    )

            for key, issue in existing_by_key.items():
                if key not in desired and issue.status == "open":
                    issue.status = "resolved"
                    issue.update_time = now

            await session.commit()

        return await self.list_lint_issues(user_id, status="open")

    async def list_lint_issues(
        self, user_id: int, *, status: str | None = "open"
    ) -> list[WikiLintIssueDTO]:
        """List lint issues for a user filtered optionally by triage status."""
        stmt = select(WikiLintIssueDO).where(WikiLintIssueDO.user_id == user_id)
        if status is not None:
            stmt = stmt.where(WikiLintIssueDO.status == status)
        stmt = stmt.order_by(WikiLintIssueDO.update_time.desc())
        async with self._session_manager.session() as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [_to_lint_dto(row) for row in rows]

    async def resolve_lint_issue(
        self, user_id: int, issue_id: int, *, status: str = "resolved"
    ) -> WikiLintIssueDTO:
        """Mark a lint issue `resolved` or `dismissed`."""
        if status not in ("resolved", "dismissed"):
            raise ValueError(f"Unsupported lint resolution status: {status!r}")
        async with self._session_manager.session() as session:
            issue = (
                await session.execute(
                    select(WikiLintIssueDO).where(
                        WikiLintIssueDO.user_id == user_id,
                        WikiLintIssueDO.issue_id == issue_id,
                    )
                )
            ).scalar_one_or_none()
            if issue is None:
                raise WikiNotFoundError(f"Lint issue {issue_id} not found")
            issue.status = status
            issue.update_time = _now_ms()
            await session.commit()
            return _to_lint_dto(issue)

    async def mark_sources_deleted(
        self,
        user_id: int,
        *,
        file_ids: Collection[int] = (),
        note_page_keys: Collection[str] = (),
        task_ids: Collection[str] = (),
    ) -> None:
        """Flag `f_wiki_source_ref` rows citing deleted files, note pages, or tasks."""
        if not (file_ids or note_page_keys or task_ids):
            return
        now = _now_ms()
        async with self._session_manager.session() as session:
            if file_ids:
                await session.execute(
                    update(WikiSourceRefDO)
                    .where(
                        WikiSourceRefDO.user_id == user_id,
                        WikiSourceRefDO.file_id.in_(file_ids),
                    )
                    .values(is_source_deleted=True, update_time=now)
                )
            if note_page_keys:
                await session.execute(
                    update(WikiSourceRefDO)
                    .where(
                        WikiSourceRefDO.user_id == user_id,
                        WikiSourceRefDO.source_type == "note_page",
                        WikiSourceRefDO.source_key.in_(note_page_keys),
                    )
                    .values(is_source_deleted=True, update_time=now)
                )
            if task_ids:
                await session.execute(
                    update(WikiSourceRefDO)
                    .where(
                        WikiSourceRefDO.user_id == user_id,
                        WikiSourceRefDO.source_type == "schedule_task",
                        WikiSourceRefDO.source_key.in_(task_ids),
                    )
                    .values(is_source_deleted=True, update_time=now)
                )
            await session.commit()

    async def get_status(self, user_id: int) -> WikiStatusDTO:
        """Return inventory counts and durable checkpoint state for a user."""
        async with self._session_manager.session() as session:
            page_count = (
                await session.execute(
                    select(func.count())
                    .select_from(WikiPageDO)
                    .where(
                        WikiPageDO.user_id == user_id,
                        WikiPageDO.is_deleted.is_(False),
                    )
                )
            ).scalar_one()
            open_lint_count = (
                await session.execute(
                    select(func.count())
                    .select_from(WikiLintIssueDO)
                    .where(
                        WikiLintIssueDO.user_id == user_id,
                        WikiLintIssueDO.status == "open",
                    )
                )
            ).scalar_one()
            cp = (
                await session.execute(
                    select(WikiCheckpointDO).where(WikiCheckpointDO.user_id == user_id)
                )
            ).scalar_one_or_none()
        overview = await self._source_service.get_backfill_overview(
            user_id,
            before_file_id=cp.backfill_file_cursor if cp else None,
        )
        return WikiStatusDTO(
            page_count=int(page_count),
            open_lint_count=int(open_lint_count),
            last_sync_token=cp.last_sync_token if cp else None,
            pending_events_since_lint=cp.pending_events_since_lint if cp else 0,
            tokens_used_day=cp.tokens_used_day if cp else 0,
            budget_day_utc=cp.budget_day_utc if cp else None,
            status=cp.status if cp else "idle",
            last_error=cp.last_error if cp else None,
            backfill_remaining_files=overview.remaining_files,
            backfill_total_files=overview.total_files,
            backfill_remaining_pages=overview.remaining_pages,
            backfill_total_pages=overview.total_pages,
            backfill_untranscribed_files=overview.untranscribed_files,
            backfill_next_files=overview.next_files,
        )

    async def sync_index_page(self, user_id: int) -> WikiPageDTO | None:
        """Deterministically maintain the root `index` hub page from active wiki pages.

        Skips updates when the user has protected or locked `index`, when no
        non-index/log pages exist, or when the rendered Markdown is unchanged.
        """
        pages = await self.list_pages(user_id, limit=500)
        existing_index = next((p for p in pages if p.slug == "index"), None)
        if existing_index is not None and existing_index.edit_policy in (
            "protected_prose",
            "locked",
        ):
            return existing_index

        indexed = [p for p in pages if p.page_kind not in ("index", "log")]
        if not indexed:
            return None

        sections: tuple[tuple[str, str], ...] = (
            ("project", "Projects"),
            ("entity", "Entities"),
            ("topic", "Topics"),
            ("source_digest", "Sources"),
        )
        lines: list[str] = [
            "# Wiki Index",
            "",
            "Automatically maintained catalog of compiled wiki pages.",
        ]
        for kind, heading in sections:
            group = sorted(
                (p for p in indexed if p.page_kind == kind),
                key=lambda p: (p.title.lower(), p.slug),
            )
            if not group:
                continue
            lines.extend(["", f"## {heading}"])
            for p in group:
                summary = p.summary.strip()
                if summary:
                    lines.append(f"- [[{p.slug}]] — {summary}")
                else:
                    lines.append(f"- [[{p.slug}]]")

        body_md = "\n".join(lines)
        summary = f"Catalog of {len(indexed)} wiki {'page' if len(indexed) == 1 else 'pages'}."
        if (
            existing_index is not None
            and existing_index.body_md == body_md
            and existing_index.summary == summary
        ):
            return existing_index

        return await self.upsert_page(
            user_id,
            WikiUpsertInput(
                slug="index",
                title="Wiki Index",
                page_kind="index",
                summary=summary,
                body_md=body_md,
                author_kind="compiler",
                author_ref="system:wiki",
                change_summary="Auto-updated Wiki Index",
            ),
        )

    async def delete_user_wiki(self, user_id: int) -> None:
        """Delete all `f_wiki_*` rows belonging to `user_id` (account deletion hook)."""
        async with self._session_manager.session() as session:
            for model in (
                WikiLintIssueDO,
                WikiCheckpointDO,
                WikiSourceRefDO,
                WikiLinkDO,
                WikiAliasDO,
                WikiRevisionDO,
                WikiPageDO,
            ):
                await session.execute(delete(model).where(model.user_id == user_id))
            await session.commit()

    async def _sync_links(
        self, session: AsyncSession, user_id: int, page: WikiPageDO, now: int
    ) -> None:
        await session.execute(
            delete(WikiLinkDO).where(
                WikiLinkDO.user_id == user_id,
                WikiLinkDO.from_page_id == page.page_id,
            )
        )
        extracted = extract_wikilinks(page.body_md)
        if extracted:
            target_slugs = [slug for slug, _ in extracted]
            targets = {
                row.slug: row.page_id
                for row in (
                    await session.execute(
                        select(WikiPageDO).where(
                            WikiPageDO.user_id == user_id,
                            WikiPageDO.slug.in_(target_slugs),
                            WikiPageDO.is_deleted.is_(False),
                        )
                    )
                )
                .scalars()
                .all()
            }
            for target_slug, label in extracted:
                session.add(
                    WikiLinkDO(
                        user_id=user_id,
                        from_page_id=page.page_id,
                        target_slug=target_slug,
                        target_page_id=targets.get(target_slug),
                        link_label=label[:255] if label else None,
                        update_time=now,
                    )
                )
        # Back-resolve any previously broken inbound links now pointing to this page.
        await session.execute(
            update(WikiLinkDO)
            .where(
                WikiLinkDO.user_id == user_id,
                WikiLinkDO.target_slug == page.slug,
            )
            .values(target_page_id=page.page_id, update_time=now)
        )

    async def _sync_aliases(
        self,
        session: AsyncSession,
        user_id: int,
        page_id: int,
        data: WikiUpsertInput,
        now: int,
    ) -> None:
        if not data.aliases:
            return
        deduped: dict[str, str] = {}
        for raw_alias in data.aliases:
            norm = normalize_alias(raw_alias)[:255]
            if norm not in deduped:
                deduped[norm] = raw_alias.strip()[:255]

        origin = "user" if data.author_kind == "user" else "compiler"
        for norm, display_text in deduped.items():
            existing = (
                await session.execute(
                    select(WikiAliasDO).where(
                        WikiAliasDO.user_id == user_id,
                        WikiAliasDO.normalized_alias == norm,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    WikiAliasDO(
                        user_id=user_id,
                        page_id=page_id,
                        alias_text=display_text,
                        normalized_alias=norm,
                        origin=origin,
                        create_time=now,
                    )
                )
            elif existing.page_id != page_id:
                if data.author_kind == "user":
                    existing.page_id = page_id
                    existing.alias_text = display_text
                    existing.origin = "user"
                else:
                    raise WikiPolicyError(
                        f"Alias {display_text!r} is already owned by another page"
                    )

    async def _sync_source_refs(
        self,
        session: AsyncSession,
        user_id: int,
        page_id: int,
        refs: list[WikiSourceRefDTO],
        now: int,
    ) -> None:
        if not refs:
            return
        for ref in refs:
            existing = (
                await session.execute(
                    select(WikiSourceRefDO).where(
                        WikiSourceRefDO.user_id == user_id,
                        WikiSourceRefDO.page_id == page_id,
                        WikiSourceRefDO.source_type == ref.source_type,
                        WikiSourceRefDO.source_key == ref.source_key,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    WikiSourceRefDO(
                        user_id=user_id,
                        page_id=page_id,
                        source_type=ref.source_type,
                        source_key=ref.source_key,
                        file_id=ref.file_id,
                        last_event_seq=ref.last_event_seq,
                        is_source_deleted=ref.is_source_deleted,
                        update_time=now,
                    )
                )
            else:
                existing.file_id = ref.file_id
                existing.last_event_seq = ref.last_event_seq
                existing.is_source_deleted = (
                    existing.is_source_deleted or ref.is_source_deleted
                )
                existing.update_time = now

    async def _hydrate_pages(
        self, session: AsyncSession, user_id: int, pages: Sequence[WikiPageDO]
    ) -> list[WikiPageDTO]:
        """Batch-hydrate aliases, outbound links, backlinks, and source refs in O(1) queries."""
        if not pages:
            return []
        page_ids = [p.page_id for p in pages]

        aliases_by_page: dict[int, list[str]] = {}
        for alias_row in (
            (
                await session.execute(
                    select(WikiAliasDO)
                    .where(
                        WikiAliasDO.user_id == user_id,
                        WikiAliasDO.page_id.in_(page_ids),
                    )
                    .order_by(WikiAliasDO.alias_text.asc())
                )
            )
            .scalars()
            .all()
        ):
            aliases_by_page.setdefault(alias_row.page_id, []).append(
                alias_row.alias_text
            )

        outbound_by_page: dict[int, list[str]] = {}
        for link_row in (
            (
                await session.execute(
                    select(WikiLinkDO)
                    .where(
                        WikiLinkDO.user_id == user_id,
                        WikiLinkDO.from_page_id.in_(page_ids),
                    )
                    .order_by(WikiLinkDO.target_slug.asc())
                )
            )
            .scalars()
            .all()
        ):
            outbound_by_page.setdefault(link_row.from_page_id, []).append(
                link_row.target_slug
            )

        inbound_rows = (
            (
                await session.execute(
                    select(WikiLinkDO).where(
                        WikiLinkDO.user_id == user_id,
                        WikiLinkDO.target_page_id.in_(page_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        backlinks_by_page: dict[int, list[str]] = {}
        if inbound_rows:
            from_ids = {r.from_page_id for r in inbound_rows}
            slug_by_id = {
                row.page_id: row.slug
                for row in (
                    await session.execute(
                        select(WikiPageDO).where(
                            WikiPageDO.user_id == user_id,
                            WikiPageDO.page_id.in_(from_ids),
                            WikiPageDO.is_deleted.is_(False),
                        )
                    )
                )
                .scalars()
                .all()
            }
            for r in inbound_rows:
                if r.target_page_id is not None and (
                    src_slug := slug_by_id.get(r.from_page_id)
                ):
                    backlinks_by_page.setdefault(r.target_page_id, []).append(src_slug)

        refs_by_page: dict[int, list[WikiSourceRefDTO]] = {}
        for ref_row in (
            (
                await session.execute(
                    select(WikiSourceRefDO)
                    .where(
                        WikiSourceRefDO.user_id == user_id,
                        WikiSourceRefDO.page_id.in_(page_ids),
                    )
                    .order_by(WikiSourceRefDO.source_type, WikiSourceRefDO.source_key)
                )
            )
            .scalars()
            .all()
        ):
            refs_by_page.setdefault(ref_row.page_id, []).append(
                WikiSourceRefDTO(
                    source_type=WikiSourceType(ref_row.source_type),
                    source_key=ref_row.source_key,
                    file_id=ref_row.file_id,
                    last_event_seq=ref_row.last_event_seq,
                    is_source_deleted=ref_row.is_source_deleted,
                )
            )

        return [
            WikiPageDTO(
                page_id=page.page_id,
                slug=page.slug,
                title=page.title,
                page_kind=page.page_kind,
                summary=page.summary,
                body_md=page.body_md,
                claims=list(page.claims_json),
                edit_policy=page.edit_policy,
                last_author_kind=page.last_author_kind,
                version=page.version,
                create_time=page.create_time,
                update_time=page.update_time,
                aliases=aliases_by_page.get(page.page_id, []),
                outbound_links=outbound_by_page.get(page.page_id, []),
                backlinks=sorted(set(backlinks_by_page.get(page.page_id, []))),
                source_refs=refs_by_page.get(page.page_id, []),
            )
            for page in pages
        ]


def _score_page(page: WikiPageDO, aliases: Sequence[str], tokens: list[str]) -> float:
    """Compute a simple weighted lexical/alias match score."""
    title_l = page.title.lower()
    slug_l = page.slug.lower()
    summary_l = page.summary.lower()
    body_l = page.body_md.lower()
    score = 0.0
    for tok in tokens:
        if tok in title_l:
            score += 4.0
        if tok in slug_l:
            score += 3.0
        if any(tok in alias for alias in aliases):
            score += 3.5
        if tok in summary_l:
            score += 2.0
        if tok in body_l:
            score += 1.0
    return score


def _to_lint_dto(row: WikiLintIssueDO) -> WikiLintIssueDTO:
    return WikiLintIssueDTO(
        issue_id=row.issue_id,
        dedup_key=row.dedup_key,
        issue_type=row.issue_type,
        severity=row.severity,
        page_id=row.page_id,
        target_page_id=row.target_page_id,
        description=row.description,
        proposal=dict(row.proposal_json) if row.proposal_json is not None else None,
        status=row.status,
        create_time=row.create_time,
        update_time=row.update_time,
    )


WIKI_SERVICE_KEY: web.AppKey[WikiService] = web.AppKey("wiki_service")
