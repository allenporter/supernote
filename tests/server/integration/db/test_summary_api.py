"""Integration test for summary server API and fixture generation."""

import hashlib
import os
import shutil
import sqlite3
from pathlib import Path

import jwt
from aiohttp.test_utils import TestClient, TestServer

from supernote.client.auth import AbstractAuth
from supernote.client.client import Client
from supernote.client.summary import SummaryClient
from supernote.models.summary import AddSummaryDTO
from supernote.models.user import UserRegisterDTO
from supernote.server.app import create_app
from supernote.server.config import AuthConfig, ServerConfig
from supernote.server.db.migrations import run_migrations
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.user import JWT_ALGORITHM, UserService


async def test_generate_legacy_summary_api_fixture(tmp_path: Path) -> None:
    """End-to-end API test verifying unmigrated summary creation over HTTP API."""
    storage_dir = tmp_path / "storage"
    db_file = storage_dir / "system" / "supernote.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    sync_db_url = f"sqlite:///{db_file}"

    # Initialize unmigrated DB schema
    run_migrations(sync_db_url)

    # Create app instance with file-backed storage
    config = ServerConfig(
        storage_dir=str(storage_dir),
        auth=AuthConfig(secret_key="test-secret-key-32-characters-long!!"),
    )
    app = create_app(config)

    # Register test user and prepare access token
    user_service: UserService = app["user_service"]
    pwd_md5 = hashlib.md5(b"password123").hexdigest()
    await user_service.register(
        UserRegisterDTO(email="api_test@example.com", password=pwd_md5)
    )

    secret = config.auth.secret_key
    token = jwt.encode({"sub": "api_test@example.com"}, secret, algorithm=JWT_ALGORITHM)
    coordination_service = app["coordination_service"]
    await coordination_service.set_value(
        f"session:{token}", "api_test@example.com|", ttl=3600
    )

    # Wrap app in TestServer and initialize authenticated SummaryClient
    class TokenAuth(AbstractAuth):
        async def async_get_access_token(self) -> str:
            return token

    test_server = TestServer(app)
    test_client = TestClient(test_server)
    await test_client.start_server()
    base_url = str(test_client.make_url("/"))

    auth_client = Client(test_client.session, auth=TokenAuth(), host=base_url)
    summary_client = SummaryClient(auth_client)

    # Execute HTTP POST request to /api/file/add/summary
    add_dto = AddSummaryDTO(
        content="End-to-end API generated summary content.",
        source_path="/Document/E2E.note",
        author="API Test",
    )
    add_resp = await summary_client.add_summary(add_dto)
    assert add_resp.success
    summary_id = add_resp.id
    assert summary_id is not None

    # Shutdown server and dispose database engine
    session_manager: DatabaseSessionManager = app["session_manager"]
    if session_manager._engine:
        await session_manager._engine.dispose()
    await test_client.close()

    # Optionally write static fixture if UPDATE_FIXTURES environment variable is set
    if os.getenv("UPDATE_FIXTURES") == "1":
        fixture_dest = Path("tests/fixtures/db_v1_summary_api.sqlite").absolute()
        shutil.copy(db_file, fixture_dest)

    # Assert unmigrated summary created via HTTP API has NULL md5_hash and timestamps in SQLite
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, md5_hash, creation_time, last_modified_time FROM f_summary WHERE id = ?",
        (summary_id,),
    )
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row[1] is None
    assert row[2] is None
    assert row[3] is None
