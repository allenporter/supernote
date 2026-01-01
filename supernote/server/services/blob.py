import hashlib
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import AsyncGenerator
import secrets

import aiofiles


class BlobStorage(ABC):
    """Interface for Physical Blob Storage (Content-Addressable)."""

    @abstractmethod
    async def write_blob(self, data: bytes) -> str:
        """Write bytes to storage and return its MD5 hash."""
        pass
    
    @abstractmethod
    async def write_stream(self, stream: AsyncGenerator[bytes, None]) -> str:
        """Write stream to storage and return its MD5 hash."""
        pass

    @abstractmethod
    async def read_blob(self, md5: str) -> bytes:
        """Read full blob content."""
        pass
        
    @abstractmethod
    def get_blob_path(self, md5: str) -> Path:
        """Get physical path to the blob (optional, useful for serving files via specialized logic)."""
        pass
        
    @abstractmethod
    async def exists(self, md5: str) -> bool:
        """Check if blob exists."""
        pass


class LocalBlobStorage(BlobStorage):
    """Local filesystem implementation of CAS Blob Storage.

    Path structure: <root>/blobs/<md5[0:2]>/<md5>
    Example: storage/blobs/ab/abc12345...
    """

    def __init__(self, storage_root: Path) -> None:
        """Create a local blob storage instance."""
        self.root = storage_root / "blobs"
        self.root.mkdir(parents=True, exist_ok=True)

    def _get_path(self, md5: str) -> Path:
        """Get physical path to the blob."""
        return self.root / md5[:2] / md5

    async def write_blob(self, data: bytes) -> str:
        """Write bytes to storage and return its MD5 hash."""
        md5 = hashlib.md5(data).hexdigest()
        blob_path = self._get_path(md5)
        
        if blob_path.exists():
            return md5
            
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        # Write to temp file and move for atomicity
        temp_path = blob_path.with_suffix(".tmp")
        async with aiofiles.open(temp_path, "wb") as f:
            await f.write(data)
        
        temp_path.rename(blob_path)
        return md5

    async def write_stream(self, stream: AsyncGenerator[bytes, None]) -> str:
        """Write stream to storage and return its MD5 hash."""
        # We need to calculate MD5 while writing
        md5_hasher = hashlib.md5()
        
        # We don't know the MD5 yet, so we write to a temp file first
        # Ideally using a temp dir not tied to final path yet
        temp_dir = self.root / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Use a random name for temp file
        temp_name = f"upload_{secrets.token_hex(8)}.tmp"
        temp_path = temp_dir / temp_name
        
        try:
            async with aiofiles.open(temp_path, "wb") as f:
                async for chunk in stream:
                    md5_hasher.update(chunk)
                    await f.write(chunk)
            
            md5 = md5_hasher.hexdigest()
            final_path = self._get_path(md5)
            
            if final_path.exists():
                # Already exists, just delete temp
                temp_path.unlink()
                return md5
                
            final_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.rename(final_path)
            return md5
            
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    async def read_blob(self, md5: str) -> bytes:
        """Read full blob content."""
        path = self._get_path(md5)
        if not path.exists():
            raise FileNotFoundError(f"Blob {md5} not found")
        async with aiofiles.open(path, "rb") as f:
            return await f.read()

    def get_blob_path(self, md5: str) -> Path:
        """Get physical path to the blob."""
        return self._get_path(md5)

    async def exists(self, md5: str) -> bool:
        """Check if blob exists."""
        return self._get_path(md5).exists()
