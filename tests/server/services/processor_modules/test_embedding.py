import json

import pytest
from sqlalchemy import select

from supernote.server.ai.models.embedding import EmbeddingTaskType
from supernote.server.ai.models.fake.embedding import FakeEmbeddingModel
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules.embedding import EmbeddingModule


@pytest.fixture
def embedding_module(
    file_service: FileService,
    fake_embedding_model: FakeEmbeddingModel,
) -> EmbeddingModule:
    return EmbeddingModule(
        file_service=file_service,
        embedding_model=fake_embedding_model,
    )


async def test_process_embedding_success(
    embedding_module: EmbeddingModule,
    session_manager: DatabaseSessionManager,
    fake_embedding_model: FakeEmbeddingModel,
) -> None:
    user_id = 100
    file_id = 999
    page_index = 0
    storage_key = "test_note_storage_key"

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
            text_content="This is the text to embed.",
        )
        session.add(content)
        await session.commit()

    await embedding_module.run(
        file_id, session_manager, page_index=page_index, page_id="p0"
    )

    assert fake_embedding_model.calls == [
        ("This is the text to embed.", EmbeddingTaskType.RETRIEVAL_DOCUMENT)
    ]

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
        assert updated_content.embedding is not None
        assert updated_content.embedding_model == fake_embedding_model.model_id
        embedding_list = json.loads(updated_content.embedding)
        assert embedding_list == await fake_embedding_model.embed(
            "This is the text to embed.",
            task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT,
        )

        task = (
            (
                await session.execute(
                    select(SystemTaskDO)
                    .where(SystemTaskDO.file_id == file_id)
                    .where(SystemTaskDO.task_type == "EMBEDDING_GENERATION")
                    .where(SystemTaskDO.key == "page_p0")
                )
            )
            .scalars()
            .first()
        )

        assert task is not None
        assert task.status == "COMPLETED"


async def test_embedding_reembeds_when_model_changes(
    file_service: FileService,
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify EmbeddingModule re-runs when embedding_model changes even if SystemTaskDO is COMPLETED."""
    file_id = 1000
    model_v1 = FakeEmbeddingModel(model_id="model-v1")
    model_v2 = FakeEmbeddingModel(model_id="model-v2", dimensions=4)

    module_v1 = EmbeddingModule(file_service=file_service, embedding_model=model_v1)
    module_v2 = EmbeddingModule(file_service=file_service, embedding_model=model_v2)

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=1,
                storage_key="key",
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
                text_content="Page text.",
            )
        )
        await session.commit()

    # Initial run with model-v1
    await module_v1.run(file_id, session_manager, page_index=0, page_id="p0")
    assert (
        await module_v1.run_if_needed(
            file_id, session_manager, page_index=0, page_id="p0"
        )
        is False
    )

    # Switching to model-v2 should require re-running despite COMPLETED SystemTaskDO
    assert (
        await module_v2.run_if_needed(
            file_id, session_manager, page_index=0, page_id="p0"
        )
        is True
    )
    await module_v2.run(file_id, session_manager, page_index=0, page_id="p0")

    async with session_manager.session() as session:
        content = (
            await session.execute(
                select(NotePageContentDO).where(NotePageContentDO.file_id == file_id)
            )
        ).scalar_one()
        assert content.embedding_model == "model-v2"
        assert content.embedding is not None
        assert len(json.loads(content.embedding)) == 4


async def test_embedding_run_if_needed_disabled(
    file_service: FileService,
    session_manager: DatabaseSessionManager,
) -> None:
    module = EmbeddingModule(file_service=file_service, embedding_model=None)

    assert (
        await module.run_if_needed(1, session_manager, page_index=0, page_id="p0")
        is False
    )

    # run() should still return True (skipped success)
    assert await module.run(1, session_manager, page_index=0, page_id="p0") is True


async def test_embedding_skips_blank_text_and_clears_stale_embedding(
    embedding_module: EmbeddingModule,
    session_manager: DatabaseSessionManager,
    fake_embedding_model: FakeEmbeddingModel,
) -> None:
    file_id = 1015
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=1,
                storage_key="key_blank",
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
                has_ink=False,
                has_drawables=False,
                text_content="",
                embedding="[0.1, 0.2]",
                embedding_model="stale-model",
            )
        )
        await session.commit()

    assert (
        await embedding_module.run(
            file_id, session_manager, page_index=0, page_id="p_blank"
        )
        is True
    )
    assert fake_embedding_model.calls == []

    async with session_manager.session() as session:
        content = (
            await session.execute(
                select(NotePageContentDO).where(NotePageContentDO.file_id == file_id)
            )
        ).scalar_one()
        assert content.embedding is None
        assert content.embedding_model is None
