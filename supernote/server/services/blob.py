"""Content-addressable blob storage interface and local filesystem implementation.

Defines the abstract `BlobStorage` interface and `LocalBlobStorage`, which stores
immutable user files (`USER_DATA_BUCKET`) and derived cache artifacts (`CACHE_BUCKET`)
under `<storage_dir>/<bucket>/<key[:2]>/<key>`. Writes are staged to `<storage_dir>/temp`
and atomically renamed on completion, while expired `.tmp` staging files and abandoned
`.part.N` multipart upload chunks are periodically reclaimed.

Used by `supernote.server.services.file.FileService`, `supernote.server.routes.oss`,
and `supernote.server.services.integrity.IntegrityService`.
"""

import asyncio
import hashlib
import logging
import os
import secrets
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path

import aiofiles
import aiofiles.os

from supernote.server.utils.paths import parse_file_chunk_name

logger = logging.getLogger(__name__)

TEMP_FILE_TTL_SECONDS = 86400.0  # 24 hours
CLEANUP_INTERVAL_SECONDS = 3600.0  # Run opportunistic cleanup at most once per hour
STREAM_CHUNK_SIZE = 1024 * 1024  # 1 MB chunks to minimize aiofiles thread-pool hops


def _compute_file_md5(path: Path) -> str:
    """Return the MD5 hex digest of a file on disk."""
    with path.open("rb") as f:
        return hashlib.file_digest(f, "md5").hexdigest()


@dataclass
class BlobMetadata:
    """Metadata for a blob."""

    content_type: str | None = None
    content_md5: str | None = None
    size: int = 0


@dataclass
class CleanupStats:
    """Statistics for storage cleanup operations."""

    files_removed: int = 0
    bytes_reclaimed: int = 0


class BlobStorage(ABC):
    """Interface for Key-Value Blob Storage."""

    @abstractmethod
    async def put(
        self, bucket: str, key: str, stream: AsyncGenerator[bytes] | bytes
    ) -> BlobMetadata:
        """Write blob to storage."""

    @abstractmethod
    def get(
        self, bucket: str, key: str, start: int | None = None, end: int | None = None
    ) -> AsyncGenerator[bytes]:
        """Read blob content.

        Args:
            bucket: Bucket name.
            key: Blob key.
            start: Start byte position (inclusive).
            end: End byte position (inclusive).
        """

    @abstractmethod
    async def delete(self, bucket: str, key: str) -> None:
        """Delete blob."""

    @abstractmethod
    async def exists(self, bucket: str, key: str) -> bool:
        """Check if blob exists."""

    @abstractmethod
    async def get_metadata(
        self, bucket: str, key: str, include_md5: bool = False
    ) -> BlobMetadata:
        """Get metadata for a blob.

        Args:
            bucket: Bucket name.
            key: Blob key.
            include_md5: If True, compute and return MD5 checksum.

        Returns:
            BlobMetadata with size and optional content_md5.
        """

    @abstractmethod
    def get_blob_path(self, bucket: str, key: str) -> Path:
        """Get physical path to the blob (optional, useful for serving files)."""

    @abstractmethod
    async def list_blobs(self, bucket: str) -> list[str]:
        """Return sorted logical keys of all stored blobs in the given bucket.

        Excludes temporary staging files and unmerged multipart `.part.N` chunks.
        """

    @abstractmethod
    async def cleanup(self) -> CleanupStats:
        """Remove expired temporary staging files and abandoned upload chunks."""


class LocalBlobStorage(BlobStorage):
    """Local filesystem implementation of Blob Storage.

    Path structure: <root>/<bucket>/<key[0:2]>/<key>
    """

    def __init__(self, storage_root: Path) -> None:
        """Create a local blob storage instance."""
        self.root = storage_root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._last_cleanup = time.time()

    def _get_path(self, bucket: str, key: str) -> Path:
        """Get physical path to the blob."""
        if len(key) < 3:
            raise ValueError(f"Invalid blob path: {bucket}/{key}")
        clean_bucket = Path(bucket).name
        prefix_dir = (self.root / clean_bucket / key[:2]).resolve()
        blob_path = (prefix_dir / key).resolve()
        if (
            not prefix_dir.is_relative_to(self.root)
            or len(prefix_dir.relative_to(self.root).parts) != 2
            or not blob_path.is_relative_to(prefix_dir)
            or blob_path == prefix_dir
            or blob_path != prefix_dir / key
        ):
            raise ValueError(f"Invalid blob path: {bucket}/{key}")
        return blob_path

    async def put(
        self, bucket: str, key: str, stream: AsyncGenerator[bytes] | bytes
    ) -> BlobMetadata:
        """Write blob to storage."""
        blob_path = self._get_path(bucket, key)
        await aiofiles.os.makedirs(blob_path.parent, exist_ok=True)

        # Write to temp file for atomicity
        temp_dir = self.root / "temp"
        await aiofiles.os.makedirs(temp_dir, exist_ok=True)
        temp_path = temp_dir / f"{secrets.token_hex(8)}.tmp"

        total_size = 0
        md5_hasher = hashlib.md5()

        try:
            async with aiofiles.open(temp_path, "wb") as f:
                if isinstance(stream, bytes):
                    total_size = len(stream)
                    md5_hasher.update(stream)
                    await f.write(stream)
                else:
                    async for chunk in stream:
                        total_size += len(chunk)
                        md5_hasher.update(chunk)
                        await f.write(chunk)

            # Move to final location
            await aiofiles.os.rename(temp_path, blob_path)

            if time.time() - self._last_cleanup >= CLEANUP_INTERVAL_SECONDS:
                await self.cleanup()

            return BlobMetadata(
                content_md5=md5_hasher.hexdigest(),
                size=total_size,
            )

        except Exception:
            if await aiofiles.os.path.exists(temp_path):
                await aiofiles.os.remove(temp_path)
            raise

    async def get(
        self, bucket: str, key: str, start: int | None = None, end: int | None = None
    ) -> AsyncGenerator[bytes]:
        """Read blob content."""
        path = self._get_path(bucket, key)
        if not await aiofiles.os.path.exists(path):
            raise FileNotFoundError(f"Blob {bucket}/{key} not found")

        bytes_remaining = None
        if end is not None:
            if start is None:
                start = 0
            bytes_remaining = end - start + 1

        async with aiofiles.open(path, "rb") as f:
            if start is not None and start > 0:
                await f.seek(start)

            while True:
                chunk_size = STREAM_CHUNK_SIZE
                if bytes_remaining is not None:
                    if bytes_remaining <= 0:
                        break
                    chunk_size = min(chunk_size, bytes_remaining)

                chunk = await f.read(chunk_size)
                if not chunk:
                    break

                if bytes_remaining is not None:
                    bytes_remaining -= len(chunk)

                yield chunk

    async def delete(self, bucket: str, key: str) -> None:
        """Delete blob."""
        path = self._get_path(bucket, key)
        if await aiofiles.os.path.exists(path):
            await aiofiles.os.remove(path)

    async def exists(self, bucket: str, key: str) -> bool:
        """Check if blob exists."""
        return bool(await aiofiles.os.path.exists(self._get_path(bucket, key)))

    async def get_metadata(
        self, bucket: str, key: str, include_md5: bool = False
    ) -> BlobMetadata:
        """Get metadata for a blob."""
        path = self._get_path(bucket, key)
        if not await aiofiles.os.path.exists(path):
            raise FileNotFoundError(f"Blob {bucket}/{key} not found")

        stat = await aiofiles.os.stat(path)

        if not include_md5:
            return BlobMetadata(size=stat.st_size)

        content_md5 = await asyncio.to_thread(_compute_file_md5, path)
        return BlobMetadata(size=stat.st_size, content_md5=content_md5)

    def get_blob_path(self, bucket: str, key: str) -> Path:
        """Get physical path to the blob."""
        return self._get_path(bucket, key)

    async def list_blobs(self, bucket: str) -> list[str]:
        """Return sorted logical keys of all stored blobs in the given bucket."""
        return await asyncio.to_thread(self._list_blobs_sync, bucket)

    def _list_blobs_sync(self, bucket: str) -> list[str]:
        clean_bucket = Path(bucket).name
        bucket_dir = (self.root / clean_bucket).resolve()
        if not bucket_dir.is_relative_to(self.root) or not bucket_dir.is_dir():
            return []

        keys: list[str] = []
        for shard_dir in bucket_dir.iterdir():
            if not shard_dir.is_dir():
                continue
            for root, _, files in os.walk(shard_dir):
                root_path = Path(root)
                for filename in files:
                    if parse_file_chunk_name(filename) is not None:
                        continue
                    file_path = root_path / filename
                    keys.append(file_path.relative_to(shard_dir).as_posix())
        keys.sort()
        return keys

    async def cleanup(self) -> CleanupStats:
        """Remove expired temporary staging files and abandoned upload chunks."""
        self._last_cleanup = time.time()
        return await asyncio.to_thread(self._cleanup_sync)

    def _cleanup_sync(self) -> CleanupStats:
        stats = CleanupStats()
        now = time.time()
        temp_dir = self.root / "temp"

        if temp_dir.is_dir():
            for file_path in temp_dir.iterdir():
                if file_path.name.endswith(".tmp") and file_path.is_file():
                    self._remove_if_expired(file_path, now, stats)

        # Group individual `.part.N` chunk files into chunk sets keyed by their
        # target upload `(root_path, base_name)` so staleness is evaluated across
        # the upload as a whole rather than per part file.
        chunk_sets: dict[tuple[Path, str], list[Path]] = defaultdict(list)
        for root, _, files in os.walk(self.root):
            root_path = Path(root)
            if root_path == temp_dir or temp_dir in root_path.parents:
                continue
            for filename in files:
                base_name = parse_file_chunk_name(filename)
                if base_name is not None:
                    chunk_sets[(root_path, base_name)].append(root_path / filename)

        for chunk_paths in chunk_sets.values():
            self._remove_chunk_set_if_expired(chunk_paths, now, stats)

        return stats

    @staticmethod
    def _remove_chunk_set_if_expired(
        chunk_paths: list[Path], now: float, stats: CleanupStats
    ) -> None:
        """Remove a multipart upload's chunk set only when its newest chunk has expired.

        A single multipart upload produces multiple `.part.N` chunk files that
        together form a chunk set for one target blob. Evaluating expiration by
        the most recently modified chunk (`newest_mtime`) keeps slow or resumed
        uploads intact while still reclaiming all chunks of abandoned uploads.
        """
        chunk_stats: list[tuple[Path, os.stat_result]] = []
        for path in chunk_paths:
            try:
                chunk_stats.append((path, path.stat()))
            except FileNotFoundError:
                continue
            except OSError as err:
                logger.warning("Failed to stat chunk file %s: %s", path, err)
                return

        if not chunk_stats:
            return

        newest_mtime = max(st.st_mtime for _, st in chunk_stats)
        if now - newest_mtime < TEMP_FILE_TTL_SECONDS:
            return

        for path, st in chunk_stats:
            try:
                path.unlink()
                stats.files_removed += 1
                stats.bytes_reclaimed += st.st_size
            except FileNotFoundError:
                pass
            except OSError as err:
                logger.warning("Failed to remove expired chunk file %s: %s", path, err)

    @staticmethod
    def _remove_if_expired(file_path: Path, now: float, stats: CleanupStats) -> None:
        try:
            stat = file_path.stat()
            if now - stat.st_mtime >= TEMP_FILE_TTL_SECONDS:
                file_path.unlink()
                stats.files_removed += 1
                stats.bytes_reclaimed += stat.st_size
        except FileNotFoundError:
            pass
        except OSError as err:
            logger.warning("Failed to remove expired file %s: %s", file_path, err)
