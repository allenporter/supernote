"""Component service tests for `supernote.server.components.transcript` internal APIs."""

from __future__ import annotations

from supernote.server.components.transcript import TRANSCRIPT_SERVICE_KEY
from supernote.server.core import ServerCore
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
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
