"""Deterministic synthetic `.note` fixture builders for server, sync, and OCR E2E tests.

Design Philosophy
-----------------
Checking binary `.note` fixtures into Git makes E2E tests opaque: test authors cannot
easily vary page counts, timestamps, handwriting vocabulary, keywords, or multi-day
chronology, nor assert exact OCR/summary accuracy against known source text.

`supernote.testing.notebook_fixtures` bridges `NotebookAuthor` with integration tests:

- `build_synthetic_notebook()` renders Markdown pages (defaulting to simulated
  `handwriting` on `ruled` paper) into a valid `.note` byte payload while recording
  the exact `FILE_ID`, per-page firmware-dated `PAGEID`s (`infer_page_date()`-compatible),
  headings, keywords, and plain-text ground-truth transcripts in `SyntheticNotebook`.
- `append_synthetic_page()` simulates incremental device edits (e.g. a user writing a
  new daily log page and syncing again) while keeping all earlier `PAGEID`s unchanged
  so per-page server caches and OCR pipelines can be tested for incremental updates.
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from supernote.notebook import Notebook, load
from supernote.notebook.author import NotebookAuthor
from supernote.notebook.renderer import BackgroundStyle, RenderStyle


@dataclass(frozen=True)
class SyntheticPage:
    """Ground-truth metadata for a single synthetically generated notebook page."""

    page_index: int
    page_id: str
    text: str
    created_at: datetime
    headings: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class SyntheticNotebook:
    """A generated `.note` binary alongside its ground-truth page transcripts and IDs."""

    data: bytes
    file_id: str
    pages: tuple[SyntheticPage, ...]

    @property
    def full_text(self) -> str:
        """Concatenated ground-truth text across all pages."""
        return "\n\n".join(p.text for p in self.pages if p.text)

    def load(self) -> Notebook:
        """Parse `self.data` back into a `Notebook` object."""
        return load(io.BytesIO(self.data))

    def write_to(self, path: str | Path) -> Path:
        """Persist `self.data` to `path` and return the `Path`."""
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.data)
        return dest


def build_synthetic_notebook(
    pages: Sequence[str] | None = None,
    *,
    markdown: str | None = None,
    style: RenderStyle | str = RenderStyle.HANDWRITING,
    background: BackgroundStyle | str = BackgroundStyle.RULED,
    layer: str | None = None,
    hidden_layer_pages: Mapping[int, str] | None = None,
    equipment: str = "N6",
    base_date: datetime | None = None,
    page_dates: Sequence[datetime] | None = None,
    auto_toc: bool = True,
    extract_keywords: bool = True,
    seed: int = 42,
) -> SyntheticNotebook:
    """Build a synthetic `.note` file with deterministic handwriting/layout and ground truth.

    Either `pages` (one Markdown string per page, Advancing `base_date` by 1 day per page
    unless `page_dates` is given) or `markdown` (free-flowing Markdown paginated automatically)
    may be supplied.
    """
    if pages is not None and markdown is not None:
        raise ValueError("Specify either `pages` or `markdown`, not both.")

    start_dt = (
        base_date if base_date is not None else datetime(2026, 1, 15, 9, 0, tzinfo=UTC)
    )
    author = NotebookAuthor(
        equipment=equipment,
        created_at=start_dt,
        seed=seed,
    )

    synthetic_pages: list[SyntheticPage] = []

    if pages is not None:
        for idx, page_md in enumerate(pages):
            dt = (
                page_dates[idx]
                if page_dates is not None and idx < len(page_dates)
                else (start_dt + timedelta(days=idx))
            )
            hidden_md = hidden_layer_pages.get(idx) if hidden_layer_pages else None
            authored = author.add_markdown(
                page_md,
                style=style,
                background=background,
                layer=layer,
                hidden_layer_markdown=hidden_md,
                auto_toc=auto_toc,
                extract_keywords=extract_keywords,
                default_page_date=dt,
                seed=seed + idx,
            )
            for sub_idx, info in enumerate(authored):
                synthetic_pages.append(
                    SyntheticPage(
                        page_index=info.page_index,
                        page_id=info.page_id,
                        text=info.text,
                        created_at=dt + timedelta(seconds=sub_idx),
                        headings=tuple(h.text for h in info.headings),
                        keywords=tuple(k.keyword for k in info.keywords),
                    )
                )
    else:
        doc_md = (
            markdown if markdown is not None else "# Test Note\n\nSynthetic content."
        )
        authored = author.add_markdown(
            doc_md,
            style=style,
            background=background,
            layer=layer,
            auto_toc=auto_toc,
            extract_keywords=extract_keywords,
            page_dates=page_dates,
            default_page_date=start_dt,
            seed=seed,
        )
        for idx, info in enumerate(authored):
            dt = (
                page_dates[idx]
                if page_dates is not None and idx < len(page_dates)
                else (start_dt + timedelta(seconds=idx))
            )
            synthetic_pages.append(
                SyntheticPage(
                    page_index=info.page_index,
                    page_id=info.page_id,
                    text=info.text,
                    created_at=dt,
                    headings=tuple(h.text for h in info.headings),
                    keywords=tuple(k.keyword for k in info.keywords),
                )
            )

    raw_bytes = author.to_bytes()
    return SyntheticNotebook(
        data=raw_bytes,
        file_id=author.file_id,
        pages=tuple(synthetic_pages),
    )


def append_synthetic_page(
    existing: SyntheticNotebook,
    page_markdown: str,
    *,
    style: RenderStyle | str = RenderStyle.HANDWRITING,
    background: BackgroundStyle | str = BackgroundStyle.RULED,
    layer: str | None = None,
    created_at: datetime | None = None,
    auto_toc: bool = True,
    extract_keywords: bool = True,
    seed: int = 99,
) -> SyntheticNotebook:
    """Append a new Markdown page onto an existing `SyntheticNotebook` without altering earlier PAGEIDs."""
    nb = existing.load()
    author = NotebookAuthor.from_notebook(nb, seed=seed)
    next_dt = (
        created_at
        if created_at is not None
        else (
            existing.pages[-1].created_at + timedelta(days=1)
            if existing.pages
            else datetime(2026, 1, 15, 9, 0, tzinfo=UTC)
        )
    )
    authored = author.add_markdown(
        page_markdown,
        style=style,
        background=background,
        layer=layer,
        auto_toc=auto_toc,
        extract_keywords=extract_keywords,
        default_page_date=next_dt,
        seed=seed,
    )
    appended = [
        SyntheticPage(
            page_index=info.page_index,
            page_id=info.page_id,
            text=info.text,
            created_at=next_dt + timedelta(seconds=sub_idx),
            headings=tuple(h.text for h in info.headings),
            keywords=tuple(k.keyword for k in info.keywords),
        )
        for sub_idx, info in enumerate(authored)
    ]
    return SyntheticNotebook(
        data=author.to_bytes(),
        file_id=author.file_id,
        pages=existing.pages + tuple(appended),
    )
