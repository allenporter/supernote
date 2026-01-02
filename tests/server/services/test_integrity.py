import hashlib

from sqlalchemy import update

from supernote.server.db.models.file import UserFileDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from supernote.server.services.integrity import IntegrityService
from supernote.server.services.user import UserService
from tests.server.conftest import UserStorageHelper


async def test_integrity_check(
    user_storage: UserStorageHelper,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    user_service: UserService,
) -> None:
    # Setup Data
    user = "test@example.com"
    await user_storage.create_directory(user, "Docs")

    # Create the correct file
    await user_storage.create_file(user, "Docs/good.txt", "content")

    # Corrupt Data (Simulate missing blob)
    md5 = hashlib.md5(b"content").hexdigest()
    blob_path = blob_storage.get_blob_path(md5)
    assert blob_path.exists()
    blob_path.unlink()  # Delete physical blob

    # Corrupt Data (Simulate size mismatch)
    await user_storage.create_file(user, "Docs/bad_size.txt", "content2")

    # Manually update VFS size to be wrong
    user_id = await user_service.get_user_id(user)

    async with session_manager.session() as session:
        stmt = (
            update(UserFileDO)
            .where(
                UserFileDO.user_id == user_id, UserFileDO.file_name == "bad_size.txt"
            )
            .values(size=99999)
        )
        await session.execute(stmt)
        await session.commit()

    # Run Check
    service = IntegrityService(session_manager, blob_storage)
    report = await service.verify_user_storage(user_id)

    # Expect:
    # "content" md5 deleted.
    # "content2" md5 exists but size mismatch.

    assert report.ok == 0
    assert report.missing_blob == 1
    assert report.size_mismatch == 1
    assert report.scanned == 2
