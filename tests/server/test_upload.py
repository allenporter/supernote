import hashlib

from aiohttp import FormData
from aiohttp.test_utils import TestClient

from supernote.server.services.storage import StorageService
from tests.server.conftest import TEST_USERNAME


async def test_upload_file(
    client: TestClient,
    storage_service: StorageService,
    auth_headers: dict[str, str],
) -> None:
    filename = "test_upload.note"
    file_content = b"some binary content"

    # Prepare multipart upload
    data = FormData()
    data.add_field("file", file_content, filename=filename)

    # Upload data
    # Note: The endpoint is /api/file/upload/data/{filename}
    # It accepts POST or PUT
    resp = await client.post(
        f"/api/file/upload/data/{filename}",
        data=data,
        headers=auth_headers,
    )
    assert resp.status == 200

    # Verify file exists in temp
    temp_file = storage_service.resolve_temp_path(TEST_USERNAME, filename)
    assert temp_file.exists()
    assert temp_file.read_bytes() == file_content


async def test_chunked_upload(
    client: TestClient,
    storage_service: StorageService,
    auth_headers: dict[str, str],
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
    resp1 = await client.post(
        f"/api/file/upload/data/{filename}?uploadId={upload_id}&totalChunks={total_chunks}&partNumber=1",
        data=data1,
        headers=auth_headers,
    )
    assert resp1.status == 200

    # Upload chunk 2 (final chunk - should trigger merge)
    data2 = FormData()
    data2.add_field("file", chunk2_content, filename=filename)
    resp2 = await client.post(
        f"/api/file/upload/data/{filename}?uploadId={upload_id}&totalChunks={total_chunks}&partNumber=2",
        data=data2,
        headers=auth_headers,
    )
    assert resp2.status == 200

    # Verify merged file exists in temp
    temp_file = storage_service.resolve_temp_path(TEST_USERNAME, filename)
    assert temp_file.exists()

    # Verify content is correctly assembled
    merged_content = temp_file.read_bytes()
    assert merged_content == full_content
    assert len(merged_content) == len(chunk1_content) + len(chunk2_content)

    # Verify MD5 hash matches
    expected_hash = hashlib.md5(full_content).hexdigest()
    actual_hash = storage_service.get_file_md5(temp_file)
    assert actual_hash == expected_hash

    # Verify chunk files were cleaned up
    upload_dir = storage_service.temp_dir / TEST_USERNAME / upload_id
    assert not upload_dir.exists()
