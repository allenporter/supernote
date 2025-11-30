import pytest
from unittest.mock import patch
from pathlib import Path


@pytest.fixture(autouse=True)
def mock_storage(tmp_path: Path):
    storage_root = tmp_path / "storage"
    temp_root = tmp_path / "storage" / "temp"
    storage_root.mkdir(parents=True)
    temp_root.mkdir(parents=True, exist_ok=True)

    # Create default folders
    (storage_root / "Note").mkdir()
    (storage_root / "Document").mkdir()
    (storage_root / "EXPORT").mkdir()

    with (
        patch("supernote.server.config.STORAGE_DIR", str(storage_root)),
        patch("supernote.server.config.TRACE_LOG_FILE", str(tmp_path / "trace.log")),
    ):
        yield storage_root
