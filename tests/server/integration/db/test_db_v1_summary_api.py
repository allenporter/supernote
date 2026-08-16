"""Integration tests for summary server API across unmigrated, migrated, and post-migration creation flows."""

import hashlib
import shutil
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


async def test_unmigrated_summary_api_query(tmp_path: Path) -> None:
    """(a) Pre-PR test: Verify unmigrated legacy db fixture returns NULL for md5_hash and timestamps on revision 7a8291f043bc."""
    fixture_path = Path("tests/fixtures/db_v1_summary_api.sqlite").absolute()
    storage_dir = tmp_path / "storage"
    db_file = storage_dir / "system" / "supernote.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(fixture_path, db_file)

    sync_db_url = f"sqlite:///{db_file}"
    # Target unmigrated revision prior to b8e9c0d1e2f3
    run_migrations(sync_db_url, "7a8291f043bc")

    config = ServerConfig(
        storage_dir=str(storage_dir),
        auth=AuthConfig(secret_key="test-secret-key-32-characters-long!!"),
        mcp_port=0,
    )
    app = create_app(config)

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

    legacy_summary_id = 741735919668691745
    query_resp = await summary_client.query_summaries(ids=[legacy_summary_id])
    assert query_resp.success
    assert len(query_resp.summary_do_list) == 1

    summary = query_resp.summary_do_list[0]
    assert summary.id == legacy_summary_id
    assert summary.md5_hash is None

    hash_dto = QuerySummaryDTO(ids=[legacy_summary_id])
    info_resp = await summary_client.query_summary_hash(hash_dto)
    assert info_resp.success
    matching_infos = [
        item for item in info_resp.summary_info_vo_list if item.id == legacy_summary_id
    ]
    assert len(matching_infos) == 1
    info_item = matching_infos[0]
    assert info_item.md5_hash is None

    await test_client.close()


async def test_migrated_legacy_db_summary_api_query(tmp_path: Path) -> None:
    """(b) Migration test: Swap in unmigrated fixture db_v1_summary_api, run Alembic upgrade, verify non-null backfilled fields over HTTP API."""
    fixture_path = Path("tests/fixtures/db_v1_summary_api.sqlite").absolute()
    storage_dir = tmp_path / "storage"
    db_file = storage_dir / "system" / "supernote.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(fixture_path, db_file)

    sync_db_url = f"sqlite:///{db_file}"
    run_migrations(sync_db_url)

    config = ServerConfig(
        storage_dir=str(storage_dir),
        auth=AuthConfig(secret_key="test-secret-key-32-characters-long!!"),
        mcp_port=0,
    )
    app = create_app(config)

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

    legacy_summary_id = 741735919668691745
    query_resp = await summary_client.query_summaries(ids=[legacy_summary_id])
    assert query_resp.success
    assert len(query_resp.summary_do_list) == 1

    summary = query_resp.summary_do_list[0]
    expected_md5 = hashlib.md5(b"End-to-end API generated summary content.").hexdigest()
    assert summary.id == legacy_summary_id
    assert summary.md5_hash == expected_md5
    assert summary.creation_time is not None
    assert summary.last_modified_time is not None

    hash_dto = QuerySummaryDTO(ids=[legacy_summary_id])
    info_resp = await summary_client.query_summary_hash(hash_dto)
    assert info_resp.success
    matching_infos = [
        item for item in info_resp.summary_info_vo_list if item.id == legacy_summary_id
    ]
    assert len(matching_infos) == 1
    info_item = matching_infos[0]
    assert info_item.md5_hash == expected_md5
    assert info_item.last_modified_time is not None

    await test_client.close()


async def test_post_migration_new_summary_creation(tmp_path: Path) -> None:
    """(c) Post-migration test: Verify new summary creation post-migration sets non-null md5_hash and timestamps over HTTP API."""
    storage_dir = tmp_path / "storage"
    db_file = storage_dir / "system" / "supernote.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    sync_db_url = f"sqlite:///{db_file}"

    # Run migrations to head
    run_migrations(sync_db_url)

    config = ServerConfig(
        storage_dir=str(storage_dir),
        auth=AuthConfig(secret_key="test-secret-key-32-characters-long!!"),
        mcp_port=0,
    )
    app = create_app(config)

    user_service: UserService = app["user_service"]
    pwd_md5 = hashlib.md5(b"password123").hexdigest()
    await user_service.register(
        UserRegisterDTO(email="new_api_test@example.com", password=pwd_md5)
    )

    secret = config.auth.secret_key
    token = jwt.encode(
        {"sub": "new_api_test@example.com"}, secret, algorithm=JWT_ALGORITHM
    )
    coordination_service = app["coordination_service"]
    await coordination_service.set_value(
        f"session:{token}", "new_api_test@example.com|", ttl=3600
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

    content = "Post-migration newly created summary content."
    expected_md5 = hashlib.md5(content.encode("utf-8")).hexdigest()

    add_dto = AddSummaryDTO(
        content=content,
        source_path="/Document/NewPostMigration.note",
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
    assert summary.md5_hash == expected_md5
    assert summary.creation_time is not None
    assert summary.last_modified_time is not None

    hash_dto = QuerySummaryDTO(ids=[summary_id])
    info_resp = await summary_client.query_summary_hash(hash_dto)
    assert info_resp.success
    matching_infos = [
        item for item in info_resp.summary_info_vo_list if item.id == summary_id
    ]
    assert len(matching_infos) == 1
    info_item = matching_infos[0]
    assert info_item.md5_hash == expected_md5
    assert info_item.last_modified_time is not None

    await test_client.close()
