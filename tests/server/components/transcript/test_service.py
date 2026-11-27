"""Component service tests for `supernote.server.components.transcript` internal APIs."""

from __future__ import annotations

from supernote.server.components.summary import SUMMARY_SERVICE_KEY
from supernote.server.components.transcript import (
    TRANSCRIPT_SERVICE_KEY,
    SummaryTranscript,
)
from supernote.server.core import ServerCore
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    NoteTitleDO,
    NoteTitleTranscriptDO,
)
from supernote.server.db.models.summary import SummaryDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import SummaryDeletedEvent
from tests.fixtures.server import TEST_USERNAME
from tests.server.components.conftest import LoadComponents


async def test_get_transcript_single_page_returns_raw_text(
    component_core: ServerCore,
    load_components: LoadComponents,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify `get_transcript(..., page_index=N)` returns unformatted raw text for internal callers."""
    await load_components("transcript")
    transcript_service = component_core.app[TRANSCRIPT_SERVICE_KEY]

    async with session_manager.session() as session:
        file_do = UserFileDO(
            user_id=test_user_id,
            file_name="Journal.note",
            directory_id=0,
            storage_key="single_page_transcript_key",
        )
        session.add(file_do)
        await session.flush()
        session.add(
            NotePageContentDO(
                file_id=file_do.id,
                page_index=0,
                page_id="P20231027120000abc",
                text_content="Page 1 content.",
            )
        )
        await session.commit()
        file_id = int(file_do.id)

    page1 = await transcript_service.get_transcript(
        user_id=test_user_id, file_id=file_id, page_index=0
    )
    assert page1 == "Page 1 content."


async def test_get_title_transcripts_scoped_to_active_owner_and_omits_empty(
    component_core: ServerCore,
    load_components: LoadComponents,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify `get_title_transcripts` returns non-empty transcripts only for active owned files."""
    await load_components("transcript")
    transcript_service = component_core.app[TRANSCRIPT_SERVICE_KEY]

    async with session_manager.session() as session:
        active_file = UserFileDO(
            user_id=test_user_id,
            file_name="Headings.note",
            directory_id=0,
            storage_key="titles_active_key",
            is_active="Y",
        )
        inactive_file = UserFileDO(
            user_id=test_user_id,
            file_name="Deleted.note",
            directory_id=0,
            storage_key="titles_inactive_key",
            is_active="N",
        )
        session.add_all([active_file, inactive_file])
        await session.flush()
        active_id = int(active_file.id)
        inactive_id = int(inactive_file.id)
        session.add_all(
            [
                NoteTitleDO(
                    user_id=test_user_id,
                    file_id=active_id,
                    title_index=0,
                    page_index=0,
                    bitmap_md5="md5_a",
                ),
                NoteTitleDO(
                    user_id=test_user_id,
                    file_id=active_id,
                    title_index=1,
                    page_index=0,
                    bitmap_md5="md5_blank",
                ),
                NoteTitleTranscriptDO(
                    user_id=test_user_id,
                    file_id=active_id,
                    bitmap_md5="md5_a",
                    text_content="Sprint Planning",
                ),
                NoteTitleTranscriptDO(
                    user_id=test_user_id,
                    file_id=active_id,
                    bitmap_md5="md5_blank",
                    text_content="",
                ),
                NoteTitleTranscriptDO(
                    user_id=test_user_id,
                    file_id=active_id,
                    bitmap_md5="md5_stale_unreferenced",
                    text_content="Stale Heading",
                ),
                NoteTitleTranscriptDO(
                    user_id=test_user_id + 1,
                    file_id=active_id,
                    bitmap_md5="md5_other_user",
                    text_content="Private Heading",
                ),
                NoteTitleDO(
                    user_id=test_user_id,
                    file_id=inactive_id,
                    title_index=0,
                    page_index=0,
                    bitmap_md5="md5_deleted",
                ),
                NoteTitleTranscriptDO(
                    user_id=test_user_id,
                    file_id=inactive_id,
                    bitmap_md5="md5_deleted",
                    text_content="Deleted Heading",
                ),
            ]
        )
        await session.commit()

    assert await transcript_service.get_title_transcripts(
        user_id=test_user_id, file_id=active_id
    ) == {"md5_a": "Sprint Planning"}
    assert (
        await transcript_service.get_title_transcripts(
            user_id=test_user_id + 1, file_id=active_id
        )
        == {}
    )
    assert (
        await transcript_service.get_title_transcripts(
            user_id=test_user_id, file_id=inactive_id
        )
        == {}
    )


async def test_summary_transcript_crud_staleness_and_overwrite(
    component_core: ServerCore,
    load_components: LoadComponents,
    test_user_id: int,
) -> None:
    """Verify summary transcript upsert, read, staleness check, and overwrite on md5 change."""
    await load_components("transcript")
    transcript_service = component_core.app[TRANSCRIPT_SERVICE_KEY]

    summary_id = 42001
    assert (
        await transcript_service.get_summary_transcript(test_user_id, summary_id)
        is None
    )
    assert await transcript_service.get_summary_transcripts(test_user_id, []) == {}
    assert (
        await transcript_service.is_summary_transcript_stale(
            test_user_id, summary_id, "md5_v1"
        )
        is True
    )

    created = await transcript_service.upsert_summary_transcript(
        user_id=test_user_id,
        summary_id=summary_id,
        handwrite_md5="md5_v1",
        text_content="First draft marginalia",
        model_id="gemini-2.5-flash",
    )
    assert isinstance(created, SummaryTranscript)
    assert created.summary_id == summary_id
    assert created.handwrite_md5 == "md5_v1"
    assert created.text == "First draft marginalia"
    assert created.model_id == "gemini-2.5-flash"
    assert created.create_time > 0
    assert created.update_time == created.create_time

    fetched = await transcript_service.get_summary_transcript(test_user_id, summary_id)
    assert fetched == created
    assert (
        await transcript_service.is_summary_transcript_stale(
            test_user_id, summary_id, "md5_v1"
        )
        is False
    )
    assert (
        await transcript_service.is_summary_transcript_stale(
            test_user_id, summary_id, "md5_v2"
        )
        is True
    )

    updated = await transcript_service.upsert_summary_transcript(
        user_id=test_user_id,
        summary_id=summary_id,
        handwrite_md5="md5_v2",
        text_content="Revised marginalia note",
        model_id="gemini-2.5-pro",
    )
    assert updated.handwrite_md5 == "md5_v2"
    assert updated.text == "Revised marginalia note"
    assert updated.model_id == "gemini-2.5-pro"
    assert updated.create_time == created.create_time
    assert updated.update_time >= created.update_time
    assert (
        await transcript_service.is_summary_transcript_stale(
            test_user_id, summary_id, "md5_v2"
        )
        is False
    )

    batch = await transcript_service.get_summary_transcripts(
        test_user_id, [summary_id, 99999]
    )
    assert batch == {summary_id: updated}


async def test_summary_transcript_multi_user_isolation(
    component_core: ServerCore,
    load_components: LoadComponents,
    test_user_id: int,
) -> None:
    """Verify two users with the same summary_id have isolated transcripts and deletions."""
    await load_components("transcript")
    transcript_service = component_core.app[TRANSCRIPT_SERVICE_KEY]

    other_user_id = test_user_id + 1
    shared_summary_id = 55001

    u1 = await transcript_service.upsert_summary_transcript(
        user_id=test_user_id,
        summary_id=shared_summary_id,
        handwrite_md5="md5_u1",
        text_content="User 1 private note",
        model_id="model-a",
    )
    u2 = await transcript_service.upsert_summary_transcript(
        user_id=other_user_id,
        summary_id=shared_summary_id,
        handwrite_md5="md5_u2",
        text_content="User 2 private note",
        model_id="model-b",
    )

    assert (
        await transcript_service.get_summary_transcript(test_user_id, shared_summary_id)
        == u1
    )
    assert (
        await transcript_service.get_summary_transcript(
            other_user_id, shared_summary_id
        )
        == u2
    )
    assert await transcript_service.get_summary_transcripts(
        test_user_id, [shared_summary_id]
    ) == {shared_summary_id: u1}
    assert (
        await transcript_service.is_summary_transcript_stale(
            test_user_id, shared_summary_id, "md5_u2"
        )
        is True
    )

    assert (
        await transcript_service.delete_summary_transcript(
            test_user_id, shared_summary_id
        )
        is True
    )
    assert (
        await transcript_service.delete_summary_transcript(
            test_user_id, shared_summary_id
        )
        is False
    )
    assert (
        await transcript_service.get_summary_transcript(test_user_id, shared_summary_id)
        is None
    )
    assert (
        await transcript_service.get_summary_transcript(
            other_user_id, shared_summary_id
        )
        == u2
    )


async def test_summary_transcript_deleted_on_summary_deleted_event(
    component_core: ServerCore,
    load_components: LoadComponents,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify `SummaryDeletedEvent` cleans up stored transcripts without affecting other users."""
    await load_components("summary", "transcript")
    transcript_service = component_core.app[TRANSCRIPT_SERVICE_KEY]
    summary_service = component_core.app[SUMMARY_SERVICE_KEY]

    other_user_id = test_user_id + 1

    async with session_manager.session() as session:
        summary_do = SummaryDO(
            user_id=test_user_id,
            unique_identifier="digest-uuid-1",
            content="Highlighted passage",
            handwrite_inner_name="blobs/hw1.mark",
            handwrite_md5="md5_hw1",
            is_summary_group=False,
        )
        session.add(summary_do)
        await session.commit()
        summary_id = int(summary_do.id)

    await transcript_service.upsert_summary_transcript(
        user_id=test_user_id,
        summary_id=summary_id,
        handwrite_md5="md5_hw1",
        text_content="Marginalia for digest",
    )
    await transcript_service.upsert_summary_transcript(
        user_id=other_user_id,
        summary_id=summary_id,
        handwrite_md5="md5_other",
        text_content="Other user's transcript",
    )

    # Group deletion event for the same ID should not remove a leaf transcript.
    await component_core.event_bus.publish(
        SummaryDeletedEvent(
            user_id=test_user_id,
            summary_id=summary_id,
            is_summary_group=True,
        )
    )
    assert (
        await transcript_service.get_summary_transcript(test_user_id, summary_id)
        is not None
    )

    # Deleting the summary via SummaryService emits SummaryDeletedEvent and removes the transcript.
    await summary_service.delete_summary(TEST_USERNAME, summary_id)

    assert (
        await transcript_service.get_summary_transcript(test_user_id, summary_id)
        is None
    )
    other_row = await transcript_service.get_summary_transcript(
        other_user_id, summary_id
    )
    assert other_row is not None
    assert other_row.text == "Other user's transcript"
