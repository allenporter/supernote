"""Unit tests for RecycleBinCleanupService and RecycleCleanupStats."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prometheus_client import REGISTRY

from supernote.server.services.file import FileService
from supernote.server.services.recycle_cleanup import (
    RecycleBinCleanupService,
    RecycleCleanupStats,
)


@pytest.fixture
def mock_file_service() -> MagicMock:
    """Fixture providing a mocked FileService instance."""
    mock = MagicMock(spec=FileService)
    mock.purge_recycle = AsyncMock(return_value=(0, 0))
    return mock


@pytest.fixture
def cleanup_service(mock_file_service: MagicMock) -> RecycleBinCleanupService:
    """Fixture providing RecycleBinCleanupService with test defaults."""
    return RecycleBinCleanupService(
        file_service=mock_file_service,
        retention_days=30,
        interval_seconds=86400.0,
        batch_size=100,
    )


def test_recycle_cleanup_stats_merge() -> None:
    """Verify merging RecycleCleanupStats correctly aggregates counts and bytes."""
    stats1 = RecycleCleanupStats(purged_count=5, bytes_freed=1024)
    stats2 = RecycleCleanupStats(purged_count=3, bytes_freed=512)

    stats1.merge(stats2)
    assert stats1.purged_count == 8
    assert stats1.bytes_freed == 1536

    default_stats = RecycleCleanupStats()
    assert default_stats.purged_count == 0
    assert default_stats.bytes_freed == 0


def test_service_initialization(mock_file_service: MagicMock) -> None:
    """Verify service initializes with explicit dependencies and parameter values."""
    service = RecycleBinCleanupService(
        file_service=mock_file_service,
        retention_days=14,
        interval_seconds=3600.0,
        batch_size=50,
    )
    assert service.file_service is mock_file_service
    assert service.retention_days == 14
    assert service.interval_seconds == 3600.0
    assert service.batch_size == 50
    assert not service._shutdown_event.is_set()
    assert service._polling_task is None


async def test_run_cleanup_single_batch(
    cleanup_service: RecycleBinCleanupService,
    mock_file_service: MagicMock,
) -> None:
    """Verify single batch sweep terminates when purged count is less than batch size."""
    mock_file_service.purge_recycle.return_value = (5, 2048)

    initial_runs = (
        REGISTRY.get_sample_value(
            "supernote_recycle_bin_cleanup_runs_total", {"status": "success"}
        )
        or 0.0
    )
    initial_items = (
        REGISTRY.get_sample_value("supernote_recycle_bin_cleanup_items_purged_total")
        or 0.0
    )
    initial_bytes = (
        REGISTRY.get_sample_value("supernote_recycle_bin_cleanup_bytes_freed_total")
        or 0.0
    )

    stats = await cleanup_service.run_cleanup()

    assert stats.purged_count == 5
    assert stats.bytes_freed == 2048
    assert mock_file_service.purge_recycle.call_count == 1

    call_args = mock_file_service.purge_recycle.call_args[1]
    assert call_args["limit"] == 100
    expected_cutoff = int((time.time() - (30 * 86400)) * 1000)
    assert abs(call_args["older_than_ms"] - expected_cutoff) < 5000

    assert (
        REGISTRY.get_sample_value(
            "supernote_recycle_bin_cleanup_runs_total", {"status": "success"}
        )
        == initial_runs + 1.0
    )
    assert (
        REGISTRY.get_sample_value("supernote_recycle_bin_cleanup_items_purged_total")
        == initial_items + 5.0
    )
    assert (
        REGISTRY.get_sample_value("supernote_recycle_bin_cleanup_bytes_freed_total")
        == initial_bytes + 2048.0
    )


async def test_run_cleanup_multiple_batches(
    cleanup_service: RecycleBinCleanupService,
    mock_file_service: MagicMock,
) -> None:
    """Verify batching continues until a batch returns fewer items than batch_size."""
    cleanup_service.batch_size = 10
    mock_file_service.purge_recycle.side_effect = [
        (10, 1000),
        (10, 1200),
        (3, 300),
    ]

    stats = await cleanup_service.run_cleanup()

    assert stats.purged_count == 23
    assert stats.bytes_freed == 2500
    assert mock_file_service.purge_recycle.call_count == 3


async def test_run_cleanup_custom_arguments(
    cleanup_service: RecycleBinCleanupService,
    mock_file_service: MagicMock,
) -> None:
    """Verify run_cleanup respects explicitly passed retention_days and batch_size."""
    mock_file_service.purge_recycle.return_value = (0, 0)

    stats = await cleanup_service.run_cleanup(retention_days=7, batch_size=25)

    assert stats.purged_count == 0
    assert stats.bytes_freed == 0
    assert mock_file_service.purge_recycle.call_count == 1

    call_args = mock_file_service.purge_recycle.call_args[1]
    assert call_args["limit"] == 25
    expected_cutoff = int((time.time() - (7 * 86400)) * 1000)
    assert abs(call_args["older_than_ms"] - expected_cutoff) < 5000


async def test_run_cleanup_failure_metrics_and_reraise(
    cleanup_service: RecycleBinCleanupService,
    mock_file_service: MagicMock,
) -> None:
    """Verify failure increments failure metric and re-raises exception."""
    mock_file_service.purge_recycle.side_effect = RuntimeError("Database error")

    initial_failures = (
        REGISTRY.get_sample_value(
            "supernote_recycle_bin_cleanup_runs_total", {"status": "failure"}
        )
        or 0.0
    )

    with pytest.raises(RuntimeError, match="Database error"):
        await cleanup_service.run_cleanup()

    assert (
        REGISTRY.get_sample_value(
            "supernote_recycle_bin_cleanup_runs_total", {"status": "failure"}
        )
        == initial_failures + 1.0
    )


async def test_run_cleanup_stops_when_shutdown_set(
    cleanup_service: RecycleBinCleanupService,
    mock_file_service: MagicMock,
) -> None:
    """Verify run_cleanup immediately exits without running queries if shutdown event is set."""
    cleanup_service._shutdown_event.set()

    stats = await cleanup_service.run_cleanup()

    assert stats.purged_count == 0
    assert stats.bytes_freed == 0
    assert mock_file_service.purge_recycle.call_count == 0


async def test_service_start_and_stop_lifecycle(
    cleanup_service: RecycleBinCleanupService,
) -> None:
    """Verify service start and stop cleanly manage the polling task and shutdown event."""
    assert cleanup_service._polling_task is None
    assert not cleanup_service._shutdown_event.is_set()

    await cleanup_service.start()
    assert cleanup_service._polling_task is not None
    assert not cleanup_service._polling_task.done()

    await cleanup_service.stop()
    assert cleanup_service._shutdown_event.is_set()
    assert cleanup_service._polling_task is None


async def test_service_start_when_already_running_is_noop(
    cleanup_service: RecycleBinCleanupService,
) -> None:
    """Verify calling start() when already running logs warning and does not duplicate polling task."""
    await cleanup_service.start()
    task1 = cleanup_service._polling_task
    assert task1 is not None

    # Second start call while running
    await cleanup_service.start()
    assert cleanup_service._polling_task is task1

    await cleanup_service.stop()
    assert cleanup_service._polling_task is None


async def test_polling_loop_triggers_cleanup(
    mock_file_service: MagicMock,
) -> None:
    """Verify background polling loop periodically executes run_cleanup."""
    service = RecycleBinCleanupService(
        file_service=mock_file_service,
        retention_days=30,
        interval_seconds=0.01,
        batch_size=10,
    )
    cleanup_called = asyncio.Event()

    async def fake_cleanup(*_args, **_kwargs) -> RecycleCleanupStats:
        cleanup_called.set()
        return RecycleCleanupStats(purged_count=1, bytes_freed=100)

    with patch.object(service, "run_cleanup", side_effect=fake_cleanup):
        await service.start()
        await asyncio.wait_for(cleanup_called.wait(), timeout=1.0)
        await service.stop()

    assert cleanup_called.is_set()


async def test_polling_loop_handles_exception_resiliently(
    mock_file_service: MagicMock,
) -> None:
    """Verify background polling loop catches exceptions from run_cleanup and continues."""
    service = RecycleBinCleanupService(
        file_service=mock_file_service,
        retention_days=30,
        interval_seconds=0.01,
        batch_size=10,
    )
    cleanup_attempts = 0
    completed_event = asyncio.Event()

    async def failing_then_success_cleanup(*_args, **_kwargs) -> RecycleCleanupStats:
        nonlocal cleanup_attempts
        cleanup_attempts += 1
        if cleanup_attempts == 1:
            raise ValueError("Transient loop failure")
        completed_event.set()
        return RecycleCleanupStats()

    with patch.object(service, "run_cleanup", side_effect=failing_then_success_cleanup):
        await service.start()
        await asyncio.wait_for(completed_event.wait(), timeout=1.0)
        await service.stop()

    assert cleanup_attempts >= 2


def test_service_initialization_invalid_arguments(
    mock_file_service: MagicMock,
) -> None:
    """Verify service rejects invalid retention_days, batch_size, or interval_seconds."""
    with pytest.raises(ValueError, match="retention_days cannot be negative"):
        RecycleBinCleanupService(mock_file_service, retention_days=-1)

    with pytest.raises(ValueError, match="batch_size must be positive"):
        RecycleBinCleanupService(mock_file_service, batch_size=0)

    with pytest.raises(ValueError, match="interval_seconds must be positive"):
        RecycleBinCleanupService(mock_file_service, interval_seconds=0)


async def test_run_cleanup_invalid_arguments(
    cleanup_service: RecycleBinCleanupService,
) -> None:
    """Verify run_cleanup rejects negative retention_days or non-positive batch_size."""
    with pytest.raises(ValueError, match="retention_days cannot be negative"):
        await cleanup_service.run_cleanup(retention_days=-5)

    with pytest.raises(ValueError, match="batch_size must be positive"):
        await cleanup_service.run_cleanup(batch_size=0)

    with pytest.raises(ValueError, match="batch_size must be positive"):
        await cleanup_service.run_cleanup(batch_size=-10)


async def test_run_cleanup_breaks_on_zero_purged(
    cleanup_service: RecycleBinCleanupService,
    mock_file_service: MagicMock,
) -> None:
    """Verify run_cleanup terminates immediately when purge_recycle returns zero items."""
    mock_file_service.purge_recycle.return_value = (0, 0)

    stats = await cleanup_service.run_cleanup()
    assert stats.purged_count == 0
    assert stats.bytes_freed == 0
    assert mock_file_service.purge_recycle.call_count == 1
