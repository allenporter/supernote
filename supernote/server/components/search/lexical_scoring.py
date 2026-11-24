"""Pure lexical query parsing, `#keyword` + transcript scoring, and snippet formatting.

Separates stateless text tokenization, CJK script-boundary segmentation, SQL prefilter
term selection, calibrated `[0.0, 1.0]` lexical relevance scoring, and match-centered
preview formatting from SQLAlchemy session management in `SearchService`.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from supernote.server.utils.stopwords import STOPWORDS

__all__ = [
    "ParsedQuery",
    "build_lexical_preview",
    "extract_centered_snippet",
    "parse_lexical_query",
    "score_page_lexical",
    "sql_prefilter_terms",
]

# Strip `#` tag prefixes unless preceded by a word character (preserving `C#` / `F#`).
_HASH_PREFIX_RE = re.compile(r"(?<![^\W_])#+")
_APOSTROPHE_SUFFIX_RE = re.compile(
    r"\b(?:can|won|shan)['\u2019]t\b|n['\u2019]t\b|['\u2019](?:s|m|re|ve|ll|d)\b"
)
_CJK_RANGES = r"\u3005\u3040-\u9fff\uf900-\ufaff\uac00-\ud7af\U00020000-\U0002ceaf"
_CJK_RE = re.compile(f"[{_CJK_RANGES}]")
# Single-pass mixed-script tokenizer:
# - Splits CJK text along Kanji (incl. `々`), Katakana, Hiragana (>=2), Hangul, and Jamo/Bopomofo runs
#   without erasing adjacent ASCII words or digits (`Python入門`, `3月15日`, `100円`).
# - Preserves `C#12` / `F#8`, `C++17`, and `$100` without gluing inline operators (`cost+tax`, `issue#42`).
_SEGMENT_RE = re.compile(
    r"[\u3005\u3400-\u9fff\uf900-\ufaff\U00020000-\U0002ceaf]+"
    r"|[\u30a0-\u30ff]+"
    r"|[\u3040-\u309f]{2,}"
    r"|[\u3100-\u33ff\uac00-\ud7af]+"
    r"|\$?[cf]#(?=\d)"
    rf"|\$?[^\W_{_CJK_RANGES}]+(?:[+#]{{2,}}|[+#](?![^\W_+#]))?"
)


@dataclass(frozen=True, slots=True)
class ParsedQuery:
    """Normalized lexical query parsed once per search."""

    raw: str
    """Original un-normalized query string for SQLite ASCII prefilter checks."""
    norm: str
    """Casefolded query with `#` tag prefixes and contraction suffixes stripped."""
    tokens: tuple[str, ...]
    """All segmented tokens in query order."""
    sig_tokens: tuple[str, ...]
    """Non-stopword tokens eligible for transcript and partial-tag matching."""
    sig_stems: tuple[str, ...]
    """Non-empty significant token stems with `$` prefixes and `+#` suffixes stripped."""
    sig_set: frozenset[str]
    """Unique significant tokens."""
    explicit_tag: bool
    """Whether the caller prefixed the query with `#`."""


def _has_cjk(text: str) -> bool:
    """Return True when `text` contains any CJK, Kana, Hangul, or Bopomofo codepoint."""
    return _CJK_RE.search(text) is not None


def _normalize_text(raw: str) -> str:
    """Normalize Unicode when non-ASCII, strip `#` prefixes and contractions, and casefold.

    Gates `unicodedata.normalize`, `#` stripping, and apostrophe stripping behind O(1)/C
    substring checks so common ASCII OCR pages pay zero extra regex or Unicode passes.
    """
    text = raw.strip()
    if not text.isascii():
        text = unicodedata.normalize("NFKC", text)
    if "#" in text:
        text = _HASH_PREFIX_RE.sub("", text)
    text = text.casefold()
    if "'" in text or "\u2019" in text:
        text = _APOSTROPHE_SUFFIX_RE.sub("", text)
    return " ".join(text.split())


def _tokenize(norm_text: str) -> tuple[str, ...]:
    """Segment normalized text into mixed-script word, CJK, and symbol-bearing tokens."""
    return tuple(_SEGMENT_RE.findall(norm_text))


def parse_lexical_query(raw_query: str) -> ParsedQuery | None:
    """Parse `raw_query` into `ParsedQuery`, or `None` if no searchable tokens exist."""
    norm = _normalize_text(raw_query)
    if not (tokens := _tokenize(norm)):
        return None

    if len(tokens) == 1:
        tok = tokens[0]
        core = tok.lstrip("$")
        base = core.rstrip("+#")
        is_lang_symbol = core in {"c#", "f#"} or core.endswith("++")
        sig = (
            (tok,)
            if (
                tok not in STOPWORDS
                and (len(base) >= 2 or is_lang_symbol or _has_cjk(tok))
            )
            else ()
        )
    else:
        sig = tuple(t for t in tokens if t not in STOPWORDS)

    stems = tuple(s for t in sig if (s := t.lstrip("$").rstrip("+#")))
    return ParsedQuery(
        raw=raw_query,
        norm=norm,
        tokens=tokens,
        sig_tokens=sig,
        sig_stems=stems,
        sig_set=frozenset(sig),
        explicit_tag=raw_query.lstrip().startswith("#"),
    )


def sql_prefilter_terms(
    parsed: ParsedQuery,
    max_terms: int = 8,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return bounded `(ascii_icontains, cjk_contains)` SQL prefilter stems.

    Caps total clauses at `max_terms` to stay far below `SQLITE_LIMIT_EXPR_DEPTH`,
    and only emits ASCII `.icontains` stems that match `parsed.raw` under ASCII-only
    case-folding (`re.ASCII | re.IGNORECASE`) so queries containing Unicode casefold
    or NFKC expansions (`"Straße"`, `"300K"`, `"ﬁnance"`) are not dropped by SQLite's
    ASCII-only `lower()`.
    """
    candidates: list[tuple[bool, str]] = []
    seen: set[str] = set()
    for stem in parsed.sig_stems:
        if stem in seen:
            continue
        seen.add(stem)
        if _has_cjk(stem):
            candidates.append((True, stem))
        elif (
            stem.isascii()
            and re.search(re.escape(stem), parsed.raw, re.ASCII | re.IGNORECASE)
            is not None
        ):
            candidates.append((False, stem))

    candidates.sort(key=lambda item: len(item[1]), reverse=True)
    capped = candidates[:max_terms]
    ascii_terms = tuple(s for is_cjk, s in capped if not is_cjk)
    cjk_terms = tuple(s for is_cjk, s in capped if is_cjk)
    return ascii_terms, cjk_terms


def _token_matches(
    tok: str,
    token_set: set[str] | frozenset[str],
    norm_text: str,
) -> bool:
    """Match CJK runs by substring (unspaced script) and non-CJK tokens by whole token."""
    return (tok in norm_text) if _has_cjk(tok) else (tok in token_set)


def _token_or_prefix_matches(
    tok: str,
    kw_tokens: tuple[str, ...],
    kw_token_set: frozenset[str],
    kw_norm: str,
) -> bool:
    """Return True if `tok` matches `kw_norm` exactly or as a >=4-char ASCII token prefix."""
    if _token_matches(tok, kw_token_set, kw_norm):
        return True
    return (
        len(tok) >= 4
        and not tok.startswith("$")
        and not _has_cjk(tok)
        and any(kw_tok.startswith(tok) for kw_tok in kw_tokens)
    )


def _score_single_keyword(q: ParsedQuery, kw_norm: str) -> float:
    """Score one normalized Supernote `#keyword` tag against `q` on a `[0.0, 1.0]` scale.

    Separates per-tag relevance into calibrated tiers so native device tags outrank
    incidental OCR body mentions while suppressing short-prefix false positives:
    - `1.00`: Exact tag match (`#KS-Tilt` -> `ks-tilt`, including 1-char tags like `#r`).
    - `0.92`: Tag contains every significant query token (`tilt` -> `ks-tilt`, `C#` -> `C#12`).
    - `0.85`: Every significant query token matches a tag token or >=4-char prefix
      (`trap` or `ks trap` -> `ks-trapezoid`, while 3-char `cat` ignores `category`).
    - `0.80`: Multi-token query embeds a substantive tag (`how to fix ocr` -> `ocr`).
    """
    if not (kw_tokens := _tokenize(kw_norm)):
        return 0.0
    if kw_norm == q.norm or kw_tokens == q.tokens:
        return 1.0
    if not q.sig_tokens:
        return 0.0
    kw_token_set = frozenset(kw_tokens)
    if all(_token_matches(t, kw_token_set, kw_norm) for t in q.sig_tokens):
        return 0.92
    if all(
        _token_or_prefix_matches(t, kw_tokens, kw_token_set, kw_norm)
        for t in q.sig_tokens
    ):
        return 0.85
    if (
        len(q.sig_tokens) > 1
        and any(t not in STOPWORDS for t in kw_tokens)
        and (len(kw_tokens) >= 2 or len(kw_tokens[0]) >= 3 or _has_cjk(kw_tokens[0]))
        and kw_token_set.issubset(q.sig_set)
    ):
        return 0.80
    return 0.0


def _match_native_keywords(
    q: ParsedQuery, keywords: Sequence[str]
) -> tuple[float, frozenset[str]]:
    """Score a page's native `#keyword` list and return `(best_score, matched_kw_norms)`.

    Besides taking the maximum `_score_single_keyword` across tags, awards `0.95` when
    multiple tags on the same page jointly cover every significant query token (e.g.,
    query `#roadmap #Q4` on a page tagged with both `#roadmap` and `#Q4`). Returning
    `matched_norms` keeps `build_lexical_preview` in exact agreement with scoring.
    """
    covered_sig: set[str] = set()
    subset_norms: list[str] = []
    matched_norms: set[str] = set()
    best = 0.0
    for raw_kw in keywords:
        kw_norm = _normalize_text(raw_kw)
        score = _score_single_keyword(q, kw_norm)
        if score > 0.0:
            matched_norms.add(kw_norm)
            best = max(best, score)
        kw_token_set = frozenset(_tokenize(kw_norm))
        if kw_token_set and kw_token_set.issubset(q.sig_set):
            covered_sig.update(kw_token_set)
            subset_norms.append(kw_norm)

    if len(q.sig_set) > 1 and covered_sig == q.sig_set:
        matched_norms.update(subset_norms)
        best = max(best, 0.95)
    return best, frozenset(matched_norms)


def _score_transcript_text(q: ParsedQuery, text_content: str | None) -> float:
    """Score OCR body text (`0.85` contiguous phrase, `0.75` all-token match, else `0.0`).

    Requires every significant query token to appear in `text_content`, and requires a
    contiguous phrase match when the caller explicitly prefixed a multi-token `#tag`.
    """
    if not q.sig_tokens or not text_content or not text_content.strip():
        return 0.0

    text_norm = _normalize_text(text_content)
    doc_tokens = _tokenize(text_norm)
    doc_token_set = frozenset(doc_tokens)
    if not all(_token_matches(t, doc_token_set, text_norm) for t in q.sig_tokens):
        return 0.0

    phrase_hit = f" {' '.join(q.tokens)} " in f" {' '.join(doc_tokens)} " or (
        any(_has_cjk(t) for t in q.sig_tokens) and "".join(q.sig_tokens) in text_norm
    )
    if phrase_hit:
        return 0.85
    return 0.0 if (q.explicit_tag and len(q.tokens) > 1) else 0.75


def score_page_lexical(
    q: ParsedQuery,
    keywords: Sequence[str],
    text_content: str | None,
) -> float:
    """Compute calibrated `[0.0, 1.0]` relevance across native `#keywords` and OCR text."""
    s_native = _match_native_keywords(q, keywords)[0] if keywords else 0.0
    s_text = _score_transcript_text(q, text_content)
    if s_native == 0.0 and s_text == 0.0:
        return 0.0
    # Add a small corroboration bonus when a page matches via both `#keyword` and OCR text.
    return min(1.0, max(s_native, s_text) + 0.05 * min(s_native, s_text))


def _casefold_index_to_raw(text: str, folded_idx: int) -> int:
    """Map an index in `text.casefold()` back to the character index in `text`."""
    end = 0
    return next(
        i for i, ch in enumerate(text) if (end := end + len(ch.casefold())) > folded_idx
    )


def extract_centered_snippet(
    text: str, terms: Sequence[str], max_len: int = 200
) -> str:
    """Return a `max_len`-bounded snippet centered around the first matched term."""
    if max_len <= 0:
        return ""
    compact = text.strip()
    if len(compact) <= max_len:
        return compact
    if max_len <= 3:
        return compact[:max_len]

    prioritized = [t for t in terms if len(t) >= 2] or [t for t in terms if t]
    folded = compact.casefold()
    matches: list[int] = []
    for term in prioritized:
        if (m := re.search(re.escape(term), compact, re.IGNORECASE)) is not None:
            matches.append(m.start())
        elif (idx := folded.find(term)) != -1:
            matches.append(_casefold_index_to_raw(compact, idx))
    pos = min(matches, default=0)
    if pos <= max_len // 2:
        return f"{compact[: max_len - 1].rstrip()}…"
    start = min(max(0, pos - max_len // 3), len(compact) - (max_len - 2))
    end = min(len(compact), start + max_len - 2)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(compact) else ""
    return f"{prefix}{compact[start:end].strip()}{suffix}"


def _tag_visible_in_snippet(tag_norm: str, snippet: str) -> bool:
    """Return True when all tokens of `tag_norm` already appear as tokens in `snippet`."""
    snip_norm = _normalize_text(snippet)
    snip_tokens = frozenset(_tokenize(snip_norm))
    return all(_token_matches(t, snip_tokens, snip_norm) for t in _tokenize(tag_norm))


def build_lexical_preview(
    keywords: Sequence[str],
    text_content: str | None,
    q: ParsedQuery,
) -> str:
    """Format match-centered OCR preview with `[#tag]` badge or `Keywords: #tag1, ...`."""
    _, matched_norms = (
        _match_native_keywords(q, keywords) if keywords else (0.0, frozenset())
    )
    matched: list[tuple[str, str]] = []
    unmatched: list[str] = []
    seen: set[str] = set()
    for kw in keywords:
        cleaned = kw.strip().lstrip("#").strip()
        if not cleaned or (dedup := cleaned.casefold()) in seen:
            continue
        seen.add(dedup)
        kw_norm = _normalize_text(cleaned)
        if kw_norm in matched_norms:
            matched.append((f"#{cleaned}", kw_norm))
        else:
            unmatched.append(f"#{cleaned}")

    if text_content and text_content.strip():
        snippet = extract_centered_snippet(text_content, q.sig_stems)
        if matched and not _tag_visible_in_snippet(matched[0][1], snippet):
            badge = f"[{matched[0][0]}] "
            budgeted = extract_centered_snippet(
                text_content, q.sig_stems, max_len=200 - len(badge)
            )
            return f"{badge}{budgeted}"
        return snippet

    ordered = [tag for tag, _ in matched] + unmatched
    return f"Keywords: {', '.join(ordered)}"[:200] if ordered else ""
