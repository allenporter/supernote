import asyncio
import hashlib
import logging
import os
import shutil
from pathlib import Path
from typing import IO, Awaitable, Callable, Generator

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(self, storage_root: Path, temp_root: Path):
        self.storage_root = storage_root
        self.temp_root = temp_root
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.temp_root.mkdir(parents=True, exist_ok=True)

    def get_file_md5(self, path: Path) -> str:
        """Calculate MD5 of a file."""
        hash_md5 = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def get_dir_size(self, path: Path) -> int:
        """Calculate total size of a directory."""
        total = 0
        for p in path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
        return total

    def get_storage_usage(self) -> int:
        """Get total storage usage."""
        return self.get_dir_size(self.storage_root)

    def resolve_path(self, rel_path: str) -> Path:
        """Resolve a relative path to an absolute path in storage."""
        # Remove leading slash to make it relative
        clean_rel_path = rel_path.lstrip("/")
        return self.storage_root / clean_rel_path

    def resolve_temp_path(self, filename: str) -> Path:
        """Resolve a filename to an absolute path in temp storage."""
        return self.temp_root / filename

    def is_safe_path(self, path: Path) -> bool:
        """Check if path is within storage root to prevent traversal."""
        try:
            resolved_path = path.resolve()
            storage_root_abs = self.storage_root.resolve()
            return str(resolved_path).startswith(str(storage_root_abs))
        except Exception:
            return False

    def list_directory(self, rel_path: str) -> Generator[os.DirEntry, None, None]:
        """List contents of a directory."""
        target_dir = self.resolve_path(rel_path)
        if target_dir.exists() and target_dir.is_dir():
            with os.scandir(target_dir) as it:
                for entry in it:
                    if entry.name == "temp" and target_dir == self.storage_root:
                        continue
                    if entry.name.startswith("."):
                        continue
                    yield entry

    def move_temp_to_storage(self, filename: str, rel_dest_path: str) -> Path:
        """Move a file from temp to storage."""
        temp_path = self.resolve_temp_path(filename)
        dest_dir = self.resolve_path(rel_dest_path)
        dest_path = dest_dir / filename

        if not temp_path.exists():
            raise FileNotFoundError(f"Temp file {filename} not found")

        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_path), str(dest_path))
        return dest_path

    def write_chunk(self, f: IO[bytes], chunk: bytes) -> None:
        """Write a chunk to a file object."""
        f.write(chunk)

    async def save_temp_file(
        self, filename: str, chunk_reader: Callable[[], Awaitable[bytes]]
    ) -> int:
        """Save data from an async chunk reader to a temp file.

        Args:
            filename: Name of the temp file.
            chunk_reader: A callable that returns an awaitable bytes object (chunk).
                          Should return empty bytes b'' on EOF.

        Returns:
            Total bytes written.
        """
        temp_path = self.resolve_temp_path(filename)
        loop = asyncio.get_running_loop()

        # Open file in executor to avoid blocking the event loop
        f = await loop.run_in_executor(None, open, temp_path, "wb")
        total_bytes = 0
        try:
            while True:
                chunk = await chunk_reader()
                if not chunk:
                    break
                await loop.run_in_executor(None, f.write, chunk)
                total_bytes += len(chunk)
        finally:
            await loop.run_in_executor(None, f.close)

        return total_bytes
