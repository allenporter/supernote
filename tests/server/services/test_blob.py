import hashlib
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from supernote.server.services.blob import LocalBlobStorage


async def test_put_get_blob(tmp_path: Path) -> None:
    storage = LocalBlobStorage(tmp_path)
    bucket = "test-bucket"
    key = "test-key-123"
    content = b"Hello World"
    md5 = hashlib.md5(content).hexdigest()

    # Put
    metadata = await storage.put(bucket, key, content)
    assert metadata.size == len(content)
    assert metadata.content_md5 == md5

    # Exists
    assert await storage.exists(bucket, key)
    assert not await storage.exists(bucket, "missing-key")

    # Get
    chunks = []
    async for chunk in storage.get(bucket, key):
        chunks.append(chunk)
    read_content = b"".join(chunks)
    assert read_content == content

    # Check physical path
    path = storage.get_blob_path(bucket, key)
    assert path.exists()
    assert path.read_bytes() == content


async def test_put_stream(tmp_path: Path) -> None:
    storage = LocalBlobStorage(tmp_path)
    bucket = "test-bucket"
    key = "stream-key"

    async def data_stream() -> AsyncGenerator[bytes, None]:
        yield b"Part1"
        yield b"Part2"

    full_content = b"Part1Part2"
    md5 = hashlib.md5(full_content).hexdigest()

    # Put Stream
    metadata = await storage.put(bucket, key, data_stream())
    assert metadata.size == len(full_content)
    assert metadata.content_md5 == md5

    # Verify
    assert await storage.exists(bucket, key)


async def test_delete_blob(tmp_path: Path) -> None:
    storage = LocalBlobStorage(tmp_path)
    bucket = "test-bucket"
    key = "del-key"
    content = b"Delete Me"

    await storage.put(bucket, key, content)
    assert await storage.exists(bucket, key)

    await storage.delete(bucket, key)
    assert not await storage.exists(bucket, key)
    assert not storage.get_blob_path(bucket, key).exists()


async def test_isolation(tmp_path: Path) -> None:
    """Verify different keys store separately even if content is same."""
    storage = LocalBlobStorage(tmp_path)
    bucket = "test-bucket"
    content = b"Same Content"

    key1 = "key-1"
    key2 = "key-2"

    await storage.put(bucket, key1, content)
    await storage.put(bucket, key2, content)

    path1 = storage.get_blob_path(bucket, key1)
    path2 = storage.get_blob_path(bucket, key2)

    assert path1 != path2
    assert path1.exists()
    assert path2.exists()


async def test_get_metadata_no_md5(tmp_path: Path) -> None:
    """Verify get_metadata returns size without MD5."""
    storage = LocalBlobStorage(tmp_path)
    bucket = "test-bucket"
    key = "meta-blob"
    content = b"1234567890"

    await storage.put(bucket, key, content)

    metadata = await storage.get_metadata(bucket, key, include_md5=False)
    assert metadata.size == 10
    assert metadata.content_md5 is None


async def test_get_metadata_with_md5(tmp_path: Path) -> None:
    """Verify get_metadata returns size and MD5."""
    storage = LocalBlobStorage(tmp_path)
    bucket = "test-bucket"
    key = "meta-md5-blob"
    content = b"Hello, World!"

    await storage.put(bucket, key, content)

    metadata = await storage.get_metadata(bucket, key, include_md5=True)
    assert metadata.size == 13
    assert metadata.content_md5 == hashlib.md5(content).hexdigest()


async def test_get_metadata_not_found(tmp_path: Path) -> None:
    """Verify get_metadata raises error for missing blob."""
    storage = LocalBlobStorage(tmp_path)
    bucket = "test-bucket"
    key = "missing-blob"

    with pytest.raises(FileNotFoundError):
        await storage.get_metadata(bucket, key)


async def test_get_range(tmp_path: Path) -> None:
    """Verify get with range returns correct bytes."""
    storage = LocalBlobStorage(tmp_path)
    bucket = "test-bucket"
    key = "range-blob"
    content = b"0123456789"

    await storage.put(bucket, key, content)

    # Read first 5 bytes
    chunks = []
    async for chunk in storage.get(bucket, key, start=0, end=4):
        chunks.append(chunk)
    assert b"".join(chunks) == b"01234"

    # Read middle
    chunks = []
    async for chunk in storage.get(bucket, key, start=3, end=6):
        chunks.append(chunk)
    assert b"".join(chunks) == b"3456"

    # Read end
    chunks = []
    async for chunk in storage.get(bucket, key, start=7, end=9):
        chunks.append(chunk)
    assert b"".join(chunks) == b"789"


async def test_get_range_large(tmp_path: Path) -> None:
    """Verify get with range on larger content (crossing chunk boundaries)."""
    storage = LocalBlobStorage(tmp_path)
    bucket = "test-bucket"
    key = "range-large-blob"
    # Create content larger than 8192 (default chunk size)
    content = b"x" * 10000 + b"y" * 10000

    await storage.put(bucket, key, content)

    # Read across boundary (e.g. 9998 range to 10002)
    chunks = []
    async for chunk in storage.get(bucket, key, start=9998, end=10002):
        chunks.append(chunk)
    data = b"".join(chunks)
    assert len(data) == 5
    assert data == b"xxyyy"
