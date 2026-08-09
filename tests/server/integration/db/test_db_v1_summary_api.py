"""Integration test verifying unmigrated summary API behavior on db_v1_summary_api fixture."""

import hashlib
from pathlib import Path

import jwt
from aiohttp.test_utils import TestClient, TestServer

from supernote.client.auth import AbstractAuth
from supernote.client.client import Client
from supernote.client.summary import SummaryClient
from supernote.models.summary import AddSummaryDTO, QuerySummaryDTO
from supernote.models.user import UserRegisterDTO
from supernote.server.app import create_app
from supernote.server.config import AuthConfig, ServerConfig
from supernote.server.db.migrations import run_migrations
from supernote.server.services.user import JWT_ALGORITHM, UserService


async def test_unmigrated_summary_api_creation(tmp_path: Path) -> None:
    """Verify legacy summary creation and query behavior over server API."""
    storage_dir = tmp_path / "storage"
    db_file = storage_dir / "system" / "supernote.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    sync_db_url = f"sqlite:///{db_file}"

    run_migrations(sync_db_url)

    config = ServerConfig(
        storage_dir=str(storage_dir),
        auth=AuthConfig(secret_key="test-secret-key-32-characters-long!!"),
    )
    app = create_app(config)

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

    class TokenAuth(AbstractAuth):
        async def async_get_access_token(self) -> str:
            return token

    test_server = TestServer(app)
    test_client = TestClient(test_server)
    await test_client.start_server()
    base_url = str(test_client.make_url("/"))

    auth_client = Client(test_client.session, auth=TokenAuth(), host=base_url)
    summary_client = SummaryClient(auth_client)

    add_dto = AddSummaryDTO(
        content="End-to-end API generated summary content.",
        source_path="/Document/E2E.note",
        author="API Test",
    )
    add_resp = await summary_client.add_summary(add_dto)
    assert add_resp.success
    summary_id = add_resp.id
    assert summary_id is not None

    query_resp = await summary_client.query_summaries(ids=[summary_id])
    assert query_resp.success
    assert len(query_resp.summary_do_list) == 1
    summary = query_resp.summary_do_list[0]
    assert summary.id == summary_id
    assert summary.content == "End-to-end API generated summary content."

    hash_dto = QuerySummaryDTO(ids=[summary_id])
    info_resp = await summary_client.query_summary_hash(hash_dto)
    assert info_resp.success
    matching_infos = [
        item for item in info_resp.summary_info_vo_list if item.id == summary_id
    ]
    assert len(matching_infos) == 1

    await test_client.close()
