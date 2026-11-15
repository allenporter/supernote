"""Tests for supernote.cli.server."""

import argparse
import os
import sys

import pytest

from supernote.cli.server import add_parser, main, serve_run


def test_serve_run_standard(monkeypatch: pytest.MonkeyPatch) -> None:
    args = argparse.Namespace(ephemeral=False, config_dir=None)
    called_with: list[argparse.Namespace] = []
    monkeypatch.setattr("supernote.server.app.run", called_with.append)

    serve_run(args)
    assert called_with == [args]


def test_serve_run_ephemeral(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    args = argparse.Namespace(ephemeral=True, config_dir=None)
    monkeypatch.delenv("SUPERNOTE_PORT", raising=False)
    monkeypatch.delenv("SUPERNOTE_HOST", raising=False)
    monkeypatch.delenv("SUPERNOTE_EPHEMERAL", raising=False)
    monkeypatch.delenv("SUPERNOTE_STORAGE_DIR", raising=False)

    called_with: list[argparse.Namespace] = []

    def check_env(parsed_args: argparse.Namespace) -> None:
        called_with.append(parsed_args)
        assert os.environ.get("SUPERNOTE_EPHEMERAL") == "true"
        assert os.environ.get("SUPERNOTE_PORT") == "8080"
        assert os.environ.get("SUPERNOTE_HOST") == "127.0.0.1"
        assert "SUPERNOTE_STORAGE_DIR" in os.environ

    monkeypatch.setattr("supernote.server.app.run", check_env)
    serve_run(args)
    assert called_with == [args]

    # Assert that environment variables were restored after serve_run completed
    assert os.environ.get("SUPERNOTE_EPHEMERAL") is None
    assert os.environ.get("SUPERNOTE_STORAGE_DIR") is None

    captured = capsys.readouterr()
    assert "Using ephemeral mode with storage directory:" in captured.out
    assert "Created default user: debug@example.com / password" in captured.out


def test_add_parser_and_parse_args() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    parsed = parser.parse_args(
        [
            "serve",
            "--config-dir",
            "/tmp/myconfig",
            "--ephemeral",
        ]
    )
    assert parsed.command == "serve"
    assert parsed.config_dir == "/tmp/myconfig"
    assert parsed.ephemeral is True
    assert parsed.func == serve_run


def test_server_main_help(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["supernote-server", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "Supernote Server CLI" in captured.out


def test_server_main_no_subcommand(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["supernote-server"])
    main()
    captured = capsys.readouterr()
    assert "Supernote Server CLI" in captured.out


def test_server_main_run_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["supernote-server", "serve"])
    called_with: list[argparse.Namespace] = []
    monkeypatch.setattr("supernote.server.app.run", called_with.append)

    main()
    assert len(called_with) == 1
