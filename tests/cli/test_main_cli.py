"""Tests for supernote.cli.main."""

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest

from supernote.cli.main import main


def test_main_help(capsys):
    with patch.object(sys, "argv", ["supernote", "--help"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "Supernote toolkit" in captured.out


def test_main_no_command(capsys):
    with patch.object(sys, "argv", ["supernote"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Supernote toolkit" in captured.out


def test_main_dispatch_success(capsys):
    with patch.object(sys, "argv", ["supernote", "analyze", "--help"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "usage: supernote analyze" in captured.out


def test_main_missing_dependency_error(capsys):
    original_import = importlib.import_module

    def mock_import(name, package=None):
        if name in (".admin", ".client"):
            raise ImportError("No module named 'fake_dep'")
        return original_import(name, package=package)

    with patch("importlib.import_module", side_effect=mock_import):
        with patch.object(sys, "argv", ["supernote", "admin"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Command 'admin' failed to load due to missing dependencies" in captured.out
    assert "pip install 'supernote[client]'" in captured.out


def test_main_missing_dependency_error_non_admin(capsys):
    original_import = importlib.import_module

    def mock_import(name, package=None):
        if name == ".server":
            raise ModuleNotFoundError("No module named 'sqlalchemy'")
        return original_import(name, package=package)

    with patch("importlib.import_module", side_effect=mock_import):
        with patch.object(sys, "argv", ["supernote", "server"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Command 'server' failed to load due to missing dependencies" in captured.out
    assert "pip install 'supernote[server]'" in captured.out


def test_main_no_func_attr(capsys):
    with patch("argparse.ArgumentParser.parse_args") as mock_parse:
        mock_args = MagicMock()
        mock_args.command = "custom"
        del mock_args.func  # ensure no func attribute
        mock_parse.return_value = mock_args

        with patch.object(sys, "argv", ["supernote"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
