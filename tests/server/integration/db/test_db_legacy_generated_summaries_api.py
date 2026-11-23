"""Integration tests verifying legacy pre-#635 generated summary database compatibility via HTTP APIs."""

import hashlib
import shutil
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from supernote.client.auth import AbstractAuth
from supernote.client.client import Client
from supernote.client.extended import ExtendedClient
from supernote.client.summary import SummaryClient
from supernote.models.summary import QuerySummaryDTO
from supernote.server.app import create_app
from supernote.server.components.fake_ai.summary import FakeSummaryModel
from supernote.server.config import AuthConfig, ServerConfig
from supernote.server.db.migrations import run_migrations
from supernote.server.keys import (
    EVENT_BUS_KEY,
    FILE_SERVICE_KEY,
    SESSION_MANAGER_KEY,
    SUMMARY_SERVICE_KEY,
    USER_SERVICE_KEY,
)
from supernote.server.services.processor import ProcessorService
from supernote.server.services.processor_modules.page_hashing import PageHashingModule
from supernote.server.services.processor_modules.summary import SummaryModule
from supernote.server.utils.paths import get_ai_summaries_group_id, get_summary_id

FIXTURES_DIR = Path(__file__).parent.parent.parent.parent / "fixtures"
LEGACY_SUMMARIES_FIXTURE_PATH = FIXTURES_DIR / "db_legacy_generated_summaries.sqlite"
SPRINT_NOTE_FILE_ID = 750000000000000001
LEGACY_USER_EMAIL = "legacy_summary@example.com"


@asynccontextmanager
async def _open_legacy_db(
    tmp_path: Path, revision: str
) -> AsyncGenerator[tuple[web.Application, int, SummaryClient, ExtendedClient]]:
    storage_dir = tmp_path / "storage"
    db_file = storage_dir / "system" / "supernote.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(LEGACY_SUMMARIES_FIXTURE_PATH, db_file)
    run_migrations(f"sqlite:///{db_file}", revision)

    app = create_app(
        ServerConfig(
            storage_dir=str(storage_dir),
            auth=AuthConfig(secret_key="test-secret-key-32-characters-long!!"),
            mcp_enabled=False,
            mcp_port=0,
        )
    )
    user_id = await app[USER_SERVICE_KEY].get_user_id(LEGACY_USER_EMAIL)
    token = await app[USER_SERVICE_KEY].create_session(LEGACY_USER_EMAIL)

    class TokenAuth(AbstractAuth):
        async def async_get_access_token(self) -> str:
            return token

    test_client = TestClient(TestServer(app))
    await test_client.start_server()
    auth_client = Client(
        test_client.session, auth=TokenAuth(), host=str(test_client.make_url("/"))
    )
    try:
        yield app, user_id, SummaryClient(auth_client), ExtendedClient(auth_client)
    finally:
        await test_client.close()


async def test_unmigrated_legacy_generated_summaries_api_query(tmp_path: Path) -> None:
    """Verify a pre-#635 database with storage_key-suffixed groups/transcripts/summaries serves cleanly at e8f9a0b1c2d3."""
    async with _open_legacy_db(tmp_path, "e8f9a0b1c2d3") as (
        _,
        _,
        summary_client,
        extended_client,
    ):
        groups_vo = await summary_client.query_groups()
        assert [(g.unique_identifier, g.name) for g in groups_vo.summary_do_list] == [
            ("11111111-aaaa-4bbb-8ccc-000000000001-095.note-group", "Sprint.note"),
            ("22222222-bbbb-4ccc-8ddd-000000000002-095.note-group", "Sprint.note"),
            ("2799b74528407f6aeeeff095f7685e9e", "Reading Notes"),
        ]

        summaries_vo = await summary_client.query_summaries()
        assert [
            (s.unique_identifier, s.data_source, s.source_path)
            for s in summaries_vo.summary_do_list
        ] == [
            (
                "11111111-aaaa-4bbb-8ccc-000000000001-095.note-transcript",
                "OCR",
                "Sprint.note",
            ),
            (
                "11111111-aaaa-4bbb-8ccc-000000000001-095.note-summary",
                "fake-summary-v1",
                "Sprint.note",
            ),
            (
                "22222222-bbbb-4ccc-8ddd-000000000002-095.note-transcript",
                "OCR",
                "Sprint.note",
            ),
            (
                "22222222-bbbb-4ccc-8ddd-000000000002-095.note-summary",
                "fake-summary-v1",
                "Sprint.note",
            ),
            ("aabbccdd11223344556677889900ff00", "USER", "Document/Paper.pdf"),
        ]

        hash_vo = await summary_client.query_summary_hash(QuerySummaryDTO())
        assert len(hash_vo.summary_info_vo_list) == 5
        assert (
            await extended_client.list_summaries(SPRINT_NOTE_FILE_ID)
        ).total_records == 4
        transcript_vo = await extended_client.get_transcript(SPRINT_NOTE_FILE_ID)
        assert [p.text for p in transcript_vo.pages] == [
            "Transcribed (68700 bytes)",
            "Transcribed (68345 bytes)",
        ]


async def test_migrated_legacy_generated_summaries_api_query(tmp_path: Path) -> None:
    """Verify upgrading the pre-#635 database to head migrates summaries to AI Summaries and serves all APIs cleanly."""
    async with _open_legacy_db(tmp_path, "head") as (
        app,
        user_id,
        summary_client,
        extended_client,
    ):
        fake_summary_model = FakeSummaryModel()
        processor = ProcessorService(
            event_bus=app[EVENT_BUS_KEY],
            session_manager=app[SESSION_MANAGER_KEY],
            file_service=app[FILE_SERVICE_KEY],
            summary_service=app[SUMMARY_SERVICE_KEY],
        )
        processor.register_modules(
            hashing=PageHashingModule(app[FILE_SERVICE_KEY]),
            summary=SummaryModule(
                app[FILE_SERVICE_KEY], app[SUMMARY_SERVICE_KEY], fake_summary_model
            ),
        )
        await processor.recover_missing_tasks(user_id=user_id)
        assert fake_summary_model.calls == []

        ai_group_uuid = get_ai_summaries_group_id(user_id)
        canonical_uuid = get_summary_id(user_id, SPRINT_NOTE_FILE_ID)
        expected_content = "## 2023-10-27 (Pages 1)\nSummary of (1768 chars)"
        expected_md5 = hashlib.md5(expected_content.encode("utf-8")).hexdigest()

        groups_vo = await summary_client.query_groups()
        assert [(g.unique_identifier, g.name) for g in groups_vo.summary_do_list] == [
            ("2799b74528407f6aeeeff095f7685e9e", "Reading Notes"),
            (ai_group_uuid, "AI Summaries"),
        ]

        summaries_vo = await summary_client.query_summaries()
        assert [
            (
                s.unique_identifier,
                s.parent_unique_identifier,
                s.source_path,
                s.content,
                s.md5_hash,
            )
            for s in summaries_vo.summary_do_list
        ] == [
            (
                "aabbccdd11223344556677889900ff00",
                "2799b74528407f6aeeeff095f7685e9e",
                "Document/Paper.pdf",
                "Standalone PDF highlight excerpt.",
                hashlib.md5(b"Standalone PDF highlight excerpt.").hexdigest(),
            ),
            (
                canonical_uuid,
                ai_group_uuid,
                "Note/Work/Sprint.note",
                expected_content,
                expected_md5,
            ),
        ]

        ai_cat_vo = await summary_client.query_summaries(parent_uuid=ai_group_uuid)
        assert [s.unique_identifier for s in ai_cat_vo.summary_do_list] == [
            canonical_uuid
        ]
        migrated_id = ai_cat_vo.summary_do_list[0].id
        assert migrated_id is not None

        by_id_vo = await summary_client.query_summary_id(
            QuerySummaryDTO(ids=[migrated_id])
        )
        assert '"segments"' in (by_id_vo.summary_do_list[0].metadata or "")

        hash_vo = await summary_client.query_summary_hash(QuerySummaryDTO())
        assert {item.id: item.md5_hash for item in hash_vo.summary_info_vo_list} == {
            777403578607207197: hashlib.md5(
                b"Standalone PDF highlight excerpt."
            ).hexdigest(),
            migrated_id: expected_md5,
        }

        ext_summaries = await extended_client.list_summaries(SPRINT_NOTE_FILE_ID)
        assert [s.unique_identifier for s in ext_summaries.summary_do_list] == [
            canonical_uuid
        ]
        transcript_vo = await extended_client.get_transcript(SPRINT_NOTE_FILE_ID)
        assert [p.text for p in transcript_vo.pages] == [
            "Transcribed (68700 bytes)",
            "Transcribed (68345 bytes)",
        ]
