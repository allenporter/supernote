from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from supernote.server.config import AuthConfig, ServerConfig
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.ai_service import AIService
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
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
    )
    conf.gemini_api_key = "fake-key"
    conf.gemini_ocr_model = "gemini-2.0-flash-exp"
    conf.gemini_embedding_model = "text-embedding-004"
    return conf


@pytest.fixture
def mock_ai_service() -> MagicMock:
    service = MagicMock(spec=AIService)
    service.is_configured = True
    service.provider_name = "GEMINI"
    service.ocr_image = AsyncMock(return_value="")
    service.embed_text = AsyncMock(return_value=[])
    service.generate_json = AsyncMock(return_value="{}")
    return service


# Backwards-compatible alias used by older tests
@pytest.fixture
def mock_gemini_service(mock_ai_service: MagicMock) -> MagicMock:
    return mock_ai_service
