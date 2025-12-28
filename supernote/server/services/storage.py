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
        if not path.exists():
            return 0
        for p in path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
        return total

    def get_storage_usage(self, user: str) -> int:
        """Get total storage usage for a specific user."""
        return self.get_dir_size(self.storage_root / user)

    def resolve_path(self, user: str, rel_path: str) -> Path:
        """Resolve a relative path to an absolute path in user's storage."""
        # Remove leading slash to make it relative
        clean_rel_path = rel_path.lstrip("/")
        return self.storage_root / user / clean_rel_path

    def resolve_temp_path(self, user: str, filename: str) -> Path:
        """Resolve a filename to an absolute path in user's temp storage."""
        return self.temp_root / user / filename

    def is_safe_path(self, user: str, path: Path) -> bool:
        """Check if path is within user's storage root to prevent traversal."""
        try:
            resolved_path = path.resolve()
            user_root_abs = (self.storage_root / user).resolve()
            return str(resolved_path).startswith(str(user_root_abs))
        except Exception:
            return False

    def list_directory(
        self, user: str, rel_path: str
    ) -> Generator[os.DirEntry, None, None]:
        """List contents of a directory for a specific user."""
        target_dir = self.resolve_path(user, rel_path)
        if target_dir.exists() and target_dir.is_dir():
            with os.scandir(target_dir) as it:
                for entry in it:
                    if entry.name == "temp":
                        continue
                    if entry.name.startswith("."):
                        continue
                    yield entry

    def is_empty(self, user: str) -> bool:
        """Check if the user's storage root is empty (excluding internal items)."""
        for _ in self.list_directory(user, "/"):
            return False
        return True

    def move_temp_to_storage(
        self, user: str, filename: str, rel_dest_path: str
    ) -> Path:
        """Move a file from user's temp to user's storage."""
        temp_path = self.resolve_temp_path(user, filename)
        dest_dir = self.resolve_path(user, rel_dest_path)
        dest_path = dest_dir / filename

        if not temp_path.exists():
            raise FileNotFoundError(f"Temp file {filename} not found for user {user}")

        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_path), str(dest_path))
        return dest_path

    def write_chunk(self, f: IO[bytes], chunk: bytes) -> None:
        """Write a chunk to a file object."""
        f.write(chunk)

    async def save_temp_file(
        self, user: str, filename: str, chunk_reader: Callable[[], Awaitable[bytes]]
    ) -> int:
        """Save data from an async chunk reader to a user's temp file."""
        temp_path = self.resolve_temp_path(user, filename)
        temp_path.parent.mkdir(parents=True, exist_ok=True)

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

    def create_directory(self, user: str, rel_path: str) -> Path:
        """Create a directory in user's storage."""
        target_path = self.resolve_path(user, rel_path)
        if not self.is_safe_path(user, target_path):
            raise ValueError("Invalid path")
        target_path.mkdir(parents=True, exist_ok=True)
        return target_path

    def delete_path(self, user: str, rel_path: str) -> None:
        """Delete a file or directory in user's storage."""
        target_path = self.resolve_path(user, rel_path)
        if not self.is_safe_path(user, target_path):
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
        md5_hash = hashlib.md5(clean_path.encode("utf-8")).hexdigest()
        return int(md5_hash[:16], 16)

    def get_path_from_id(self, user: str, file_id: int) -> str | None:
        """Find relative path from ID by scanning user's storage."""
        user_root = self.storage_root / user
        if not user_root.exists():
            return None

        # Simple BFS scan within user root
        queue = [Path(".")]
        while queue:
            current_rel_dir = queue.pop(0)
            if ".." in str(current_rel_dir):
                continue

            target_dir = user_root / current_rel_dir
            if current_rel_dir == Path("."):
                target_dir = user_root

            if not target_dir.exists() or not target_dir.is_dir():
                continue

            try:
                with os.scandir(target_dir) as it:
                    for entry in it:
                        if entry.name == "temp":
                            continue
                        if entry.name.startswith(".") and entry.name != ".trash":
                            continue

                        if current_rel_dir == Path("."):
                            entry_rel_path = entry.name
                        else:
                            entry_rel_path = str(current_rel_dir / entry.name)

                        if self.get_id_from_path(entry_rel_path) == file_id:
                            return entry_rel_path

                        if entry.is_dir():
                            if current_rel_dir == Path("."):
                                queue.append(Path(entry.name))
                            else:
                                queue.append(current_rel_dir / entry.name)
            except OSError:
                continue

        return None

    def move_path(self, user: str, rel_src: str, rel_dest: str) -> None:
        """Move a file or directory within user's storage."""
        src_path = self.resolve_path(user, rel_src)
        dest_path = self.resolve_path(user, rel_dest)

        if not self.is_safe_path(user, src_path) or not self.is_safe_path(
            user, dest_path
        ):
            raise ValueError("Invalid path")

        if not src_path.exists():
            raise FileNotFoundError(f"Source {rel_src} not found")

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dest_path))

    def copy_path(self, user: str, rel_src: str, rel_dest: str) -> None:
        """Copy a file or directory within user's storage."""
        src_path = self.resolve_path(user, rel_src)
        dest_path = self.resolve_path(user, rel_dest)

        if not self.is_safe_path(user, src_path) or not self.is_safe_path(
            user, dest_path
        ):
            raise ValueError("Invalid path")

        if not src_path.exists():
            raise FileNotFoundError(f"Source {rel_src} not found")

        dest_path.parent.mkdir(parents=True, exist_ok=True)

        if src_path.is_dir():
            shutil.copytree(str(src_path), str(dest_path))
        else:
            shutil.copy2(str(src_path), str(dest_path))

    def get_trash_dir(self, user: str) -> Path:
        """Get the trash directory path for a user."""
        return self.storage_root / user / ".trash"

    def ensure_trash_dir(self, user: str) -> None:
        """Ensure trash directory exists for a user."""
        trash_dir = self.get_trash_dir(user)
        trash_dir.mkdir(parents=True, exist_ok=True)

    def soft_delete(self, user: str, rel_path: str) -> tuple[str, int]:
        """Move file/folder to user's trash."""
        src_path = self.resolve_path(user, rel_path)
        if not self.is_safe_path(user, src_path):
            raise ValueError("Invalid path")

        if not src_path.exists():
            raise FileNotFoundError(f"Path {rel_path} not found")

        self.ensure_trash_dir(user)

        import time

        timestamp = int(time.time() * 1000)
        name = src_path.name
        trash_name = f"{timestamp}_{name}"
        trash_path = self.get_trash_dir(user) / trash_name

        shutil.move(str(src_path), str(trash_path))
        return f".trash/{trash_name}", timestamp

    def list_trash(self, user: str) -> list[tuple[Path, int]]:
        """List all items in user's trash."""
        self.ensure_trash_dir(user)
        trash_dir = self.get_trash_dir(user)
        items = []

        for entry in trash_dir.iterdir():
            if entry.name.startswith("."):
                continue
            try:
                timestamp_str = entry.name.split("_", 1)[0]
                timestamp = int(timestamp_str)
                items.append((entry, timestamp))
            except (ValueError, IndexError):
                continue
        return items

    def restore_from_trash(
        self, user: str, trash_rel_path: str, original_rel_path: str
    ) -> None:
        """Restore file/folder from user's trash."""
        trash_path = (self.storage_root / user) / trash_rel_path
        if not trash_path.exists():
            raise FileNotFoundError(f"Trash item {trash_rel_path} not found")

        dest_path = self.resolve_path(user, original_rel_path)
        if not self.is_safe_path(user, dest_path):
            raise ValueError("Invalid destination path")

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(trash_path), str(dest_path))

    def delete_from_trash(self, user: str, trash_rel_path: str) -> None:
        """Permanently delete item from user's trash."""
        trash_path = (self.storage_root / user) / trash_rel_path
        if not trash_path.exists():
            return

        if trash_path.is_dir():
            shutil.rmtree(trash_path)
        else:
            trash_path.unlink()

    def empty_trash(self, user: str) -> None:
        """Delete all items in user's trash."""
        trash_dir = self.get_trash_dir(user)
        if trash_dir.exists():
            for entry in trash_dir.iterdir():
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
