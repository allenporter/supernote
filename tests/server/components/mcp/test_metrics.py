"""Unit tests for `supernote.server.components.mcp.metrics`."""

from __future__ import annotations

import asyncio

import pytest
from prometheus_client import REGISTRY

from supernote.server.components.mcp.metrics import (
    init_mcp_metrics,
    track_mcp_tool_call,
)
from supernote.server.metrics import REQUEST_DURATION_BUCKETS


def _call_count(tool: str, status: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_calls_total",
            {"tool": tool, "status": status},
        )
        or 0.0
    )


def _duration_count(tool: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_duration_seconds_count",
            {"tool": tool},
        )
        or 0.0
    )


def test_init_mcp_metrics_seeds_tools() -> None:
    """Verify `init_mcp_metrics` pre-seeds counters and latency histograms at 0."""
    init_mcp_metrics(["custom_seeded_tool"])
    assert (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_duration_seconds_count",
            {"tool": "custom_seeded_tool"},
        )
        == 0.0
    )
    for status in ("success", "failure"):
        assert (
            REGISTRY.get_sample_value(
                "supernote_mcp_tool_calls_total",
                {"tool": "custom_seeded_tool", "status": status},
            )
            == 0.0
        )


def test_mcp_tool_duration_histogram_buckets() -> None:
    """Verify `supernote_mcp_tool_duration_seconds` exports exact `REQUEST_DURATION_BUCKETS`."""
    tool_name = "bucket_test_tool"
    init_mcp_metrics([tool_name])

    metric_families = {
        family.name: family
        for family in REGISTRY.collect()
        if family.name == "supernote_mcp_tool_duration_seconds"
    }
    assert "supernote_mcp_tool_duration_seconds" in metric_families
    family = metric_families["supernote_mcp_tool_duration_seconds"]
    finite_bounds = tuple(
        float(sample.labels["le"])
        for sample in family.samples
        if sample.name == "supernote_mcp_tool_duration_seconds_bucket"
        and sample.labels.get("tool") == tool_name
        and sample.labels["le"] != "+Inf"
    )
    assert finite_bounds == REQUEST_DURATION_BUCKETS
    assert (
        REGISTRY.get_sample_value(
            "supernote_mcp_tool_duration_seconds_bucket",
            {"tool": tool_name, "le": "+Inf"},
        )
        is not None
    )


def test_track_mcp_tool_call_success_and_failure() -> None:
    """Verify `track_mcp_tool_call` records success, failure, and exception outcomes."""
    tool = "unit_test_tool"
    before_ok = _call_count(tool, "success")
    before_fail = _call_count(tool, "failure")
    before_dur = _duration_count(tool)

    with track_mcp_tool_call(tool=tool) as call:
        call.set_succeeded(True)

    with track_mcp_tool_call(tool=tool):
        pass

    with pytest.raises(RuntimeError, match="boom"):
        with track_mcp_tool_call(tool=tool) as call:
            call.set_succeeded(True)
            raise RuntimeError("boom")

    assert _call_count(tool, "success") == before_ok + 1.0
    assert _call_count(tool, "failure") == before_fail + 2.0
    assert _duration_count(tool) == before_dur + 3.0


def test_track_mcp_tool_call_cancelled_after_set_succeeded() -> None:
    """Verify cancellation overrides a prior `set_succeeded(True)` without observing latency."""
    tool = "cancelled_test_tool"
    before_ok = _call_count(tool, "success")
    before_cancel = _call_count(tool, "cancelled")
    before_dur = _duration_count(tool)

    with pytest.raises(asyncio.CancelledError):
        with track_mcp_tool_call(tool=tool) as call:
            call.set_succeeded(True)
            raise asyncio.CancelledError

    assert _call_count(tool, "success") == before_ok
    assert _call_count(tool, "cancelled") == before_cancel + 1.0
    assert _duration_count(tool) == before_dur
