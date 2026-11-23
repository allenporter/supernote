"""Tests for supernote.cli.main."""

import argparse
import importlib
import sys
from unittest.mock import patch

import pytest

from supernote.cli.main import main


def test_main_help(capsys: pytest.CaptureFixture[str]) -> None:
    with (
        patch.object(sys, "argv", ["supernote", "--help"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "Supernote toolkit" in captured.out


def test_main_no_command(capsys: pytest.CaptureFixture[str]) -> None:
    with (
        patch.object(sys, "argv", ["supernote"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Supernote toolkit" in captured.out


def test_main_dispatch_success(capsys: pytest.CaptureFixture[str]) -> None:
    with (
        patch.object(sys, "argv", ["supernote", "analyze", "--help"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "usage: supernote analyze" in captured.out


def test_main_missing_dependency_error(capsys: pytest.CaptureFixture[str]) -> None:
    original_import = importlib.import_module

    def fake_import(name: str, package: str | None = None) -> object:
        if name in (".admin", ".client"):
            raise ImportError("No module named 'fake_dep'")
        return original_import(name, package=package)

    with (
        patch.object(importlib, "import_module", fake_import),
        patch.object(sys, "argv", ["supernote", "admin"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Command 'admin' failed to load due to missing dependencies" in captured.out
    assert "pip install 'supernote[client]'" in captured.out


def test_main_missing_dependency_error_non_admin(
    capsys: pytest.CaptureFixture[str],
) -> None:
    original_import = importlib.import_module

    def fake_import(name: str, package: str | None = None) -> object:
        if name == ".server":
            raise ModuleNotFoundError("No module named 'sqlalchemy'")
        return original_import(name, package=package)

    with (
        patch.object(importlib, "import_module", fake_import),
        patch.object(sys, "argv", ["supernote", "server"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Command 'server' failed to load due to missing dependencies" in captured.out
    assert "pip install 'supernote[server]'" in captured.out


def test_main_no_func_attr(capsys: pytest.CaptureFixture[str]) -> None:
    with (
        patch.object(
            argparse.ArgumentParser,
            "parse_args",
            lambda self: argparse.Namespace(command="custom"),
        ),
        patch.object(sys, "argv", ["supernote"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()
    assert exc_info.value.code == 1
