import asyncio
import hashlib
import logging
import os
import secrets
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from pathlib import Path

import aiofiles
import aiofiles.os

from supernote.server.utils.paths import parse_file_chunk_name

logger = logging.getLogger(__name__)


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

    def merge(self, other: "CleanupStats") -> None:
        """Merge stats from another cleanup operation."""
        self.files_removed += other.files_removed
        self.bytes_reclaimed += other.bytes_reclaimed


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
    async def cleanup_staging(self, ttl_seconds: float) -> CleanupStats:
        """Remove orphaned staging files older than ttl_seconds.

        Args:
            ttl_seconds: Maximum age in seconds before a staging file is considered abandoned.

        Returns:
            CleanupStats detailing files removed and bytes reclaimed.
        """

    @abstractmethod
    async def cleanup_chunks(
        self,
        bucket: str,
        ttl_seconds: float,
        chunk_parser: Callable[[str], str | None] | None = None,
    ) -> CleanupStats:
        """Remove abandoned multipart chunk files older than ttl_seconds.

        Args:
            bucket: Bucket name containing the chunks.
            ttl_seconds: Maximum age in seconds before an upload session is considered abandoned.
            chunk_parser: Optional callable mapping a chunk filename to its base object name.
                Defaults to standard multipart chunk wire parser.

        Returns:
            CleanupStats detailing files removed and bytes reclaimed.
        """


class LocalBlobStorage(BlobStorage):
    """Local filesystem implementation of Blob Storage.

    Path structure: <root>/<bucket>/<key[0:2]>/<key>
    """

    def __init__(self, storage_root: Path) -> None:
        """Create a local blob storage instance."""
        self.root = storage_root
        self.root.mkdir(parents=True, exist_ok=True)

    def _get_path(self, bucket: str, key: str) -> Path:
        """Get physical path to the blob."""
        # Clean inputs to prevent traversal
        clean_bucket = Path(bucket).name
        clean_key = Path(key).name
        prefix = clean_key[:2] if len(clean_key) >= 2 else "misc"
        return self.root / clean_bucket / prefix / clean_key

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
                chunk_size = 8192
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

        # Compute MD5 and size
        md5_hasher = hashlib.md5()
        read_size = 0
        async with aiofiles.open(path, "rb") as f:
            while True:
                chunk = await f.read(8192)
                if not chunk:
                    break
                md5_hasher.update(chunk)
                read_size += len(chunk)

        if read_size != stat.st_size:
            # This could happen if file was modified during read
            raise ValueError(
                f"File size changed during read: metadata={stat.st_size}, read={read_size}"
            )

        return BlobMetadata(size=stat.st_size, content_md5=md5_hasher.hexdigest())

    def get_blob_path(self, bucket: str, key: str) -> Path:
        """Get physical path to the blob."""
        return self._get_path(bucket, key)

    async def cleanup_staging(self, ttl_seconds: float) -> CleanupStats:
        """Remove orphaned staging files older than ttl_seconds."""
        temp_dir = self.root / "temp"
        if not await aiofiles.os.path.exists(temp_dir):
            return CleanupStats()

        return await asyncio.to_thread(
            self._cleanup_staging_sync, temp_dir, ttl_seconds
        )

    def _cleanup_staging_sync(self, temp_dir: Path, ttl_seconds: float) -> CleanupStats:
        stats = CleanupStats()
        now = time.time()
        try:
            with os.scandir(temp_dir) as entries:
                for entry in entries:
                    if not entry.name.endswith(".tmp") or not entry.is_file():
                        continue
                    try:
                        stat = entry.stat()
                        if now - stat.st_mtime >= ttl_seconds:
                            os.remove(entry.path)
                            stats.files_removed += 1
                            stats.bytes_reclaimed += stat.st_size
                    except FileNotFoundError:
                        continue
                    except OSError as e:
                        logger.warning(
                            f"Failed to remove staging file {entry.path}: {e}"
                        )
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning(f"Failed to scan temp staging directory {temp_dir}: {e}")
        return stats

    async def cleanup_chunks(
        self,
        bucket: str,
        ttl_seconds: float,
        chunk_parser: Callable[[str], str | None] | None = None,
    ) -> CleanupStats:
        """Remove abandoned multipart chunk files older than ttl_seconds."""
        clean_bucket = Path(bucket).name
        if not clean_bucket or clean_bucket in (".", ".."):
            return CleanupStats()

        bucket_dir = self.root / clean_bucket
        if not (
            await aiofiles.os.path.exists(bucket_dir)
            and await aiofiles.os.path.isdir(bucket_dir)
        ):
            return CleanupStats()

        parser = chunk_parser or parse_file_chunk_name
        return await asyncio.to_thread(
            self._cleanup_chunks_sync, bucket_dir, ttl_seconds, parser
        )

    def _cleanup_chunks_sync(
        self,
        bucket_dir: Path,
        ttl_seconds: float,
        chunk_parser: Callable[[str], str | None],
    ) -> CleanupStats:
        stats = CleanupStats()
        if not bucket_dir.is_dir():
            return stats

        now = time.time()
        chunks_by_object: dict[str, list[tuple[Path, float, int]]] = {}

        try:
            for root, _, files in os.walk(bucket_dir):
                for filename in files:
                    object_name = chunk_parser(filename)
                    if not object_name:
                        continue
                    file_path = Path(root) / filename
                    try:
                        stat = file_path.stat()
                        chunks_by_object.setdefault(object_name, []).append(
                            (file_path, stat.st_mtime, stat.st_size)
                        )
                    except FileNotFoundError:
                        continue
                    except OSError as e:
                        logger.warning(f"Failed to stat chunk file {file_path}: {e}")
        except OSError as e:
            logger.warning(f"Failed to scan bucket directory {bucket_dir}: {e}")
            return stats

        for parts in chunks_by_object.values():
            if not parts:
                continue
            latest_mtime = max(mtime for _, mtime, _ in parts)
            if now - latest_mtime < ttl_seconds:
                continue

            for file_path, _, size in parts:
                try:
                    os.remove(file_path)
                    stats.files_removed += 1
                    stats.bytes_reclaimed += size
                except FileNotFoundError:
                    continue
                except OSError as e:
                    logger.warning(f"Failed to remove abandoned chunk {file_path}: {e}")

        return stats
