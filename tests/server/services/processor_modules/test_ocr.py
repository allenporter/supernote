import pytest
from sqlalchemy import select
from sqlalchemy.orm import undefer

from supernote.server.ai.models.ocr import OcrModel
from supernote.server.components.fake_ai.ocr import FakeOcrModel
from supernote.server.constants import CACHE_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    NotePageMetadataDO,
    SystemTaskDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import NotePageTranscribedEvent
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules.ocr import OcrModule
from supernote.server.utils.paths import get_page_png_path


@pytest.fixture
def ocr_module(
    file_service: FileService,
    fake_ocr_model: FakeOcrModel,
) -> OcrModule:
    return OcrModule(
        file_service=file_service,
        ocr_model=fake_ocr_model,
    )


async def test_process_ocr_success(
    ocr_module: OcrModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    fake_ocr_model: FakeOcrModel,
) -> None:
    # Setup Data
    user_id = 100
    file_id = 999
    page_index = 0
    storage_key = "test_note_storage_key"

    # Create dummy PNG
    png_content = b"fake-png-data"
    png_path = get_page_png_path(file_id, "p0")
    await blob_storage.put(CACHE_BUCKET, png_path, png_content)

    async with session_manager.session() as session:
        user_file = UserFileDO(
            id=file_id,
            user_id=user_id,
            storage_key=storage_key,
            file_name="real.note",
            directory_id=0,
        )
        session.add(user_file)

        content = NotePageContentDO(
            file_id=file_id,
            page_index=page_index,
            page_id="p0",
            content_hash="somehash",
        )
        session.add(content)
        await session.commit()

    await ocr_module.run(file_id, session_manager, page_index=page_index, page_id="p0")

    assert len(fake_ocr_model.calls) == 1
    called_png, called_prompt = fake_ocr_model.calls[0]
    assert called_png == png_content
    assert "--- Page 1 ---" in called_prompt
    assert "Notebook Filename: real.note" in called_prompt
    assert "Page ID: p0" in called_prompt

    # Verify DB Updates
    async with session_manager.session() as session:
        updated_content = (
            (
                await session.execute(
                    select(NotePageContentDO)
                    .where(NotePageContentDO.file_id == file_id)
                    .where(NotePageContentDO.page_index == page_index)
                )
            )
            .scalars()
            .first()
        )

        assert updated_content is not None
        assert updated_content.text_content == f"Transcribed ({len(png_content)} bytes)"

        task = (
            (
                await session.execute(
                    select(SystemTaskDO)
                    .where(SystemTaskDO.file_id == file_id)
                    .where(SystemTaskDO.task_type == "OCR_EXTRACTION")
                    .where(SystemTaskDO.key == "page_p0")
                )
            )
            .scalars()
            .first()
        )

        assert task is not None
        assert task.status == "COMPLETED"


async def test_ocr_run_if_needed_disabled(
    file_service: FileService,
    session_manager: DatabaseSessionManager,
) -> None:
    module = OcrModule(file_service=file_service, ocr_model=None)

    assert (
        await module.run_if_needed(1, session_manager, page_index=0, page_id="p0")
        is False
    )

    # run() should still return True (skipped success)
    assert await module.run(1, session_manager, page_index=0, page_id="p0") is True


async def test_ocr_skips_llm_call_for_blank_page(
    ocr_module: OcrModule,
    session_manager: DatabaseSessionManager,
    fake_ocr_model: FakeOcrModel,
) -> None:
    """Verify blank pages (has_drawables=False) write empty text_content and complete without calling OcrModel."""
    file_id = 1005
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=7,
                storage_key="blank_key",
                file_name="blank.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p_blank",
                content_hash="h_blank",
                text_content=None,
            )
        )
        session.add(
            NotePageMetadataDO(
                user_id=7,
                file_id=file_id,
                page_index=0,
                page_id="p_blank",
                content_hash="h_blank",
                has_ink=False,
                has_drawables=False,
            )
        )
        await session.commit()

    assert (
        await ocr_module.run(file_id, session_manager, page_index=0, page_id="p_blank")
        is True
    )
    assert fake_ocr_model.calls == []

    async with session_manager.session() as session:
        content = (
            await session.execute(
                select(NotePageContentDO).where(NotePageContentDO.file_id == file_id)
            )
        ).scalar_one()
        assert content.text_content == ""

        task = (
            await session.execute(
                select(SystemTaskDO)
                .where(SystemTaskDO.file_id == file_id)
                .where(SystemTaskDO.task_type == "OCR_EXTRACTION")
                .where(SystemTaskDO.key == "page_p_blank")
            )
        ).scalar_one()
        assert task.status == "COMPLETED"


async def test_ocr_runs_when_blank_metadata_has_different_page_id(
    ocr_module: OcrModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    fake_ocr_model: FakeOcrModel,
) -> None:
    """Verify a stale blank metadata row at the same page_index for another page_id does not skip OCR."""
    file_id = 1006
    await blob_storage.put(
        CACHE_BUCKET, get_page_png_path(file_id, "p_new_inked"), b"inked-png"
    )

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=7,
                storage_key="stale_slot_key",
                file_name="stale_slot.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p_new_inked",
                content_hash="h_new",
            )
        )
        session.add(
            NotePageMetadataDO(
                user_id=7,
                file_id=file_id,
                page_index=0,
                page_id="p_old_blank",
                content_hash="h_new",
                has_ink=False,
                has_drawables=False,
            )
        )
        await session.commit()

    assert (
        await ocr_module.run(
            file_id, session_manager, page_index=0, page_id="p_new_inked"
        )
        is True
    )
    assert len(fake_ocr_model.calls) == 1


async def test_ocr_runs_when_blank_metadata_hash_is_stale(
    ocr_module: OcrModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    fake_ocr_model: FakeOcrModel,
) -> None:
    """Verify a stale blank metadata content_hash on the same page_id does not skip OCR."""
    file_id = 1007
    await blob_storage.put(CACHE_BUCKET, get_page_png_path(file_id, "p0"), b"inked-png")

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=7,
                storage_key="stale_hash_key",
                file_name="stale_hash.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="h_v2_inked",
            )
        )
        session.add(
            NotePageMetadataDO(
                user_id=7,
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="h_v1_blank",
                has_ink=False,
                has_drawables=False,
            )
        )
        await session.commit()

    assert (
        await ocr_module.run(file_id, session_manager, page_index=0, page_id="p0")
        is True
    )
    assert len(fake_ocr_model.calls) == 1


async def test_ocr_run_if_needed_requires_page_content_row(
    ocr_module: OcrModule,
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify run_if_needed returns False when NotePageContentDO is missing even if NotePageMetadataDO marks blank."""
    file_id = 1008
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=7,
                storage_key="missing_content_key",
                file_name="missing.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageMetadataDO(
                user_id=7,
                file_id=file_id,
                page_index=0,
                page_id="p_blank",
                content_hash="h_blank",
                has_ink=False,
                has_drawables=False,
            )
        )
        await session.commit()

    assert (
        await ocr_module.run_if_needed(
            file_id, session_manager, page_index=0, page_id="p_blank"
        )
        is False
    )


async def test_ocr_passes_verified_keywords_and_page_style_prompt(
    ocr_module: OcrModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    fake_ocr_model: FakeOcrModel,
) -> None:
    """Verify OcrModule injects decoded page keywords and routes page_style to matching custom prompt."""
    file_id = 1009
    await blob_storage.put(CACHE_BUCKET, get_page_png_path(file_id, "p0"), b"inked-png")

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=7,
                storage_key="kw_style_key",
                file_name="WorkNotes.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="h_match",
            )
        )
        session.add(
            NotePageMetadataDO(
                user_id=7,
                file_id=file_id,
                page_index=0,
                page_id="p0",
                content_hash="h_match",
                page_style="user_Daily_a5x2",
                has_ink=True,
                has_drawables=True,
                keywords_json='[{"KEYWORDPAGE": "1", "KEYWORD": "Project Mercury"}]',
            )
        )
        await session.commit()

    assert (
        await ocr_module.run(file_id, session_manager, page_index=0, page_id="p0")
        is True
    )
    assert len(fake_ocr_model.calls) == 1
    _, prompt = fake_ocr_model.calls[0]
    assert "Page Keywords: Project Mercury" in prompt
    assert "Daily Log" in prompt


async def test_ocr_emits_previous_text_diff_on_retranscription(
    ocr_module: OcrModule,
    file_service: FileService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Verify OcrModule emits previous_text=None initially and prior text on re-transcription."""
    assert file_service.event_bus is not None
    transcribed_events: list[NotePageTranscribedEvent] = []

    async def on_transcribed(event: NotePageTranscribedEvent) -> None:
        transcribed_events.append(event)

    file_service.event_bus.subscribe(
        NotePageTranscribedEvent, on_transcribed, inline=True
    )

    file_id = 1015
    await blob_storage.put(CACHE_BUCKET, get_page_png_path(file_id, "p0"), b"v1-png")

    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=file_id,
                    user_id=7,
                    storage_key="delta_key",
                    file_name="Daily.note",
                    directory_id=0,
                ),
                NotePageContentDO(
                    file_id=file_id,
                    page_index=2,
                    page_id="p0",
                    content_hash="h_v1",
                    text_content=None,
                ),
            ]
        )
        await session.commit()

    await ocr_module.process(file_id, session_manager, page_id="p0")
    async with session_manager.session() as session:
        row = (
            await session.execute(
                select(NotePageContentDO).where(
                    NotePageContentDO.file_id == file_id,
                    NotePageContentDO.page_id == "p0",
                )
            )
        ).scalar_one()
        # Simulate PageHashingModule invalidation moving text_content -> previous_text
        row.previous_text = row.text_content
        row.text_content = None
        await session.commit()

    await blob_storage.put(
        CACHE_BUCKET, get_page_png_path(file_id, "p0"), b"v2-longer-png"
    )
    await ocr_module.process(file_id, session_manager, page_id="p0")

    async with session_manager.session() as session:
        row = (
            await session.execute(
                select(NotePageContentDO)
                .options(undefer(NotePageContentDO.previous_text))
                .where(
                    NotePageContentDO.file_id == file_id,
                    NotePageContentDO.page_id == "p0",
                )
            )
        ).scalar_one()
        assert row.previous_text is None
        assert row.text_content == "Transcribed (13 bytes)"

    assert [ev.to_payload() for ev in transcribed_events] == [
        {
            "file_id": "1015",
            "file_path": "Daily.note",
            "page_id": "p0",
            "page_index": 2,
            "text_content": "Transcribed (6 bytes)",
            "previous_text": None,
        },
        {
            "file_id": "1015",
            "file_path": "Daily.note",
            "page_id": "p0",
            "page_index": 2,
            "text_content": "Transcribed (13 bytes)",
            "previous_text": "Transcribed (6 bytes)",
        },
    ]


async def test_ocr_blank_page_emits_event_only_when_clearing_prior_text(
    ocr_module: OcrModule,
    file_service: FileService,
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify blank pages emit NotePageTranscribedEvent when clearing prior text, not on fresh blank pages."""
    assert file_service.event_bus is not None
    transcribed_events: list[NotePageTranscribedEvent] = []

    async def on_transcribed(event: NotePageTranscribedEvent) -> None:
        transcribed_events.append(event)

    file_service.event_bus.subscribe(
        NotePageTranscribedEvent, on_transcribed, inline=True
    )

    file_id = 1016
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=file_id,
                    user_id=7,
                    storage_key="blank_delta_key",
                    file_name="Daily.note",
                    directory_id=0,
                ),
                NotePageContentDO(
                    file_id=file_id,
                    page_index=0,
                    page_id="p_fresh",
                    content_hash="h_blank",
                    text_content=None,
                ),
                NotePageContentDO(
                    file_id=file_id,
                    page_index=1,
                    page_id="p_erased",
                    content_hash="h_erased",
                    text_content=None,
                    previous_text="• Buy milk",
                ),
                NotePageMetadataDO(
                    user_id=7,
                    file_id=file_id,
                    page_index=0,
                    page_id="p_fresh",
                    content_hash="h_blank",
                    has_ink=False,
                    has_drawables=False,
                ),
                NotePageMetadataDO(
                    user_id=7,
                    file_id=file_id,
                    page_index=1,
                    page_id="p_erased",
                    content_hash="h_erased",
                    has_ink=False,
                    has_drawables=False,
                ),
            ]
        )
        await session.commit()

    await ocr_module.process(file_id, session_manager, page_index=0, page_id="p_fresh")
    assert transcribed_events == []

    await ocr_module.process(file_id, session_manager, page_index=1, page_id="p_erased")
    assert [ev.to_payload() for ev in transcribed_events] == [
        {
            "file_id": "1016",
            "file_path": "Daily.note",
            "page_id": "p_erased",
            "page_index": 1,
            "text_content": "",
            "previous_text": "• Buy milk",
        }
    ]


async def test_ocr_suppresses_event_when_transcript_unchanged_or_empty_doodle(
    file_service: FileService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Verify OcrModule suppresses no-op events on unchanged re-OCR and empty doodle pages."""

    class _ConstantOcrModel(OcrModel):
        def __init__(self, text: str) -> None:
            self._text = text

        @property
        def provider(self) -> str:
            return "stub"

        @property
        def model_id(self) -> str:
            return "stub-constant"

        async def extract_text(self, png_data: bytes, prompt: str) -> str:
            return self._text

    assert file_service.event_bus is not None
    transcribed_events: list[NotePageTranscribedEvent] = []

    async def on_transcribed(event: NotePageTranscribedEvent) -> None:
        transcribed_events.append(event)

    file_service.event_bus.subscribe(
        NotePageTranscribedEvent, on_transcribed, inline=True
    )

    file_id = 1017
    await blob_storage.put(CACHE_BUCKET, get_page_png_path(file_id, "p_same"), b"png1")
    await blob_storage.put(
        CACHE_BUCKET, get_page_png_path(file_id, "p_doodle"), b"png2"
    )
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=file_id,
                    user_id=7,
                    storage_key="noop_key",
                    file_name="Daily.note",
                    directory_id=0,
                ),
                NotePageContentDO(
                    file_id=file_id,
                    page_index=0,
                    page_id="p_same",
                    content_hash="h_same",
                    text_content="• Buy milk",
                ),
                NotePageContentDO(
                    file_id=file_id,
                    page_index=1,
                    page_id="p_doodle",
                    content_hash="h_doodle",
                    text_content=None,
                ),
            ]
        )
        await session.commit()

    same_ocr = OcrModule(
        file_service=file_service, ocr_model=_ConstantOcrModel("• Buy milk")
    )
    await same_ocr.process(file_id, session_manager, page_index=0, page_id="p_same")

    doodle_ocr = OcrModule(file_service=file_service, ocr_model=_ConstantOcrModel(""))
    await doodle_ocr.process(file_id, session_manager, page_index=1, page_id="p_doodle")

    assert transcribed_events == []
