import hashlib

from sqlalchemy import update

from supernote.client.device import DeviceClient
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from supernote.server.services.integrity import IntegrityService
from supernote.server.services.user import UserService


async def test_integrity_check(
    device_client: DeviceClient,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    user_service: UserService,
) -> None:
    # Setup Data
    user = "test@example.com"
    await device_client.create_folder(path="/Docs", equipment_no="test")

    # Create the correct file
    await device_client.upload_content("Docs/good.txt", "content", equipment_no="test")

    # Corrupt Data (Simulate missing blob)
    md5 = hashlib.md5(b"content").hexdigest()
    blob_path = blob_storage.get_blob_path(md5)
    assert blob_path.exists()
    blob_path.unlink()  # Delete physical blob

    # Corrupt Data (Simulate size mismatch)
    await device_client.upload_content(
        "Docs/bad_size.txt", "content2", equipment_no="test"
    )

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
    # No orphans in this scenario
    # Scanned: 3 (Docs folder + good.txt + bad_size.txt)
    # Docs folder: OK
    # good.txt: missing blob
    # bad_size.txt: size mismatch

    assert report.orphans == 0
    assert report.missing_blob == 1
    assert report.size_mismatch == 1
    # Scanned: 3 (default folders) + Docs + good + bad_size = 6
    assert report.scanned == 6
    assert report.ok == 4  # 4 folders (3 default + Docs) are OK.


async def test_integrity_orphans(
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    user_service: UserService,
) -> None:
    """Test detection of orphaned files (invalid parent)."""
    user_email = "orphan@example.com"

    # Create the user manually
    async with session_manager.session() as session:
        new_user = UserDO(
            email=user_email,
            password_md5="md5",
            is_active=True,
            display_name="Orphan Test User",
        )
        session.add(new_user)
        await session.commit()

    user_id = await user_service.get_user_id(user_email)

    # 1. Create a valid file manually (since user_storage uses default user)
    valid_content = b"valid"
    valid_md5 = await blob_storage.write_blob(valid_content)

    async with session_manager.session() as session:
        valid_file = UserFileDO(
            user_id=user_id,
            directory_id=0,  # Root is valid
            file_name="valid.txt",
            md5=valid_md5,
            size=len(valid_content),
            is_active="Y",
        )
        session.add(valid_file)
        await session.commit()

    # 2. Plant an orphaned file (directory_id=99999)
    async with session_manager.session() as session:
        orphan = UserFileDO(
            user_id=user_id,
            directory_id=99999,
            file_name="orphan.txt",
            md5="fakehash",
            size=10,
            is_active="Y",
        )
        session.add(orphan)
        await session.commit()

    # Run Check
    service = IntegrityService(session_manager, blob_storage)
    report = await service.verify_user_storage(user_id)

    assert report.orphans == 1
    assert report.scanned == 2  # valid.txt, orphan.txt
    assert (
        report.ok == 1
    )  # valid.txt (blob check would fail if we checked it, but orphan check comes first?
    # Wait, valid.txt needs a blob. create_file makes a real file.
    # orphan.txt has invalid parent.

    # "valid.txt" is at root. root (0) is valid.
