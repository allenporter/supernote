import hashlib
import os
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import patch

import pytest

from supernote.server.services.blob import (
    CLEANUP_INTERVAL_SECONDS,
    TEMP_FILE_TTL_SECONDS,
    CleanupStats,
    LocalBlobStorage,
)
from supernote.server.utils.paths import (
    get_conversion_pdf_path,
    get_page_png_path,
)


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


@pytest.mark.parametrize(
    ("bucket", "key"),
    [
        ("..", "valid-key"),
        (".", "valid-key"),
        ("", "valid-key"),
        ("test-bucket", ".."),
        ("test-bucket", "."),
        ("test-bucket", ""),
        ("test-bucket", "ab"),
        ("test-bucket", "foo/.."),
        ("test-bucket", "../foo"),
    ],
)
async def test_invalid_blob_path_rejected(
    tmp_path: Path, bucket: str, key: str
) -> None:
    """Verify invalid bucket or key names that do not resolve within the bucket dir raise ValueError."""
    storage = LocalBlobStorage(tmp_path)

    with pytest.raises(ValueError, match="Invalid blob path"):
        storage.get_blob_path(bucket, key)

    with pytest.raises(ValueError, match="Invalid blob path"):
        await storage.put(bucket, key, b"data")


async def test_storage_root_containment(tmp_path: Path) -> None:
    """Verify resolved blob paths are strictly contained within the storage root."""
    storage = LocalBlobStorage(tmp_path)
    bucket = "secure-bucket"
    key = "normal-key-abc"

    await storage.put(bucket, key, b"safe content")
    blob_path = storage.get_blob_path(bucket, key)

    assert blob_path.is_file()
    assert blob_path.is_relative_to(tmp_path.resolve())


async def test_cleanup_staging_and_chunks(tmp_path: Path) -> None:
    """Verify cleanup removes expired staging .tmp files and abandoned .part.N chunks while preserving fresh or normal files."""
    storage = LocalBlobStorage(tmp_path)
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    bucket = "user-data"

    now = time.time()
    expired_mtime = now - TEMP_FILE_TTL_SECONDS - 100
    fresh_mtime = now - 100

    # 1. Staging files in <root>/temp
    stale_tmp = temp_dir / "stale.tmp"
    stale_tmp.write_bytes(b"stale staging data")
    os.utime(stale_tmp, (expired_mtime, expired_mtime))

    fresh_tmp = temp_dir / "fresh.tmp"
    fresh_tmp.write_bytes(b"fresh staging data")
    os.utime(fresh_tmp, (fresh_mtime, fresh_mtime))

    non_tmp = temp_dir / "other.log"
    non_tmp.write_bytes(b"log data")
    os.utime(non_tmp, (expired_mtime, expired_mtime))

    # 2a. Active multipart upload (chunk 1 old, chunk 2 fresh -> entire set preserved)
    await storage.put(bucket, "active.note.part.1", b"chunk act1")
    await storage.put(bucket, "active.note.part.2", b"chunk act2")
    path_act1 = storage.get_blob_path(bucket, "active.note.part.1")
    path_act2 = storage.get_blob_path(bucket, "active.note.part.2")
    os.utime(path_act1, (expired_mtime, expired_mtime))
    os.utime(path_act2, (fresh_mtime, fresh_mtime))

    # 2b. Abandoned multipart upload (all chunks expired -> entire set removed)
    await storage.put(bucket, "abandoned.note.part.1", b"chunk a1")
    await storage.put(bucket, "abandoned.note.part.2", b"chunk a2")
    path_a1 = storage.get_blob_path(bucket, "abandoned.note.part.1")
    path_a2 = storage.get_blob_path(bucket, "abandoned.note.part.2")
    os.utime(path_a1, (expired_mtime, expired_mtime))
    os.utime(path_a2, (expired_mtime, expired_mtime))

    # 3. Normal blob (must never be removed even if old)
    await storage.put(bucket, "normal.note", b"normal file content")
    path_normal = storage.get_blob_path(bucket, "normal.note")
    os.utime(path_normal, (expired_mtime, expired_mtime))

    stats = await storage.cleanup()
    assert stats.files_removed == 3
    assert stats.bytes_reclaimed == (
        len(b"stale staging data") + len(b"chunk a1") + len(b"chunk a2")
    )
    assert not stale_tmp.exists()
    assert fresh_tmp.exists()
    assert non_tmp.exists()
    assert path_act1.exists()
    assert path_act2.exists()
    assert not path_a1.exists()
    assert not path_a2.exists()
    assert path_normal.exists()


async def test_put_triggers_opportunistic_cleanup(tmp_path: Path) -> None:
    """Verify put() opportunistically cleans up expired files when CLEANUP_INTERVAL_SECONDS has elapsed."""
    storage = LocalBlobStorage(tmp_path)
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    now = time.time()
    expired_mtime = now - TEMP_FILE_TTL_SECONDS - 100
    stale_tmp = temp_dir / "abandoned.tmp"
    stale_tmp.write_bytes(b"orphaned")
    os.utime(stale_tmp, (expired_mtime, expired_mtime))

    # Simulate CLEANUP_INTERVAL_SECONDS having elapsed since last cleanup
    storage._last_cleanup = now - CLEANUP_INTERVAL_SECONDS - 1

    await storage.put("user-data", "new.note", b"data")
    assert not stale_tmp.exists()


async def test_page_png_paths_for_different_files_do_not_collide(
    tmp_path: Path,
) -> None:
    """Verify two different files with the same page_id do not collide in LocalBlobStorage."""
    storage = LocalBlobStorage(tmp_path)
    bucket = "cache"
    shared_page_id = "P20260101120000"

    key_file_1 = get_page_png_path(file_id=101, page_id=shared_page_id)
    key_file_2 = get_page_png_path(file_id=202, page_id=shared_page_id)

    await storage.put(bucket, key_file_1, b"png-for-file-101")
    await storage.put(bucket, key_file_2, b"png-for-file-202")

    assert storage.get_blob_path(bucket, key_file_1) != storage.get_blob_path(
        bucket, key_file_2
    )
    assert storage.get_blob_path(bucket, key_file_1).read_bytes() == b"png-for-file-101"
    assert storage.get_blob_path(bucket, key_file_2).read_bytes() == b"png-for-file-202"


async def test_conversion_paths_for_different_users_do_not_collide(
    tmp_path: Path,
) -> None:
    """Verify conversion PDF keys for different users/files do not collide in LocalBlobStorage."""
    storage = LocalBlobStorage(tmp_path)
    bucket = "cache"
    shared_md5 = "d41d8cd98f00b204e9800998ecf8427e"

    pdf_user_1 = get_conversion_pdf_path(user_id=1, file_id=101, file_md5=shared_md5)
    pdf_user_2 = get_conversion_pdf_path(user_id=2, file_id=202, file_md5=shared_md5)
    assert storage.get_blob_path(bucket, pdf_user_1) != storage.get_blob_path(
        bucket, pdf_user_2
    )

    # Intra-shard '..' traversal within the same 2-character prefix must be rejected
    with pytest.raises(ValueError, match="Invalid blob path"):
        storage.get_blob_path(bucket, "101/pages/../../102/pages/victim.png")


async def test_list_blobs_returns_logical_keys_and_skips_chunks(
    tmp_path: Path,
) -> None:
    """Verify list_blobs enumerates logical keys across flat and nested buckets while skipping .part.N chunks."""
    storage = LocalBlobStorage(tmp_path)
    assert await storage.list_blobs("nonexistent-bucket") == []

    await storage.put("user-data", "blob_b.note", b"b")
    await storage.put("user-data", "blob_a.note", b"a")
    await storage.put("user-data", "upload.note.part.1", b"part1")

    assert await storage.list_blobs("user-data") == ["blob_a.note", "blob_b.note"]

    # Non-directory files directly under the bucket directory are ignored
    (tmp_path / "user-data" / "stray_top_level_file").write_bytes(b"ignored")
    assert await storage.list_blobs("user-data") == ["blob_a.note", "blob_b.note"]

    png_key = get_page_png_path(file_id=42, page_id="P1")
    pdf_key = get_conversion_pdf_path(user_id=7, file_id=42, file_md5="deadbeef")
    await storage.put("cache", png_key, b"png")
    await storage.put("cache", pdf_key, b"pdf")

    assert await storage.list_blobs("cache") == sorted([png_key, pdf_key])

    other_pdf_key = get_conversion_pdf_path(user_id=7, file_id=43, file_md5="deadbeef")
    await storage.put("cache", other_pdf_key, b"pdf")
    assert await storage.list_blobs("cache", "conversions/7/42/") == [pdf_key]
    assert await storage.list_blobs("cache", "42/") == [png_key]
    assert await storage.list_blobs("cache", "c") == sorted([pdf_key, other_pdf_key])
    assert await storage.list_blobs("cache", "conversions/8/") == []


async def test_put_stream_error_cleans_up_temp_file(tmp_path: Path) -> None:
    """Verify put() cleans up temporary staging file and re-raises when stream fails."""
    storage = LocalBlobStorage(tmp_path)

    async def failing_stream() -> AsyncGenerator[bytes]:
        yield b"partial data"
        raise RuntimeError("stream interrupted")

    with pytest.raises(RuntimeError, match="stream interrupted"):
        await storage.put("test-bucket", "failed-key", failing_stream())

    temp_dir = tmp_path / "temp"
    assert list(temp_dir.glob("*.tmp")) == []
    assert not await storage.exists("test-bucket", "failed-key")


async def test_get_not_found_and_open_start_range(tmp_path: Path) -> None:
    """Verify get() raises FileNotFoundError on missing blob and defaults start=0 when only end is given."""
    storage = LocalBlobStorage(tmp_path)

    with pytest.raises(FileNotFoundError):
        async for _ in storage.get("test-bucket", "missing-key"):
            pass

    await storage.put("test-bucket", "range-key", b"abcdef")
    chunks = [chunk async for chunk in storage.get("test-bucket", "range-key", end=2)]
    assert b"".join(chunks) == b"abc"


def test_cleanup_helpers_handle_missing_files_and_os_errors(tmp_path: Path) -> None:
    """Verify _remove_chunk_set_if_expired and _remove_if_expired tolerate disappearing files and OSErrors."""
    now = time.time()
    expired_mtime = now - TEMP_FILE_TTL_SECONDS - 100
    stats = CleanupStats()

    missing_path = tmp_path / "missing.tmp"
    LocalBlobStorage._remove_if_expired(missing_path, now, stats)
    LocalBlobStorage._remove_chunk_set_if_expired([missing_path], now, stats)
    assert stats.files_removed == 0

    tmp_file = tmp_path / "err.tmp"
    tmp_file.write_bytes(b"abc")
    os.utime(tmp_file, (expired_mtime, expired_mtime))

    with patch.object(Path, "unlink", side_effect=PermissionError("denied")):
        LocalBlobStorage._remove_if_expired(tmp_file, now, stats)
        LocalBlobStorage._remove_chunk_set_if_expired([tmp_file], now, stats)
    assert stats.files_removed == 0

    with patch.object(Path, "unlink", side_effect=FileNotFoundError):
        LocalBlobStorage._remove_chunk_set_if_expired([tmp_file], now, stats)
    assert stats.files_removed == 0

    with patch.object(Path, "stat", side_effect=PermissionError("stat denied")):
        LocalBlobStorage._remove_chunk_set_if_expired([tmp_file], now, stats)
    assert stats.files_removed == 0
