
import hashlib
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from supernote.server.services.blob import LocalBlobStorage


@pytest.mark.asyncio
async def test_write_read_blob(tmp_path: Path) -> None:
    storage = LocalBlobStorage(tmp_path)
    
    content = b"Hello World"
    md5 = hashlib.md5(content).hexdigest()
    
    # Write
    written_md5 = await storage.write_blob(content)
    assert written_md5 == md5
    
    # Check physical existence (white-box)
    path = storage.get_blob_path(md5)
    assert path.exists()
    assert path.read_bytes() == content
    
    # Read
    read_content = await storage.read_blob(md5)
    assert read_content == content
    
    # Exists check
    assert await storage.exists(md5) is True
    assert await storage.exists("invalid_md5") is False

@pytest.mark.asyncio
async def test_write_stream_blob(tmp_path: Path) -> None:
    storage = LocalBlobStorage(tmp_path)
    
    # Create a stream generator
    async def data_stream() -> AsyncGenerator[bytes, None]:
        yield b"Part1"
        yield b"Part2"
        
    full_content = b"Part1Part2"
    md5 = hashlib.md5(full_content).hexdigest()
    
    # Write stream
    written_md5 = await storage.write_stream(data_stream())
    assert written_md5 == md5
    
    # Read back
    read_content = await storage.read_blob(md5)
    assert read_content == full_content

@pytest.mark.asyncio
async def test_deduplication(tmp_path: Path) -> None:
    storage = LocalBlobStorage(tmp_path)
    content = b"Duplicate Content"
    
    md5_1 = await storage.write_blob(content)
    file_stat_1 = storage.get_blob_path(md5_1).stat()
    
    md5_2 = await storage.write_blob(content)
    file_stat_2 = storage.get_blob_path(md5_2).stat()
    
    assert md5_1 == md5_2
    # Should be the same file/inode/creation time essentially
    assert file_stat_1.st_ino == file_stat_2.st_ino
