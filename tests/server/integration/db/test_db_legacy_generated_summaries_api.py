"""Integration tests verifying legacy pre-#635 generated summary database compatibility via HTTP APIs."""

import shutil
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from supernote.client.auth import AbstractAuth
from supernote.client.client import Client
from supernote.client.extended import ExtendedClient
from supernote.client.summary import SummaryClient
from supernote.models.summary import QuerySummaryDTO
from supernote.server.app import create_app
from supernote.server.config import AuthConfig, ServerConfig
from supernote.server.db.migrations import run_migrations
from supernote.server.keys import USER_SERVICE_KEY

FIXTURES_DIR = Path(__file__).parent.parent.parent.parent / "fixtures"
LEGACY_SUMMARIES_FIXTURE_PATH = FIXTURES_DIR / "db_legacy_generated_summaries.sqlite"
SPRINT_NOTE_FILE_ID = 750000000000000001
LEGACY_USER_EMAIL = "legacy_summary@example.com"


async def test_unmigrated_legacy_generated_summaries_api_query(tmp_path: Path) -> None:
    """Verify a pre-#635 database with storage_key-suffixed groups/transcripts/summaries serves cleanly at e8f9a0b1c2d3."""
    storage_dir = tmp_path / "storage"
    db_file = storage_dir / "system" / "supernote.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(LEGACY_SUMMARIES_FIXTURE_PATH, db_file)

    sync_db_url = f"sqlite:///{db_file}"
    run_migrations(sync_db_url, "e8f9a0b1c2d3")

    config = ServerConfig(
        storage_dir=str(storage_dir),
        auth=AuthConfig(secret_key="test-secret-key-32-characters-long!!"),
        mcp_enabled=False,
        mcp_port=0,
    )
    app = create_app(config)
    token = await app[USER_SERVICE_KEY].create_session(LEGACY_USER_EMAIL)

    class TokenAuth(AbstractAuth):
        async def async_get_access_token(self) -> str:
            return token

    test_server = TestServer(app)
    test_client = TestClient(test_server)
    await test_client.start_server()
    base_url = str(test_client.make_url("/"))

    auth_client = Client(test_client.session, auth=TokenAuth(), host=base_url)
    summary_client = SummaryClient(auth_client)
    extended_client = ExtendedClient(auth_client)

    try:
        groups_vo = await summary_client.query_groups()
        assert groups_vo.success
        assert [(g.unique_identifier, g.name) for g in groups_vo.summary_do_list] == [
            ("11111111-aaaa-4bbb-8ccc-000000000001-095.note-group", "Sprint.note"),
            ("22222222-bbbb-4ccc-8ddd-000000000002-095.note-group", "Sprint.note"),
            ("2799b74528407f6aeeeff095f7685e9e", "Reading Notes"),
        ]

        summaries_vo = await summary_client.query_summaries()
        assert summaries_vo.success
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
            (
                "aabbccdd11223344556677889900ff00",
                "USER",
                "Document/Paper.pdf",
            ),
        ]

        hash_vo = await summary_client.query_summary_hash(QuerySummaryDTO())
        assert hash_vo.success
        assert len(hash_vo.summary_info_vo_list) == 5

        ext_summaries = await extended_client.list_summaries(SPRINT_NOTE_FILE_ID)
        assert ext_summaries.total_records == 4

        transcript_vo = await extended_client.get_transcript(SPRINT_NOTE_FILE_ID)
        assert len(transcript_vo.pages) == 2
        assert [p.text for p in transcript_vo.pages] == [
            "Transcribed (68700 bytes)",
            "Transcribed (68345 bytes)",
        ]
    finally:
        await test_client.close()
