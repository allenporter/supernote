"""Prometheus metrics definition module for Supernote Private Cloud Server."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum

from prometheus_client import Counter, Gauge, Histogram

__all__ = [
    "AIStage",
    "DB_SESSIONS_ACTIVE",
    "DB_SESSION_ERRORS_TOTAL",
    "HTTP_REQUESTS_TOTAL",
    "HTTP_REQUEST_DURATION_SECONDS",
    "NoteProcessingMode",
    "PROCESSOR_FILES_PROCESSING",
    "PROCESSOR_MISSING_TASKS_RECOVERED_TOTAL",
    "PROCESSOR_QUEUE_PAUSED",
    "PROCESSOR_QUEUE_SIZE",
    "PROCESSOR_STALLED_TASKS_RECOVERED_TOTAL",
    "PROCESSOR_TASKS_TOTAL",
    "PROCESSOR_TASK_DURATION_SECONDS",
    "init_ai_metrics",
    "init_note_processing_metrics",
    "record_ai_tokens",
    "record_note_page_diff",
    "track_ai_request",
    "track_note_processing_run",
]

AI_LATENCY_BUCKETS: tuple[float, ...] = (
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    20.0,
    45.0,
    90.0,
    180.0,
    300.0,
    600.0,
)

NOTE_PROCESSING_DURATION_BUCKETS: tuple[float, ...] = (
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    20.0,
    45.0,
    90.0,
    180.0,
    300.0,
    600.0,
)

NOTE_PAGES_PER_RUN_BUCKETS: tuple[float, ...] = (
    0.0,
    1.0,
    2.0,
    5.0,
    10.0,
    20.0,
    50.0,
    100.0,
    250.0,
    500.0,
    1000.0,
)

PROCESSOR_TASK_DURATION_BUCKETS: tuple[float, ...] = (
    0.01,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    20.0,
    45.0,
    90.0,
    180.0,
    300.0,
    600.0,
)


class AIStage(StrEnum):
    """Canonical pipeline/query stage labels for AI model metrics."""

    OCR = "ocr"
    SUMMARY = "summary"
    EMBEDDING_DOCUMENT = "embedding_doc"
    EMBEDDING_QUERY = "embedding_query"


class NoteProcessingMode(StrEnum):
    """Execution mode labels for `.note` pipeline processing runs."""

    FULL = "full"
    ON_DEMAND = "on_demand"


class _OutcomeStatus(StrEnum):
    """Terminal status labels for logical AI and `.note` pipeline runs."""

    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"


class _NotePageChangeType(StrEnum):
    """Mutually exclusive reconciliation outcomes for `.note` pages."""

    ADDED = "added"
    MODIFIED = "modified"
    MOVED = "moved"
    UNCHANGED = "unchanged"
    DELETED = "deleted"


class _NotePageScope(StrEnum):
    """Scope labels for per-`.note` page count distributions."""

    TOTAL = "total"
    DIRTY = "dirty"


class _AITokenType(StrEnum):
    """Mutually exclusive token category labels for AI token metrics.

    Categories are disjoint (`input` + `output` + `thinking` == total billed
    tokens): `output` counts visible completion tokens excluding `thinking`
    (reasoning) tokens.
    """

    INPUT = "input"
    OUTPUT = "output"
    THINKING = "thinking"


@dataclass(frozen=True)
class _ActiveAIRequest:
    """Active AI model request metadata used to attribute downstream token usage."""

    provider: str
    model: str
    stage: AIStage


_active_ai_request: ContextVar[_ActiveAIRequest | None] = ContextVar(
    "active_ai_request", default=None
)

# HTTP metrics
HTTP_REQUESTS_TOTAL: Counter = Counter(
    "supernote_http_requests_total",
    "Total number of HTTP requests processed.",
    ["method", "path", "status"],
)

HTTP_REQUEST_DURATION_SECONDS: Histogram = Histogram(
    "supernote_http_request_duration_seconds",
    "Latency of HTTP requests in seconds.",
    ["method", "path"],
)

# Processor metrics
PROCESSOR_TASKS_TOTAL: Counter = Counter(
    "supernote_processor_tasks_total",
    "Total number of background pipeline task runs.",
    ["module", "status"],
)

PROCESSOR_TASK_DURATION_SECONDS: Histogram = Histogram(
    "supernote_processor_task_duration_seconds",
    "Latency of background pipeline tasks in seconds.",
    ["module"],
    buckets=PROCESSOR_TASK_DURATION_BUCKETS,
)

PROCESSOR_QUEUE_SIZE: Gauge = Gauge(
    "supernote_processor_queue_size",
    "Current size of the background processor queue.",
)

PROCESSOR_QUEUE_PAUSED: Gauge = Gauge(
    "supernote_processor_queue_paused",
    "Whether background processor queue execution is currently paused (1 = paused, 0 = active).",
)

PROCESSOR_FILES_PROCESSING: Gauge = Gauge(
    "supernote_processor_files_processing",
    "Current number of files actively undergoing background pipeline processing.",
)

PROCESSOR_STALLED_TASKS_RECOVERED_TOTAL: Counter = Counter(
    "supernote_processor_stalled_tasks_recovered_total",
    "Total number of stalled processing tasks recovered.",
)

PROCESSOR_MISSING_TASKS_RECOVERED_TOTAL: Counter = Counter(
    "supernote_processor_missing_tasks_recovered_total",
    "Total number of missing tasks recovered/enqueued.",
)

_NOTE_PROCESSING_RUNS_TOTAL: Counter = Counter(
    "supernote_note_processing_runs_total",
    "Total number of .note pipeline processing runs.",
    ["mode", "status"],
)

_NOTE_PROCESSING_DURATION_SECONDS: Histogram = Histogram(
    "supernote_note_processing_duration_seconds",
    "End-to-end latency of completed .note pipeline processing runs in seconds (excluding per-file lock wait).",
    ["mode"],
    buckets=NOTE_PROCESSING_DURATION_BUCKETS,
)

_NOTE_PAGES_PARSED_TOTAL: Counter = Counter(
    "supernote_note_pages_parsed_total",
    "Total number of .note pages reconciled during page hashing by change type.",
    ["change_type"],
)

_NOTE_PAGES_PER_RUN: Histogram = Histogram(
    "supernote_note_pages_per_run",
    "Number of pages per .note page-hashing run (total notebook pages vs dirty added/modified pages).",
    ["scope"],
    buckets=NOTE_PAGES_PER_RUN_BUCKETS,
)


class NoteProcessingRun:
    """Mutable outcome handle for an active `.note` pipeline processing run."""

    def __init__(self) -> None:
        self._succeeded = False

    def set_succeeded(self, succeeded: bool) -> None:
        """Record whether all requested stages of the pipeline run succeeded."""
        self._succeeded = succeeded


def init_note_processing_metrics() -> None:
    """Pre-initialize `.note` run and page-diff counter series at 0."""
    for mode in NoteProcessingMode:
        for status in (_OutcomeStatus.SUCCESS, _OutcomeStatus.FAILURE):
            _NOTE_PROCESSING_RUNS_TOTAL.labels(
                mode=mode.value,
                status=status.value,
            )
    for change_type in _NotePageChangeType:
        _NOTE_PAGES_PARSED_TOTAL.labels(change_type=change_type.value)


def record_note_page_diff(
    *,
    added: int = 0,
    modified: int = 0,
    moved: int = 0,
    unchanged: int = 0,
    deleted: int = 0,
) -> None:
    """Record mutually exclusive `.note` page diff counts and per-run page distributions."""
    counts = (
        (_NotePageChangeType.ADDED, max(0, added)),
        (_NotePageChangeType.MODIFIED, max(0, modified)),
        (_NotePageChangeType.MOVED, max(0, moved)),
        (_NotePageChangeType.UNCHANGED, max(0, unchanged)),
        (_NotePageChangeType.DELETED, max(0, deleted)),
    )
    for change_type, count in counts:
        if count > 0:
            _NOTE_PAGES_PARSED_TOTAL.labels(change_type=change_type.value).inc(count)

    total_pages = max(0, added) + max(0, modified) + max(0, moved) + max(0, unchanged)
    dirty_pages = max(0, added) + max(0, modified)
    _NOTE_PAGES_PER_RUN.labels(scope=_NotePageScope.TOTAL.value).observe(total_pages)
    _NOTE_PAGES_PER_RUN.labels(scope=_NotePageScope.DIRTY.value).observe(dirty_pages)


@contextmanager
def track_note_processing_run(
    *,
    mode: NoteProcessingMode,
) -> Generator[NoteProcessingRun]:
    """Record Prometheus run count and completed latency for a `.note` pipeline run."""
    run = NoteProcessingRun()
    start_time = time.monotonic()
    status = _OutcomeStatus.FAILURE
    try:
        yield run
        if run._succeeded:
            status = _OutcomeStatus.SUCCESS
    except asyncio.CancelledError:
        status = _OutcomeStatus.CANCELLED
        raise
    finally:
        duration = time.monotonic() - start_time
        _NOTE_PROCESSING_RUNS_TOTAL.labels(
            mode=mode.value,
            status=status.value,
        ).inc()
        if status != _OutcomeStatus.CANCELLED:
            _NOTE_PROCESSING_DURATION_SECONDS.labels(mode=mode.value).observe(duration)


# AI model metrics
_AI_REQUESTS_TOTAL: Counter = Counter(
    "supernote_ai_requests_total",
    "Total number of logical AI model invocations.",
    ["provider", "model", "stage", "status"],
)

_AI_REQUEST_DURATION_SECONDS: Histogram = Histogram(
    "supernote_ai_request_duration_seconds",
    "Latency of completed AI model invocations in seconds (excluding concurrency queue wait).",
    ["provider", "model", "stage"],
    buckets=AI_LATENCY_BUCKETS,
)

_AI_TOKENS_TOTAL: Counter = Counter(
    "supernote_ai_tokens_total",
    "Total number of mutually exclusive tokens processed by AI models (when reported by provider).",
    ["provider", "model", "stage", "token_type"],
)


def init_ai_metrics(
    *,
    provider: str,
    model: str,
    stage: AIStage,
) -> None:
    """Pre-initialize `success` and `failure` counter series at 0 for rate()/increase()."""
    for status in (_OutcomeStatus.SUCCESS, _OutcomeStatus.FAILURE):
        _AI_REQUESTS_TOTAL.labels(
            provider=provider,
            model=model,
            stage=stage.value,
            status=status.value,
        )


@contextmanager
def track_ai_request(
    *,
    provider: str,
    model: str,
    stage: AIStage,
) -> Generator[None]:
    """Record Prometheus request count and latency for an AI model invocation."""
    token = _active_ai_request.set(
        _ActiveAIRequest(provider=provider, model=model, stage=stage)
    )
    start_time = time.monotonic()
    status = _OutcomeStatus.FAILURE
    try:
        yield
        status = _OutcomeStatus.SUCCESS
    except asyncio.CancelledError:
        status = _OutcomeStatus.CANCELLED
        raise
    finally:
        duration = time.monotonic() - start_time
        _active_ai_request.reset(token)
        _AI_REQUESTS_TOTAL.labels(
            provider=provider,
            model=model,
            stage=stage.value,
            status=status.value,
        ).inc()
        if status != _OutcomeStatus.CANCELLED:
            _AI_REQUEST_DURATION_SECONDS.labels(
                provider=provider,
                model=model,
                stage=stage.value,
            ).observe(duration)


def _coerce_positive_tokens(value: object) -> int | None:
    """Safely coerce a raw provider token count to a positive int, never raising."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and math.isfinite(value) and value > 0:
        coerced = int(value)
        return coerced if coerced > 0 else None
    return None


def record_ai_tokens(
    *,
    provider: str,
    input_tokens: object = None,
    output_tokens: object = None,
    thinking_tokens: object = None,
) -> None:
    """Record token usage for the active AI model request when `provider` matches.

    Token values are raw provider payload values; missing, non-numeric,
    non-finite, or non-positive values are ignored.
    """
    active = _active_ai_request.get()
    if active is None or active.provider != provider:
        return

    for token_type, raw_count in (
        (_AITokenType.INPUT, input_tokens),
        (_AITokenType.OUTPUT, output_tokens),
        (_AITokenType.THINKING, thinking_tokens),
    ):
        count = _coerce_positive_tokens(raw_count)
        if count is not None:
            _AI_TOKENS_TOTAL.labels(
                provider=active.provider,
                model=active.model,
                stage=active.stage.value,
                token_type=token_type.value,
            ).inc(count)


# Database metrics
DB_SESSIONS_ACTIVE: Gauge = Gauge(
    "supernote_db_sessions_active",
    "Current number of active/open database sessions.",
)

DB_SESSION_ERRORS_TOTAL: Counter = Counter(
    "supernote_db_session_errors_total",
    "Total number of database session errors causing rollbacks.",
)
