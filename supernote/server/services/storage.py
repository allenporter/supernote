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

    def create_directory(self, rel_path: str) -> Path:
        """Create a directory in storage."""
        target_path = self.resolve_path(rel_path)
        if not self.is_safe_path(target_path):
            raise ValueError("Invalid path")
        target_path.mkdir(parents=True, exist_ok=True)
        return target_path

    def delete_path(self, rel_path: str) -> None:
        """Delete a file or directory in storage."""
        target_path = self.resolve_path(rel_path)
        if not self.is_safe_path(target_path):
            raise ValueError("Invalid path")

        if not target_path.exists():
            return  # Idempotent

        if target_path.is_dir():
            shutil.rmtree(target_path)
        else:
            target_path.unlink()

    def get_id_from_path(self, rel_path: str) -> int:
        """Generate a stable 64-bit ID from a relative path."""
        clean_path = rel_path.strip("/")
        # Use first 16 chars of MD5 (64 bits)
        md5_hash = hashlib.md5(clean_path.encode("utf-8")).hexdigest()
        return int(md5_hash[:16], 16)

    def get_path_from_id(self, file_id: int) -> str | None:
        """Find relative path from ID by scanning storage."""
        # Simple BFS scan
        queue = [Path(".")]
        while queue:
            current_rel_dir = queue.pop(0)
            # Avoid traversing up
            if ".." in str(current_rel_dir):
                continue
                
            target_dir = self.storage_root / current_rel_dir
            if current_rel_dir == Path("."):
                target_dir = self.storage_root

            if not target_dir.exists() or not target_dir.is_dir():
                continue

            try:
                with os.scandir(target_dir) as it:
                    for entry in it:
                        if entry.name == "temp" and target_dir == self.storage_root:
                            continue
                        if entry.name.startswith("."):
                            continue
                        
                        # Construct relative path string
                        if current_rel_dir == Path("."):
                            entry_rel_path = entry.name
                        else:
                            entry_rel_path = str(current_rel_dir / entry.name)

                        # Check ID
                        if self.get_id_from_path(entry_rel_path) == file_id:
                            return entry_rel_path
                        
                        if entry.is_dir():
                            # Enqueue directory for recursion
                            if current_rel_dir == Path("."):
                                queue.append(Path(entry.name))
                            else:
                                queue.append(current_rel_dir / entry.name)
            except OSError:
                continue
                
        return None

    def move_path(self, rel_src: str, rel_dest: str) -> None:
        """Move a file or directory.
        
        Args:
            rel_src: Relative source path.
            rel_dest: Relative destination path (full path including name).
        """
        src_path = self.resolve_path(rel_src)
        dest_path = self.resolve_path(rel_dest)

        if not self.is_safe_path(src_path) or not self.is_safe_path(dest_path):
            raise ValueError("Invalid path")

        if not src_path.exists():
            raise FileNotFoundError(f"Source {rel_src} not found")

        # Ensure parent exists
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        shutil.move(str(src_path), str(dest_path))

    def copy_path(self, rel_src: str, rel_dest: str) -> None:
        """Copy a file or directory.

        Args:
            rel_src: Relative source path.
            rel_dest: Relative destination path (full path including name).
        """
        src_path = self.resolve_path(rel_src)
        dest_path = self.resolve_path(rel_dest)

        if not self.is_safe_path(src_path) or not self.is_safe_path(dest_path):
            raise ValueError("Invalid path")

        if not src_path.exists():
            raise FileNotFoundError(f"Source {rel_src} not found")

        # Ensure parent exists
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        if src_path.is_dir():
            shutil.copytree(str(src_path), str(dest_path))
        else:
            shutil.copy2(str(src_path), str(dest_path))
