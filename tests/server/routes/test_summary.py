import pytest

from supernote.client.client import Client
from supernote.client.summary import SummaryClient
from supernote.models.summary import (
    AddSummaryDTO,
    AddSummaryGroupDTO,
    UpdateSummaryDTO,
    UpdateSummaryGroupDTO,
)


@pytest.fixture
def summary_client(authenticated_client: Client) -> SummaryClient:
    """Create a SummaryClient."""
    return SummaryClient(authenticated_client)


async def test_summary_tags_crud(summary_client: SummaryClient) -> None:
    # 1. Query initial tags (should be empty)
    response = await summary_client.query_tags()
    assert response.success
    assert len(response.summary_tag_do_list) == 0

    # 2. Add a tag
    add_response = await summary_client.add_tag(name="Work")
    assert add_response.success
    tag_id = add_response.id
    assert tag_id is not None

    # 3. Verify tag was added
    response = await summary_client.query_tags()
    assert len(response.summary_tag_do_list) == 1
    assert response.summary_tag_do_list[0].name == "Work"
    assert response.summary_tag_do_list[0].id == tag_id

    # 4. Update the tag
    update_response = await summary_client.update_tag(tag_id=tag_id, name="Job")
    assert update_response.success

    # 5. Verify update
    response = await summary_client.query_tags()
    assert response.summary_tag_do_list[0].name == "Job"

    # 6. Delete the tag
    delete_response = await summary_client.delete_tag(tag_id=tag_id)
    assert delete_response.success

    # 7. Verify deletion
    response = await summary_client.query_tags()
    assert len(response.summary_tag_do_list) == 0


async def test_summary_crud(summary_client: SummaryClient) -> None:
    # 1. Add a summary
    add_dto = AddSummaryDTO(
        content="This is a test summary",
        data_source="TEST",
        tags="test,summary",
        metadata='{"key": "value"}',
    )
    add_response = await summary_client.add_summary(add_dto)
    assert add_response.success
    summary_id = add_response.id
    assert summary_id is not None

    # 2. Query the summary
    query_response = await summary_client.query_summaries(ids=[summary_id])
    assert query_response.success
    assert len(query_response.summary_do_list) == 1
    summary = query_response.summary_do_list[0]
    assert summary.content == "This is a test summary"
    assert summary.data_source == "TEST"
    assert summary.tags == "test,summary"
    assert summary.metadata == '{"key": "value"}'

    # 3. Update the summary
    update_dto = UpdateSummaryDTO(
        id=summary_id,
        content="Updated test summary",
        tags="updated",
    )
    update_response = await summary_client.update_summary(update_dto)
    assert update_response.success

    # 4. Verify update
    query_response = await summary_client.query_summaries(ids=[summary_id])
    summary = query_response.summary_do_list[0]
    assert summary.content == "Updated test summary"
    assert summary.tags == "updated"

    # 5. Delete the summary
    delete_response = await summary_client.delete_summary(summary_id)
    assert delete_response.success

    # 6. Verify deletion
    query_response = await summary_client.query_summaries(ids=[summary_id])
    assert len(query_response.summary_do_list) == 0


async def test_group_crud(summary_client: SummaryClient) -> None:
    # 1. Add a group
    group_uuid = "test-group-uuid"
    add_dto = AddSummaryGroupDTO(
        unique_identifier=group_uuid,
        name="Test Group",
        md5_hash="hash123",
        description="A test group",
    )
    add_response = await summary_client.add_group(add_dto)
    assert add_response.success
    group_id = add_response.id
    assert group_id is not None

    # 2. Query groups
    query_response = await summary_client.query_groups()
    assert query_response.success
    assert [
        (g.id, g.unique_identifier, g.name) for g in query_response.summary_do_list
    ] == [(group_id, group_uuid, "Test Group")]

    # 3. Update group
    update_dto = UpdateSummaryGroupDTO(
        id=group_id,
        unique_identifier=group_uuid,
        name="Updated Group",
        md5_hash="newhash",
    )
    update_response = await summary_client.update_group(update_dto)
    assert update_response.success

    # 4. Verify update
    query_response = await summary_client.query_groups()
    assert [
        (g.id, g.unique_identifier, g.name) for g in query_response.summary_do_list
    ] == [(group_id, group_uuid, "Updated Group")]

    # 5. Delete group
    delete_response = await summary_client.delete_group(group_id)
    assert delete_response.success

    # 6. Verify deletion
    query_response = await summary_client.query_groups()
    assert not any(g.id == group_id for g in query_response.summary_do_list)


async def test_summary_binary_flow(summary_client: SummaryClient) -> None:
    # 1. Apply for upload
    upload_response = await summary_client.upload_apply("test_strokes.bin")
    assert upload_response.success
    assert upload_response.full_upload_url is not None
    assert upload_response.inner_name is not None
    inner_name = upload_response.inner_name

    # 2. Add summary with that inner name
    add_dto = AddSummaryDTO(
        content="Summary with binary",
        data_source="TEST",
        handwrite_inner_name=inner_name,
    )
    add_response = await summary_client.add_summary(add_dto)
    assert add_response.id
    summary_id = add_response.id

    # 3. Apply for download
    download_response = await summary_client.download_summary(summary_id)
    assert download_response.success
    assert download_response.url is not None
    assert inner_name in download_response.url
