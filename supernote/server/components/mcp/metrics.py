"""Prometheus metrics definitions and instrumentation helpers for the MCP component."""

from __future__ import annotations

from collections.abc import Generator, Iterable
from contextlib import contextmanager

from prometheus_client import Counter, Histogram

from supernote.server.metrics import (
    REQUEST_DURATION_BUCKETS,
    OutcomeHandle,
    OutcomeStatus,
    track_outcome,
)

__all__ = [
    "init_mcp_metrics",
    "track_mcp_tool_call",
]


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


def init_mcp_metrics(tool_names: Iterable[str] = ()) -> None:
    """Pre-initialize MCP tool call counters and latency histograms at 0."""
    for tool in tool_names:
        tool_label = str(tool)
        _MCP_TOOL_DURATION_SECONDS.labels(tool=tool_label)
        for status in (OutcomeStatus.SUCCESS, OutcomeStatus.FAILURE):
            _MCP_TOOL_CALLS_TOTAL.labels(
                tool=tool_label,
                status=status.value,
            )


@contextmanager
def track_mcp_tool_call(
    *,
    tool: str,
) -> Generator[OutcomeHandle]:
    """Record Prometheus call count and completed latency for an MCP tool invocation."""
    with track_outcome(
        counter=_MCP_TOOL_CALLS_TOTAL,
        histogram=_MCP_TOOL_DURATION_SECONDS,
        labels={"tool": str(tool)},
    ) as handle:
        yield handle
