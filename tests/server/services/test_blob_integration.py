import hashlib
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import LocalBlobStorage
from supernote.server.services.file import FileService
from supernote.server.services.user import UserService
from supernote.server.utils.paths import generate_inner_name


@pytest.fixture
def file_service(
    storage_root: Path,
    blob_storage: LocalBlobStorage,
    user_service: UserService,
    session_manager: DatabaseSessionManager,
) -> FileService:
    return FileService(storage_root, blob_storage, user_service, session_manager)


async def test_blob_kv_separation(
    file_service: FileService,
    db_session: AsyncSession,
    create_test_user: None,
) -> None:
    """
    Verify that two files with IDENTICAL content are stored as TWO separate physical blobs
    under the new Key-Value architecture (Bucket + UUID), breaking the old CAS deduplication.
    """
    user_email = "test@example.com"
    content = b"Hello World Repeated Content"
    content_md5 = hashlib.md5(content).hexdigest()

    # 1. Upload File A
    file_a_name = "file_a.txt"
    inner_name_a = generate_inner_name(file_a_name, "EQ1")
    # Simulate direct upload (bypass FileService as per refactor)
    bucket = USER_DATA_BUCKET
    blob_storage = file_service.blob_storage
    await blob_storage.put(bucket, inner_name_a, content)

    entity_a = await file_service.finish_upload(
        user=user_email,
        filename=file_a_name,
        path_str="/files",
        content_hash=content_md5,
        inner_name=inner_name_a,
    )

    # 2. Upload File B (Identical Content)
    file_b_name = "file_b.txt"
    inner_name_b = generate_inner_name(file_b_name, "EQ1")

    # Simulate direct upload
    await blob_storage.put(bucket, inner_name_b, content)

    entity_b = await file_service.finish_upload(
        user=user_email,
        filename=file_b_name,
        path_str="/files",
        content_hash=content_md5,
        inner_name=inner_name_b,
    )

    # 3. Verify Database State
    async with db_session.begin():
        stmt = select(UserFileDO).where(UserFileDO.id.in_([entity_a.id, entity_b.id]))
        result = await db_session.execute(stmt)
        files = result.scalars().all()

        file_a = next(f for f in files if f.file_name == file_a_name)
        file_b = next(f for f in files if f.file_name == file_b_name)

        # Keys must correspond to the provided inner_names
        assert file_a.storage_key == inner_name_a
        assert file_b.storage_key == inner_name_b

        # Keys must be DIFFERENT (UUIDs)
        assert file_a.storage_key != file_b.storage_key

        # MD5s must be SAME
        assert file_a.md5 == file_b.md5

    # 4. Verify Physical Storage
    blob_storage = file_service.blob_storage
    bucket = USER_DATA_BUCKET
    path_a = blob_storage.get_blob_path(bucket, inner_name_a)
    path_b = blob_storage.get_blob_path(bucket, inner_name_b)

    # Both files must exist on disk
    assert path_a.exists()
    assert path_b.exists()

    # Paths must be different
    assert path_a != path_b

    # Content must match
    assert path_a.read_bytes() == content
    assert path_b.read_bytes() == content

    # 5. Verify Cleanup
    # Temp files check removed as we write directly to blob


async def test_finish_upload_detects_corruption(
    file_service: FileService,
    create_test_user: None,
) -> None:
    """
    Verify that finish_upload detects if the existing blob does NOT match the provided hash.
    This ensures that even if we bypass temp files, we still verify integrity.
    """
    user_email = "test@example.com"
    content = b"Corrupted or Different Content"
    fake_md5 = "00000000000000000000000000000000"

    file_name = "corrupt.txt"
    inner_name = generate_inner_name(file_name, "EQ1")
    bucket = USER_DATA_BUCKET

    # 1. Put the blob (so it exists)
    blob_storage = file_service.blob_storage
    await blob_storage.put(bucket, inner_name, content)

    # 2. Try to finish upload with WRONG hash
    # This should raise HashMismatch (or similar)
    from supernote.server.exceptions import HashMismatch

    with pytest.raises(HashMismatch, match="Hash mismatch"):
        await file_service.finish_upload(
            user=user_email,
            filename=file_name,
            path_str="/files",
            content_hash=fake_md5,
            inner_name=inner_name,
        )
