"""Tests for supernote.cli.admin."""

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from supernote.cli.admin import (
    add_parser,
    add_user,
    list_users,
    queue_start,
    queue_status,
    queue_stop,
    reprocess,
    reset_password,
)
from supernote.client.exceptions import ApiException


def test_add_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    parsed = parser.parse_args(
        ["admin", "--url", "http://localhost:8080", "user", "list"]
    )
    assert parsed.command == "admin"
    assert parsed.url == "http://localhost:8080"
    assert parsed.admin_command == "user"
    assert parsed.user_command == "list"
    assert parsed.func == list_users

    parsed = parser.parse_args(
        [
            "admin",
            "user",
            "add",
            "test@example.com",
            "--password",
            "secret",
            "--name",
            "Test User",
        ]
    )
    assert parsed.email == "test@example.com"
    assert parsed.password == "secret"
    assert parsed.name == "Test User"
    assert parsed.func == add_user

    parsed = parser.parse_args(["admin", "user", "reset-password", "user@example.com"])
    assert parsed.email == "user@example.com"
    assert parsed.func == reset_password

    parsed = parser.parse_args(["admin", "queue", "status"])
    assert parsed.func == queue_status

    parsed = parser.parse_args(["admin", "queue", "stop"])
    assert parsed.func == queue_stop

    parsed = parser.parse_args(["admin", "queue", "start"])
    assert parsed.func == queue_start

    parsed = parser.parse_args(
        ["admin", "reprocess", "--type", "ocr", "--file-id", "123"]
    )
    assert parsed.type == "ocr"
    assert parsed.file_id == 123
    assert parsed.func == reprocess


def test_add_user_public_registration_success(capsys):
    args = argparse.Namespace(
        url="http://localhost:8080",
        email="user@example.com",
        password="secret",
        name="User",
    )
    mock_admin_client = AsyncMock()
    mock_session = MagicMock()
    mock_session.client = MagicMock()

    with (
        patch("supernote.cli.admin.create_session") as mock_create_session,
        patch("supernote.cli.admin.AdminClient", return_value=mock_admin_client),
    ):
        mock_create_session.return_value.__aenter__.return_value = mock_session
        add_user(args)

    captured = capsys.readouterr()
    assert "Success! User created (Public Registration)." in captured.out
    mock_admin_client.register.assert_called_once()


def test_add_user_fallback_admin_creation_success(capsys):
    args = argparse.Namespace(
        url="http://localhost:8080", email="user@example.com", password=None, name=None
    )
    mock_admin_client = AsyncMock()
    mock_admin_client.register.side_effect = ApiException(
        "Public registration disabled"
    )
    mock_session = MagicMock()
    mock_session.client = MagicMock()

    with (
        patch("supernote.cli.admin.create_session") as mock_create_session,
        patch("supernote.cli.admin.AdminClient", return_value=mock_admin_client),
        patch("getpass.getpass", return_value="prompted_pass"),
    ):
        mock_create_session.return_value.__aenter__.return_value = mock_session
        add_user(args)

    captured = capsys.readouterr()
    assert "Success! User created (Admin API)." in captured.out
    mock_admin_client.admin_create_user.assert_called_once()


def test_add_user_failure(capsys):
    args = argparse.Namespace(
        url="http://localhost:8080",
        email="user@example.com",
        password="pass",
        name="Name",
    )
    mock_admin_client = AsyncMock()
    mock_admin_client.register.side_effect = ApiException("Disabled")
    mock_admin_client.admin_create_user.side_effect = Exception("Admin creation error")
    mock_session = MagicMock()
    mock_session.client = MagicMock()

    with (
        patch("supernote.cli.admin.create_session") as mock_create_session,
        patch("supernote.cli.admin.AdminClient", return_value=mock_admin_client),
    ):
        mock_create_session.return_value.__aenter__.return_value = mock_session
        with pytest.raises(SystemExit) as exc_info:
            add_user(args)
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Admin creation failed: Admin creation error" in captured.out


def test_list_users_success(capsys):
    args = argparse.Namespace(url="http://localhost:8080")
    mock_resp = AsyncMock()
    mock_resp.json.return_value = [
        {"email": "admin@example.com", "userName": "Admin", "totalCapacity": "10GB"}
    ]
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    mock_session = MagicMock()
    mock_session.client = mock_client

    with patch("supernote.cli.admin.create_session") as mock_create_session:
        mock_create_session.return_value.__aenter__.return_value = mock_session
        list_users(args)

    captured = capsys.readouterr()
    assert "admin@example.com" in captured.out
    assert "Admin" in captured.out


def test_list_users_failure(capsys):
    args = argparse.Namespace(url="http://localhost:8080")
    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("Network Error")

    mock_session = MagicMock()
    mock_session.client = mock_client

    with patch("supernote.cli.admin.create_session") as mock_create_session:
        mock_create_session.return_value.__aenter__.return_value = mock_session
        list_users(args)

    captured = capsys.readouterr()
    assert "Failed to list users: Network Error" in captured.out


def test_reset_password_mismatch(capsys):
    args = argparse.Namespace(
        url="http://localhost:8080", email="user@example.com", password=None
    )
    with patch("getpass.getpass", side_effect=["pass1", "pass2"]):
        with pytest.raises(SystemExit) as exc_info:
            reset_password(args)
        assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Passwords do not match." in captured.out


def test_reset_password_success(capsys):
    args = argparse.Namespace(
        url="http://localhost:8080", email="user@example.com", password="newpass"
    )
    mock_admin_client = AsyncMock()
    mock_session = MagicMock()
    mock_session.client = MagicMock()

    with (
        patch("supernote.cli.admin.create_session") as mock_create_session,
        patch("supernote.cli.admin.AdminClient", return_value=mock_admin_client),
    ):
        mock_create_session.return_value.__aenter__.return_value = mock_session
        reset_password(args)

    captured = capsys.readouterr()
    assert "Success! Password Reset." in captured.out


def test_reset_password_failure(capsys):
    args = argparse.Namespace(
        url="http://localhost:8080", email="user@example.com", password="newpass"
    )
    mock_admin_client = AsyncMock()
    mock_admin_client.admin_reset_password.side_effect = Exception("User not found")
    mock_session = MagicMock()
    mock_session.client = MagicMock()

    with (
        patch("supernote.cli.admin.create_session") as mock_create_session,
        patch("supernote.cli.admin.AdminClient", return_value=mock_admin_client),
    ):
        mock_create_session.return_value.__aenter__.return_value = mock_session
        with pytest.raises(SystemExit) as exc_info:
            reset_password(args)
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Failed to reset password: User not found" in captured.out


def test_queue_status_running(capsys):
    args = argparse.Namespace(url="http://localhost:8080")
    mock_status = MagicMock()
    mock_status.paused = False
    mock_status.queue_size = 5
    mock_status.processing_files = [1, 2]

    mock_admin_client = AsyncMock()
    mock_admin_client.get_queue_status.return_value = mock_status
    mock_session = MagicMock()
    mock_session.client = MagicMock()

    with (
        patch("supernote.cli.admin.create_session") as mock_create_session,
        patch("supernote.cli.admin.AdminClient", return_value=mock_admin_client),
    ):
        mock_create_session.return_value.__aenter__.return_value = mock_session
        queue_status(args)

    captured = capsys.readouterr()
    assert "Status:            RUNNING" in captured.out
    assert "Queue Size:        5" in captured.out


def test_queue_status_failure(capsys):
    args = argparse.Namespace(url="http://localhost:8080")
    mock_admin_client = AsyncMock()
    mock_admin_client.get_queue_status.side_effect = Exception("Server Error")
    mock_session = MagicMock()
    mock_session.client = MagicMock()

    with (
        patch("supernote.cli.admin.create_session") as mock_create_session,
        patch("supernote.cli.admin.AdminClient", return_value=mock_admin_client),
    ):
        mock_create_session.return_value.__aenter__.return_value = mock_session
        with pytest.raises(SystemExit) as exc_info:
            queue_status(args)
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Failed to get queue status: Server Error" in captured.out


def test_queue_stop_success(capsys):
    args = argparse.Namespace(url="http://localhost:8080")
    mock_admin_client = AsyncMock()
    mock_session = MagicMock()
    mock_session.client = MagicMock()

    with (
        patch("supernote.cli.admin.create_session") as mock_create_session,
        patch("supernote.cli.admin.AdminClient", return_value=mock_admin_client),
    ):
        mock_create_session.return_value.__aenter__.return_value = mock_session
        queue_stop(args)

    captured = capsys.readouterr()
    assert "Success: Queue processing stopped." in captured.out


def test_queue_start_success(capsys):
    args = argparse.Namespace(url="http://localhost:8080")
    mock_admin_client = AsyncMock()
    mock_session = MagicMock()
    mock_session.client = MagicMock()

    with (
        patch("supernote.cli.admin.create_session") as mock_create_session,
        patch("supernote.cli.admin.AdminClient", return_value=mock_admin_client),
    ):
        mock_create_session.return_value.__aenter__.return_value = mock_session
        queue_start(args)

    captured = capsys.readouterr()
    assert "Success: Queue processing started." in captured.out


def test_reprocess_success(capsys):
    args = argparse.Namespace(url="http://localhost:8080", type="summary", file_id=42)
    mock_admin_client = AsyncMock()
    mock_session = MagicMock()
    mock_session.client = MagicMock()

    with (
        patch("supernote.cli.admin.create_session") as mock_create_session,
        patch("supernote.cli.admin.AdminClient", return_value=mock_admin_client),
    ):
        mock_create_session.return_value.__aenter__.return_value = mock_session
        reprocess(args)

    captured = capsys.readouterr()
    assert "Triggered reprocessing of 'summary' for file ID 42." in captured.out
