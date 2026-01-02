import hashlib
from pathlib import Path

from aiohttp import FormData

from supernote.client.file import FileClient
from tests.server.conftest import TEST_USERNAME, UserStorageHelper


async def test_upload_file(
    file_client: FileClient,
    storage_root: Path,
) -> None:
    filename = "test_upload.note"
    file_content = b"some binary content"

    # Prepare multipart upload
    data = FormData()
    data.add_field("file", file_content, filename=filename)

    # Upload data
    await file_client.upload_data(filename=filename, data=data)

    # Verify file exists in temp
    # Verify file exists in temp
    temp_file = storage_root / "temp" / TEST_USERNAME / filename
    assert temp_file.exists()
    assert temp_file.read_bytes() == file_content


async def test_chunked_upload(
    file_client: FileClient,
    storage_root: Path,
    user_storage: UserStorageHelper,
) -> None:
    """Test uploading a file in multiple chunks."""

    filename = "chunked_test.note"
    # Create content that will be split into 2 chunks
    chunk1_content = b"first chunk data " * 100  # ~1.7KB
    chunk2_content = b"second chunk data " * 100  # ~1.8KB
    full_content = chunk1_content + chunk2_content

    upload_id = "test-upload-123"
    total_chunks = 2

    # Upload chunk 1
    data1 = FormData()
    data1.add_field("file", chunk1_content, filename=filename)
    await file_client.upload_data(
        filename=filename,
        data=data1,
        params={"uploadId": upload_id, "totalChunks": total_chunks, "partNumber": 1},
    )

    # Upload chunk 2 (final chunk - should trigger merge)
    data2 = FormData()
    data2.add_field("file", chunk2_content, filename=filename)
    await file_client.upload_data(
        filename=filename,
        data=data2,
        params={"uploadId": upload_id, "totalChunks": total_chunks, "partNumber": 2},
    )

    # Verify merged file exists in BlobStorage (via hash)
    # The temp file is gone because merge_chunks cleans it up (or writes directly to blob and never creates it)
    full_hash = hashlib.md5(full_content).hexdigest()
    assert await user_storage.blob_storage.exists(full_hash)

    # Content verification via blob
    blob_path = user_storage.blob_storage.get_blob_path(full_hash)
    assert blob_path.read_bytes() == full_content

    # Verify chunk files were cleaned up
    upload_dir = storage_root / "temp" / TEST_USERNAME / upload_id
    assert not upload_dir.exists()
