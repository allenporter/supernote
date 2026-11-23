import asyncio
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
from supernote.server.ai.prompts import SummarySegment
from supernote.server.components.fake_ai.summary import FakeSummaryModel
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
    AI_SUMMARIES_GROUP_NAME,
    get_ai_summaries_group_id,
    get_summary_id,
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

    group_uuid = get_ai_summaries_group_id(user_id)
    group = await summary_service.get_summary_by_uuid(user_email, group_uuid)
    assert group is not None
    assert group.is_summary_group == BooleanEnum.YES
    assert group.name == AI_SUMMARIES_GROUP_NAME

    file_summaries = await summary_service.list_summaries_for_file_internal(
        user_email, file_id
    )
    assert len(file_summaries) == 1

    ai_summary = await summary_service.get_summary_by_uuid(
        user_email, get_summary_id(user_id, file_id)
    )
    assert ai_summary is not None
    assert ai_summary.parent_unique_identifier == group_uuid
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

    group_uuid = get_ai_summaries_group_id(user_id)
    existing_group = await summary_service.add_group(
        user_email,
        AddSummaryGroupDTO(
            unique_identifier=group_uuid,
            name="Renamed AI Category",
            md5_hash="old_hash",
        ),
    )
    existing_summary = await summary_service.add_summary(
        user_email,
        AddSummaryDTO(
            file_id=file_id,
            unique_identifier=get_summary_id(user_id, file_id),
            parent_unique_identifier=group_uuid,
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

    updated_group = await summary_service.get_summary_by_uuid(user_email, group_uuid)
    assert updated_group is not None
    assert updated_group.id == existing_group.id
    assert updated_group.name == "Renamed AI Category"

    updated_summary = await summary_service.get_summary_by_uuid(
        user_email, get_summary_id(user_id, file_id)
    )
    assert updated_summary is not None
    assert updated_summary.id == existing_summary.id
    assert updated_summary.parent_unique_identifier == group_uuid
    assert updated_summary.content is not None
    assert "## 2023-10-28 (Pages 3, 4)" in updated_summary.content
    assert "New AI Summary" in updated_summary.content

    assert updated_summary.metadata is not None
    meta = json.loads(updated_summary.metadata)
    assert meta[METADATA_SEGMENTS][0]["page_refs"] == [3, 4]

    # Deleting the shared group and child summary, then rerunning recreates both
    assert updated_group.id is not None
    await summary_service.delete_group(user_email, updated_group.id)
    assert await summary_service.get_summary_by_uuid(user_email, group_uuid) is None
    await summary_module.process(file_id, session_manager)
    assert await summary_service.get_summary_by_uuid(user_email, group_uuid) is not None
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

    assert len(empty_summary_model.calls) == 1
    prompt_arg = empty_summary_model.calls[0]
    assert "--- Page 1 ---" in prompt_arg
    assert "Page ID: P20231027120000abc" in prompt_arg
    assert "Page Date (Inferred): 2023-10-27" in prompt_arg

    group = await summary_service.get_summary_by_uuid(
        user_email, get_ai_summaries_group_id(user_id)
    )
    assert group is not None
    assert group.name == AI_SUMMARIES_GROUP_NAME


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

    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_ai_summaries_group_id(user_id)
        )
        is None
    )
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
            user_email, get_ai_summaries_group_id(user_id)
        )
        is None
    )


async def test_summary_deletes_existing_summary_when_all_pages_erased(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    fake_summary_model: FakeSummaryModel,
    summary_service: SummaryService,
) -> None:
    """Verify erasing all pages on an already-summarized note deletes its summary without an LLM call."""
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
            user_email, get_summary_id(user_id, file_id)
        )
        is None
    )
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_ai_summaries_group_id(user_id)
        )
        is not None
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
            user_email, get_ai_summaries_group_id(user_id)
        )
        is None
    )


async def test_summary_preserves_manual_digests_when_notebook_erased(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    fake_summary_model: FakeSummaryModel,
    summary_service: SummaryService,
) -> None:
    """Verify erasing a notebook deletes AI summary items while preserving user-created digests in the category."""
    user_id = 111
    user_email = "manual_digest@example.com"
    file_id = 811
    storage_key = "manual_digest_note_key"
    group_uuid = get_ai_summaries_group_id(user_id)

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
            file_id=file_id,
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

    # AI summary is removed, while the user digest and shared category survive
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


async def test_summary_includes_page_keywords_in_prompt(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    fake_summary_model: FakeSummaryModel,
) -> None:
    """Verify SummaryModule injects Page Keywords from NotePageMetadataDO into the summary prompt."""
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
    assert len(fake_summary_model.calls) == 1
    assert "Page Keywords: OKR" in fake_summary_model.calls[0]


async def test_summary_storage_key_rotation_updates_in_place_and_resolves_vfs_source_path(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    fake_summary_model: FakeSummaryModel,
    summary_service: SummaryService,
) -> None:
    """Verify rotating storage_key across syncs updates the same summary row and uses full VFS source_path."""
    user_id = 113
    user_email = "rotation@example.com"
    container_dir_id = 899
    note_dir_id = 900
    work_dir_id = 901
    file_id = 902

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email=user_email, password_md5="hash"))
        session.add_all(
            [
                UserFileDO(
                    id=container_dir_id,
                    user_id=user_id,
                    file_name="NOTE",
                    directory_id=0,
                    is_folder="Y",
                    is_active="Y",
                ),
                UserFileDO(
                    id=note_dir_id,
                    user_id=user_id,
                    file_name="Note",
                    directory_id=container_dir_id,
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
    first_items = await summary_service.list_summaries_for_file_internal(
        user_email, file_id
    )
    expected_group_uuid = get_ai_summaries_group_id(user_id)
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

    updated_model = FakeSummaryModel(
        segments=[
            SummarySegment(
                date_range="2026-11-16",
                summary="Sync 2 updated summary",
                extracted_dates=["2026-11-16"],
                page_refs=[1],
            )
        ]
    )
    summary_module.summary_model = updated_model
    await summary_module.process(file_id, session_manager)
    assert "Sync 2 updated content" in updated_model.calls[-1]
    second_items = await summary_service.list_summaries_for_file_internal(
        user_email, file_id
    )
    assert [item.id for item in second_items] == first_ids
    assert "Sync 2 updated summary" in (second_items[0].content or "")


async def test_summary_leaves_legacy_storage_key_rows_untouched_at_runtime(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    summary_service: SummaryService,
) -> None:
    """Verify runtime processing never deletes pre-existing legacy storage_key rows or groups."""
    user_id = 114
    user_email = "legacy_untouched@example.com"
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
            unique_identifier="legacy-1.note-summary",
            parent_unique_identifier="legacy-1.note-group",
            content="Old summary",
            data_source="GEMINI",
        ),
    )

    assert await summary_module.run(file_id, session_manager) is True

    assert (
        await summary_service.get_summary_by_uuid(user_email, "legacy-1.note-summary")
        is not None
    )
    assert (
        await summary_service.get_summary_by_uuid(user_email, "legacy-1.note-group")
        is not None
    )
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_summary_id(user_id, file_id)
        )
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
    preserved = await summary_service.get_summary_by_uuid(
        user_email, get_summary_id(user_id, file_id)
    )
    assert preserved is not None
    assert preserved.comment_str == "Keep my reflection"
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_ai_summaries_group_id(user_id)
        )
        is not None
    )


async def test_summary_preserves_partner_app_category_reassignment(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    summary_service: SummaryService,
) -> None:
    """Verify moving a generated summary to a custom category or Uncategorized in Partner App sticks across syncs."""
    user_id = 117
    user_email = "reassign@example.com"
    file_id = 917

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email=user_email, password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key="reassign.note",
                file_name="reassign.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="h0",
                text_content="First draft",
            )
        )
        await session.commit()

    assert await summary_module.run(file_id, session_manager) is True
    created = await summary_service.get_summary_by_uuid(
        user_email, get_summary_id(user_id, file_id)
    )
    assert created is not None and created.id is not None
    assert created.parent_unique_identifier == get_ai_summaries_group_id(user_id)

    # User moves summary into custom Partner App category
    custom_cat = await summary_service.add_group(
        user_email,
        AddSummaryGroupDTO(
            unique_identifier="2799b74528407f6aeeeff095f7685e9e",
            name="example category",
            md5_hash="custom-md5",
        ),
    )
    await summary_service.update_summary(
        user_email,
        UpdateSummaryDTO(
            id=created.id,
            parent_unique_identifier=custom_cat.unique_identifier,
        ),
    )

    await summary_module.process(file_id, session_manager)
    after_custom = await summary_service.get_summary(user_email, created.id)
    assert after_custom.parent_unique_identifier == "2799b74528407f6aeeeff095f7685e9e"

    # User moves summary to Uncategorized ("")
    await summary_service.update_summary(
        user_email,
        UpdateSummaryDTO(id=created.id, parent_unique_identifier=""),
    )
    await summary_module.process(file_id, session_manager)
    after_uncat = await summary_service.get_summary(user_email, created.id)
    assert after_uncat.parent_unique_identifier == ""


async def test_summary_reparents_existing_summary_off_legacy_group_without_deleting_legacy_rows(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    summary_service: SummaryService,
) -> None:
    """Verify existing summary pointing to a legacy '-group' reparents to 'AI Summaries' without deleting legacy rows."""
    user_id = 118
    user_email = "migrate_group@example.com"
    file_id = 918

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email=user_email, password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key="mig.note",
                file_name="mig.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="h0",
                text_content="Updated note text",
            )
        )
        await session.commit()

    await summary_service.add_group(
        user_email,
        AddSummaryGroupDTO(
            unique_identifier="mig.note-group",
            name="mig.note",
            md5_hash="old-md5",
        ),
    )
    await summary_service.add_summary(
        user_email,
        AddSummaryDTO(
            file_id=file_id,
            unique_identifier=get_summary_id(user_id, file_id),
            parent_unique_identifier="mig.note-group",
            content="Existing summary on legacy group",
            data_source="GEMINI",
        ),
    )

    assert await summary_module.run(file_id, session_manager) is True

    migrated = await summary_service.get_summary_by_uuid(
        user_email, get_summary_id(user_id, file_id)
    )
    assert migrated is not None
    assert migrated.parent_unique_identifier == get_ai_summaries_group_id(user_id)
    assert (
        await summary_service.get_summary_by_uuid(user_email, "mig.note-group")
        is not None
    )


async def test_summary_cleanup_file_preserves_user_data_and_scopes_by_user(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    summary_service: SummaryService,
) -> None:
    """Verify cleanup_file deletes unannotated generated rows while detaching user Digests and preserving categories."""
    user_id = 119
    user_email = "cleanup1@example.com"
    other_user_id = 120
    other_email = "cleanup2@example.com"
    file_id = 919

    async with session_manager.session() as session:
        session.add_all(
            [
                UserDO(id=user_id, email=user_email, password_md5="hash"),
                UserDO(id=other_user_id, email=other_email, password_md5="hash"),
                UserFileDO(
                    id=file_id,
                    user_id=user_id,
                    storage_key="del.note",
                    file_name="del.note",
                    directory_id=0,
                ),
                NotePageContentDO(
                    file_id=file_id,
                    page_index=0,
                    page_id="p0",
                    content_hash="h0",
                    text_content="To be deleted",
                ),
            ]
        )
        await session.commit()

    assert await summary_module.run(file_id, session_manager) is True

    # Custom Partner App category + manual user digest + annotated legacy summary + annotated legacy group
    custom_cat = await summary_service.add_group(
        user_email,
        AddSummaryGroupDTO(
            unique_identifier="2799b74528407f6aeeeff095f7685e9e",
            name="example category",
            md5_hash="cat-md5",
        ),
    )
    manual_digest = await summary_service.add_summary(
        user_email,
        AddSummaryDTO(
            file_id=file_id,
            unique_identifier="manual-user-digest",
            parent_unique_identifier=custom_cat.unique_identifier,
            content="User highlight",
            data_source="USER",
        ),
    )
    annotated_legacy_group = await summary_service.add_group(
        user_email,
        AddSummaryGroupDTO(
            unique_identifier="annotated-legacy.note-group",
            name="del.note",
            md5_hash="lg-md5",
        ),
    )
    assert annotated_legacy_group.id is not None
    await summary_service.update_group(
        user_email,
        UpdateSummaryGroupDTO(
            id=annotated_legacy_group.id,
            md5_hash="lg-md5",
            comment_str="Keep group comment",
        ),
    )
    await summary_service.add_summary(
        user_email,
        AddSummaryDTO(
            file_id=file_id,
            unique_identifier="unannotated-in-annotated.note-summary",
            parent_unique_identifier=annotated_legacy_group.unique_identifier,
            content="Unannotated child",
            data_source="GEMINI",
        ),
    )
    annotated_summary = await summary_service.add_summary(
        user_email,
        AddSummaryDTO(
            file_id=file_id,
            unique_identifier="annotated-legacy.note-summary",
            content="Summary with user ink",
            data_source="GEMINI",
            handwrite_inner_name="ink-key.bin",
        ),
    )

    other_summary = await summary_service.add_summary(
        other_email,
        AddSummaryDTO(
            file_id=file_id,
            unique_identifier="other-user-summary",
            content="Other user's summary with colliding file_id",
        ),
    )

    await summary_module.cleanup_file(file_id, user_id, session_manager)

    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_summary_id(user_id, file_id)
        )
        is None
    )
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, "unannotated-in-annotated.note-summary"
        )
        is None
    )
    # Shared 'AI Summaries', user custom category, and annotated legacy group all survive
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_ai_summaries_group_id(user_id)
        )
        is not None
    )
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, "2799b74528407f6aeeeff095f7685e9e"
        )
        is not None
    )
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, "annotated-legacy.note-group"
        )
        is not None
    )
    # Manual user digest and annotated summary survive with file_id detached (None)
    assert manual_digest.id is not None and annotated_summary.id is not None
    detached_manual = await summary_service.get_summary(user_email, manual_digest.id)
    assert detached_manual.file_id is None
    assert detached_manual.content == "User highlight"
    detached_annotated = await summary_service.get_summary(
        user_email, annotated_summary.id
    )
    assert detached_annotated.file_id is None
    assert detached_annotated.handwrite_inner_name == "ink-key.bin"
    # Other user's row is untouched
    assert (
        await summary_service.get_summary_by_uuid(other_email, "other-user-summary")
        == other_summary
    )


async def test_summary_concurrent_group_creation_is_race_free(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    summary_service: SummaryService,
) -> None:
    """Verify concurrent processing of multiple files for the same user creates 'AI Summaries' exactly once."""
    user_id = 121
    user_email = "concurrent@example.com"
    f1, f2 = 921, 922

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email=user_email, password_md5="hash"))
        session.add_all(
            [
                UserFileDO(
                    id=f1,
                    user_id=user_id,
                    storage_key="c1.note",
                    file_name="c1.note",
                    directory_id=0,
                ),
                UserFileDO(
                    id=f2,
                    user_id=user_id,
                    storage_key="c2.note",
                    file_name="c2.note",
                    directory_id=0,
                ),
                NotePageContentDO(
                    file_id=f1,
                    page_index=0,
                    page_id="p0",
                    content_hash="h1",
                    text_content="Note 1 text",
                ),
                NotePageContentDO(
                    file_id=f2,
                    page_index=0,
                    page_id="p0",
                    content_hash="h2",
                    text_content="Note 2 text",
                ),
            ]
        )
        await session.commit()

    await asyncio.gather(
        summary_module.process(f1, session_manager),
        summary_module.process(f2, session_manager),
    )

    assert await summary_service.count_groups(user_email) == 1
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_summary_id(user_id, f1)
        )
        is not None
    )
    assert (
        await summary_service.get_summary_by_uuid(
            user_email, get_summary_id(user_id, f2)
        )
        is not None
    )


async def test_summary_clears_stale_metadata_when_updated_segments_empty(
    summary_module: SummaryModule,
    session_manager: DatabaseSessionManager,
    summary_service: SummaryService,
) -> None:
    """Verify updating an existing summary when SummaryModel returns zero segments clears stale segment metadata."""
    user_id = 122
    user_email = "empty_seg@example.com"
    file_id = 923

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email=user_email, password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key="seg.note",
                file_name="seg.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="h1",
                text_content="Initial structured note",
            )
        )
        await session.commit()

    assert await summary_module.run(file_id, session_manager) is True
    first = await summary_service.get_summary_by_uuid(
        user_email, get_summary_id(user_id, file_id)
    )
    assert first is not None and bool(first.metadata)

    summary_module.summary_model = FakeSummaryModel(segments=[])
    await summary_module.process(file_id, session_manager)
    updated = await summary_service.get_summary_by_uuid(
        user_email, get_summary_id(user_id, file_id)
    )
    assert updated is not None
    assert updated.content == "No summary generated."
    assert updated.metadata == ""
