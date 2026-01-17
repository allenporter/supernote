from pathlib import Path
from unittest.mock import MagicMock

import pytest

from supernote.server.config import AuthConfig, ServerConfig
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.services.gemini import GeminiService
from supernote.server.services.user import UserService


@pytest.fixture
def file_service(
    storage_root: Path,
    blob_storage: BlobStorage,
    user_service: UserService,
    session_manager: DatabaseSessionManager,
) -> FileService:
    return FileService(
        storage_root=storage_root,
        blob_storage=blob_storage,
        user_service=user_service,
        session_manager=session_manager,
        event_bus=MagicMock(),
    )


@pytest.fixture
def server_config_gemini(tmp_path: Path) -> ServerConfig:
    conf = ServerConfig(
        auth=AuthConfig(secret_key="secret"),
        storage_dir=str(tmp_path),
        # db_url is a property, not an init arg. We mock session_manager anyway.
    )
    conf.gemini_api_key = "fake-key"
    conf.gemini_ocr_model = "gemini-2.0-flash-exp"
    conf.gemini_embedding_model = "text-embedding-004"
    return conf


@pytest.fixture
def gemini_service(server_config_gemini: ServerConfig) -> GeminiService:
    return GeminiService(api_key=server_config_gemini.gemini_api_key)


@pytest.fixture
def mock_gemini_service() -> MagicMock:
    service = MagicMock(spec=GeminiService)
    service.is_configured = True
    return service
