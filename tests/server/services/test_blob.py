import hashlib
import os
import time
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from supernote.server.services.blob import CleanupStats, LocalBlobStorage


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

    async def data_stream() -> AsyncGenerator[bytes]:
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


async def test_cleanup_staging(tmp_path: Path) -> None:
    """Verify cleanup_staging removes only staging files older than TTL."""
    storage = LocalBlobStorage(tmp_path)
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    now = time.time()
    stale_file = temp_dir / "stale.tmp"
    stale_file.write_bytes(b"stale staging data")
    os.utime(stale_file, (now - 5000, now - 5000))

    fresh_file = temp_dir / "fresh.tmp"
    fresh_file.write_bytes(b"fresh staging data")
    os.utime(fresh_file, (now - 100, now - 100))

    non_tmp_file = temp_dir / "other.log"
    non_tmp_file.write_bytes(b"log data")
    os.utime(non_tmp_file, (now - 5000, now - 5000))

    stats = await storage.cleanup_staging(ttl_seconds=3600)
    assert stats.files_removed == 1
    assert stats.bytes_reclaimed == len(b"stale staging data")
    assert not stale_file.exists()
    assert fresh_file.exists()
    assert non_tmp_file.exists()


async def test_cleanup_chunks_expiration(tmp_path: Path) -> None:
    """Verify cleanup_chunks prunes chunks older than ttl_seconds while preserving recent ones."""
    storage = LocalBlobStorage(tmp_path)
    bucket = "user-data"

    # Put chunks for abandoned upload A
    await storage.put(bucket, "abandoned.note.part.1", b"chunk a1")
    await storage.put(bucket, "abandoned.note.part.2", b"chunk a2")
    path_a1 = storage.get_blob_path(bucket, "abandoned.note.part.1")
    path_a2 = storage.get_blob_path(bucket, "abandoned.note.part.2")

    # Put chunks for upload B (part 1 old, part 2 recent)
    await storage.put(bucket, "mixed.note.part.1", b"chunk b1")
    await storage.put(bucket, "mixed.note.part.2", b"chunk b2")
    path_b1 = storage.get_blob_path(bucket, "mixed.note.part.1")
    path_b2 = storage.get_blob_path(bucket, "mixed.note.part.2")

    # Put normal file
    await storage.put(bucket, "normal.note", b"normal file content")
    path_normal = storage.get_blob_path(bucket, "normal.note")

    now = time.time()
    # Abandoned upload A: both chunks old
    os.utime(path_a1, (now - 7200, now - 7200))
    os.utime(path_a2, (now - 7000, now - 7000))

    # Upload B: part 1 is old, but part 2 is recent (e.g. uploaded 10s ago)
    os.utime(path_b1, (now - 7200, now - 7200))
    os.utime(path_b2, (now - 10, now - 10))

    # Normal file is old
    os.utime(path_normal, (now - 7200, now - 7200))

    stats = await storage.cleanup_chunks(bucket, ttl_seconds=3600)

    # Chunks older than 3600s should be pruned (a1, a2, and b1)
    assert stats.files_removed == 3
    assert stats.bytes_reclaimed == len(b"chunk a1") + len(b"chunk a2") + len(
        b"chunk b1"
    )
    assert not path_a1.exists()
    assert not path_a2.exists()
    assert not path_b1.exists()

    # Recent chunk b2 must NOT be pruned
    assert path_b2.exists()

    # Normal file must NOT be pruned
    assert path_normal.exists()


async def test_cleanup_chunks_bucket_safety(tmp_path: Path) -> None:
    """Verify cleanup_chunks safely handles empty, root, and non-directory bucket strings."""
    storage = LocalBlobStorage(tmp_path)
    stats_empty = await storage.cleanup_chunks("", 3600)
    assert stats_empty == CleanupStats(files_removed=0, bytes_reclaimed=0)

    stats_slash = await storage.cleanup_chunks("/", 3600)
    assert stats_slash == CleanupStats(files_removed=0, bytes_reclaimed=0)

    stats_dots = await storage.cleanup_chunks("../..", 3600)
    assert stats_dots == CleanupStats(files_removed=0, bytes_reclaimed=0)

    # Non-existent bucket
    stats_missing = await storage.cleanup_chunks("nonexistent_bucket", 3600)
    assert stats_missing == CleanupStats(files_removed=0, bytes_reclaimed=0)


async def test_cleanup_chunks_custom_parser(tmp_path: Path) -> None:
    """Verify cleanup_chunks accepts a custom chunk parser callable."""
    storage = LocalBlobStorage(tmp_path)
    bucket = "custom-bucket"
    await storage.put(bucket, "doc-part-1.tmp", b"part1")
    path1 = storage.get_blob_path(bucket, "doc-part-1.tmp")
    now = time.time()
    os.utime(path1, (now - 5000, now - 5000))

    def custom_parser(name: str) -> str | None:
        if name.startswith("doc-part-"):
            return "doc"
        return None

    stats = await storage.cleanup_chunks(
        bucket, ttl_seconds=3600, chunk_parser=custom_parser
    )
    assert stats == CleanupStats(files_removed=1, bytes_reclaimed=len(b"part1"))
    assert not path1.exists()
