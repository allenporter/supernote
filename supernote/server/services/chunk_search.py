"""Modular keyword and vector page-chunk searchers and hybrid result ranking.

Provides two complementary retrieval strategies for `.note` pages:
- `KeywordChunkSearcher`: Matches native Supernote page keywords (`NotePageMetadataDO.keyword_texts`)
  and OCR page transcripts (`NotePageContentDO.text_content`), working even when no
  `EmbeddingModel` is configured or before OCR/embedding tasks run.
- `EmbeddingChunkSearcher`: Computes cosine similarity in `[-1.0, 1.0]` against stored
  page embeddings in `NotePageContentDO` for the active `EmbeddingModel`.

`rank_and_merge_results` deduplicates hits across both searchers and combines keyword and
hybrid scores monotonically in `[0.0, 1.0]` while preserving vector-only cosine scores.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from sqlalchemy import Select, select

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import EmbeddingModel, EmbeddingTaskType
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    NotePageMetadataDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.utils.note_content import infer_page_date

logger = logging.getLogger(__name__)

__all__ = [
    "EmbeddingChunkSearcher",
    "KeywordChunkSearcher",
    "SearchQuery",
    "SearchResult",
    "normalize_keyword_query",
    "rank_and_merge_results",
]

_WORD_TOKEN_RE = re.compile(r"[^\W_]+")
_HASH_PREFIX_RE = re.compile(r"(?:^|(?<=\s))#+")
_TECH_TOKEN_RE = re.compile(r"(?:[$@#%&][^\W_]+|[^\W_]+(?:[+#%&@=]+[^\W_]*)+)")
_FUNCTION_WORDS = frozenset(
    "a about an and are at by did for from how in is of on or the to was we were what with".split()
)


@dataclass
class SearchResult:
    """A single notebook page search hit."""

    file_id: int
    """Numeric VFS ID of the notebook."""
    file_name: str
    """Filename of the notebook."""
    page_index: int
    """0-based index of the matched page within the notebook."""
    page_id: str
    """Stable Supernote PAGEID string, or empty string on legacy firmware pages."""
    score: float
    """Relevance score (`[0.0, 1.0]` for keyword/hybrid hits; `[-1.0, 1.0]` for vector-only hits)."""
    text_preview: str
    """Short snippet of page OCR text or formatted native `#keyword` tags."""
    date: str | None = None
    """Inferred ISO 8601 page creation date (`YYYY-MM-DD`) when encoded in `page_id`."""


@dataclass(frozen=True)
class SearchQuery:
    """Validated query parameters shared across page-chunk searchers."""

    user_id: int
    """Authenticated user ID whose active notebooks are searched."""
    raw_query: str
    """Original user search string."""
    name_filter: str | None = None
    """Optional case-insensitive filename substring filter."""
    after_date: date | None = None
    """Optional inclusive lower bound on inferred page calendar date."""
    before_date: date | None = None
    """Optional inclusive upper bound on inferred page calendar date."""


@dataclass
class _KeywordCandidate:
    """Aligned metadata and OCR content for a single notebook page."""

    file_id: int
    file_name: str
    page_index: int
    page_id: str
    keywords: tuple[str, ...]
    text_content: str | None


def _has_cjk(text: str) -> bool:
    return any("\u3040" <= ch <= "\u9fff" or "\uac00" <= ch <= "\ud7af" for ch in text)


def normalize_keyword_query(raw_query: str) -> str:
    """Strip `#` tag prefixes, casefold, and return `''` if no word characters remain."""
    without_hashes = _HASH_PREFIX_RE.sub("", raw_query.strip())
    if not _WORD_TOKEN_RE.search(without_hashes):
        return ""
    return " ".join(without_hashes.casefold().split())


def _score_single_keyword(
    q_norm: str,
    q_tokens: list[str],
    q_token_set: set[str],
    q_tech: set[str],
    kw_norm: str,
) -> float:
    if not q_norm or not kw_norm:
        return 0.0
    kw_tokens = _WORD_TOKEN_RE.findall(kw_norm)
    kw_token_set = set(kw_tokens)
    kw_tech = set(_TECH_TOKEN_RE.findall(kw_norm))
    if q_tech and not q_tech.issubset(kw_tech):
        return 0.0
    if kw_norm == q_norm or (q_tokens and kw_tokens == q_tokens and kw_tech == q_tech):
        return 1.0
    if q_token_set and q_token_set.issubset(kw_token_set):
        return 0.92
    if (
        any(t not in _FUNCTION_WORDS for t in kw_token_set)
        and kw_token_set.issubset(q_token_set)
        and kw_tech.issubset(q_tech)
    ):
        return 0.88
    if _has_cjk(q_norm):
        return 0.85 if q_tokens and all(tok in kw_norm for tok in q_tokens) else 0.0
    if (
        not q_tech
        and len(q_tokens) == 1
        and len(q_tokens[0]) >= 3
        and any(tok.startswith(q_tokens[0]) for tok in kw_tokens)
    ):
        return 0.85
    return 0.0


def _format_keyword_preview(keywords: Sequence[str], raw_query: str = "") -> str:
    """Format native page keywords as `Keywords: #tag1, #tag2`, ordering matched tags first."""
    q_norm = normalize_keyword_query(raw_query)
    q_tokens = _WORD_TOKEN_RE.findall(q_norm)
    q_token_set = set(q_tokens)
    q_tech = set(_TECH_TOKEN_RE.findall(q_norm))
    matched: list[str] = []
    unmatched: list[str] = []
    seen: set[str] = set()

    for kw in keywords:
        cleaned = kw.lstrip("#").strip()
        if not cleaned or (dedup_key := cleaned.casefold()) in seen:
            continue
        seen.add(dedup_key)
        kw_norm = normalize_keyword_query(cleaned)
        hit = (
            _score_single_keyword(q_norm, q_tokens, q_token_set, q_tech, kw_norm) > 0.0
        )
        (matched if hit else unmatched).append(f"#{cleaned}")

    ordered = matched + unmatched
    return f"Keywords: {', '.join(ordered)}"[:200] if ordered else ""


def _score_native_keywords(
    q_norm: str,
    q_tokens: list[str],
    sig_tokens: list[str],
    q_tech: set[str],
    keywords: Sequence[str],
) -> float:
    if not keywords:
        return 0.0

    q_token_set = set(q_tokens)
    all_kw_tokens: set[str] = set()
    all_kw_tech: set[str] = set()
    best = 0.0

    for raw_kw in keywords:
        kw_norm = normalize_keyword_query(raw_kw)
        if not kw_norm:
            continue
        all_kw_tokens.update(_WORD_TOKEN_RE.findall(kw_norm))
        all_kw_tech.update(_TECH_TOKEN_RE.findall(kw_norm))
        score = _score_single_keyword(q_norm, q_tokens, q_token_set, q_tech, kw_norm)
        if score == 1.0:
            return 1.0
        best = max(best, score)

    if (
        len(sig_tokens) > 1
        and set(sig_tokens).issubset(all_kw_tokens)
        and q_tech.issubset(all_kw_tech)
    ):
        best = max(best, 0.95)

    return best


def _score_transcript_text(
    q_norm: str,
    q_tokens: list[str],
    sig_tokens: list[str],
    q_tech: set[str],
    text_content: str | None,
) -> float:
    if not text_content or not text_content.strip():
        return 0.0

    text_norm = " ".join(text_content.casefold().split())
    if q_tech and not q_tech.issubset(set(_TECH_TOKEN_RE.findall(text_norm))):
        return 0.0

    if _has_cjk(q_norm):
        if not all(tok in text_norm for tok in q_tokens):
            return 0.0
        return 0.85 if " ".join(q_tokens) in text_norm else 0.75

    doc_tokens = _WORD_TOKEN_RE.findall(text_norm)
    if not set(sig_tokens).issubset(set(doc_tokens)):
        return 0.0

    if f" {' '.join(q_tokens)} " in f" {' '.join(doc_tokens)} ":
        return 0.85
    return 0.75


def _score_keyword_match(
    raw_query: str,
    keywords: Sequence[str],
    text_content: str | None = None,
) -> float:
    """Compute calibrated `[0.0, 1.0]` lexical relevance across native `#keywords` and OCR text."""
    q_norm = normalize_keyword_query(raw_query)
    if not q_norm:
        return 0.0

    q_tokens = _WORD_TOKEN_RE.findall(q_norm)
    sig_tokens = [t for t in q_tokens if t not in _FUNCTION_WORDS] or q_tokens
    q_tech = set(_TECH_TOKEN_RE.findall(q_norm))

    s_native = _score_native_keywords(q_norm, q_tokens, sig_tokens, q_tech, keywords)
    s_text = _score_transcript_text(q_norm, q_tokens, sig_tokens, q_tech, text_content)
    if s_native == 0.0 and s_text == 0.0:
        return 0.0
    return min(1.0, max(s_native, s_text) + 0.05 * min(s_native, s_text))


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
    )
    if query.name_filter:
        stmt = stmt.where(
            UserFileDO.file_name.icontains(query.name_filter, autoescape=True)
        )
    return stmt


class KeywordChunkSearcher:
    """Searches native Supernote page keywords and OCR transcripts."""

    def __init__(self, session_manager: DatabaseSessionManager) -> None:
        self.session_manager = session_manager

    async def _load_candidates(self, query: SearchQuery) -> list[_KeywordCandidate]:
        async with self.session_manager.session() as session:
            meta_stmt = _apply_active_file_filters(
                select(NotePageMetadataDO, UserFileDO.file_name)
                .join(
                    UserFileDO,
                    (UserFileDO.id == NotePageMetadataDO.file_id)
                    & (UserFileDO.user_id == NotePageMetadataDO.user_id),
                )
                .where(NotePageMetadataDO.user_id == query.user_id)
                .where(NotePageMetadataDO.keywords_json != "[]")
                .where(NotePageMetadataDO.keywords_json != ""),
                query,
            )
            meta_rows = (await session.execute(meta_stmt)).all()

            content_stmt = _apply_active_file_filters(
                select(
                    NotePageContentDO.id,
                    NotePageContentDO.file_id,
                    NotePageContentDO.page_index,
                    NotePageContentDO.page_id,
                    NotePageContentDO.text_content,
                    UserFileDO.file_name,
                )
                .join(UserFileDO, UserFileDO.id == NotePageContentDO.file_id)
                .where(NotePageContentDO.text_content.isnot(None))
                .where(NotePageContentDO.text_content != ""),
                query,
            )
            content_rows = (await session.execute(content_stmt)).all()

        # Pair by (file_id, page_id) for non-empty page_ids so moved pages and out-of-sync
        # rows never cross-join or attach another page's OCR text.
        content_by_page_id: dict[tuple[int, str], tuple[int, str]] = {}
        legacy_by_slot: dict[tuple[int, int], tuple[int, str]] = {}
        non_blank_rows = [
            r for r in content_rows if r.text_content and r.text_content.strip()
        ]
        for row in non_blank_rows:
            assert row.text_content is not None
            if row.page_id:
                content_by_page_id[(row.file_id, row.page_id)] = (
                    row.id,
                    row.text_content,
                )
            else:
                legacy_by_slot[(row.file_id, row.page_index)] = (
                    row.id,
                    row.text_content,
                )

        consumed_ids: set[int] = set()
        candidates: list[_KeywordCandidate] = []

        for pm, file_name in meta_rows:
            kws = tuple(pm.keyword_texts)
            if not kws:
                continue
            paired = (
                content_by_page_id.get((pm.file_id, pm.page_id))
                if pm.page_id
                else legacy_by_slot.get((pm.file_id, pm.page_index))
            )
            matched_text: str | None = None
            if paired is not None:
                consumed_ids.add(paired[0])
                matched_text = paired[1]
            candidates.append(
                _KeywordCandidate(
                    file_id=pm.file_id,
                    file_name=file_name,
                    page_index=pm.page_index,
                    page_id=pm.page_id,
                    keywords=kws,
                    text_content=matched_text,
                )
            )

        for row in non_blank_rows:
            if row.id not in consumed_ids:
                candidates.append(
                    _KeywordCandidate(
                        file_id=row.file_id,
                        file_name=row.file_name,
                        page_index=row.page_index,
                        page_id=row.page_id,
                        keywords=(),
                        text_content=row.text_content,
                    )
                )

        return candidates

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        if not normalize_keyword_query(query.raw_query):
            return []

        results: list[SearchResult] = []
        for cand in await self._load_candidates(query):
            date_ok, date_str = _matches_date_bounds(
                cand.page_id, query.after_date, query.before_date
            )
            if not date_ok:
                continue
            score = _score_keyword_match(
                query.raw_query, cand.keywords, cand.text_content
            )
            if score <= 0.0:
                continue
            preview = (
                cand.text_content[:200]
                if cand.text_content and cand.text_content.strip()
                else _format_keyword_preview(cand.keywords, query.raw_query)
            )
            results.append(
                SearchResult(
                    file_id=cand.file_id,
                    file_name=cand.file_name,
                    page_index=cand.page_index,
                    page_id=cand.page_id,
                    score=score,
                    text_preview=preview,
                    date=date_str,
                )
            )
        return results


class EmbeddingChunkSearcher:
    """Searches page vector embeddings by cosine similarity."""

    def __init__(
        self,
        session_manager: DatabaseSessionManager,
        embedding_model: EmbeddingModel | None,
    ) -> None:
        self.session_manager = session_manager
        self.embedding_model = embedding_model

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        model = self.embedding_model
        if model is None or not query.raw_query or not query.raw_query.strip():
            return []

        try:
            embedding_values = await model.embed(
                query.raw_query, task_type=EmbeddingTaskType.RETRIEVAL_QUERY
            )
            query_embedding = np.array(embedding_values, dtype=float)
        except (AIError, ValueError, TypeError) as e:
            logger.error(f"Failed to fetch or process query embedding: {e}")
            return []

        if query_embedding.ndim != 1 or query_embedding.size == 0:
            return []
        query_norm = float(np.linalg.norm(query_embedding))
        if not math.isfinite(query_norm) or math.isclose(
            query_norm, 0.0, abs_tol=1e-12
        ):
            return []
        query_unit = query_embedding / query_norm

        async with self.session_manager.session() as session:
            stmt = _apply_active_file_filters(
                select(NotePageContentDO, UserFileDO.file_name)
                .join(UserFileDO, UserFileDO.id == NotePageContentDO.file_id)
                .where(NotePageContentDO.embedding.isnot(None))
                .where(NotePageContentDO.embedding_model == model.model_id),
                query,
            )
            candidates = (await session.execute(stmt)).all()

        results: list[SearchResult] = []
        for content_do, file_name in candidates:
            if not content_do.embedding:
                continue
            date_ok, date_str = _matches_date_bounds(
                content_do.page_id, query.after_date, query.before_date
            )
            if not date_ok:
                continue

            try:
                candidate_embedding = np.array(
                    json.loads(content_do.embedding), dtype=float
                )
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                logger.warning(
                    f"Failed to decode embedding for result {content_do.id}: {e}"
                )
                continue

            if candidate_embedding.shape != query_unit.shape:
                continue
            cand_norm = float(np.linalg.norm(candidate_embedding))
            if not math.isfinite(cand_norm) or math.isclose(
                cand_norm, 0.0, abs_tol=1e-12
            ):
                continue

            raw_cos = float(np.dot(query_unit, candidate_embedding / cand_norm))
            if not math.isfinite(raw_cos):
                continue
            score = max(-1.0, min(1.0, raw_cos))
            preview = (
                content_do.text_content[:200]
                if content_do.text_content and content_do.text_content.strip()
                else ""
            )
            results.append(
                SearchResult(
                    file_id=content_do.file_id,
                    file_name=file_name,
                    page_index=content_do.page_index,
                    page_id=content_do.page_id,
                    score=score,
                    text_preview=preview,
                    date=date_str,
                )
            )

        return results


def _fuse_scores(kw_score: float | None, vec_score: float | None) -> float:
    if kw_score is None or kw_score <= 0.0:
        return vec_score if vec_score is not None else 0.0
    if vec_score is None:
        return kw_score
    pos_vec = max(0.0, min(1.0, vec_score))
    high, low = max(kw_score, pos_vec), min(kw_score, pos_vec)
    return min(1.0, high + 0.5 * low * (1.0 - high))


def _dedup_key(hit: SearchResult) -> tuple[int, str]:
    # Key by (file_id, page_id) when page_id is present so moved pages reconcile cleanly
    # across metadata and content tables, while keeping legacy page_id == "" slots distinct.
    return (
        hit.file_id,
        f"id:{hit.page_id}" if hit.page_id else f"idx:{hit.page_index}",
    )


def rank_and_merge_results(
    keyword_results: Sequence[SearchResult],
    embedding_results: Sequence[SearchResult],
    top_n: int,
) -> list[SearchResult]:
    """Deduplicate keyword and vector hits, fuse scores monotonically, and return top `top_n`."""
    if top_n <= 0:
        return []

    kw_by_key: dict[tuple[int, str], SearchResult] = {}
    for hit in keyword_results:
        key = _dedup_key(hit)
        if key not in kw_by_key or hit.score > kw_by_key[key].score:
            kw_by_key[key] = hit

    vec_by_key: dict[tuple[int, str], SearchResult] = {}
    for hit in embedding_results:
        key = _dedup_key(hit)
        if key not in vec_by_key or hit.score > vec_by_key[key].score:
            vec_by_key[key] = hit

    scored_entries: list[tuple[tuple[float, float, float, int, int], SearchResult]] = []
    for key in kw_by_key.keys() | vec_by_key.keys():
        kw_hit = kw_by_key.get(key)
        vec_hit = vec_by_key.get(key)
        kw_score = kw_hit.score if kw_hit is not None else None
        vec_score = vec_hit.score if vec_hit is not None else None
        fused = _fuse_scores(kw_score, vec_score)

        anchor = kw_hit if kw_hit is not None else vec_hit
        assert anchor is not None
        other = vec_hit if anchor is kw_hit else kw_hit

        if vec_hit is not None and vec_hit.text_preview.strip():
            preview = vec_hit.text_preview
        elif kw_hit is not None and kw_hit.text_preview.strip():
            preview = kw_hit.text_preview
        else:
            preview = ""

        merged = SearchResult(
            file_id=anchor.file_id,
            file_name=anchor.file_name,
            page_index=anchor.page_index,
            page_id=anchor.page_id or (other.page_id if other else ""),
            score=fused,
            text_preview=preview,
            date=anchor.date or (other.date if other else None),
        )
        sort_key = (
            -round(fused, 6),
            -round(kw_score if kw_score is not None else 0.0, 6),
            -round(vec_score if vec_score is not None else 0.0, 6),
            merged.file_id,
            merged.page_index,
        )
        scored_entries.append((sort_key, merged))

    scored_entries.sort(key=lambda item: item[0])
    return [entry for _, entry in scored_entries[:top_n]]
