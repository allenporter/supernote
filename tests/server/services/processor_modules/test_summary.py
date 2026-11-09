import json

import pytest
from sqlalchemy import select

from supernote.models.base import BooleanEnum
from supernote.models.summary import (
    METADATA_SEGMENTS,
    AddSummaryDTO,
    AddSummaryGroupDTO,
)
from supernote.server.ai.base import AIError
from supernote.server.ai.models.fake.summary import FakeSummaryModel
from supernote.server.ai.prompts import SummarySegment
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules.summary import SummaryModule
from supernote.server.services.summary import SummaryService
from supernote.server.utils.paths import (
    get_summary_group_id,
    get_summary_id,
    get_transcript_id,
)


@pytest.fixture
def summary_module(
    file_service: FileService,
    fake_summary_model: FakeSummaryModel,
    summary_service: SummaryService,
) -> SummaryModule:
    return SummaryModule(
        file_service=file_service,
        summary_service=summary_service,
        summary_model=fake_summary_model,
    )


async def test_summary_success(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    fake_summary_model: FakeSummaryModel,
    summary_service: SummaryService,
) -> None:
    user_id = 100
    user_email = "test@example.com"
    file_id = 999
    storage_key = "test_storage_key"

    async with session_manager.session() as session:
        user = UserDO(id=user_id, email=user_email, password_md5="hash")
        session.add(user)

        user_file = UserFileDO(
            id=file_id,
            user_id=user_id,
            storage_key=storage_key,
            file_name="real.note",
            directory_id=0,
        )
        session.add(user_file)

        p1 = NotePageContentDO(
            file_id=file_id,
            page_index=0,
            page_id="p0",
            content_hash="h1",
            text_content="Page 1 text",
        )
        p2 = NotePageContentDO(
            file_id=file_id,
            page_index=1,
            page_id="p1",
            content_hash="h2",
            text_content="Page 2 text",
        )
        session.add(p1)
        session.add(p2)
        await session.commit()

    await summary_module.run(file_id, session_manager)

    assert len(fake_summary_model.calls) == 1
    prompt_arg = fake_summary_model.calls[0]
    assert "TRANSCRIPT:" in prompt_arg
    assert "Page 1 text" in prompt_arg
    assert "Page 2 text" in prompt_arg

    group = await summary_service.get_summary_by_uuid(
        user_email, get_summary_group_id(storage_key)
    )
    assert group is not None
    assert group.is_summary_group == BooleanEnum.YES
    assert group.name == "real.note"

    transcript = await summary_service.get_summary_by_uuid(
        user_email, get_transcript_id(storage_key)
    )
    assert transcript is not None
    assert transcript.parent_unique_identifier == get_summary_group_id(storage_key)
    assert transcript.content is not None
    assert "Page 1 text" in transcript.content
    assert "Page 2 text" in transcript.content
    assert transcript.data_source == "OCR"

    ai_summary = await summary_service.get_summary_by_uuid(
        user_email, get_summary_id(storage_key)
    )
    assert ai_summary is not None
    assert ai_summary.parent_unique_identifier == get_summary_group_id(storage_key)
    assert ai_summary.content is not None
    assert "## 2023-10-27 (Pages 1)" in ai_summary.content
    assert "Summary of (" in ai_summary.content
    assert ai_summary.data_source == "fake-summary-v1"

    assert ai_summary.metadata is not None
    meta = json.loads(ai_summary.metadata)
    assert meta[METADATA_SEGMENTS][0]["page_refs"] == [1]

    async with session_manager.session() as session:
        task = (
            (
                await session.execute(
                    select(SystemTaskDO)
                    .where(SystemTaskDO.file_id == file_id)
                    .where(SystemTaskDO.task_type == "SUMMARY_GENERATION")
                    .where(SystemTaskDO.key == "global")
                )
            )
            .scalars()
            .first()
        )
        assert task is not None
        assert task.status == "COMPLETED"


async def test_summary_idempotency_update(
    file_service: FileService,
    session_manager: DatabaseSessionManager,
    summary_service: SummaryService,
) -> None:
    user_id = 101
    user_email = "update@example.com"
    file_id = 888
    storage_key = "update_key"

    async with session_manager.session() as session:
        user = UserDO(id=user_id, email=user_email, password_md5="hash")
        session.add(user)
        user_file = UserFileDO(
            id=file_id,
            user_id=user_id,
            storage_key=storage_key,
            file_name="update.note",
            directory_id=0,
        )
        session.add(user_file)
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="h1",
                text_content="Some text",
            )
        )
        await session.commit()

    existing_group = await summary_service.add_group(
        user_email,
        AddSummaryGroupDTO(
            unique_identifier=get_summary_group_id(storage_key),
            name="old.note",
            md5_hash="old_hash",
        ),
    )
    existing_summary = await summary_service.add_summary(
        user_email,
        AddSummaryDTO(
            file_id=file_id,
            unique_identifier=get_summary_id(storage_key),
            parent_unique_identifier=get_summary_group_id(storage_key),
            content="Old AI Summary",
            data_source="fake-summary-v1",
        ),
    )

    custom_summary_model = FakeSummaryModel(
        segments=[
            SummarySegment(
                date_range="2023-10-28",
                summary="New AI Summary",
                extracted_dates=[],
                page_refs=[3, 4],
            )
        ]
    )
    summary_module = SummaryModule(
        file_service=file_service,
        summary_service=summary_service,
        summary_model=custom_summary_model,
    )

    await summary_module.run(file_id, session_manager)

    updated_group = await summary_service.get_summary_by_uuid(
        user_email, get_summary_group_id(storage_key)
    )
    assert updated_group is not None
    assert updated_group.id == existing_group.id
    assert updated_group.name == "update.note"

    transcript = await summary_service.get_summary_by_uuid(
        user_email, get_transcript_id(storage_key)
    )
    assert transcript is not None
    assert transcript.parent_unique_identifier == get_summary_group_id(storage_key)

    updated_summary = await summary_service.get_summary_by_uuid(
        user_email, get_summary_id(storage_key)
    )
    assert updated_summary is not None
    assert updated_summary.id == existing_summary.id
    assert updated_summary.parent_unique_identifier == get_summary_group_id(storage_key)
    assert updated_summary.content is not None
    assert "## 2023-10-28 (Pages 3, 4)" in updated_summary.content
    assert "New AI Summary" in updated_summary.content

    assert updated_summary.metadata is not None
    meta = json.loads(updated_summary.metadata)
    assert meta[METADATA_SEGMENTS][0]["page_refs"] == [3, 4]

    # Deleting the summary group and rerunning SummaryModule.process recreates active group and summaries
    assert updated_group.id is not None
    await summary_service.delete_group(user_email, updated_group.id)
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_summary_group_id(storage_key)
        )
        is None
    )
    await summary_module.process(file_id, session_manager)
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_summary_group_id(storage_key)
        )
        is not None
    )
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_summary_id(storage_key)
        )
        is not None
    )


async def test_summary_transcript_with_dates(
    file_service: FileService,
    session_manager: DatabaseSessionManager,
    summary_service: SummaryService,
) -> None:
    user_id = 100
    user_email = "test@example.com"
    file_id = 123
    storage_key = "date_test_key"

    async with session_manager.session() as session:
        user = UserDO(id=user_id, email=user_email, password_md5="hash")
        session.add(user)
        user_file = UserFileDO(
            id=file_id,
            user_id=user_id,
            storage_key=storage_key,
            file_name="dates.note",
            directory_id=0,
        )
        session.add(user_file)

        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="P20231027120000abc",
                text_content="Content on Oct 27",
            )
        )
        await session.commit()

    empty_summary_model = FakeSummaryModel(segments=[])
    summary_module = SummaryModule(
        file_service=file_service,
        summary_service=summary_service,
        summary_model=empty_summary_model,
    )

    await summary_module.run(file_id, session_manager)

    group = await summary_service.get_summary_by_uuid(
        user_email, get_summary_group_id(storage_key)
    )
    assert group is not None
    assert group.name == "dates.note"

    transcript = await summary_service.get_summary_by_uuid(
        user_email, get_transcript_id(storage_key)
    )
    assert transcript is not None
    assert transcript.parent_unique_identifier == get_summary_group_id(storage_key)
    assert transcript.content is not None
    assert "--- Page 1 ---" in transcript.content
    assert "Page ID: P20231027120000abc" in transcript.content
    assert "Page Date (Inferred): 2023-10-27" in transcript.content


async def test_summary_waits_until_all_pages_have_ocr_text(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    fake_summary_model: FakeSummaryModel,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user_id = 105
    user_email = "partial@example.com"
    file_id = 555

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email=user_email, password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key="partial_key",
                file_name="partial.note",
                directory_id=0,
            )
        )
        session.add_all(
            [
                NotePageContentDO(
                    file_id=file_id,
                    page_index=0,
                    page_id="p0",
                    content_hash="h0",
                    text_content="Page 1 text",
                ),
                NotePageContentDO(
                    file_id=file_id,
                    page_index=1,
                    page_id="p1",
                    content_hash="h1",
                    text_content=None,
                ),
            ]
        )
        await session.commit()

    # While page 2 still has text_content=None, SummaryModule must wait and log why
    with caplog.at_level("WARNING"):
        assert await summary_module.run_if_needed(file_id, session_manager) is False
    assert (
        f"OCR prerequisite not met for summary of file {file_id} (1/2 pages missing text)"
        in caplog.text
    )
    await summary_module.run(file_id, session_manager)
    assert fake_summary_model.calls == []

    # Once page 2 OCR finishes, SummaryModule runs and marks SUMMARY_GENERATION COMPLETED
    async with session_manager.session() as session:
        p1 = (
            await session.execute(
                select(NotePageContentDO)
                .where(NotePageContentDO.file_id == file_id)
                .where(NotePageContentDO.page_id == "p1")
            )
        ).scalar_one()
        p1.text_content = "Page 2 text"
        await session.commit()

    assert await summary_module.run_if_needed(file_id, session_manager) is True
    await summary_module.run(file_id, session_manager)
    assert len(fake_summary_model.calls) == 1
    assert "Page 1 text" in fake_summary_model.calls[0]
    assert "Page 2 text" in fake_summary_model.calls[0]


async def test_summary_failure_marks_task_failed(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    fake_summary_model: FakeSummaryModel,
    summary_service: SummaryService,
) -> None:
    user_id = 102
    user_email = "fail@example.com"
    file_id = 777
    storage_key = "fail_storage_key"

    async with session_manager.session() as session:
        user = UserDO(id=user_id, email=user_email, password_md5="hash")
        session.add(user)
        user_file = UserFileDO(
            id=file_id,
            user_id=user_id,
            storage_key=storage_key,
            file_name="fail.note",
            directory_id=0,
        )
        session.add(user_file)
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="h1",
                text_content="Page 1 text",
            )
        )
        await session.commit()

    fake_summary_model.error = AIError("Gemini API unavailable")

    result = await summary_module.run(file_id, session_manager)
    assert result is False

    transcript = await summary_service.get_summary_by_uuid(
        user_email, get_transcript_id(storage_key)
    )
    assert transcript is not None
    assert transcript.data_source == "OCR"

    ai_summary = await summary_service.get_summary_by_uuid(
        user_email, get_summary_id(storage_key)
    )
    assert ai_summary is None

    async with session_manager.session() as session:
        task = (
            (
                await session.execute(
                    select(SystemTaskDO)
                    .where(SystemTaskDO.file_id == file_id)
                    .where(SystemTaskDO.task_type == "SUMMARY_GENERATION")
                    .where(SystemTaskDO.key == "global")
                )
            )
            .scalars()
            .first()
        )
        assert task is not None
        assert task.status == "FAILED"
        assert task.last_error == "AIError: Gemini API unavailable"


async def test_summary_skips_llm_and_group_creation_when_all_pages_blank(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    fake_summary_model: FakeSummaryModel,
    summary_service: SummaryService,
) -> None:
    """Verify all-blank notebooks skip SummaryModel calls and avoid creating empty summary groups."""
    user_id = 108
    user_email = "blank@example.com"
    file_id = 808
    storage_key = "blank_note_key"

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email=user_email, password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key=storage_key,
                file_name="blank.note",
                directory_id=0,
            )
        )
        session.add_all(
            [
                NotePageContentDO(
                    file_id=file_id,
                    page_index=0,
                    page_id="p0",
                    content_hash="h0",
                    text_content="",
                ),
                NotePageContentDO(
                    file_id=file_id,
                    page_index=1,
                    page_id="p1",
                    content_hash="h1",
                    text_content="",
                ),
            ]
        )
        await session.commit()

    assert await summary_module.run(file_id, session_manager) is True
    assert fake_summary_model.calls == []
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_summary_group_id(storage_key)
        )
        is None
    )


async def test_summary_deletes_existing_group_when_all_pages_erased(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    fake_summary_model: FakeSummaryModel,
    summary_service: SummaryService,
) -> None:
    """Verify erasing all pages on an already-summarized note deletes its summary group without an LLM call."""
    user_id = 109
    user_email = "erased@example.com"
    file_id = 809
    storage_key = "erased_note_key"

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email=user_email, password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key=storage_key,
                file_name="erased.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="h0",
                text_content="Initial handwritten note",
            )
        )
        await session.commit()

    assert await summary_module.run(file_id, session_manager) is True
    assert len(fake_summary_model.calls) == 1
    fake_summary_model.calls.clear()

    async with session_manager.session() as session:
        p0 = (
            await session.execute(
                select(NotePageContentDO).where(NotePageContentDO.file_id == file_id)
            )
        ).scalar_one()
        p0.text_content = ""
        await session.commit()

    await summary_module.process(file_id, session_manager)
    assert fake_summary_model.calls == []

    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_summary_group_id(storage_key)
        )
        is None
    )
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_transcript_id(storage_key)
        )
        is None
    )
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_summary_id(storage_key)
        )
        is None
    )


async def test_summary_skips_whitespace_only_pages(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    fake_summary_model: FakeSummaryModel,
    summary_service: SummaryService,
) -> None:
    """Verify whitespace-only OCR text ('  \\n ') does not emit a metadata-only transcript to SummaryModel."""
    user_id = 110
    user_email = "whitespace@example.com"
    file_id = 810
    storage_key = "ws_note_key"

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email=user_email, password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key=storage_key,
                file_name="whitespace.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="h0",
                text_content="   \n\t  ",
            )
        )
        await session.commit()

    assert await summary_module.run(file_id, session_manager) is True
    assert fake_summary_model.calls == []
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_summary_group_id(storage_key)
        )
        is None
    )


async def test_summary_preserves_manual_digests_when_notebook_erased(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    fake_summary_model: FakeSummaryModel,
    summary_service: SummaryService,
) -> None:
    """Verify erasing a notebook deletes AI transcript/summary items while preserving user-created digests in the group."""
    user_id = 111
    user_email = "manual_digest@example.com"
    file_id = 811
    storage_key = "manual_digest_note_key"
    group_uuid = get_summary_group_id(storage_key)

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email=user_email, password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key=storage_key,
                file_name="project.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="h0",
                text_content="Initial project notes",
            )
        )
        await session.commit()

    assert await summary_module.run(file_id, session_manager) is True
    fake_summary_model.calls.clear()

    # User adds a manual digest on their Supernote device under the same category
    await summary_service.add_summary(
        user_email,
        AddSummaryDTO(
            unique_identifier="user-manual-digest-uuid",
            parent_unique_identifier=group_uuid,
            content="User handwritten highlight",
            data_source="USER",
        ),
    )

    async with session_manager.session() as session:
        p0 = (
            await session.execute(
                select(NotePageContentDO).where(NotePageContentDO.file_id == file_id)
            )
        ).scalar_one()
        p0.text_content = ""
        await session.commit()

    await summary_module.process(file_id, session_manager)
    assert fake_summary_model.calls == []

    # AI transcript and AI summary are removed, while the user digest and parent group survive
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_transcript_id(storage_key)
        )
        is None
    )
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_summary_id(storage_key)
        )
        is None
    )
    manual = await summary_service.get_summary_by_uuid(
        user_email, "user-manual-digest-uuid"
    )
    assert manual is not None
    assert manual.content == "User handwritten highlight"
    assert await summary_service.get_summary_by_uuid(user_email, group_uuid) is not None
