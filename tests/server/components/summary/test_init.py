"""Unit tests for `supernote.server.components.summary.SummaryComponent`."""

from __future__ import annotations

from sqlalchemy import delete

from supernote.server.components.summary import (
    SUMMARY_CONFIG_KEY,
    SUMMARY_SERVICE_KEY,
    SummaryConfig,
    SummaryService,
)
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.core import Component, ServerCore
from supernote.server.db.models.summary import SummaryDO
from tests.server.components.conftest import LoadComponents


async def test_summary_component_full_lifecycle(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    """Verify SummaryComponent exposes SummaryService and runs setup -> start -> stop idempotently."""
    loader = await load_components("summary", "transcript")
    component = loader.get("summary")
    assert isinstance(component, Component)
    assert component.domain == "summary"
    assert component.dependencies == ("ai", "conversion", "transcript")
    assert component.platforms == ("http", "mcp", "processor")

    service = component_core.app[SUMMARY_SERVICE_KEY]
    assert isinstance(service, SummaryService)
    assert isinstance(component_core.app[SUMMARY_CONFIG_KEY], SummaryConfig)
    assert service._purge_task is not None
    assert not service._purge_task.done()

    await loader.async_stop_all(component_core)
    assert service._purge_task is None
    await loader.async_stop_all(component_core)


async def test_summary_component_protects_summary_blobs_during_file_gc(
    component_core: ServerCore,
    load_components: LoadComponents,
    test_user_id: int,
) -> None:
    """Verify SummaryComponent registers a FileService blob-reference provider for SummaryDO."""
    await load_components("summary", "transcript")

    blob_storage = component_core.blob_storage
    file_service = component_core.file_service
    await blob_storage.put(USER_DATA_BUCKET, "sum_active_blob", b"active")
    await blob_storage.put(USER_DATA_BUCKET, "sum_deleted_blob", b"soft-deleted")
    await blob_storage.put(USER_DATA_BUCKET, "sum_orphan_blob", b"orphan")

    async with component_core.session_manager.session() as session:
        session.add_all(
            [
                SummaryDO(
                    user_id=test_user_id,
                    unique_identifier="sum-gc-active",
                    handwrite_inner_name="sum_active_blob",
                    is_deleted=False,
                ),
                SummaryDO(
                    user_id=test_user_id,
                    unique_identifier="sum-gc-deleted",
                    handwrite_inner_name="sum_deleted_blob",
                    is_deleted=True,
                ),
            ]
        )
        await session.commit()

    await file_service.cleanup_unreferenced_blobs(
        {"sum_active_blob", "sum_deleted_blob", "sum_orphan_blob"}
    )
    assert await blob_storage.exists(USER_DATA_BUCKET, "sum_active_blob") is True
    assert await blob_storage.exists(USER_DATA_BUCKET, "sum_deleted_blob") is True
    assert await blob_storage.exists(USER_DATA_BUCKET, "sum_orphan_blob") is False

    async with component_core.session_manager.session() as session:
        await session.execute(
            delete(SummaryDO).where(SummaryDO.user_id == test_user_id)
        )
        await session.commit()

    await file_service.cleanup_unreferenced_blobs(
        {"sum_active_blob", "sum_deleted_blob"}
    )
    assert await blob_storage.exists(USER_DATA_BUCKET, "sum_active_blob") is False
    assert await blob_storage.exists(USER_DATA_BUCKET, "sum_deleted_blob") is False


async def test_summary_component_stop_after_setup_only(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    """Verify stopping after async_setup (without async_start) is clean."""
    loader = await load_components("summary", "transcript", start=False)
    await loader.async_stop_all(component_core)
