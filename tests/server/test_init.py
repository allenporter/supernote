"""Tests for supernote.server package initialization."""

import subprocess
import sys

import supernote.server


def test_server_package_does_not_eagerly_import_app() -> None:
    """Importing supernote.server or lightweight submodules should not eagerly load app.py."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys, supernote.server.socket_auth; "
                "assert 'supernote.server.app' not in sys.modules; "
                "assert 'sqlalchemy' not in sys.modules"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "app" in supernote.server.__all__
