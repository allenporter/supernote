"""Tests for StorageCleanupService."""

import asyncio
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY

from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.services.blob import CleanupStats, LocalBlobStorage
from supernote.server.services.storage_cleanup import StorageCleanupService


@pytest.fixture
def storage(tmp_path: Path) -> LocalBlobStorage:
    """Fixture providing a LocalBlobStorage instance rooted in tmp_path."""
    return LocalBlobStorage(tmp_path)


@pytest.fixture
def cleanup_service(storage: LocalBlobStorage) -> StorageCleanupService:
    """Fixture providing StorageCleanupService initialized with explicit primitive parameters."""
    return StorageCleanupService(
        blob_storage=storage,
        interval_seconds=3600.0,
        temp_ttl_seconds=3600.0,
        buckets=(USER_DATA_BUCKET,),
    )


@pytest.fixture
def temp_staging_dir(tmp_path: Path) -> Path:
    """Fixture providing the temporary staging directory."""
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


@pytest.fixture
def sample_stale_staging_file(temp_staging_dir: Path) -> tuple[Path, bytes]:
    """Fixture creating a stale staging .tmp file older than TTL."""
    stale_file = temp_staging_dir / "stale.tmp"
    content = b"stale_bytes_123"
    stale_file.write_bytes(content)
    now = time.time()
    os.utime(stale_file, (now - 5000, now - 5000))
    return stale_file, content


@pytest.fixture
async def sample_chunks(storage: LocalBlobStorage) -> tuple[list[Path], int]:
    """Fixture creating abandoned multipart chunks in USER_DATA_BUCKET older than TTL."""
    c1 = b"part1_data"
    c2 = b"part2_data"
    await storage.put(USER_DATA_BUCKET, "file1.note.part.1", c1)
    await storage.put(USER_DATA_BUCKET, "file1.note.part.2", c2)
    p1 = storage.get_blob_path(USER_DATA_BUCKET, "file1.note.part.1")
    p2 = storage.get_blob_path(USER_DATA_BUCKET, "file1.note.part.2")

    now = time.time()
    os.utime(p1, (now - 7200, now - 7200))
    os.utime(p2, (now - 7000, now - 7000))
    return [p1, p2], len(c1) + len(c2)


async def test_run_staging_cleanup(
    cleanup_service: StorageCleanupService,
    sample_stale_staging_file: tuple[Path, bytes],
) -> None:
    """Verify run_staging_cleanup prunes staging files and increments metrics."""
    stale_file, content = sample_stale_staging_file
    initial_files = (
        REGISTRY.get_sample_value("supernote_storage_cleanup_temp_files_removed_total")
        or 0.0
    )
    initial_bytes = (
        REGISTRY.get_sample_value("supernote_storage_cleanup_bytes_reclaimed_total")
        or 0.0
    )

    stats = await cleanup_service.run_staging_cleanup()
    assert stats == CleanupStats(files_removed=1, bytes_reclaimed=len(content))
    assert not stale_file.exists()

    assert (
        REGISTRY.get_sample_value("supernote_storage_cleanup_temp_files_removed_total")
        == initial_files + 1.0
    )
    assert REGISTRY.get_sample_value(
        "supernote_storage_cleanup_bytes_reclaimed_total"
    ) == initial_bytes + len(content)


async def test_run_chunks_cleanup(
    cleanup_service: StorageCleanupService,
    sample_chunks: tuple[list[Path], int],
) -> None:
    """Verify run_chunks_cleanup prunes abandoned upload parts and increments metrics."""
    paths, total_bytes = sample_chunks
    initial_chunks = (
        REGISTRY.get_sample_value("supernote_storage_cleanup_chunks_removed_total")
        or 0.0
    )
    initial_bytes = (
        REGISTRY.get_sample_value("supernote_storage_cleanup_bytes_reclaimed_total")
        or 0.0
    )

    stats = await cleanup_service.run_chunks_cleanup()
    assert stats == CleanupStats(files_removed=2, bytes_reclaimed=total_bytes)
    for p in paths:
        assert not p.exists()

    assert (
        REGISTRY.get_sample_value("supernote_storage_cleanup_chunks_removed_total")
        == initial_chunks + 2.0
    )
    assert (
        REGISTRY.get_sample_value("supernote_storage_cleanup_bytes_reclaimed_total")
        == initial_bytes + total_bytes
    )


async def test_run_cleanup_cycle(
    cleanup_service: StorageCleanupService,
    sample_stale_staging_file: tuple[Path, bytes],
    sample_chunks: tuple[list[Path], int],
) -> None:
    """Verify run_cleanup executes both staging and chunk cleanup cycles."""
    stale_file, staging_bytes = sample_stale_staging_file
    paths, chunk_bytes = sample_chunks

    stats = await cleanup_service.run_cleanup()
    assert stats == CleanupStats(
        files_removed=3, bytes_reclaimed=len(staging_bytes) + chunk_bytes
    )
    assert not stale_file.exists()
    for p in paths:
        assert not p.exists()


async def test_start_immediate_sweep_and_stop(
    storage: LocalBlobStorage,
    temp_staging_dir: Path,
) -> None:
    """Verify start() sweeps crash-orphaned staging files immediately with ttl=0 and stop() shuts down cleanly."""
    service = StorageCleanupService(
        blob_storage=storage,
        interval_seconds=3600.0,
        temp_ttl_seconds=86400.0,
    )
    crash_file = temp_staging_dir / "recent_crash.tmp"
    crash_file.write_bytes(b"interrupted_write")

    await service.start()
    assert not crash_file.exists()
    assert service._polling_task is not None
    assert not service._polling_task.done()

    await service.stop()
    assert service._polling_task is None


async def test_poll_loop_periodic_execution(
    storage: LocalBlobStorage,
) -> None:
    """Verify background poll_loop executes periodic cleanup until shutdown."""
    service = StorageCleanupService(
        blob_storage=storage,
        interval_seconds=3600.0,
        temp_ttl_seconds=3600.0,
    )
    cleanup_invoked = asyncio.Event()

    async def fake_cleanup() -> CleanupStats:
        cleanup_invoked.set()
        return CleanupStats()

    iterations = 0

    async def fake_sleep(_duration: float) -> None:
        nonlocal iterations
        iterations += 1
        if iterations > 1:
            await service._shutdown_event.wait()

    with (
        patch.object(service, "run_cleanup", side_effect=fake_cleanup),
        patch(
            "supernote.server.services.storage_cleanup.asyncio.sleep",
            side_effect=fake_sleep,
        ),
    ):
        await service.start()
        await asyncio.wait_for(cleanup_invoked.wait(), timeout=1.0)
        await service.stop()
        assert cleanup_invoked.is_set()


async def test_start_stop_restart_lifecycle_cycles(
    cleanup_service: StorageCleanupService,
    temp_staging_dir: Path,
) -> None:
    """Verify StorageCleanupService can undergo multiple start/stop cycles while keeping polling loop active."""
    for cycle in range(1, 4):
        crash_file = temp_staging_dir / f"crash_cycle_{cycle}.tmp"
        crash_file.write_bytes(b"temp_crash_data")
        assert crash_file.exists()

        await cleanup_service.start()
        assert not crash_file.exists()
        assert not cleanup_service._shutdown_event.is_set()
        assert cleanup_service._polling_task is not None

        await asyncio.sleep(0.01)
        assert not cleanup_service._polling_task.done()

        await cleanup_service.stop()
        assert cleanup_service._shutdown_event.is_set()
        assert cleanup_service._polling_task is None


async def test_restart_cycle_continues_periodic_polling(
    storage: LocalBlobStorage,
) -> None:
    """Verify restarted StorageCleanupService actively executes periodic cleanup runs across cycles."""
    service = StorageCleanupService(
        blob_storage=storage,
        interval_seconds=0.01,
        temp_ttl_seconds=3600.0,
    )
    cleanup_counts = [0, 0]
    active_cycle = 0

    async def fake_cleanup() -> CleanupStats:
        cleanup_counts[active_cycle] += 1
        return CleanupStats()

    with patch.object(service, "run_cleanup", side_effect=fake_cleanup):
        for cycle_idx in range(2):
            active_cycle = cycle_idx
            await service.start()
            for _ in range(50):
                if cleanup_counts[cycle_idx] >= 1:
                    break
                await asyncio.sleep(0.005)
            assert cleanup_counts[cycle_idx] >= 1
            await service.stop()


async def test_start_idempotency_when_already_running(
    cleanup_service: StorageCleanupService,
    temp_staging_dir: Path,
) -> None:
    """Verify start() is idempotent when called consecutively while running without leaking tasks."""
    crash_file = temp_staging_dir / "crash_before_first_start.tmp"
    crash_file.write_bytes(b"initial_crash")

    await cleanup_service.start()
    assert not crash_file.exists()
    initial_task = cleanup_service._polling_task
    assert initial_task is not None
    assert not initial_task.done()

    mid_run_file = temp_staging_dir / "mid_run.tmp"
    mid_run_file.write_bytes(b"mid_run_data")

    await cleanup_service.start()
    await cleanup_service.start()

    assert cleanup_service._polling_task is initial_task
    assert not initial_task.done()
    assert mid_run_file.exists()

    await cleanup_service.stop()
    assert cleanup_service._polling_task is None
    assert initial_task.done()


async def test_stop_idempotency_when_already_stopped(
    cleanup_service: StorageCleanupService,
) -> None:
    """Verify stop() is safe and idempotent when invoked multiple times or before start()."""
    await cleanup_service.stop()
    assert cleanup_service._polling_task is None
    assert cleanup_service._shutdown_event.is_set()

    await cleanup_service.start()
    assert cleanup_service._polling_task is not None
    assert not cleanup_service._shutdown_event.is_set()

    await cleanup_service.stop()
    assert cleanup_service._polling_task is None
    assert cleanup_service._shutdown_event.is_set()

    await cleanup_service.stop()
    assert cleanup_service._polling_task is None
    assert cleanup_service._shutdown_event.is_set()
