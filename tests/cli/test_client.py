"""Tests for supernote.cli.client against a real in-process Supernote server."""

import argparse
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from supernote.cli.client import (
    add_parser,
    async_cloud_download,
    async_cloud_insights,
    async_cloud_login,
    async_cloud_ls,
    async_cloud_mkdir,
    async_cloud_rm,
    async_cloud_search,
    async_cloud_socket,
    async_cloud_upload,
    create_session,
    load_cached_auth,
    server_url_override,
    setup_logging,
    subcommand_cloud_download,
    subcommand_cloud_insights,
    subcommand_cloud_login,
    subcommand_cloud_ls,
    subcommand_cloud_mkdir,
    subcommand_cloud_rm,
    subcommand_cloud_search,
    subcommand_cloud_socket,
    subcommand_cloud_upload,
)
from supernote.client.auth import FileCacheAuth
from supernote.models.summary import AddSummaryDTO
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.keys import SUMMARY_SERVICE_KEY
from supernote.server.services.summary import SummaryService

from .conftest import ADMIN_EMAIL, ADMIN_PASSWORD, CliServerEnv


def test_add_parser() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    parsed = parser.parse_args(
        ["cloud", "login", "user@example.com", "--url", "http://localhost:8080"]
    )
    assert parsed.command == "cloud"
    assert parsed.cloud_command == "login"
    assert parsed.email == "user@example.com"
    assert parsed.url == "http://localhost:8080"
    assert parsed.func == subcommand_cloud_login

    parsed = parser.parse_args(["cloud", "ls", "/MyFolder"])
    assert parsed.path == "/MyFolder"
    assert parsed.func == subcommand_cloud_ls

    parsed = parser.parse_args(["cloud", "upload", "local.note", "/remote.note"])
    assert parsed.local_path == "local.note"
    assert parsed.remote_path == "/remote.note"
    assert parsed.func == subcommand_cloud_upload

    parsed = parser.parse_args(["cloud", "download", "/remote.note", "local.note"])
    assert parsed.remote_path == "/remote.note"
    assert parsed.local_path == "local.note"
    assert parsed.func == subcommand_cloud_download

    parsed = parser.parse_args(["cloud", "mkdir", "/NewFolder"])
    assert parsed.path == "/NewFolder"
    assert parsed.func == subcommand_cloud_mkdir

    parsed = parser.parse_args(["cloud", "rm", "/OldFolder"])
    assert parsed.path == "/OldFolder"
    assert parsed.func == subcommand_cloud_rm

    parsed = parser.parse_args(["cloud", "insights", "/note.note"])
    assert parsed.path == "/note.note"
    assert parsed.func == subcommand_cloud_insights

    parsed = parser.parse_args(["cloud", "search", "meeting notes", "--top-n", "3"])
    assert parsed.query == "meeting notes"
    assert parsed.top_n == 3
    assert parsed.func == subcommand_cloud_search


def test_add_parser_socket() -> None:
    """Verify that 'cloud socket' parser registers options correctly."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    parsed = parser.parse_args(
        ["cloud", "socket", "--duration", "5.0", "--type", "ANDROID"]
    )
    assert parsed.command == "cloud"
    assert parsed.cloud_command == "socket"
    assert parsed.duration == 5.0
    assert parsed.type == "ANDROID"
    assert parsed.func == subcommand_cloud_socket


def test_load_cached_auth_no_cache_no_url(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        load_cached_auth()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "No cached credentials found" in captured.out


def test_load_cached_auth_no_host_in_cache(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cache_path = os.path.expanduser("~/.cache/supernote.pkl")
    FileCacheAuth(cache_path).save_credentials("token-123", "")

    with pytest.raises(SystemExit) as exc_info:
        load_cached_auth()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "No server URL found in cached credentials" in captured.out


def test_load_cached_auth_success() -> None:
    cache_path = os.path.expanduser("~/.cache/supernote.pkl")
    FileCacheAuth(cache_path).save_credentials("token-123", "http://cached-server:8080")

    auth, url = load_cached_auth()
    assert url == "http://cached-server:8080"
    assert auth.token == "token-123"


async def test_server_url_override_precedence() -> None:
    """Verify server_url_override supersedes cached host and resets cleanly."""
    with server_url_override("http://bootstrap.example"):
        assert load_cached_auth()[1] == "http://bootstrap.example"

    cache_path = os.path.expanduser("~/.cache/supernote.pkl")
    FileCacheAuth(cache_path).save_credentials("token-123", "http://cached.example")

    assert load_cached_auth()[1] == "http://cached.example"
    with server_url_override("http://override.example"):
        assert load_cached_auth()[1] == "http://override.example"
        async with create_session() as sn:
            assert sn.client.host == "http://override.example"
        with server_url_override(None):
            assert load_cached_auth()[1] == "http://cached.example"
        assert load_cached_auth()[1] == "http://override.example"
    assert load_cached_auth()[1] == "http://cached.example"


def test_setup_logging() -> None:
    setup_logging(verbose=True)
    setup_logging(verbose=False)


async def test_async_cloud_login_success(
    cli_env: CliServerEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    await async_cloud_login(ADMIN_EMAIL, ADMIN_PASSWORD, cli_env.url)

    captured = capsys.readouterr()
    assert "✓ Login successful!" in captured.out
    assert "✓ User query successful!" in captured.out
    assert "✓ File list successful!" in captured.out


async def test_async_cloud_login_invalid_credentials(
    cli_env: CliServerEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        await async_cloud_login(ADMIN_EMAIL, "wrong-password", cli_env.url)
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Error during login flow:" in captured.out


async def test_async_cloud_mkdir_upload_ls_download_rm(
    cli_env: CliServerEnv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await async_cloud_mkdir("/NOTE/Note/Projects")
    captured = capsys.readouterr()
    assert "✓ Folder created successfully!" in captured.out

    local_file = tmp_path / "test.txt"
    local_file.write_bytes(b"note binary content")

    await async_cloud_upload(str(local_file), "/NOTE/Note/Projects/test.txt")
    captured = capsys.readouterr()
    assert "✓ Upload successful!" in captured.out

    await async_cloud_ls("/NOTE/Note/Projects")
    captured = capsys.readouterr()
    assert "Total files: 1" in captured.out
    assert "test.txt" in captured.out

    downloaded_file = tmp_path / "downloaded.txt"
    await async_cloud_download("/NOTE/Note/Projects/test.txt", str(downloaded_file))
    captured = capsys.readouterr()
    assert f"✓ Downloaded to {downloaded_file}" in captured.out
    assert downloaded_file.read_bytes() == b"note binary content"

    await async_cloud_rm("/NOTE/Note/Projects/test.txt")
    captured = capsys.readouterr()
    assert "✓ Removed successfully!" in captured.out


async def test_async_cloud_ls_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cache_path = os.path.expanduser("~/.cache/supernote.pkl")
    FileCacheAuth(cache_path).save_credentials("token", "http://127.0.0.1:1")

    with pytest.raises(SystemExit) as exc_info:
        await async_cloud_ls("/")
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Error:" in captured.out


def test_subcommand_cloud_upload_file_not_found(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = argparse.Namespace(
        local_path="nonexistent_file.note", remote_path=None, verbose=False
    )
    with pytest.raises(SystemExit) as exc_info:
        subcommand_cloud_upload(args)
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Local file not found" in captured.out


async def test_async_cloud_insights_not_found(
    cli_env: CliServerEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        await async_cloud_insights("/NOTE/Note/nonexistent.note")
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Error: File not found" in captured.out


async def test_async_cloud_insights_success(
    cli_env: CliServerEnv,
    test_note_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await async_cloud_upload(str(test_note_path), "/NOTE/Note/my_note.note")
    capsys.readouterr()

    assert cli_env.client.app is not None
    summary_service: SummaryService = cli_env.client.app[SUMMARY_SERVICE_KEY]
    async with cli_env.session_manager.session() as session:
        user_file = (
            await session.execute(
                select(UserFileDO).where(UserFileDO.file_name == "my_note.note")
            )
        ).scalar_one()

    await summary_service.add_summary(
        ADMIN_EMAIL,
        AddSummaryDTO(
            file_id=user_file.id,
            unique_identifier="summary-insight-1",
            content="Key take-aways from meeting.",
            data_source="AI Synthesis",
            creation_time=1700000000000,
        ),
    )

    await async_cloud_insights("/NOTE/Note/my_note.note")
    captured = capsys.readouterr()
    assert "AI INSIGHTS & SYNCHRONIZED SYNTHESIS" in captured.out
    assert "Key take-aways from meeting." in captured.out


async def test_async_cloud_search_no_results_and_with_results(
    cli_env: CliServerEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    await async_cloud_search("project deadline")
    captured = capsys.readouterr()
    assert "No results found." in captured.out

    admin_id = await cli_env.user_service.get_user_id(ADMIN_EMAIL)
    async with cli_env.session_manager.session() as session:
        session.add(
            UserFileDO(
                id=501,
                user_id=admin_id,
                file_name="20250615_Project_Notes.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=501,
                page_index=0,
                page_id="P2025061500000000000000000",
                text_content="Deadline is end of month.",
                embedding="[1.0, 0.0, 0.0]",
                embedding_model="fake-embedding-v1",
            )
        )
        await session.commit()

    await async_cloud_search(
        "project deadline",
        top_n=5,
        name_filter="Project",
        after="2025-01-01",
        before="2025-12-31",
    )
    captured = capsys.readouterr()
    assert "Semantic Search Results for: 'project deadline'" in captured.out
    assert "20250615_Project_Notes.note" in captured.out
    assert "Deadline is end of month." in captured.out


async def test_async_cloud_socket_success(
    cli_env: CliServerEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    await async_cloud_socket(duration=0.1, conn_type="ANDROID", verbose=True)

    captured = capsys.readouterr()
    assert "[SUCCESS] Connected to Socket.IO real-time server!" in captured.out
    assert "Ping:" in captured.out
    assert "Status check:" in captured.out
    assert "Disconnected cleanly from Socket.IO server." in captured.out
