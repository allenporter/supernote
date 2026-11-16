import json

import pytest
from sqlalchemy import select

from supernote.models.base import BooleanEnum
from supernote.models.summary import (
    METADATA_SEGMENTS,
    AddSummaryDTO,
    AddSummaryGroupDTO,
    UpdateSummaryDTO,
    UpdateSummaryGroupDTO,
)
from supernote.server.ai.base import AIError
from supernote.server.ai.models.fake.summary import FakeSummaryModel
from supernote.server.ai.prompts import SummarySegment
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    NotePageMetadataDO,
    SystemTaskDO,
)
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
        user_email, get_summary_group_id(user_id, file_id)
    )
    assert group is not None
    assert group.is_summary_group == BooleanEnum.YES
    assert group.name == "real.note"

    transcript = await summary_service.get_summary_by_uuid(
        user_email, get_transcript_id(user_id, file_id)
    )
    assert transcript is not None
    assert transcript.parent_unique_identifier == get_summary_group_id(user_id, file_id)
    assert transcript.content is not None
    assert "Page 1 text" in transcript.content
    assert "Page 2 text" in transcript.content
    assert transcript.data_source == "OCR"

    ai_summary = await summary_service.get_summary_by_uuid(
        user_email, get_summary_id(user_id, file_id)
    )
    assert ai_summary is not None
    assert ai_summary.parent_unique_identifier == get_summary_group_id(user_id, file_id)
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
            unique_identifier=get_summary_group_id(user_id, file_id),
            name="old.note",
            md5_hash="old_hash",
        ),
    )
    existing_summary = await summary_service.add_summary(
        user_email,
        AddSummaryDTO(
            file_id=file_id,
            unique_identifier=get_summary_id(user_id, file_id),
            parent_unique_identifier=get_summary_group_id(user_id, file_id),
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
        user_email, get_summary_group_id(user_id, file_id)
    )
    assert updated_group is not None
    assert updated_group.id == existing_group.id
    assert updated_group.name == "update.note"

    transcript = await summary_service.get_summary_by_uuid(
        user_email, get_transcript_id(user_id, file_id)
    )
    assert transcript is not None
    assert transcript.parent_unique_identifier == get_summary_group_id(user_id, file_id)

    updated_summary = await summary_service.get_summary_by_uuid(
        user_email, get_summary_id(user_id, file_id)
    )
    assert updated_summary is not None
    assert updated_summary.id == existing_summary.id
    assert updated_summary.parent_unique_identifier == get_summary_group_id(
        user_id, file_id
    )
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
            user_email, get_summary_group_id(user_id, file_id)
        )
        is None
    )
    await summary_module.process(file_id, session_manager)
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_summary_group_id(user_id, file_id)
        )
        is not None
    )
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_summary_id(user_id, file_id)
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
        user_email, get_summary_group_id(user_id, file_id)
    )
    assert group is not None
    assert group.name == "dates.note"

    transcript = await summary_service.get_summary_by_uuid(
        user_email, get_transcript_id(user_id, file_id)
    )
    assert transcript is not None
    assert transcript.parent_unique_identifier == get_summary_group_id(user_id, file_id)
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
        user_email, get_transcript_id(user_id, file_id)
    )
    assert transcript is not None
    assert transcript.data_source == "OCR"

    ai_summary = await summary_service.get_summary_by_uuid(
        user_email, get_summary_id(user_id, file_id)
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
            user_email, get_summary_group_id(user_id, file_id)
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
            user_email, get_summary_group_id(user_id, file_id)
        )
        is None
    )
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_transcript_id(user_id, file_id)
        )
        is None
    )
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_summary_id(user_id, file_id)
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
            user_email, get_summary_group_id(user_id, file_id)
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
    group_uuid = get_summary_group_id(user_id, file_id)

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
            user_email, get_transcript_id(user_id, file_id)
        )
        is None
    )
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_summary_id(user_id, file_id)
        )
        is None
    )
    manual = await summary_service.get_summary_by_uuid(
        user_email, "user-manual-digest-uuid"
    )
    assert manual is not None
    assert manual.content == "User handwritten highlight"
    assert await summary_service.get_summary_by_uuid(user_email, group_uuid) is not None


async def test_summary_includes_page_keywords_in_transcript(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    fake_summary_model: FakeSummaryModel,
    summary_service: SummaryService,
) -> None:
    """Verify SummaryModule includes Page Keywords from NotePageMetadataDO in the transcript."""
    user_id = 112
    user_email = "kw_summary@example.com"
    file_id = 812
    storage_key = "kw_summary_key"

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email=user_email, password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key=storage_key,
                file_name="roadmap.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="h0",
                text_content="Page 1 text",
            )
        )
        session.add(
            NotePageMetadataDO(
                user_id=user_id,
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="h0",
                keywords_json='[{"KEYWORDPAGE": "1", "KEYWORD": "OKR"}]',
            )
        )
        await session.commit()

    assert await summary_module.run(file_id, session_manager) is True
    transcript = await summary_service.get_summary_by_uuid(
        user_email, get_transcript_id(user_id, file_id)
    )
    assert transcript is not None and transcript.content is not None
    assert "Page Keywords: OKR" in transcript.content


async def test_summary_storage_key_rotation_updates_in_place_and_resolves_vfs_source_path(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    summary_service: SummaryService,
) -> None:
    """Verify rotating storage_key across syncs updates the same summary rows and uses full VFS source_path."""
    user_id = 113
    user_email = "rotation@example.com"
    note_dir_id = 900
    work_dir_id = 901
    file_id = 902

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email=user_email, password_md5="hash"))
        session.add_all(
            [
                UserFileDO(
                    id=note_dir_id,
                    user_id=user_id,
                    file_name="Note",
                    directory_id=0,
                    is_folder="Y",
                    is_active="Y",
                ),
                UserFileDO(
                    id=work_dir_id,
                    user_id=user_id,
                    file_name="Work",
                    directory_id=note_dir_id,
                    is_folder="Y",
                    is_active="Y",
                ),
                UserFileDO(
                    id=file_id,
                    user_id=user_id,
                    storage_key="uuid-v1-550.note",
                    file_name="daily.note",
                    directory_id=work_dir_id,
                    is_folder="N",
                    is_active="Y",
                ),
                NotePageContentDO(
                    file_id=file_id,
                    page_index=0,
                    page_id="p0",
                    content_hash="h1",
                    text_content="Sync 1 content",
                ),
            ]
        )
        await session.commit()

    assert await summary_module.run(file_id, session_manager) is True
    first_items = sorted(
        await summary_service.list_summaries_for_file_internal(user_email, file_id),
        key=lambda x: x.data_source or "",
    )
    expected_group_uuid = get_summary_group_id(user_id, file_id)
    assert [
        (
            i.unique_identifier,
            i.parent_unique_identifier,
            i.source_path,
            i.data_source,
        )
        for i in first_items
    ] == [
        (
            get_transcript_id(user_id, file_id),
            expected_group_uuid,
            "Note/Work/daily.note",
            "OCR",
        ),
        (
            get_summary_id(user_id, file_id),
            expected_group_uuid,
            "Note/Work/daily.note",
            "fake-summary-v1",
        ),
    ]
    first_ids = [item.id for item in first_items]

    # Simulate tablet sync rotating storage_key and updating page text
    async with session_manager.session() as session:
        uf = await session.get(UserFileDO, file_id)
        assert uf is not None
        uf.storage_key = "uuid-v2-550.note"
        p0 = (
            await session.execute(
                select(NotePageContentDO).where(NotePageContentDO.file_id == file_id)
            )
        ).scalar_one()
        p0.text_content = "Sync 2 updated content"
        await session.commit()

    await summary_module.process(file_id, session_manager)
    second_items = sorted(
        await summary_service.list_summaries_for_file_internal(user_email, file_id),
        key=lambda x: x.data_source or "",
    )
    assert [item.id for item in second_items] == first_ids
    assert any("Sync 2 updated content" in (i.content or "") for i in second_items)


async def test_summary_cleans_up_legacy_storage_key_duplicates_while_preserving_annotated_rows(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    summary_service: SummaryService,
) -> None:
    """Verify legacy storage_key-keyed duplicates and empty groups are soft-deleted while user-annotated rows survive."""
    user_id = 114
    user_email = "legacy_cleanup@example.com"
    file_id = 914

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email=user_email, password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key="current-key.note",
                file_name="daily.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="h0",
                text_content="Active page text",
            )
        )
        await session.commit()

    # Legacy unannotated sync artifacts -> should be soft-deleted along with their empty group
    await summary_service.add_group(
        user_email,
        AddSummaryGroupDTO(
            unique_identifier="legacy-1.note-group",
            name="daily.note",
            md5_hash="m1",
        ),
    )
    await summary_service.add_summary(
        user_email,
        AddSummaryDTO(
            file_id=file_id,
            unique_identifier="legacy-1.note-transcript",
            parent_unique_identifier="legacy-1.note-group",
            content="Old transcript",
            data_source="OCR",
        ),
    )
    await summary_service.add_summary(
        user_email,
        AddSummaryDTO(
            file_id=file_id,
            unique_identifier="legacy-1.note-summary",
            parent_unique_identifier="legacy-1.note-group",
            content="Old summary",
            data_source="GEMINI",
        ),
    )

    # Legacy user-annotated sync artifacts -> must NEVER be deleted
    await summary_service.add_group(
        user_email,
        AddSummaryGroupDTO(
            unique_identifier="legacy-2.note-group",
            name="daily.note",
            md5_hash="m2",
        ),
    )
    await summary_service.add_summary(
        user_email,
        AddSummaryDTO(
            file_id=file_id,
            unique_identifier="legacy-2.note-summary",
            parent_unique_identifier="legacy-2.note-group",
            content="Annotated summary",
            data_source="GEMINI",
            comment_str="Important user note",
        ),
    )
    await summary_service.add_summary(
        user_email,
        AddSummaryDTO(
            file_id=file_id,
            unique_identifier="legacy-3.note-summary",
            content="Handwritten annotated summary",
            data_source="GEMINI",
            handwrite_inner_name="user-ink.bin",
        ),
    )

    assert await summary_module.run(file_id, session_manager) is True

    assert (
        await summary_service.get_summary_by_uuid(
            user_email, "legacy-1.note-transcript"
        )
        is None
    )
    assert (
        await summary_service.get_summary_by_uuid(user_email, "legacy-1.note-summary")
        is None
    )
    assert (
        await summary_service.get_summary_by_uuid(user_email, "legacy-1.note-group")
        is None
    )

    assert (
        await summary_service.get_summary_by_uuid(user_email, "legacy-2.note-summary")
        is not None
    )
    assert (
        await summary_service.get_summary_by_uuid(user_email, "legacy-2.note-group")
        is not None
    )
    assert (
        await summary_service.get_summary_by_uuid(user_email, "legacy-3.note-summary")
        is not None
    )


async def test_summary_erase_preserves_annotated_generated_rows(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    summary_service: SummaryService,
) -> None:
    """Verify erasing all pages deletes unannotated generated rows while preserving user-annotated ones."""
    user_id = 115
    user_email = "erase_annotated@example.com"
    file_id = 915

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email=user_email, password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key="annotated.note",
                file_name="annotated.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="h0",
                text_content="Initial note",
            )
        )
        await session.commit()

    assert await summary_module.run(file_id, session_manager) is True
    summary_item = await summary_service.get_summary_by_uuid(
        user_email, get_summary_id(user_id, file_id)
    )
    assert summary_item is not None and summary_item.id is not None

    await summary_service.update_summary(
        user_email,
        UpdateSummaryDTO(id=summary_item.id, comment_str="Keep my reflection"),
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
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_transcript_id(user_id, file_id)
        )
        is None
    )
    preserved = await summary_service.get_summary_by_uuid(
        user_email, get_summary_id(user_id, file_id)
    )
    assert preserved is not None
    assert preserved.comment_str == "Keep my reflection"
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_summary_group_id(user_id, file_id)
        )
        is not None
    )


async def test_summary_pruning_preserves_user_categories_and_annotated_groups(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    summary_service: SummaryService,
) -> None:
    """Verify pruning never deletes user-created categories or groups carrying user annotations."""
    user_id = 116
    user_email = "preserve_groups@example.com"
    file_id = 916

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email=user_email, password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key="note.note",
                file_name="note.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="h0",
                text_content="Active page",
            )
        )
        await session.commit()

    # User-created Partner App category (32-char hex UUID, not ending in '-group')
    user_category = await summary_service.add_group(
        user_email,
        AddSummaryGroupDTO(
            unique_identifier="2799b74528407f6aeeeff095f7685e9e",
            name="example category",
            md5_hash="cat-md5",
        ),
    )
    await summary_service.add_summary(
        user_email,
        AddSummaryDTO(
            file_id=file_id,
            unique_identifier="legacy-user-cat.note-summary",
            parent_unique_identifier=user_category.unique_identifier,
            content="Old summary moved to user category",
            data_source="GEMINI",
        ),
    )

    # Legacy '-group' that itself has a group-level user comment
    annotated_group = await summary_service.add_group(
        user_email,
        AddSummaryGroupDTO(
            unique_identifier="legacy-annotated.note-group",
            name="note.note",
            md5_hash="grp-md5",
        ),
    )
    assert annotated_group.id is not None
    await summary_service.update_group(
        user_email,
        UpdateSummaryGroupDTO(
            id=annotated_group.id,
            md5_hash="grp-md5",
            comment_str="Group-level note",
        ),
    )
    await summary_service.add_summary(
        user_email,
        AddSummaryDTO(
            file_id=file_id,
            unique_identifier="legacy-annotated.note-summary",
            parent_unique_identifier=annotated_group.unique_identifier,
            content="Unannotated child summary",
            data_source="GEMINI",
        ),
    )

    assert await summary_module.run(file_id, session_manager) is True

    # Both unannotated legacy child summaries were pruned, while both groups survive
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, "legacy-user-cat.note-summary"
        )
        is None
    )
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, "legacy-annotated.note-summary"
        )
        is None
    )
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, "2799b74528407f6aeeeff095f7685e9e"
        )
        is not None
    )
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, "legacy-annotated.note-group"
        )
        is not None
    )
