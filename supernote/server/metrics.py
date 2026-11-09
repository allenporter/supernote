"""Prometheus metrics definition module for Supernote Private Cloud Server."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum

from prometheus_client import Counter, Gauge, Histogram

__all__ = [
    "AIStage",
    "BlobStorageKind",
    "DB_SESSIONS_ACTIVE",
    "DB_SESSION_ERRORS_TOTAL",
    "HTTP_REQUESTS_IN_PROGRESS",
    "HTTP_REQUESTS_TOTAL",
    "HTTP_REQUEST_DURATION_SECONDS",
    "MCPToolName",
    "NoteProcessingMode",
    "NoteUploadSource",
    "OSSTransferDirection",
    "OSSTransferKind",
    "PROCESSOR_FILES_PROCESSING",
    "PROCESSOR_MISSING_TASKS_RECOVERED_TOTAL",
    "PROCESSOR_QUEUE_PAUSED",
    "PROCESSOR_QUEUE_SIZE",
    "PROCESSOR_STALLED_TASKS_RECOVERED_TOTAL",
    "PROCESSOR_TASKS_TOTAL",
    "PROCESSOR_TASK_DURATION_SECONDS",
    "init_ai_metrics",
    "init_mcp_metrics",
    "init_note_processing_metrics",
    "init_oss_and_upload_metrics",
    "record_ai_tokens",
    "record_note_page_diff",
    "record_note_upload",
    "record_oss_transfer_bytes",
    "set_blob_storage_metrics",
    "track_ai_request",
    "track_mcp_tool_call",
    "track_note_processing_run",
]

REQUEST_DURATION_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
)

PIPELINE_DURATION_BUCKETS: tuple[float, ...] = (
    0.01,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
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
    """Terminal status labels for tracked operations."""

    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"


class _OutcomeHandle:
    """Mutable outcome handle for tracked operations whose success is decided inline."""

    def __init__(self) -> None:
        self._succeeded = False

    def set_succeeded(self, succeeded: bool) -> None:
        """Record whether the tracked operation succeeded."""
        self._succeeded = succeeded


@contextmanager
def _track_outcome(
    *,
    counter: Counter,
    histogram: Histogram,
    labels: Mapping[str, str],
    default_succeeded: bool = False,
) -> Generator[_OutcomeHandle]:
    """Shared outcome counter and non-cancelled duration observer."""
    handle = _OutcomeHandle()
    start_time = time.monotonic()
    status = _OutcomeStatus.FAILURE
    try:
        yield handle
        if default_succeeded or handle._succeeded:
            status = _OutcomeStatus.SUCCESS
    except asyncio.CancelledError:
        status = _OutcomeStatus.CANCELLED
        raise
    finally:
        duration = time.monotonic() - start_time
        counter.labels(**labels, status=status.value).inc()
        if status != _OutcomeStatus.CANCELLED:
            histogram.labels(**labels).observe(duration)


class _NotePageChangeType(StrEnum):
    """Mutually exclusive reconciliation outcomes for `.note` pages."""

    ADDED = "added"
    MODIFIED = "modified"
    MOVED = "moved"
    UNCHANGED = "unchanged"
    DELETED = "deleted"


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
    buckets=REQUEST_DURATION_BUCKETS,
)

HTTP_REQUESTS_IN_PROGRESS: Gauge = Gauge(
    "supernote_http_requests_in_progress",
    "Current number of HTTP requests actively being processed.",
    ["method"],
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
    buckets=PIPELINE_DURATION_BUCKETS,
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
    buckets=PIPELINE_DURATION_BUCKETS,
)

_NOTE_PAGES_PARSED_TOTAL: Counter = Counter(
    "supernote_note_pages_parsed_total",
    "Total number of .note pages reconciled during page hashing by change type.",
    ["change_type"],
)


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
    """Record mutually exclusive `.note` page diff counts."""
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


@contextmanager
def track_note_processing_run(
    *,
    mode: NoteProcessingMode,
) -> Generator[_OutcomeHandle]:
    """Record Prometheus run count and completed latency for a `.note` pipeline run."""
    with _track_outcome(
        counter=_NOTE_PROCESSING_RUNS_TOTAL,
        histogram=_NOTE_PROCESSING_DURATION_SECONDS,
        labels={"mode": mode.value},
    ) as handle:
        yield handle


class OSSTransferDirection(StrEnum):
    """Transfer direction labels for OSS byte transfer metrics."""

    UPLOAD = "upload"
    DOWNLOAD = "download"


class OSSTransferKind(StrEnum):
    """Payload kind labels for OSS byte transfer metrics."""

    USER_BLOB = "user_blob"
    USER_CHUNK = "user_chunk"
    PNG_PREVIEW = "png_preview"
    PDF_EXPORT = "pdf_export"


class NoteUploadSource(StrEnum):
    """Origin API labels for completed `.note` file uploads."""

    DEVICE_SYNC = "device_sync"
    WEB = "web"


_OSS_TRANSFER_SERIES: tuple[tuple[OSSTransferDirection, OSSTransferKind], ...] = (
    (OSSTransferDirection.UPLOAD, OSSTransferKind.USER_BLOB),
    (OSSTransferDirection.UPLOAD, OSSTransferKind.USER_CHUNK),
    (OSSTransferDirection.DOWNLOAD, OSSTransferKind.USER_BLOB),
    (OSSTransferDirection.DOWNLOAD, OSSTransferKind.PNG_PREVIEW),
    (OSSTransferDirection.DOWNLOAD, OSSTransferKind.PDF_EXPORT),
)

_OSS_TRANSFER_BYTES_TOTAL: Counter = Counter(
    "supernote_oss_transfer_bytes_total",
    "Total number of OSS object bytes transferred by direction and payload kind.",
    ["direction", "kind"],
)

_NOTE_UPLOADS_TOTAL: Counter = Counter(
    "supernote_note_uploads_total",
    "Total number of completed .note file uploads by source.",
    ["source"],
)


def init_oss_and_upload_metrics() -> None:
    """Pre-initialize OSS byte transfer and `.note` upload counter series at 0."""
    for direction, kind in _OSS_TRANSFER_SERIES:
        _OSS_TRANSFER_BYTES_TOTAL.labels(
            direction=direction.value,
            kind=kind.value,
        )
    for source in NoteUploadSource:
        _NOTE_UPLOADS_TOTAL.labels(source=source.value)


def record_oss_transfer_bytes(
    *,
    direction: OSSTransferDirection,
    kind: OSSTransferKind,
    byte_count: int,
) -> None:
    """Record OSS object bytes transferred when `byte_count` is positive."""
    if byte_count > 0:
        _OSS_TRANSFER_BYTES_TOTAL.labels(
            direction=direction.value,
            kind=kind.value,
        ).inc(byte_count)


def record_note_upload(
    *,
    source: NoteUploadSource,
) -> None:
    """Record a completed `.note` file upload for `source`."""
    _NOTE_UPLOADS_TOTAL.labels(source=source.value).inc()


class BlobStorageKind(StrEnum):
    """Payload kind labels for blob storage inventory gauges."""

    USER_BLOB = "user_blob"
    PNG = "png"
    PDF = "pdf"


_BLOB_STORAGE_OBJECTS: Gauge = Gauge(
    "supernote_blob_storage_objects",
    "Current number of stored blobs by bucket and payload kind.",
    ["bucket", "kind"],
)

_BLOB_STORAGE_BYTES: Gauge = Gauge(
    "supernote_blob_storage_bytes",
    "Current total size in bytes of stored blobs by bucket and payload kind.",
    ["bucket", "kind"],
)

_BLOB_STORAGE_AVAILABLE_BYTES: Gauge = Gauge(
    "supernote_blob_storage_available_bytes",
    "Current available free bytes on the storage backend backing blob storage.",
)


def set_blob_storage_metrics(
    *,
    counts: Mapping[tuple[str, BlobStorageKind], tuple[int, int]],
    available_bytes: int | None = None,
) -> None:
    """Update blob storage object count, byte size, and available free space gauges."""
    for (bucket, kind), (objects, byte_count) in counts.items():
        _BLOB_STORAGE_OBJECTS.labels(bucket=bucket, kind=kind.value).set(
            max(0, objects)
        )
        _BLOB_STORAGE_BYTES.labels(bucket=bucket, kind=kind.value).set(
            max(0, byte_count)
        )
    if available_bytes is not None:
        _BLOB_STORAGE_AVAILABLE_BYTES.set(max(0, available_bytes))


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
    buckets=PIPELINE_DURATION_BUCKETS,
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
    try:
        with _track_outcome(
            counter=_AI_REQUESTS_TOTAL,
            histogram=_AI_REQUEST_DURATION_SECONDS,
            labels={
                "provider": provider,
                "model": model,
                "stage": stage.value,
            },
            default_succeeded=True,
        ):
            yield
    finally:
        _active_ai_request.reset(token)


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


# MCP server metrics
class MCPToolName(StrEnum):
    """Canonical tool name labels for MCP server metrics."""

    LIST_NOTEBOOKS = "list_notebooks"
    SEARCH_NOTEBOOK_CHUNKS = "search_notebook_chunks"
    GET_NOTEBOOK_TRANSCRIPT = "get_notebook_transcript"


_MCP_TOOL_CALLS_TOTAL: Counter = Counter(
    "supernote_mcp_tool_calls_total",
    "Total number of MCP tool invocations.",
    ["tool", "status"],
)

_MCP_TOOL_DURATION_SECONDS: Histogram = Histogram(
    "supernote_mcp_tool_duration_seconds",
    "Latency of completed MCP tool invocations in seconds.",
    ["tool"],
    buckets=REQUEST_DURATION_BUCKETS,
)


def init_mcp_metrics() -> None:
    """Pre-initialize MCP tool call `success` and `failure` counter series at 0."""
    for tool in MCPToolName:
        for status in (_OutcomeStatus.SUCCESS, _OutcomeStatus.FAILURE):
            _MCP_TOOL_CALLS_TOTAL.labels(
                tool=tool.value,
                status=status.value,
            )


@contextmanager
def track_mcp_tool_call(
    *,
    tool: MCPToolName,
) -> Generator[_OutcomeHandle]:
    """Record Prometheus call count and completed latency for an MCP tool invocation."""
    with _track_outcome(
        counter=_MCP_TOOL_CALLS_TOTAL,
        histogram=_MCP_TOOL_DURATION_SECONDS,
        labels={"tool": tool.value},
    ) as handle:
        yield handle


# Database metrics
DB_SESSIONS_ACTIVE: Gauge = Gauge(
    "supernote_db_sessions_active",
    "Current number of active/open database sessions.",
)

DB_SESSION_ERRORS_TOTAL: Counter = Counter(
    "supernote_db_session_errors_total",
    "Total number of database and SQLAlchemy session errors.",
)
