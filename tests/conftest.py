"""Root pytest configuration and common fixtures."""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def test_data_dir() -> Path:
    """Return the path to the test data directory."""
    return Path("tests/testdata")


@pytest.fixture(scope="session")
def test_note_path(test_data_dir: Path) -> Path:
    """Return the path to the real test note file 20251207_221454.note."""
    return test_data_dir / "20251207_221454.note"
