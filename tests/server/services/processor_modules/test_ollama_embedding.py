import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from supernote.server.config import ServerConfig
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules.ollama_embedding import (
    OllamaEmbeddingModule,
)


@pytest.fixture
def ollama_embedding_module(
    file_service: FileService,
    server_config_ollama: ServerConfig,
    mock_ollama_service: MagicMock,
) -> OllamaEmbeddingModule:
    return OllamaEmbeddingModule(
        file_service=file_service,
        config=server_config_ollama,
        ollama_service=mock_ollama_service,
    )


async def test_process_embedding_success(
    ollama_embedding_module: OllamaEmbeddingModule,
    session_manager: DatabaseSessionManager,
    mock_ollama_service: MagicMock,
) -> None:
    # Setup Data
    user_id = 100
    file_id = 999
    page_index = 0
    storage_key = "test_note_storage_key"

    async with session_manager.session() as session:
        # UserFile
        user_file = UserFileDO(
            id=file_id,
            user_id=user_id,
            storage_key=storage_key,
            file_name="real.note",
            directory_id=0,
        )
        session.add(user_file)

        # NotePageContent (Pre-existing from OCR)
        content = NotePageContentDO(
            file_id=file_id,
            page_index=page_index,
            page_id="p0",
            content_hash="somehash",
            text_content="This is the text to embed.",
        )
        session.add(content)
        await session.commit()

    # Mock Ollama API Response
    mock_ollama_service.embed.return_value = [0.1, 0.2, 0.3]

    # Run full module lifecycle
    await ollama_embedding_module.run(
        file_id, session_manager, page_index=page_index, page_id="p0"
    )

    # Verifications
    # Verify API Call
    mock_ollama_service.embed.assert_called_once_with("This is the text to embed.")

    # Verify DB Updates
    async with session_manager.session() as session:
        # Check Content Update
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
        embedding_list = json.loads(updated_content.embedding)
        assert embedding_list == [0.1, 0.2, 0.3]

        # Check Task Status
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


async def test_embedding_run_if_needed_missing_text_content(
    ollama_embedding_module: OllamaEmbeddingModule,
    session_manager: DatabaseSessionManager,
) -> None:
    file_id = 1000

    async with session_manager.session() as session:
        user_file = UserFileDO(
            id=file_id,
            user_id=100,
            storage_key="key",
            file_name="real.note",
            directory_id=0,
        )
        session.add(user_file)
        await session.commit()

    # No NotePageContentDO row at all yet (OCR hasn't run).
    assert (
        await ollama_embedding_module.run_if_needed(
            file_id, session_manager, page_index=0, page_id="p0"
        )
        is False
    )


async def test_embedding_run_if_needed_disabled(
    ollama_embedding_module: OllamaEmbeddingModule,
    session_manager: DatabaseSessionManager,
    mock_ollama_service: MagicMock,
) -> None:
    # Disable Ollama
    mock_ollama_service.is_configured = False

    # Should return False
    assert (
        await ollama_embedding_module.run_if_needed(
            1, session_manager, page_index=0, page_id="p0"
        )
        is False
    )

    # run() should still return True (skipped success)
    assert (
        await ollama_embedding_module.run(
            1, session_manager, page_index=0, page_id="p0"
        )
        is True
    )


async def test_process_embedding_service_failure(
    ollama_embedding_module: OllamaEmbeddingModule,
    session_manager: DatabaseSessionManager,
    mock_ollama_service: MagicMock,
) -> None:
    file_id = 1001
    page_index = 0

    async with session_manager.session() as session:
        user_file = UserFileDO(
            id=file_id,
            user_id=100,
            storage_key="key",
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

    mock_ollama_service.embed.side_effect = ValueError("Ollama embedding request failed")

    # run() catches the exception and marks the task FAILED rather than raising.
    await ollama_embedding_module.run(
        file_id, session_manager, page_index=page_index, page_id="p0"
    )

    async with session_manager.session() as session:
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
        assert task.status == "FAILED"
