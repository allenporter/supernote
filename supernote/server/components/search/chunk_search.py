"""Notebook page-chunk search primitives and vector similarity searcher.

Separates per-strategy page-chunk retrieval from `SearchService` orchestration so
queries validate bounds once, compute embeddings outside SQLite transactions, score
candidate vectors off the `asyncio` event loop, and load `text_content` snippets only
for the top-ranked winning pages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import (
    EmbeddingModel,
    EmbeddingTaskType,
    validate_embedding_vector,
)
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.utils.note_content import infer_page_date

from .models import SearchResult

logger = logging.getLogger(__name__)

__all__ = [
    "EmbeddingChunkSearcher",
    "SearchQuery",
]


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """Validated query parameters shared across page-chunk searchers."""

    user_id: int
    """Authenticated user ID whose active notebooks are searched."""
    raw_query: str
    """Original user search string."""
    top_n: int = 5
    """Maximum number of results to return."""
    name_filter: str | None = None
    """Optional case-insensitive filename substring filter."""
    after_date: date | None = None
    """Optional inclusive lower bound on inferred page calendar date."""
    before_date: date | None = None
    """Optional inclusive upper bound on inferred page calendar date."""


@dataclass(frozen=True, slots=True)
class _EmbeddingRow:
    content_id: int
    file_id: int
    file_name: str
    page_index: int
    page_id: str
    date: str | None
    embedding_json: str


def _matches_date_bounds(
    page_id: str,
    after_date: date | None,
    before_date: date | None,
) -> tuple[bool, str | None]:
    inferred = infer_page_date(page_id)
    page_day = inferred.date() if inferred is not None else None
    if after_date and (page_day is None or page_day < after_date):
        return False, None
    if before_date and (page_day is None or page_day > before_date):
        return False, None
    return True, (page_day.isoformat() if page_day else None)


def _apply_active_file_filters[*Ts](
    stmt: Select[*Ts], query: SearchQuery
) -> Select[*Ts]:
    stmt = (
        stmt.where(UserFileDO.user_id == query.user_id)
        .where(UserFileDO.is_active == "Y")
        .where(UserFileDO.is_folder == "N")
        .where(UserFileDO.file_name.ilike("%.note"))
    )
    if query.name_filter:
        stmt = stmt.where(
            UserFileDO.file_name.icontains(query.name_filter, autoescape=True)
        )
    return stmt


def _score_embedding_rows(
    query_unit: np.ndarray,
    rows: Sequence[_EmbeddingRow],
) -> list[tuple[_EmbeddingRow, float]]:
    """Decode JSON vectors and rank cosine similarity in a worker thread.

    Kept synchronous over plain `_EmbeddingRow` values (never ORM instances) so
    `EmbeddingChunkSearcher.search` can offload CPU-heavy JSON parsing and `numpy`
    dot products via `asyncio.to_thread` without stalling the `asyncio` event loop
    or touching `AsyncSession` state across threads.
    """
    scored: list[tuple[_EmbeddingRow, float]] = []
    for row in rows:
        try:
            cand = np.asarray(json.loads(row.embedding_json), dtype=float)
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(
                f"Failed to decode embedding for result {row.content_id}: {e}"
            )
            continue

        if cand.shape != query_unit.shape:
            continue
        cand_norm = float(np.linalg.norm(cand))
        if not math.isfinite(cand_norm) or math.isclose(cand_norm, 0.0, abs_tol=1e-12):
            continue

        raw_cos = float(np.dot(query_unit, cand / cand_norm))
        scored.append((row, max(-1.0, min(1.0, raw_cos))))

    scored.sort(
        key=lambda item: (-round(item[1], 6), item[0].file_id, item[0].page_index)
    )
    return scored


class EmbeddingChunkSearcher:
    """Stateless vector chunk searcher ranking page embeddings by cosine similarity."""

    async def embed_query(
        self, raw_query: str, model: EmbeddingModel | None
    ) -> np.ndarray | None:
        """Embed `raw_query` outside any DB transaction and return a 1D unit vector."""
        if model is None or not any(
            unicodedata.category(c)[0] in "LNS" for c in raw_query
        ):
            return None

        try:
            validated = validate_embedding_vector(
                await model.embed(
                    raw_query, task_type=EmbeddingTaskType.RETRIEVAL_QUERY
                ),
                model.model_id,
            )
            vec = np.asarray(validated, dtype=float)
        except (AIError, ValueError, TypeError) as e:
            logger.error(f"Failed to fetch or process query embedding: {e}")
            return None

        return vec / float(np.linalg.norm(vec))

    async def search(
        self,
        session: AsyncSession,
        query: SearchQuery,
        query_unit: np.ndarray,
        model: EmbeddingModel,
    ) -> list[SearchResult]:
        """Score candidate page embeddings in `session` and load snippets for top `query.top_n`."""
        # Project scalar columns without `text_content` to avoid loading multi-KB OCR
        # transcripts and ORM objects for every embedded page in the user's library.
        stmt = _apply_active_file_filters(
            select(
                NotePageContentDO.id,
                NotePageContentDO.file_id,
                NotePageContentDO.page_index,
                NotePageContentDO.page_id,
                NotePageContentDO.embedding,
                UserFileDO.file_name,
            )
            .join(UserFileDO, UserFileDO.id == NotePageContentDO.file_id)
            .where(NotePageContentDO.embedding.isnot(None))
            .where(NotePageContentDO.embedding_model == model.model_id),
            query,
        )
        raw_rows = (await session.execute(stmt)).all()

        filtered: list[_EmbeddingRow] = []
        for row in raw_rows:
            if not row.embedding:
                continue
            date_ok, date_str = _matches_date_bounds(
                row.page_id, query.after_date, query.before_date
            )
            if not date_ok:
                continue
            filtered.append(
                _EmbeddingRow(
                    content_id=row.id,
                    file_id=row.file_id,
                    file_name=row.file_name,
                    page_index=row.page_index,
                    page_id=row.page_id,
                    date=date_str,
                    embedding_json=row.embedding,
                )
            )

        if not filtered:
            return []

        winners = (
            await asyncio.to_thread(_score_embedding_rows, query_unit, filtered)
        )[: query.top_n]
        if not winners:
            return []

        # Fetch `text_content` only for the top-ranked winners needed to build previews.
        winner_ids = [row.content_id for row, _ in winners]
        text_rows = (
            await session.execute(
                select(NotePageContentDO.id, NotePageContentDO.text_content).where(
                    NotePageContentDO.id.in_(winner_ids)
                )
            )
        ).all()
        text_by_id = {
            r.id: r.text_content[:200]
            for r in text_rows
            if r.text_content and r.text_content.strip()
        }

        return [
            SearchResult(
                file_id=row.file_id,
                file_name=row.file_name,
                page_index=row.page_index,
                page_id=row.page_id,
                score=score,
                text_preview=text_by_id.get(row.content_id, ""),
                date=row.date,
            )
            for row, score in winners
        ]
