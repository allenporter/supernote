"""Tests for supernote.cli.client."""

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from supernote.cli.client import (
    add_parser,
    load_cached_auth,
    setup_logging,
    subcommand_cloud_download,
    subcommand_cloud_insights,
    subcommand_cloud_login,
    subcommand_cloud_ls,
    subcommand_cloud_mkdir,
    subcommand_cloud_rm,
    subcommand_cloud_search,
    subcommand_cloud_upload,
)
from supernote.client.exceptions import SmsVerificationRequired, SupernoteException


def test_add_parser():
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


def test_load_cached_auth_no_cache_no_url(tmp_path, capsys):
    fake_cache = tmp_path / "nonexistent.pkl"
    with (
        patch("os.path.exists", return_value=False),
        patch("os.path.expanduser", return_value=str(fake_cache)),
    ):
        with pytest.raises(SystemExit) as exc_info:
            load_cached_auth(url=None)
        assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "No cached credentials found" in captured.out


def test_load_cached_auth_no_host_in_cache(tmp_path, capsys):
    fake_cache = tmp_path / "cache.pkl"
    mock_auth = MagicMock()
    mock_auth.get_host.return_value = None

    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.expanduser", return_value=str(fake_cache)),
        patch("supernote.cli.client.FileCacheAuth", return_value=mock_auth),
    ):
        with pytest.raises(SystemExit) as exc_info:
            load_cached_auth(url=None)
        assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "No server URL found in cached credentials" in captured.out


def test_load_cached_auth_success(tmp_path):
    fake_cache = tmp_path / "cache.pkl"
    mock_auth = MagicMock()
    mock_auth.get_host.return_value = "http://cached-server:8080"

    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.expanduser", return_value=str(fake_cache)),
        patch("supernote.cli.client.FileCacheAuth", return_value=mock_auth),
    ):
        auth, url = load_cached_auth(url=None)
        assert url == "http://cached-server:8080"
        assert auth == mock_auth


def test_setup_logging():
    setup_logging(verbose=True)
    setup_logging(verbose=False)


def test_subcommand_cloud_login_success(capsys):
    args = argparse.Namespace(
        email="user@example.com",
        password="secret",
        url="http://localhost:8080",
        verbose=False,
    )
    mock_sn = MagicMock()
    mock_sn.token = "test-token-12345678901234567890"
    mock_sn.web = AsyncMock()
    mock_sn.web.query_user.return_value = MagicMock(user=None)
    mock_sn.device = AsyncMock()
    mock_sn.device.list_folder.return_value = MagicMock(entries=[])
    mock_sn.__aenter__ = AsyncMock(return_value=mock_sn)
    mock_sn.__aexit__ = AsyncMock(return_value=None)

    with (
        patch(
            "supernote.cli.client.Supernote.login",
            new_callable=AsyncMock,
            return_value=mock_sn,
        ),
        patch("supernote.cli.client.FileCacheAuth"),
    ):
        subcommand_cloud_login(args)

    captured = capsys.readouterr()
    assert "✓ Login successful!" in captured.out


def test_subcommand_cloud_login_prompt_password(capsys):
    args = argparse.Namespace(
        email="user@example.com",
        password=None,
        url="http://localhost:8080",
        verbose=False,
    )
    mock_sn = MagicMock()
    mock_sn.token = "test-token-12345678901234567890"
    mock_sn.web = AsyncMock()
    mock_sn.web.query_user.return_value = MagicMock(user=None)
    mock_sn.device = AsyncMock()
    mock_sn.device.list_folder.return_value = MagicMock(entries=[])
    mock_sn.__aenter__ = AsyncMock(return_value=mock_sn)
    mock_sn.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("getpass.getpass", return_value="prompted_pass"),
        patch(
            "supernote.cli.client.Supernote.login",
            new_callable=AsyncMock,
            return_value=mock_sn,
        ),
        patch("supernote.cli.client.FileCacheAuth"),
    ):
        subcommand_cloud_login(args)

    captured = capsys.readouterr()
    assert "✓ Login successful!" in captured.out


def test_subcommand_cloud_login_sms_verification(capsys):
    args = argparse.Namespace(
        email="user@example.com",
        password="secret",
        url="http://localhost:8080",
        verbose=False,
    )
    mock_sn = MagicMock()
    mock_sn.token = "test-token-12345678901234567890"
    mock_sn.web = AsyncMock()
    mock_sn.web.query_user.return_value = MagicMock(user=None)
    mock_sn.device = AsyncMock()
    mock_sn.device.list_folder.return_value = MagicMock(entries=[])
    mock_sn.__aenter__ = AsyncMock(return_value=mock_sn)
    mock_sn.__aexit__ = AsyncMock(return_value=None)

    sms_err = SmsVerificationRequired("SMS code sent", "123456")

    temp_sn = MagicMock()
    temp_sn.login_client = AsyncMock()
    temp_sn.login_client.sms_login.return_value = "sms-token-12345678901234567890"
    temp_sn.with_auth.return_value = mock_sn
    temp_sn.__aenter__ = AsyncMock(return_value=temp_sn)
    temp_sn.__aexit__ = AsyncMock(return_value=None)

    mock_supernote_cls = MagicMock(return_value=temp_sn)
    mock_supernote_cls.login = AsyncMock(side_effect=sms_err)

    with (
        patch("supernote.cli.client.Supernote", mock_supernote_cls),
        patch("builtins.input", return_value="123456"),
        patch("supernote.cli.client.FileCacheAuth"),
    ):
        subcommand_cloud_login(args)

    captured = capsys.readouterr()
    assert "SMS Verification Required" in captured.out
    assert "✓ Login successful!" in captured.out


def test_subcommand_cloud_login_supernote_exception(capsys):
    args = argparse.Namespace(
        email="user@example.com",
        password="wrong",
        url="http://localhost:8080",
        verbose=False,
    )
    with patch(
        "supernote.cli.client.Supernote.login",
        new_callable=AsyncMock,
        side_effect=SupernoteException("Auth error"),
    ):
        with pytest.raises(SystemExit) as exc_info:
            subcommand_cloud_login(args)
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Error during login flow: Auth error" in captured.out


def test_subcommand_cloud_ls_success(capsys):
    args = argparse.Namespace(path="/", verbose=False)

    file_entry = MagicMock()
    file_entry.name = "Document.note"
    file_entry.id = "1001"
    file_entry.tag = "file"

    mock_sn = MagicMock()
    mock_sn.client = MagicMock(host="http://localhost:8080")
    mock_sn.device = AsyncMock()
    mock_sn.device.list_folder.return_value = MagicMock(entries=[file_entry])

    with patch("supernote.cli.client.create_session") as mock_create_session:
        mock_create_session.return_value.__aenter__.return_value = mock_sn
        subcommand_cloud_ls(args)

    captured = capsys.readouterr()
    assert "Total files: 1" in captured.out
    assert "Document.note" in captured.out


def test_subcommand_cloud_ls_error(capsys):
    args = argparse.Namespace(path="/", verbose=False)
    with patch("supernote.cli.client.create_session") as mock_create_session:
        mock_create_session.side_effect = SupernoteException("Connection refused")
        with pytest.raises(SystemExit) as exc_info:
            subcommand_cloud_ls(args)
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Error: Connection refused" in captured.out


def test_subcommand_cloud_upload_file_not_found(capsys):
    args = argparse.Namespace(
        local_path="nonexistent_file.note", remote_path=None, verbose=False
    )
    with pytest.raises(SystemExit) as exc_info:
        subcommand_cloud_upload(args)
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Local file not found" in captured.out


def test_subcommand_cloud_upload_success(tmp_path, capsys):
    local_file = tmp_path / "test.note"
    local_file.write_bytes(b"content")

    args = argparse.Namespace(
        local_path=str(local_file), remote_path="/folder/", verbose=False
    )

    mock_sn = MagicMock()
    mock_sn.device = AsyncMock()

    with patch("supernote.cli.client.create_session") as mock_create_session:
        mock_create_session.return_value.__aenter__.return_value = mock_sn
        subcommand_cloud_upload(args)

    captured = capsys.readouterr()
    assert "✓ Upload successful!" in captured.out
    mock_sn.device.upload_content.assert_called_once_with(
        "/folder/test.note", b"content"
    )


def test_subcommand_cloud_download_success(tmp_path, capsys):
    out_file = tmp_path / "downloaded.note"
    args = argparse.Namespace(
        remote_path="/remote.note", local_path=str(out_file), verbose=False
    )

    mock_sn = MagicMock()
    mock_sn.device = AsyncMock()
    mock_sn.device.download_content.return_value = b"remote_content"

    with patch("supernote.cli.client.create_session") as mock_create_session:
        mock_create_session.return_value.__aenter__.return_value = mock_sn
        subcommand_cloud_download(args)

    captured = capsys.readouterr()
    assert f"✓ Downloaded to {out_file}" in captured.out
    assert out_file.read_bytes() == b"remote_content"


def test_subcommand_cloud_download_directory_local_path(tmp_path, capsys):
    args = argparse.Namespace(
        remote_path="/folder/remote.note", local_path=str(tmp_path), verbose=False
    )

    mock_sn = MagicMock()
    mock_sn.device = AsyncMock()
    mock_sn.device.download_content.return_value = b"data"

    with patch("supernote.cli.client.create_session") as mock_create_session:
        mock_create_session.return_value.__aenter__.return_value = mock_sn
        subcommand_cloud_download(args)

    expected_file = tmp_path / "remote.note"
    assert expected_file.exists()


def test_subcommand_cloud_mkdir_success(capsys):
    args = argparse.Namespace(path="/NewDir", verbose=False)
    mock_sn = MagicMock()
    mock_sn.device = AsyncMock()

    with patch("supernote.cli.client.create_session") as mock_create_session:
        mock_create_session.return_value.__aenter__.return_value = mock_sn
        subcommand_cloud_mkdir(args)

    captured = capsys.readouterr()
    assert "✓ Folder created successfully!" in captured.out
    mock_sn.device.create_folder.assert_called_once_with("/NewDir", equipment_no="WEB")


def test_subcommand_cloud_rm_success(capsys):
    args = argparse.Namespace(path="/OldDir", verbose=False)
    mock_sn = MagicMock()
    mock_sn.device = AsyncMock()

    with patch("supernote.cli.client.create_session") as mock_create_session:
        mock_create_session.return_value.__aenter__.return_value = mock_sn
        subcommand_cloud_rm(args)

    captured = capsys.readouterr()
    assert "✓ Removed successfully!" in captured.out
    mock_sn.device.delete_by_path.assert_called_once_with("/OldDir")


def test_subcommand_cloud_insights_not_found(capsys):
    args = argparse.Namespace(path="/nonexistent.note", verbose=False)
    mock_sn = MagicMock()
    mock_sn.device = AsyncMock()
    mock_sn.device.query_by_path.return_value = MagicMock(entries_vo=None)

    with patch("supernote.cli.client.create_session") as mock_create_session:
        mock_create_session.return_value.__aenter__.return_value = mock_sn
        with pytest.raises(SystemExit) as exc_info:
            subcommand_cloud_insights(args)
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Error: File not found" in captured.out


def test_subcommand_cloud_insights_success(capsys):
    args = argparse.Namespace(path="/my_note.note", verbose=False)

    entry_vo = MagicMock()
    entry_vo.id = "123"
    entry_vo.name = "my_note.note"

    mock_sn = MagicMock()
    mock_sn.device = AsyncMock()
    mock_sn.device.query_by_path.return_value = MagicMock(entries_vo=entry_vo)
    mock_sn.client = MagicMock()

    summary_item = MagicMock()
    summary_item.data_source = "AI Synthesis"
    summary_item.creation_time = 1700000000000
    summary_item.content = "Key take-aways from meeting."

    mock_summaries_vo = MagicMock()
    mock_summaries_vo.summary_do_list = [summary_item]

    with (
        patch("supernote.cli.client.create_session") as mock_create_session,
        patch(
            "supernote.client.extended.ExtendedClient.list_summaries",
            new_callable=AsyncMock,
            return_value=mock_summaries_vo,
        ),
    ):
        mock_create_session.return_value.__aenter__.return_value = mock_sn
        subcommand_cloud_insights(args)

    captured = capsys.readouterr()
    assert "AI INSIGHTS & SYNCHRONIZED SYNTHESIS" in captured.out
    assert "Key take-aways from meeting." in captured.out


def test_subcommand_cloud_search_no_results(capsys):
    args = argparse.Namespace(
        query="project deadline",
        top_n=5,
        name_filter=None,
        after=None,
        before=None,
        verbose=False,
    )
    mock_sn = MagicMock()
    mock_sn.client = MagicMock()
    mock_resp = MagicMock(results=[])

    with (
        patch("supernote.cli.client.create_session") as mock_create_session,
        patch(
            "supernote.client.extended.ExtendedClient.search",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ),
    ):
        mock_create_session.return_value.__aenter__.return_value = mock_sn
        subcommand_cloud_search(args)

    captured = capsys.readouterr()
    assert "No results found." in captured.out


def test_subcommand_cloud_search_with_results(capsys):
    args = argparse.Namespace(
        query="project deadline",
        top_n=5,
        name_filter="project",
        after="2025-01-01",
        before="2025-12-31",
        verbose=False,
    )
    mock_sn = MagicMock()
    mock_sn.client = MagicMock()

    result_item = MagicMock()
    result_item.file_name = "Project_Notes.note"
    result_item.page_index = 0
    result_item.score = 0.95
    result_item.date = "2025-06-15"
    result_item.text_preview = "Deadline is end of month."

    mock_resp = MagicMock(results=[result_item])

    with (
        patch("supernote.cli.client.create_session") as mock_create_session,
        patch(
            "supernote.client.extended.ExtendedClient.search",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ),
    ):
        mock_create_session.return_value.__aenter__.return_value = mock_sn
        subcommand_cloud_search(args)

    captured = capsys.readouterr()
    assert "Semantic Search Results for: 'project deadline'" in captured.out
    assert "Project_Notes.note" in captured.out
    assert "95.0%" in captured.out
    assert "Deadline is end of month." in captured.out
