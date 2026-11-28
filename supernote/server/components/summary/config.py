"""Configuration model for the notebook summary (Digest) server component (`SummaryConfig`)."""

from __future__ import annotations

from dataclasses import dataclass

from mashumaro.mixins.json import DataClassJSONMixin

__all__ = ["SummaryConfig"]


@dataclass
class SummaryConfig(DataClassJSONMixin):
    """Per-component settings for `supernote.server.components.summary`."""

    enabled: bool = True
    """Whether the summary (Digest) component—including tablet Digest sync and AI summarization—is enabled."""

    max_pages_per_chunk: int = 8
    """Maximum non-blank pages sent to the LLM in a single summarization chunk.

    Large notebooks are split into ordered chunks of at most this many pages
    (preferring date boundaries) and stitched into one Digest summary. Set to
    `0` to disable chunking and summarize the entire notebook in one LLM call.
    """

    max_chars_per_chunk: int = 16_000
    """Maximum formatted transcript characters per summarization chunk.

    Prevents dense pages from exceeding prompt budgets even when a chunk has
    fewer than `max_pages_per_chunk` pages (a single oversized page still runs
    in its own 1-page chunk).
    """

    incremental: bool = True
    """Reuse cached per-chunk summaries when only part of a large notebook changes.

    When `True`, unchanged chunks are reused so appending or editing pages only
    re-summarizes modified chunks instead of re-sending the whole notebook.
    Changing the summary model, prompt type, or chunk settings automatically
    invalidates affected chunks, and explicit reprocessing of an unchanged
    notebook bypasses the cache. When `False`, every chunk is re-summarized
    from scratch on each run.
    """

    carry_over_context: bool = True
    """Pass the prior chunk's trailing segments (up to 2 segments / 1,200 chars) as read-only context to the next chunk.

    When `True`, chunks are summarized sequentially so undated continuation
    pages crossing a chunk boundary inherit the active date and topic from the
    preceding chunk (without re-sending earlier transcripts or rewriting prior
    chunks). When `False`, every chunk is summarized independently—avoiding
    cross-chunk cache cascades on mid-notebook edits, at the cost of undated
    boundary continuation pages potentially losing their date context.
    """

    def __post_init__(self) -> None:
        if self.max_pages_per_chunk < 0:
            raise ValueError("max_pages_per_chunk must be >= 0")
        if self.max_chars_per_chunk < 1:
            raise ValueError("max_chars_per_chunk must be >= 1")
