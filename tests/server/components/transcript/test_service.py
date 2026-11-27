"""Component service tests for `supernote.server.components.transcript` internal APIs."""

from __future__ import annotations

from supernote.server.components.transcript import TRANSCRIPT_SERVICE_KEY
from supernote.server.core import ServerCore
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    NoteTitleDO,
    NoteTitleTranscriptDO,
)
from supernote.server.db.session import DatabaseSessionManager
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
