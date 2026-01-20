import pytest

from supernote.client.client import Client
from supernote.client.exceptions import BadRequestException
from supernote.models.extended import WebSummaryListRequestDTO, WebSummaryListVO
from supernote.models.summary import AddSummaryVO


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
