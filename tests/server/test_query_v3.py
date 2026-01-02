from supernote.client.file import FileClient
from tests.server.conftest import TEST_USERNAME, UserStorageHelper


async def test_query_v3_success(
    file_client: FileClient,
    user_storage: UserStorageHelper,
) -> None:
    # Create a test file
    await user_storage.create_file(TEST_USERNAME, "Note/test.note", content="content")

    # Query by ID (resolve first)
    path_str = "Note/test.note"
    # Resolve valid ID using query_by_path
    path_resp = await file_client.query_by_path(path=path_str, equipment_no="SN123")
    assert path_resp.entries_vo
    real_id = int(path_resp.entries_vo.id)

    # Now Query by strict ID
    data = await file_client.query_by_id(file_id=real_id, equipment_no="SN123")

    assert data.entries_vo
    assert data.entries_vo.id == str(real_id)
    assert data.entries_vo.name == "test.note"
    # When querying by ID, VFS returns /{filename} generally unless fully walked
    assert data.entries_vo.path_display == "/test.note"
    # MD5 of "content" is 9a0364b9e99bb480dd25e1f0284c8555
    assert data.entries_vo.content_hash == "9a0364b9e99bb480dd25e1f0284c8555"


async def test_query_v3_not_found(
    file_client: FileClient,
) -> None:
    """Query with an identifier that does not exist."""
    # Use a specific ID that should not exist
    data = await file_client.query_by_id(file_id=99999999, equipment_no="SN123")

    assert data.entries_vo is None
    assert data.equipment_no == "SN123"
