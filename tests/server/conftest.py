"""Server-scoped autouse fixtures and shared server service fixtures.

Core non-autouse server and client harness fixtures (`session_manager`, `client`,
`auth_headers`, `user_service`, `server_config`, etc.) live in
`tests/fixtures/server.py` (registered via `pytest_plugins` in `tests/conftest.py`).
"""

import logging
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

import supernote.server.db.models  # noqa: F401
from supernote.server.components.fake_ai.embedding import FakeEmbeddingModel
from supernote.server.components.fake_ai.ocr import FakeOcrModel
from supernote.server.components.fake_ai.summary import FakeSummaryModel
from supernote.server.config import ServerConfig
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.services.summary import SummaryService
from supernote.server.services.user import UserService


@pytest.fixture(autouse=True)
def ignore_aiossqllite_debug() -> None:
    """Always ignore debug logs from aiosqlite since they are too verbose."""
    logging.getLogger("aiosqlite").setLevel(logging.INFO)


@pytest.fixture(autouse=True)
def patch_server_config(server_config: ServerConfig) -> Generator[None]:
    """Automatically patch server config for all server tests."""
    with patch("supernote.server.config.ServerConfig.load", return_value=server_config):
        yield


@pytest.fixture(autouse=True)
def patch_run_migrations() -> Generator[None]:
    """Bypass redundant DB migrations during app startup across server tests.

    _session_manager_shared already initializes all database schema tables
    at session start via create_all_tables(). Full Alembic migration execution
    is separately verified in tests/server/db/test_migrations.py.
    """
    with patch("supernote.server.app.run_migrations"):
        yield


@pytest.fixture
def file_service(
    storage_root: Path,
    blob_storage: BlobStorage,
    user_service: UserService,
    session_manager: DatabaseSessionManager,
) -> FileService:
    """Provide a FileService wired to the test storage and session manager."""
    return FileService(
        storage_root=storage_root,
        blob_storage=blob_storage,
        user_service=user_service,
        session_manager=session_manager,
        event_bus=LocalEventBus(),
    )


@pytest.fixture
def summary_service(
    user_service: UserService,
    session_manager: DatabaseSessionManager,
) -> SummaryService:
    """Provide a SummaryService wired to the test session manager."""
    return SummaryService(
        user_service=user_service,
        session_manager=session_manager,
    )


@pytest.fixture
def fake_ocr_model() -> FakeOcrModel:
    """Provide a deterministic fake OCR model."""
    return FakeOcrModel()


@pytest.fixture
def fake_embedding_model() -> FakeEmbeddingModel:
    """Provide a deterministic fake embedding model."""
    return FakeEmbeddingModel()


@pytest.fixture
def fake_summary_model() -> FakeSummaryModel:
    """Provide a deterministic fake summary model."""
    return FakeSummaryModel()
