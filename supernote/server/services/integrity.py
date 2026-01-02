import logging
from dataclasses import dataclass

from sqlalchemy import select

from supernote.server.db.models.file import UserFileDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage

logger = logging.getLogger(__name__)


@dataclass
class IntegrityReport:
    scanned: int
    missing_blob: int
    size_mismatch: int
    ok: int


class IntegrityService:
    """Service to verify data consistency between VFS and BlobStorage."""

    def __init__(
        self, session_manager: DatabaseSessionManager, blob_storage: BlobStorage
    ) -> None:
        """Create an integrity service instance."""
        self.session_manager = session_manager
        self.blob_storage = blob_storage

    async def verify_user_storage(self, user_id: int) -> IntegrityReport:
        """Check all files for a user."""
        report = IntegrityReport(scanned=0, missing_blob=0, size_mismatch=0, ok=0)

        async with self.session_manager.session() as session:
            # Query all active files (not folders)
            stmt = select(UserFileDO).where(
                UserFileDO.user_id == user_id,
                UserFileDO.is_active == "Y",
                UserFileDO.is_folder == "N",
            )
            result = await session.execute(stmt)
            files = result.scalars().all()

            for file_do in files:
                report.scanned += 1
                md5 = file_do.md5

                # Check Blob Existence
                if not md5 or not await self.blob_storage.exists(md5):
                    logger.error(
                        f"Integrity Fail: File {file_do.id} ({file_do.file_name}) missing blob {md5}"
                    )
                    report.missing_blob += 1
                    continue

                # Check Size
                blob_size = await self.blob_storage.get_size(md5)
                if blob_size != file_do.size:
                    logger.warning(
                        f"Integrity Warning: File {file_do.id} size mismatch. VFS: {file_do.size}, Blob: {blob_size}"
                    )
                    report.size_mismatch += 1
                    continue

                report.ok += 1

        return report
