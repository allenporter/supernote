import hashlib

import pytest
from sqlalchemy import select

from supernote.client.client import Client
from supernote.client.exceptions import BadRequestException, ForbiddenException
from supernote.client.web import WebClient
from supernote.models.extended import WebSummaryListRequestDTO, WebSummaryListVO
from supernote.models.summary import AddSummaryVO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from tests.server.conftest import TEST_USERNAME


@pytest.fixture
def web_summary_list_url() -> str:
    return "/api/extended/file/summary/list"


async def test_web_summary_list(
    authenticated_client: Client,
    web_summary_list_url: str,
) -> None:
    pass


async def test_web_summary_list_implementation(
    authenticated_client: Client, web_summary_list_url: str
) -> None:
    """Implement the test logic knowing AddSummaryDTO structure."""

    # 1. Add a summary for a specific file
    file_id = 88888
    add_payload = {
        "content": "Extension test",
        "dataSource": "WEB",
        "fileId": file_id,  # AddSummaryDTO has file_id
    }
    # Use AddSummaryVO as response type
    resp = await authenticated_client.post_json(
        "/api/file/add/summary", AddSummaryVO, json=add_payload
    )
    assert resp.id is not None

    # 2. Call the web extension endpoint using post_json and expect WebSummaryListVO
    req_dto = WebSummaryListRequestDTO(file_id=file_id)
    web_resp = await authenticated_client.post_json(
        web_summary_list_url, WebSummaryListVO, json=req_dto.to_dict()
    )

    assert web_resp.success
    assert len(web_resp.summary_do_list) == 1
    assert web_resp.total_records == 1
    assert web_resp.summary_do_list[0].file_id == file_id
    assert web_resp.summary_do_list[0].content == "Extension test"


async def test_web_summary_list_invalid(
    authenticated_client: Client, web_summary_list_url: str
) -> None:
    # Test missing fileId - Should raise BadRequestException
    with pytest.raises(BadRequestException):
        await authenticated_client.post(
            web_summary_list_url,
            json={},
        )

    # Test invalid fileId - Should raise BadRequestException
    with pytest.raises(BadRequestException):
        await authenticated_client.post(
            web_summary_list_url,
            json={"fileId": "invalid"},
        )


async def test_web_upload_apply_returns_part_upload_url_and_standard_inner_name(
    authenticated_client: Client,
) -> None:
    """Verify /api/file/upload/apply returns partUploadUrl and standard innerName."""
    web_client = WebClient(authenticated_client)
    file_name = "2025.01.15.Report (Draft).pdf"
    apply_vo = await web_client.upload_apply(
        directory_id=0,
        file_name=file_name,
        size=1024,
        md5=hashlib.md5(b"test").hexdigest(),
    )
    assert apply_vo.inner_name is not None
    assert apply_vo.inner_name.endswith("-000.pdf")
    assert ".01.15" not in apply_vo.inner_name
    assert apply_vo.full_upload_url is not None
    assert "/api/oss/upload?" in apply_vo.full_upload_url
    assert apply_vo.part_upload_url is not None
    assert "/api/oss/upload/part?" in apply_vo.part_upload_url


async def test_web_client_upload_large_file_multipart(
    authenticated_client: Client,
) -> None:
    """Verify WebClient.upload_file succeeds for multi-chunk files using partUploadUrl."""
    web_client = WebClient(authenticated_client)
    folder = await web_client.create_folder(0, "MultipartUploads")
    folder_id = int(folder.id)

    # > 5MB triggers chunked multipart upload in Client._upload_to_oss
    large_content = b"x" * (5 * 1024 * 1024 + 128)
    expected_md5 = hashlib.md5(large_content).hexdigest()
    await web_client.upload_file(folder_id, "2025.01.15.Large.pdf", large_content)

    listing = await web_client.list_query(folder_id)
    assert len(listing.user_file_vo_list) == 1
    uploaded = listing.user_file_vo_list[0]
    assert uploaded.file_name == "2025.01.15.Large.pdf"
    assert uploaded.size == len(large_content)
    assert uploaded.md5 == expected_md5
    assert uploaded.inner_name is not None
    assert uploaded.inner_name.endswith("-000.pdf")


async def test_web_list_query_returns_recursive_folder_sizes(
    authenticated_client: Client,
) -> None:
    """Verify /api/file/list/query computes recursive folder sizes including flattened root folders."""
    web_client = WebClient(authenticated_client)

    # Query root to find the flattened 'Note' system folder
    root_listing = await web_client.list_query(0)
    note_folder = next(
        item for item in root_listing.user_file_vo_list if item.file_name == "Note"
    )
    note_id = int(note_folder.id)
    assert note_folder.size == 0

    # Create nested hierarchy inside Note: Note -> Projects -> 2026, plus an EmptySub folder
    projects_vo = await web_client.create_folder(note_id, "Projects")
    projects_id = int(projects_vo.id)
    year_vo = await web_client.create_folder(projects_id, "2026")
    year_id = int(year_vo.id)
    empty_vo = await web_client.create_folder(note_id, "EmptySub")
    empty_id = int(empty_vo.id)

    await web_client.upload_file(note_id, "root_note.note", b"a" * 120)
    await web_client.upload_file(projects_id, "proj.note", b"b" * 300)
    await web_client.upload_file(year_id, "deep.note", b"c" * 580)
    await web_client.upload_file(year_id, "temp.note", b"d" * 1000)

    # Delete temp.note and verify its bytes are excluded
    year_listing = await web_client.list_query(year_id)
    temp_item = next(
        item for item in year_listing.user_file_vo_list if item.file_name == "temp.note"
    )
    await web_client.file_delete([int(temp_item.id)], parent_id=year_id)

    # Check Note directory listing
    note_listing = await web_client.list_query(note_id)
    by_id = {int(item.id): item for item in note_listing.user_file_vo_list}
    assert by_id[projects_id].size == 300 + 580
    assert by_id[empty_id].size == 0

    # Check root listing for flattened Note folder recursive size (120 + 300 + 580 = 1000)
    root_listing_after = await web_client.list_query(0)
    note_folder_after = next(
        item
        for item in root_listing_after.user_file_vo_list
        if item.file_name == "Note"
    )
    assert note_folder_after.size == 1000


async def test_web_capacity_query_returns_volume_backed_capacity_by_default(
    authenticated_client: Client,
    blob_storage: BlobStorage,
) -> None:
    """Verify Web capacity endpoint returns positive volume-backed capacity when uncapped."""
    web_client = WebClient(authenticated_client)
    capacity = await web_client.get_capacity_web()
    assert capacity.used_capacity == 0
    assert capacity.total_capacity > 0
    available = blob_storage.get_available_bytes()
    assert available is not None
    assert abs(capacity.total_capacity - available) < 64 * 1024 * 1024


async def test_web_capacity_query_returns_custom_user_capacity(
    authenticated_client: Client,
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify Web capacity endpoint returns customized user total_capacity."""
    custom_capacity = 25 * 1024 * 1024 * 1024  # 25GB
    async with session_manager.session() as session:
        stmt = select(UserDO).where(UserDO.email == TEST_USERNAME)
        user = (await session.execute(stmt)).scalar_one()
        user.total_capacity = str(custom_capacity)
        await session.commit()

    web_client = WebClient(authenticated_client)
    capacity = await web_client.get_capacity_web()
    assert capacity.total_capacity == custom_capacity


async def test_web_upload_finish_enforces_quota_via_api(
    authenticated_client: Client,
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify Web upload completion rejects uploads exceeding quota with 403."""
    # Set quota to 500 bytes
    async with session_manager.session() as session:
        stmt = select(UserDO).where(UserDO.email == TEST_USERNAME)
        user = (await session.execute(stmt)).scalar_one()
        user.total_capacity = "500"
        await session.commit()

    web_client = WebClient(authenticated_client)

    # Upload 300 bytes - fits under 500-byte quota
    await web_client.upload_file(0, "fit.txt", b"a" * 300)

    # Next upload of 300 bytes brings total to 600 > 500 - should fail with ForbiddenException (403)
    with pytest.raises(ForbiddenException):
        await web_client.upload_file(0, "overflow.txt", b"b" * 300)
