"""Unit tests for periodic blob storage and cache inventory metrics collection."""

import asyncio
import dataclasses
from pathlib import Path
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient
from prometheus_client import REGISTRY
from pytest_aiohttp import AiohttpClient

from supernote.server.app import create_app
from supernote.server.config import ServerConfig
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.keys import STORAGE_METRICS_COLLECTOR_KEY
from supernote.server.services.blob import LocalBlobStorage
from supernote.server.services.storage_metrics import StorageMetricsCollector
from supernote.server.utils.paths import (
    get_conversion_pdf_path,
    get_page_png_path,
)


def _object_sample(bucket: str, kind: str) -> float | None:
    return REGISTRY.get_sample_value(
        "supernote_blob_storage_objects",
        {"bucket": bucket, "kind": kind},
    )


def _bytes_sample(bucket: str, kind: str) -> float | None:
    return REGISTRY.get_sample_value(
        "supernote_blob_storage_bytes",
        {"bucket": bucket, "kind": kind},
    )


def _available_bytes_sample() -> float | None:
    return REGISTRY.get_sample_value("supernote_blob_storage_available_bytes")


async def test_collect_once_populates_and_resets_inventory_gauges(
    tmp_path: Path,
) -> None:
    """Verify collect_once populates object/byte/available gauges and resets to 0 on deletion."""
    storage = LocalBlobStorage(tmp_path)
    collector = StorageMetricsCollector(storage)

    # Staging .tmp files and multipart .part.N chunks must be ignored
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    (temp_dir / "inflight.tmp").write_bytes(b"staging-bytes")
    await storage.put(USER_DATA_BUCKET, "multipart.note.part.1", b"chunk-data")

    await storage.put(USER_DATA_BUCKET, "note_1.note", b"user-note-one")
    await storage.put(USER_DATA_BUCKET, "note_2.note", b"user-two")

    png_1 = get_page_png_path(file_id=10, page_id="P1")
    png_2 = get_page_png_path(file_id=10, page_id="P2")
    pdf_1 = get_conversion_pdf_path(user_id=1, file_id=10, file_md5="abcd1234")
    await storage.put(CACHE_BUCKET, png_1, b"png-bytes-1")
    await storage.put(CACHE_BUCKET, png_2, b"png-2")
    await storage.put(CACHE_BUCKET, pdf_1, b"rendered-pdf-document")

    with patch.object(storage, "get_available_bytes", return_value=42_000_000):
        await collector.collect_once()

    assert _object_sample(USER_DATA_BUCKET, "user_blob") == 2.0
    assert _bytes_sample(USER_DATA_BUCKET, "user_blob") == float(
        len(b"user-note-one") + len(b"user-two")
    )
    assert _object_sample(CACHE_BUCKET, "png") == 2.0
    assert _bytes_sample(CACHE_BUCKET, "png") == float(
        len(b"png-bytes-1") + len(b"png-2")
    )
    assert _object_sample(CACHE_BUCKET, "pdf") == 1.0
    assert _bytes_sample(CACHE_BUCKET, "pdf") == float(len(b"rendered-pdf-document"))
    assert _available_bytes_sample() == 42_000_000.0

    # Delete all cached PNGs, PDFs, and user blobs -> gauges must drop back to 0
    await storage.delete(USER_DATA_BUCKET, "note_1.note")
    await storage.delete(USER_DATA_BUCKET, "note_2.note")
    await storage.delete(CACHE_BUCKET, png_1)
    await storage.delete(CACHE_BUCKET, png_2)
    await storage.delete(CACHE_BUCKET, pdf_1)

    with patch.object(storage, "get_available_bytes", return_value=43_000_000):
        await collector.collect_once()

    assert _object_sample(USER_DATA_BUCKET, "user_blob") == 0.0
    assert _bytes_sample(USER_DATA_BUCKET, "user_blob") == 0.0
    assert _object_sample(CACHE_BUCKET, "png") == 0.0
    assert _bytes_sample(CACHE_BUCKET, "png") == 0.0
    assert _object_sample(CACHE_BUCKET, "pdf") == 0.0
    assert _bytes_sample(CACHE_BUCKET, "pdf") == 0.0
    assert _available_bytes_sample() == 43_000_000.0


async def test_collect_once_preserves_available_bytes_when_backend_returns_none(
    tmp_path: Path,
) -> None:
    """Verify get_available_bytes() returning None leaves the gauge untouched."""
    storage = LocalBlobStorage(tmp_path)
    collector = StorageMetricsCollector(storage)

    with patch.object(storage, "get_available_bytes", return_value=12_345_678):
        await collector.collect_once()
    assert _available_bytes_sample() == 12_345_678.0

    with patch.object(storage, "get_available_bytes", return_value=None):
        await collector.collect_once()
    assert _available_bytes_sample() == 12_345_678.0


def test_collector_rejects_non_positive_interval(tmp_path: Path) -> None:
    """Verify StorageMetricsCollector rejects zero or negative intervals."""
    storage = LocalBlobStorage(tmp_path)
    with pytest.raises(ValueError, match="interval_seconds must be positive"):
        StorageMetricsCollector(storage, interval_seconds=0)


async def test_periodic_loop_executes_ticks_survives_oserror_and_stops_cleanly(
    tmp_path: Path,
) -> None:
    """Verify start/stop timer loop runs periodically, survives transient OSError, and stops cleanly."""
    storage = LocalBlobStorage(tmp_path)
    await storage.put(USER_DATA_BUCKET, "tick_blob.note", b"tick-content")

    collector = StorageMetricsCollector(storage, interval_seconds=0.02)
    original_list_blob_sizes = storage.list_blob_sizes
    sweep_attempts = 0
    third_attempt_done = asyncio.Event()

    async def flaky_list_blob_sizes(bucket: str) -> list[tuple[str, int]]:
        nonlocal sweep_attempts
        if bucket == USER_DATA_BUCKET:
            sweep_attempts += 1
            if sweep_attempts == 1:
                raise OSError("transient disk error")
        result = await original_list_blob_sizes(bucket)
        if bucket == CACHE_BUCKET and sweep_attempts >= 3:
            third_attempt_done.set()
        return result

    with patch.object(storage, "list_blob_sizes", side_effect=flaky_list_blob_sizes):
        await collector.start()
        # Calling start() again while running is a no-op
        first_task = collector._task
        await collector.start()
        assert collector._task is first_task

        async with asyncio.timeout(2.0):
            await third_attempt_done.wait()

        await collector.stop()
        assert collector._task is None
        assert first_task is not None and first_task.done()

        # Calling stop() again is a safe no-op
        await collector.stop()

    assert sweep_attempts >= 3
    assert _object_sample(USER_DATA_BUCKET, "user_blob") == 1.0
    assert _bytes_sample(USER_DATA_BUCKET, "user_blob") == float(len(b"tick-content"))


async def test_app_wires_storage_metrics_collector_when_metrics_enabled(
    client: TestClient,
) -> None:
    """Verify create_app starts StorageMetricsCollector and exposes gauges when metrics_enabled is True."""
    assert client.app is not None
    collector = client.app.get(STORAGE_METRICS_COLLECTOR_KEY)
    assert isinstance(collector, StorageMetricsCollector)
    assert collector._task is not None and not collector._task.done()

    await collector.collect_once()
    resp = await client.get("/metrics")
    assert resp.status == 200
    body = await resp.text()
    assert "supernote_blob_storage_objects" in body
    assert "supernote_blob_storage_bytes" in body
    assert "supernote_blob_storage_available_bytes" in body


async def test_app_skips_storage_metrics_collector_when_metrics_disabled(
    aiohttp_client: AiohttpClient,
    server_config: ServerConfig,
) -> None:
    """Verify create_app does not start StorageMetricsCollector when metrics_enabled is False."""
    disabled_cfg = dataclasses.replace(
        server_config, metrics_enabled=False, mcp_enabled=False
    )
    disabled_client = await aiohttp_client(create_app(disabled_cfg))
    assert disabled_client.app is not None
    assert disabled_client.app.get(STORAGE_METRICS_COLLECTOR_KEY) is None
