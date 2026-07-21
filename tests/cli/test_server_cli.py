"""Tests for supernote.cli.server."""

import argparse
import os
import sys
from unittest.mock import patch

import pytest

from supernote.cli.server import add_parser, main, serve_run


def test_serve_run_standard():
    args = argparse.Namespace(ephemeral=False, config_dir=None)
    with patch("supernote.server.app.run") as mock_run:
        serve_run(args)
        mock_run.assert_called_once_with(args)


def test_serve_run_ephemeral(capsys):
    args = argparse.Namespace(ephemeral=True, config_dir=None)
    # Clear env vars if set to test defaults
    os.environ.pop("SUPERNOTE_PORT", None)
    os.environ.pop("SUPERNOTE_HOST", None)

    with patch("supernote.server.app.run") as mock_run:
        serve_run(args)
        mock_run.assert_called_once_with(args)
        assert os.environ.get("SUPERNOTE_EPHEMERAL") == "true"
        assert os.environ.get("SUPERNOTE_PORT") == "8080"
        assert os.environ.get("SUPERNOTE_HOST") == "127.0.0.1"
        assert "SUPERNOTE_STORAGE_DIR" in os.environ

    captured = capsys.readouterr()
    assert "Using ephemeral mode with storage directory:" in captured.out
    assert "Created default user: debug@example.com / password" in captured.out


def test_add_parser_and_parse_args():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    parsed = parser.parse_args(
        ["serve", "--config-dir", "/tmp/myconfig", "--ephemeral"]
    )
    assert parsed.command == "serve"
    assert parsed.config_dir == "/tmp/myconfig"
    assert parsed.ephemeral is True
    assert parsed.func == serve_run


def test_server_main_help(capsys):
    with patch.object(sys, "argv", ["supernote-server", "--help"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "Supernote Server CLI" in captured.out


def test_server_main_no_subcommand(capsys):
    with patch.object(sys, "argv", ["supernote-server"]):
        main()
    captured = capsys.readouterr()
    assert "Supernote Server CLI" in captured.out


def test_server_main_run_command():
    with patch.object(sys, "argv", ["supernote-server", "serve"]):
        with patch("supernote.server.app.run") as mock_run:
            main()
            mock_run.assert_called_once()
