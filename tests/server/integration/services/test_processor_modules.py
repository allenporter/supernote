from dataclasses import dataclass, field
from pathlib import Path

import pytest

from supernote.models.base import TaskType
from supernote.server.components.processor import (
    ProcessorModule,
    ProcessorService,
    TaskScope,
)
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.services.user import UserService

_DEFAULT_SCOPES = {
    TaskType.PAGE_HASHING: TaskScope.FILE,
    TaskType.PNG_CONVERSION: TaskScope.PAGE,
    TaskType.OCR_EXTRACTION: TaskScope.PAGE,
    TaskType.EMBEDDING_GENERATION: TaskScope.PAGE,
    TaskType.SUMMARY_GENERATION: TaskScope.FILE,
}

_DEFAULT_DEPS: dict[TaskType, tuple[TaskType, ...]] = {
    TaskType.PAGE_HASHING: (),
    TaskType.PNG_CONVERSION: (TaskType.PAGE_HASHING,),
    TaskType.OCR_EXTRACTION: (TaskType.PNG_CONVERSION,),
    TaskType.EMBEDDING_GENERATION: (TaskType.OCR_EXTRACTION,),
    TaskType.SUMMARY_GENERATION: (TaskType.OCR_EXTRACTION,),
}


@dataclass
class FakeModule(ProcessorModule):
    """Fake processor module that records invocations and returns a configured outcome."""

    module_name: str
    should_succeed: bool = True
    calls: list[tuple[int, int | None, str | None]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.module_name

    @property
    def task_type(self) -> TaskType:
        return TaskType.from_friendly(self.module_name)

    @property
    def scope(self) -> TaskScope:
        return _DEFAULT_SCOPES[self.task_type]

    @property
    def depends_on(self) -> tuple[TaskType, ...]:
        return _DEFAULT_DEPS[self.task_type]

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        **kwargs: object,
    ) -> None:
        self.calls.append((file_id, page_index, page_id))
        if not self.should_succeed:
            raise RuntimeError(f"{self.module_name} failed")


@pytest.fixture
def processor_service(
    storage_root: Path,
    blob_storage: BlobStorage,
    user_service: UserService,
    session_manager: DatabaseSessionManager,
) -> ProcessorService:
    event_bus = LocalEventBus()
    file_service = FileService(
        storage_root=storage_root,
        blob_storage=blob_storage,
        user_service=user_service,
        session_manager=session_manager,
        event_bus=event_bus,
    )
    return ProcessorService(
        event_bus=event_bus,
        session_manager=session_manager,
        file_service=file_service,
    )


async def test_explicit_orchestration_flow(
    processor_service: ProcessorService,
    session_manager: DatabaseSessionManager,
) -> None:
    hashing = FakeModule("hashing")
    png = FakeModule("png")
    ocr = FakeModule("ocr")
    embedding = FakeModule("embedding")
    summary = FakeModule("summary")

    processor_service.register_modules(
        hashing=hashing,
        png=png,
        ocr=ocr,
        embedding=embedding,
        summary=summary,
    )

    file_id = 123
    async with session_manager.session() as session:
        session.add_all(
            [
                NotePageContentDO(
                    file_id=file_id, page_index=0, page_id="p0", content_hash="h0"
                ),
                NotePageContentDO(
                    file_id=file_id, page_index=1, page_id="p1", content_hash="h1"
                ),
            ]
        )
        await session.commit()

    await processor_service.process_file(file_id)

    assert hashing.calls == [(file_id, None, None)]
    assert set(png.calls) == {(file_id, 0, "p0"), (file_id, 1, "p1")}
    assert set(ocr.calls) == {(file_id, 0, "p0"), (file_id, 1, "p1")}
    assert set(embedding.calls) == {(file_id, 0, "p0"), (file_id, 1, "p1")}
    assert summary.calls == [(file_id, None, None)]


async def test_dependant_skipping(
    processor_service: ProcessorService,
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify that if a module fails (returns False), the page pipeline stops."""
    hashing = FakeModule("hashing")
    png = FakeModule("png", should_succeed=False)
    ocr = FakeModule("ocr")
    embedding = FakeModule("embedding")
    summary = FakeModule("summary")

    processor_service.register_modules(
        hashing=hashing,
        png=png,
        ocr=ocr,
        embedding=embedding,
        summary=summary,
    )

    file_id = 123
    async with session_manager.session() as session:
        session.add(
            NotePageContentDO(
                file_id=file_id, page_index=0, page_id="p0", content_hash="h0"
            )
        )
        await session.commit()

    await processor_service.process_file(file_id)

    assert png.calls == [(file_id, 0, "p0")]
    assert ocr.calls == []
    assert embedding.calls == []
    assert summary.calls == []

    tasks = await processor_service.list_system_tasks(file_id=file_id, status="failed")
    assert len(tasks) == 1
    assert tasks[0].last_error == "RuntimeError: png failed"
    assert tasks[0].retry_count == 0

    # Retrying the failed file increments retry_count
    await processor_service.process_file(file_id)
    tasks = await processor_service.list_system_tasks(file_id=file_id, status="failed")
    assert len(tasks) == 1
    assert tasks[0].retry_count == 1
