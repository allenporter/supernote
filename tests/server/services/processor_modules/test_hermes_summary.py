"""Tests for HermesSummaryModule.

Uses a mocked HermesSummaryService (never shells out to a real Hermes CLI)
and a generic, purpose-authored fixture transcript
(`tests/fixtures/ambiguous_ocr_sample.txt`) that mixes clear meeting/journal
notes with one deliberately garbled line, to exercise the
"resolve ambiguous OCR text using surrounding context" flow described in the
issue.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from supernote.models.summary import AddSummaryDTO, AddSummaryGroupDTO
from supernote.server.config import AuthConfig, ServerConfig
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.models.summary import SummaryDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.hermes_summary import (
    HermesSummaryProcessError,
    HermesSummaryService,
)
from supernote.server.services.processor_modules.hermes_summary import (
    METADATA_PAGE_COUNT,
    METADATA_SOURCE_HASH,
    HermesSummaryModule,
)
from supernote.server.services.summary import SummaryService
from supernote.server.services.user import UserService
from supernote.server.utils.paths import (
    get_hermes_summary_id,
    get_summary_group_id,
    get_transcript_id,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "fixtures" / "ambiguous_ocr_sample.txt"
)
FIXTURE_TEXT = FIXTURE_PATH.read_text()


@pytest.fixture
def server_config_hermes(tmp_path: Path) -> ServerConfig:
    conf = ServerConfig(
        auth=AuthConfig(secret_key="secret"),
        storage_dir=str(tmp_path),
    )
    conf.hermes_summary_enabled = True
    return conf


@pytest.fixture
def server_config_hermes_disabled(tmp_path: Path) -> ServerConfig:
    conf = ServerConfig(
        auth=AuthConfig(secret_key="secret"),
        storage_dir=str(tmp_path),
    )
    # hermes_summary_enabled defaults to False.
    return conf


@pytest.fixture
def mock_hermes_summary_service() -> MagicMock:
    service = MagicMock(spec=HermesSummaryService)
    service.generate_interpretation = AsyncMock(
        return_value=(
            "Follow up with Sarah about the draft contract before signing it "
            "(uncertain: name inferred from context)."
        )
    )
    return service


@pytest.fixture
def summary_service(
    user_service: UserService, session_manager: DatabaseSessionManager
) -> SummaryService:
    return SummaryService(user_service, session_manager)


@pytest.fixture
def hermes_module(
    file_service: FileService,
    server_config_hermes: ServerConfig,
    mock_hermes_summary_service: MagicMock,
    summary_service: SummaryService,
) -> HermesSummaryModule:
    return HermesSummaryModule(
        file_service=file_service,
        config=server_config_hermes,
        hermes_summary_service=mock_hermes_summary_service,
        summary_service=summary_service,
    )


async def _setup_file(
    session_manager: DatabaseSessionManager,
    file_id: int,
    user_id: int,
    user_email: str,
    storage_key: str,
    file_name: str,
    page_text: str,
) -> None:
    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email=user_email, password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key=storage_key,
                file_name=file_name,
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="content-hash-v1",
                text_content=page_text,
                embedding=json.dumps([0.1, 0.2, 0.3]),
            )
        )
        await session.commit()


async def _get_task(
    session_manager: DatabaseSessionManager, file_id: int
) -> SystemTaskDO | None:
    async with session_manager.session() as session:
        return (
            (
                await session.execute(
                    select(SystemTaskDO)
                    .where(SystemTaskDO.file_id == file_id)
                    .where(SystemTaskDO.task_type == "HERMES_SUMMARY_GENERATION")
                    .where(SystemTaskDO.key == "global")
                )
            )
            .scalars()
            .first()
        )


async def _get_summary_rows(
    session_manager: DatabaseSessionManager, unique_identifier: str
) -> list[SummaryDO]:
    async with session_manager.session() as session:
        return list(
            (
                await session.execute(
                    select(SummaryDO).where(
                        SummaryDO.unique_identifier == unique_identifier
                    )
                )
            )
            .scalars()
            .all()
        )


async def test_hermes_summary_completed_and_creates_row(
    hermes_module: HermesSummaryModule,
    session_manager: DatabaseSessionManager,
    mock_hermes_summary_service: MagicMock,
    summary_service: SummaryService,
) -> None:
    user_id = 500
    user_email = "hermes-basic@example.com"
    file_id = 5001
    storage_key = "hermes_key_1"

    await _setup_file(
        session_manager,
        file_id,
        user_id,
        user_email,
        storage_key,
        "notes.note",
        FIXTURE_TEXT,
    )

    # Pre-existing OCR transcript summary row that must remain byte-for-byte
    # unchanged by the Hermes module.
    ocr_content = f"--- Page 1 ---\n{FIXTURE_TEXT}"
    await summary_service.upsert_group(
        user_email,
        AddSummaryGroupDTO(
            unique_identifier=get_summary_group_id(storage_key),
            name="notes.note",
            md5_hash="groupmd5",
        ),
    )

    await summary_service.upsert_summary(
        user_email,
        AddSummaryDTO(
            file_id=file_id,
            unique_identifier=get_transcript_id(storage_key),
            parent_unique_identifier=get_summary_group_id(storage_key),
            content=ocr_content,
            data_source="OCR",
            source_path="notes.note",
        ),
    )

    result = await hermes_module.run(file_id, session_manager)
    assert result is True

    # Task reaches COMPLETED.
    task = await _get_task(session_manager, file_id)
    assert task is not None
    assert task.status == "COMPLETED"

    # A HERMES_INTERPRETATION row now exists.
    hermes_uuid = get_hermes_summary_id(storage_key)
    hermes_rows = await _get_summary_rows(session_manager, hermes_uuid)
    assert len(hermes_rows) == 1
    hermes_row = hermes_rows[0]
    assert hermes_row.data_source == "HERMES_INTERPRETATION"
    assert hermes_row.parent_unique_identifier == get_summary_group_id(storage_key)
    assert hermes_row.content == (
        "Follow up with Sarah about the draft contract before signing it "
        "(uncertain: name inferred from context)."
    )
    assert hermes_row.extra_metadata is not None
    meta = json.loads(hermes_row.extra_metadata)
    assert METADATA_SOURCE_HASH in meta
    assert meta[METADATA_PAGE_COUNT] == 1

    # The OCR transcript row is untouched.
    ocr_rows = await _get_summary_rows(session_manager, get_transcript_id(storage_key))
    assert len(ocr_rows) == 1
    assert ocr_rows[0].content == ocr_content
    assert ocr_rows[0].data_source == "OCR"

    # Hermes service was called with the page-marked transcript.
    call_kwargs = mock_hermes_summary_service.generate_interpretation.call_args.kwargs
    assert call_kwargs["file_id"] == file_id
    assert call_kwargs["page_count"] == 1
    assert "S4rah" in call_kwargs["transcript"]  # The ambiguous/garbled phrase.
    assert "vendor renewal deadline" in call_kwargs["transcript"]  # Clear context.


async def test_hermes_summary_rerun_unchanged_does_not_duplicate(
    hermes_module: HermesSummaryModule,
    session_manager: DatabaseSessionManager,
    mock_hermes_summary_service: MagicMock,
) -> None:
    user_id = 501
    user_email = "hermes-rerun@example.com"
    file_id = 5002
    storage_key = "hermes_key_2"

    await _setup_file(
        session_manager,
        file_id,
        user_id,
        user_email,
        storage_key,
        "rerun.note",
        FIXTURE_TEXT,
    )

    await hermes_module.run(file_id, session_manager)
    await hermes_module.run(file_id, session_manager)

    hermes_uuid = get_hermes_summary_id(storage_key)
    hermes_rows = await _get_summary_rows(session_manager, hermes_uuid)
    assert len(hermes_rows) == 1

    # Hermes CLI should only have been invoked once -- the second run detected
    # the unchanged source hash and skipped regeneration.
    assert mock_hermes_summary_service.generate_interpretation.call_count == 1


async def test_hermes_summary_regenerates_on_ocr_change(
    hermes_module: HermesSummaryModule,
    session_manager: DatabaseSessionManager,
    mock_hermes_summary_service: MagicMock,
) -> None:
    user_id = 502
    user_email = "hermes-change@example.com"
    file_id = 5003
    storage_key = "hermes_key_3"

    await _setup_file(
        session_manager,
        file_id,
        user_id,
        user_email,
        storage_key,
        "change.note",
        FIXTURE_TEXT,
    )

    await hermes_module.run(file_id, session_manager)

    # Simulate a page edit: OCR text and content hash change.
    async with session_manager.session() as session:
        stmt = select(NotePageContentDO).where(NotePageContentDO.file_id == file_id)
        page = (await session.execute(stmt)).scalars().first()
        assert page is not None
        page.text_content = FIXTURE_TEXT + "\nAdditional note added after review."
        page.content_hash = "content-hash-v2"
        await session.commit()

    mock_hermes_summary_service.generate_interpretation.return_value = (
        "Updated interpretation reflecting the newly added note."
    )

    await hermes_module.run(file_id, session_manager)

    hermes_uuid = get_hermes_summary_id(storage_key)
    hermes_rows = await _get_summary_rows(session_manager, hermes_uuid)
    assert len(hermes_rows) == 1  # Updated in place, not duplicated.
    assert (
        hermes_rows[0].content
        == "Updated interpretation reflecting the newly added note."
    )
    assert mock_hermes_summary_service.generate_interpretation.call_count == 2


async def test_hermes_summary_failure_marks_task_failed_and_leaves_rest_untouched(
    hermes_module: HermesSummaryModule,
    session_manager: DatabaseSessionManager,
    mock_hermes_summary_service: MagicMock,
) -> None:
    user_id = 503
    user_email = "hermes-fail@example.com"
    file_id = 5004
    storage_key = "hermes_key_4"

    await _setup_file(
        session_manager,
        file_id,
        user_id,
        user_email,
        storage_key,
        "fail.note",
        FIXTURE_TEXT,
    )

    mock_hermes_summary_service.generate_interpretation.side_effect = (
        HermesSummaryProcessError(1, "boom")
    )

    result = await hermes_module.run(file_id, session_manager)
    assert result is False

    task = await _get_task(session_manager, file_id)
    assert task is not None
    assert task.status == "FAILED"
    assert task.last_error is not None
    assert "boom" in task.last_error

    # No Hermes summary row was created.
    hermes_uuid = get_hermes_summary_id(storage_key)
    assert await _get_summary_rows(session_manager, hermes_uuid) == []

    # OCR/embedding data for the page is unaffected.
    async with session_manager.session() as session:
        stmt = select(NotePageContentDO).where(NotePageContentDO.file_id == file_id)
        page = (await session.execute(stmt)).scalars().first()
        assert page is not None
        assert page.text_content == FIXTURE_TEXT
        assert page.embedding is not None


async def test_hermes_summary_disabled_is_noop(
    file_service: FileService,
    server_config_hermes_disabled: ServerConfig,
    mock_hermes_summary_service: MagicMock,
    summary_service: SummaryService,
    session_manager: DatabaseSessionManager,
) -> None:
    module = HermesSummaryModule(
        file_service=file_service,
        config=server_config_hermes_disabled,
        hermes_summary_service=mock_hermes_summary_service,
        summary_service=summary_service,
    )

    user_id = 504
    user_email = "hermes-disabled@example.com"
    file_id = 5005
    storage_key = "hermes_key_5"

    await _setup_file(
        session_manager,
        file_id,
        user_id,
        user_email,
        storage_key,
        "disabled.note",
        FIXTURE_TEXT,
    )

    result = await module.run(file_id, session_manager)
    assert result is True

    mock_hermes_summary_service.generate_interpretation.assert_not_called()

    # No task row is created at all (graceful skip via run_if_needed).
    task = await _get_task(session_manager, file_id)
    assert task is None

    hermes_uuid = get_hermes_summary_id(storage_key)
    assert await _get_summary_rows(session_manager, hermes_uuid) == []
