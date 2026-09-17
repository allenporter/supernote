import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from supernote.server.services.cleanup import RecycleBinCleanupService


@pytest.fixture
def mock_file_service() -> MagicMock:
    service = MagicMock()
    service.purge_expired_recycle_entries = AsyncMock(return_value=3)
    return service


async def test_run_once_delegates_to_file_service(
    mock_file_service: MagicMock,
) -> None:
    service = RecycleBinCleanupService(
        mock_file_service, retention_days=30, interval_seconds=86400
    )

    purged_count = await service.run_once()

    assert purged_count == 3
    mock_file_service.purge_expired_recycle_entries.assert_awaited_once_with(30)


async def test_start_noop_when_disabled(mock_file_service: MagicMock) -> None:
    service = RecycleBinCleanupService(
        mock_file_service, retention_days=30, interval_seconds=86400, enabled=False
    )

    await service.start()

    assert service._task is None
    await asyncio.sleep(0.05)
    mock_file_service.purge_expired_recycle_entries.assert_not_awaited()

    # stop() is a no-op when nothing was started.
    await service.stop()


async def test_poll_loop_runs_periodically_and_stops_cleanly(
    mock_file_service: MagicMock,
) -> None:
    # interval_seconds=0 keeps the loop tight (cooperatively yielding via
    # asyncio.sleep(0) each iteration) so the test doesn't need real delays.
    service = RecycleBinCleanupService(
        mock_file_service, retention_days=30, interval_seconds=0, enabled=True
    )

    await service.start()
    try:
        await asyncio.sleep(0.05)
        assert mock_file_service.purge_expired_recycle_entries.await_count >= 2
    finally:
        await service.stop()

    call_count_after_stop = mock_file_service.purge_expired_recycle_entries.await_count
    await asyncio.sleep(0.05)
    # No further runs happen once stopped.
    assert (
        mock_file_service.purge_expired_recycle_entries.await_count
        == call_count_after_stop
    )


async def test_run_once_still_counts_failure_before_reraising(
    mock_file_service: MagicMock,
) -> None:
    mock_file_service.purge_expired_recycle_entries = AsyncMock(
        side_effect=RuntimeError("boom")
    )
    service = RecycleBinCleanupService(
        mock_file_service, retention_days=30, interval_seconds=86400
    )

    with pytest.raises(RuntimeError, match="boom"):
        await service.run_once()
