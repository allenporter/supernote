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
    "PROCESSOR_FILES_PROCESSING",
    "PROCESSOR_MISSING_TASKS_RECOVERED_TOTAL",
    "PROCESSOR_QUEUE_SIZE",
    "PROCESSOR_STALLED_TASKS_RECOVERED_TOTAL",
    "PROCESSOR_TASKS_TOTAL",
    "PROCESSOR_TASK_DURATION_SECONDS",
    "init_ai_metrics",
    "record_ai_tokens",
    "track_ai_request",
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


class AIStage(StrEnum):
    """Canonical pipeline/query stage labels for AI model metrics."""

    OCR = "ocr"
    SUMMARY = "summary"
    EMBEDDING_DOCUMENT = "embedding_doc"
    EMBEDDING_QUERY = "embedding_query"


class _AIRequestStatus(StrEnum):
    """Terminal status labels for logical AI model invocations."""

    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"


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
)

PROCESSOR_QUEUE_SIZE: Gauge = Gauge(
    "supernote_processor_queue_size",
    "Current size of the background processor queue.",
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
    for status in (_AIRequestStatus.SUCCESS, _AIRequestStatus.FAILURE):
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
    status = _AIRequestStatus.FAILURE
    try:
        yield
        status = _AIRequestStatus.SUCCESS
    except asyncio.CancelledError:
        status = _AIRequestStatus.CANCELLED
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
        if status != _AIRequestStatus.CANCELLED:
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
