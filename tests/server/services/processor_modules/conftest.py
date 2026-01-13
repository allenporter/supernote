from pathlib import Path
from unittest.mock import MagicMock

import pytest

from supernote.server.config import AuthConfig, ServerConfig
from supernote.server.db.session import DatabaseSessionManager
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
def server_config_gemini() -> ServerConfig:
    conf = ServerConfig(
        auth=AuthConfig(secret_key="secret"),
        storage_dir=".",
        # db_url is a property, not an init arg. We mock session_manager anyway.
    )
    conf.gemini_api_key = "fake-key"
    conf.gemini_ocr_model = "gemini-2.0-flash-exp"
    return conf
