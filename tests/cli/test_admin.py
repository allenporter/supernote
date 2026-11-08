"""Tests for supernote.cli.admin against a real in-process Supernote server."""

import argparse
import hashlib
import os

import pytest
from sqlalchemy import select

from supernote.cli.admin import (
    add_parser,
    add_user,
    add_user_async,
    integrity,
    integrity_async,
    list_tasks,
    list_tasks_async,
    list_users,
    list_users_async,
    queue_start,
    queue_start_async,
    queue_status,
    queue_status_async,
    queue_stop,
    queue_stop_async,
    reprocess,
    reprocess_async,
    reset_password,
    reset_password_async,
    set_quota,
    set_quota_async,
)
from supernote.cli.client import load_cached_auth, server_url_override
from supernote.client.auth import FileCacheAuth
from supernote.models.base import ProcessingStatus
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import SystemTaskDO
from supernote.server.db.models.user import UserDO

from .conftest import ADMIN_EMAIL, CliServerEnv


def test_add_parser() -> None:
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

    parsed = parser.parse_args(
        ["admin", "user", "set-quota", "user@example.com", "21474836480"]
    )
    assert parsed.email == "user@example.com"
    assert parsed.quota == 21474836480
    assert parsed.func == set_quota

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

    parsed = parser.parse_args(
        [
            "admin",
            "integrity",
            "--email",
            "user@example.com",
            "--file-id",
            "55",
            "--json",
        ]
    )
    assert parsed.email == "user@example.com"
    assert parsed.file_id == 55
    assert parsed.full_disk is False
    assert parsed.json is True
    assert parsed.func == integrity

    parsed_full_disk = parser.parse_args(["admin", "integrity", "--full-disk"])
    assert parsed_full_disk.email is None
    assert parsed_full_disk.full_disk is True
    assert parsed_full_disk.func == integrity

    parsed = parser.parse_args(
        ["admin", "tasks", "--status", "failed", "--type", "ocr", "--json"]
    )
    assert parsed.status == "failed"
    assert parsed.type == "ocr"
    assert parsed.json is True
    assert parsed.func == list_tasks


async def test_add_user_public_registration_success(
    cli_env: CliServerEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    await add_user_async("user@example.com", "secret", "User")

    captured = capsys.readouterr()
    assert "Success! User created (Public Registration)." in captured.out
    assert await cli_env.user_service.check_user_exists("user@example.com") is True


async def test_add_user_fallback_admin_creation_success(
    cli_env: CliServerEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    cli_env.server_config.auth.enable_registration = False
    await add_user_async("user2@example.com", "prompted_pass", "User 2")

    captured = capsys.readouterr()
    assert "Success! User created (Admin API)." in captured.out
    assert await cli_env.user_service.check_user_exists("user2@example.com") is True


async def test_add_user_failure(
    cli_env: CliServerEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    cli_env.server_config.auth.enable_registration = False
    with pytest.raises(SystemExit) as exc_info:
        await add_user_async(ADMIN_EMAIL, "pass", "Duplicate Admin")
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Admin creation failed:" in captured.out


async def test_list_users_success(
    cli_env: CliServerEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    await list_users_async()

    captured = capsys.readouterr()
    assert ADMIN_EMAIL in captured.out
    assert "Test User" in captured.out


async def test_list_users_failure(capsys: pytest.CaptureFixture[str]) -> None:
    with server_url_override("http://127.0.0.1:1"):
        await list_users_async()

    captured = capsys.readouterr()
    assert "Failed to list users:" in captured.out


def test_admin_url_flag_overrides_cached_url(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The `admin --url` flag reaches the session without being passed down."""
    FileCacheAuth(os.path.expanduser("~/.cache/supernote.pkl")).save_credentials(
        "token", "http://cached.invalid"
    )
    list_users(argparse.Namespace(url="http://127.0.0.1:1"))

    captured = capsys.readouterr()
    assert "Failed to list users:" in captured.out
    assert "127.0.0.1:1" in captured.out
    assert "cached.invalid" not in captured.out


def test_server_url_override_precedence() -> None:
    FileCacheAuth(os.path.expanduser("~/.cache/supernote.pkl")).save_credentials(
        "token", "http://cached.example"
    )
    assert load_cached_auth()[1] == "http://cached.example"
    with server_url_override("http://override.example"):
        assert load_cached_auth()[1] == "http://override.example"
        assert load_cached_auth("http://explicit.example")[1] == (
            "http://explicit.example"
        )
    with server_url_override(None):
        assert load_cached_auth()[1] == "http://cached.example"
    assert load_cached_auth()[1] == "http://cached.example"


def test_reset_password_mismatch(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    args = argparse.Namespace(
        url="http://localhost:8080", email="user@example.com", password=None
    )
    prompts = iter(["pass1", "pass2"])
    monkeypatch.setattr("getpass.getpass", lambda *_: next(prompts))
    with pytest.raises(SystemExit) as exc_info:
        reset_password(args)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Passwords do not match." in captured.out


async def test_reset_password_success(
    cli_env: CliServerEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    await reset_password_async(ADMIN_EMAIL, "newpass")

    captured = capsys.readouterr()
    assert "Success! Password Reset." in captured.out

    expected_md5 = hashlib.md5(b"newpass").hexdigest()
    async with cli_env.session_manager.session() as session:
        user = (
            await session.execute(select(UserDO).where(UserDO.email == ADMIN_EMAIL))
        ).scalar_one()
        assert user.password_md5 == expected_md5


async def test_reset_password_failure(
    cli_env: CliServerEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        await reset_password_async("missing@example.com", "newpass")
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Failed to reset password:" in captured.out


async def test_queue_status_running(
    cli_env: CliServerEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    await queue_status_async()

    captured = capsys.readouterr()
    assert "Status:            RUNNING" in captured.out
    assert "Queue Size:        0" in captured.out


async def test_queue_status_failure(capsys: pytest.CaptureFixture[str]) -> None:
    with (
        server_url_override("http://127.0.0.1:1"),
        pytest.raises(SystemExit) as exc_info,
    ):
        await queue_status_async()
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Failed to get queue status:" in captured.out


async def test_queue_stop_and_start_success(
    cli_env: CliServerEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    await queue_stop_async()
    captured = capsys.readouterr()
    assert "Success: Queue processing stopped." in captured.out

    await queue_status_async()
    captured = capsys.readouterr()
    assert "Status:            PAUSED" in captured.out

    await queue_start_async()
    captured = capsys.readouterr()
    assert "Success: Queue processing started." in captured.out


async def test_reprocess_success(
    cli_env: CliServerEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    async with cli_env.session_manager.session() as session:
        session.add(
            SystemTaskDO(
                file_id=42,
                task_type="SUMMARY_GENERATION",
                key="global",
                status=ProcessingStatus.COMPLETED,
                update_time=12345,
            )
        )
        await session.commit()

    await reprocess_async("summary", 42)

    captured = capsys.readouterr()
    assert "Triggered reprocessing of 'summary' for file ID 42." in captured.out

    async with cli_env.session_manager.session() as session:
        tasks = (
            (
                await session.execute(
                    select(SystemTaskDO).where(SystemTaskDO.file_id == 42)
                )
            )
            .scalars()
            .all()
        )
        assert tasks == []


async def test_integrity_success_and_json(
    cli_env: CliServerEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    admin_id = await cli_env.user_service.get_user_id(ADMIN_EMAIL)
    assert admin_id is not None

    await integrity_async(email=ADMIN_EMAIL, as_json=False)
    captured = capsys.readouterr()
    assert "All integrity checks passed." in captured.out

    await integrity_async(email=ADMIN_EMAIL, as_json=True)
    captured = capsys.readouterr()
    assert '"scanned": 8' in captured.out
    assert '"ok": 8' in captured.out

    async with cli_env.session_manager.session() as session:
        folder_id = (
            await session.execute(
                select(UserFileDO.id).where(UserFileDO.user_id == admin_id).limit(1)
            )
        ).scalar_one()

    await integrity_async(email=ADMIN_EMAIL, file_id=folder_id, as_json=True)
    captured = capsys.readouterr()
    assert '"scanned": 1' in captured.out
    assert '"ok": 1' in captured.out

    await integrity_async(full_disk=True, as_json=True)
    captured = capsys.readouterr()
    assert '"scanned": 8' in captured.out
    assert '"ok": 8' in captured.out


async def test_integrity_issues_detected(
    cli_env: CliServerEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    admin_id = await cli_env.user_service.get_user_id(ADMIN_EMAIL)
    assert admin_id is not None
    async with cli_env.session_manager.session() as session:
        session.add(
            UserFileDO(
                id=999,
                user_id=admin_id,
                directory_id=0,
                file_name="broken.note",
                is_folder="N",
                storage_key="missing-blob-key",
                size=100,
                md5="deadbeef",
            )
        )
        await session.commit()

    with pytest.raises(SystemExit) as exc_info:
        await integrity_async(email=ADMIN_EMAIL, as_json=False)
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Total Issues:      1" in captured.out
    assert "missing_blob:" in captured.out
    assert "broken.note" in captured.out
    assert "Suggested Remediation:" in captured.out
    assert "Re-upload or re-sync affected files" in captured.out
    assert "Integrity issues detected." in captured.out


async def test_integrity_failure(capsys: pytest.CaptureFixture[str]) -> None:
    with (
        server_url_override("http://127.0.0.1:1"),
        pytest.raises(SystemExit) as exc_info,
    ):
        await integrity_async(email=ADMIN_EMAIL)
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Failed to verify integrity:" in captured.out


async def test_list_tasks_cli(
    cli_env: CliServerEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    await list_tasks_async(as_json=False)
    captured = capsys.readouterr()
    assert "No matching tasks found." in captured.out

    await list_tasks_async(as_json=True)
    captured = capsys.readouterr()
    assert '"tasks": []' in captured.out

    async with cli_env.session_manager.session() as session:
        session.add(
            SystemTaskDO(
                file_id=42,
                task_type="OCR_EXTRACTION",
                key="page_1",
                status=ProcessingStatus.FAILED,
                retry_count=2,
                update_time=1000,
                last_error="Rate limit exceeded",
            )
        )
        await session.commit()

    await list_tasks_async(status="failed", task_type="ocr", as_json=False)
    captured = capsys.readouterr()
    assert "OCR_EXTRACTION" in captured.out
    assert "Rate limit exceeded" in captured.out


async def test_list_tasks_failure(capsys: pytest.CaptureFixture[str]) -> None:
    with (
        server_url_override("http://127.0.0.1:1"),
        pytest.raises(SystemExit) as exc_info,
    ):
        await list_tasks_async()
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Failed to list tasks:" in captured.out


async def test_set_quota_cli(
    cli_env: CliServerEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    await list_users_async()
    captured = capsys.readouterr()
    assert "unlimited" in captured.out

    quota_bytes = 20 * 1024**3
    await set_quota_async(ADMIN_EMAIL, quota_bytes)
    captured = capsys.readouterr()
    assert (
        f"Set storage quota for '{ADMIN_EMAIL}' to {quota_bytes} bytes." in captured.out
    )

    await list_users_async()
    captured = capsys.readouterr()
    assert str(quota_bytes) in captured.out

    await set_quota_async(ADMIN_EMAIL, 0)
    captured = capsys.readouterr()
    assert "unlimited" in captured.out

    with pytest.raises(SystemExit) as exc_info:
        await set_quota_async(ADMIN_EMAIL, -1)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Invalid quota value" in captured.out

    with pytest.raises(SystemExit) as exc_info:
        await set_quota_async("missing@example.com", quota_bytes)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Failed to set quota:" in captured.out
