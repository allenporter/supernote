from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.client import Client
from supernote.client.summary import SummaryClient
from supernote.models.summary import (
    AddSummaryDTO,
    AddSummaryGroupDTO,
    QuerySummaryDTO,
    UpdateSummaryDTO,
    UpdateSummaryGroupDTO,
)
from supernote.server.exceptions import SupernoteError


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


async def test_advanced_queries(summary_client: SummaryClient) -> None:
    # 1. Setup: Add a test summary
    add_dto = AddSummaryDTO(
        content="Advanced Test content",
        md5_hash="advhash",
        handwrite_md5="advhwmd5",
        comment_handwrite_name="advhw.bin",
    )
    add_response = await summary_client.add_summary(add_dto)
    summary_id = add_response.id
    assert summary_id is not None

    # 2. Test query/summary/hash
    query_dto = QuerySummaryDTO(ids=[summary_id])
    hash_response = await summary_client.query_summary_hash(query_dto)
    assert hash_response.success
    assert len(hash_response.summary_info_vo_list) == 1
    info = hash_response.summary_info_vo_list[0]
    assert info.id == summary_id
    assert info.md5_hash == "advhash"
    assert info.handwrite_md5 == "advhwmd5"
    assert info.comment_handwrite_name == "advhw.bin"

    # 3. Test query/summary/id
    id_response = await summary_client.query_summary_id(query_dto)
    assert id_response.success
    assert len(id_response.summary_do_list) == 1
    summary = id_response.summary_do_list[0]
    assert summary.id == summary_id
    assert summary.content == "Advanced Test content"


async def test_download_summary_handwriting_not_found(
    summary_client: SummaryClient,
) -> None:
    # 1. Add summary without handwriting data
    add_dto = AddSummaryDTO(
        content="No handwriting summary",
        data_source="TEST",
    )
    add_response = await summary_client.add_summary(add_dto)
    assert add_response.id
    summary_id = add_response.id

    # 2. Request download -> should fail with 404 / Handwriting data not found
    with pytest.raises(Exception) as exc_info:
        await summary_client.download_summary(summary_id)
    assert "404" in str(exc_info.value) or "Handwriting data not found" in str(
        exc_info.value
    )


async def test_summary_pagination_and_query_options(
    summary_client: SummaryClient,
) -> None:
    resp = await summary_client.query_summaries(parent_uuid="group-xyz", page=2, size=5)
    assert resp.success
    assert resp.current_page == 2
    assert resp.page_size == 5

    group_resp = await summary_client.query_groups(page=3, size=10)
    group_resp = await summary_client.query_groups(page=3, size=10)
    assert group_resp.success
    assert group_resp.current_page == 3
    assert group_resp.page_size == 10

    hash_query = QuerySummaryDTO(page=4, size=15)
    hash_resp = await summary_client.query_summary_hash(hash_query)
    assert hash_resp.success
    assert hash_resp.current_page == 4
    assert hash_resp.page_size == 15


async def test_summary_route_error_handling(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    endpoints = [
        ("/api/file/add/summary/tag", {"name": "tag"}),
        ("/api/file/update/summary/tag", {"id": 1, "name": "tag"}),
        ("/api/file/delete/summary/tag", {"id": 1}),
        ("/api/file/query/summary/tag", {}),
        ("/api/file/add/summary", {"content": "c"}),
        ("/api/file/update/summary", {"id": 1, "content": "c"}),
        ("/api/file/delete/summary", {"id": 1}),
        ("/api/file/query/summary", {}),
        (
            "/api/file/add/summary/group",
            {"name": "g", "uniqueIdentifier": "u", "md5Hash": "h"},
        ),
        (
            "/api/file/update/summary/group",
            {"id": 1, "name": "g", "uniqueIdentifier": "u", "md5Hash": "h"},
        ),
        ("/api/file/delete/summary/group", {"id": 1}),
        ("/api/file/query/summary/group", {}),
        ("/api/file/download/summary", {"id": 9999}),
        ("/api/file/query/summary/hash", {}),
        ("/api/file/query/summary/id", {}),
    ]

    for ep, payload in endpoints:
        # SupernoteError path
        with patch.object(
            client.app["summary_service"],
            "list_tags",
            side_effect=SupernoteError("Err", status_code=400),
        ):
            with patch.object(
                client.app["summary_service"],
                "add_tag",
                side_effect=SupernoteError("Err", status_code=400),
            ):
                with patch.object(
                    client.app["summary_service"],
                    "update_tag",
                    side_effect=SupernoteError("Err", status_code=400),
                ):
                    with patch.object(
                        client.app["summary_service"],
                        "delete_tag",
                        side_effect=SupernoteError("Err", status_code=400),
                    ):
                        with patch.object(
                            client.app["summary_service"],
                            "add_summary",
                            side_effect=SupernoteError("Err", status_code=400),
                        ):
                            with patch.object(
                                client.app["summary_service"],
                                "update_summary",
                                side_effect=SupernoteError("Err", status_code=400),
                            ):
                                with patch.object(
                                    client.app["summary_service"],
                                    "delete_summary",
                                    side_effect=SupernoteError("Err", status_code=400),
                                ):
                                    with patch.object(
                                        client.app["summary_service"],
                                        "list_summaries",
                                        side_effect=SupernoteError(
                                            "Err", status_code=400
                                        ),
                                    ):
                                        with patch.object(
                                            client.app["summary_service"],
                                            "add_group",
                                            side_effect=SupernoteError(
                                                "Err", status_code=400
                                            ),
                                        ):
                                            with patch.object(
                                                client.app["summary_service"],
                                                "update_group",
                                                side_effect=SupernoteError(
                                                    "Err", status_code=400
                                                ),
                                            ):
                                                with patch.object(
                                                    client.app["summary_service"],
                                                    "delete_group",
                                                    side_effect=SupernoteError(
                                                        "Err", status_code=400
                                                    ),
                                                ):
                                                    with patch.object(
                                                        client.app["summary_service"],
                                                        "list_groups",
                                                        side_effect=SupernoteError(
                                                            "Err", status_code=400
                                                        ),
                                                    ):
                                                        with patch.object(
                                                            client.app[
                                                                "summary_service"
                                                            ],
                                                            "get_summary",
                                                            side_effect=SupernoteError(
                                                                "Err", status_code=400
                                                            ),
                                                        ):
                                                            with patch.object(
                                                                client.app[
                                                                    "summary_service"
                                                                ],
                                                                "list_summary_infos",
                                                                side_effect=SupernoteError(
                                                                    "Err",
                                                                    status_code=400,
                                                                ),
                                                            ):
                                                                with patch.object(
                                                                    client.app[
                                                                        "summary_service"
                                                                    ],
                                                                    "list_summaries_by_id",
                                                                    side_effect=SupernoteError(
                                                                        "Err",
                                                                        status_code=400,
                                                                    ),
                                                                ):
                                                                    resp = await client.post(
                                                                        ep,
                                                                        json=payload,
                                                                        headers=auth_headers,
                                                                    )
                                                                    assert (
                                                                        resp.status
                                                                        == 400
                                                                    )

        # Uncaught Exception path
        with patch.object(
            client.app["summary_service"],
            "list_tags",
            side_effect=Exception("Uncaught"),
        ):
            with patch.object(
                client.app["summary_service"],
                "add_tag",
                side_effect=Exception("Uncaught"),
            ):
                with patch.object(
                    client.app["summary_service"],
                    "update_tag",
                    side_effect=Exception("Uncaught"),
                ):
                    with patch.object(
                        client.app["summary_service"],
                        "delete_tag",
                        side_effect=Exception("Uncaught"),
                    ):
                        with patch.object(
                            client.app["summary_service"],
                            "add_summary",
                            side_effect=Exception("Uncaught"),
                        ):
                            with patch.object(
                                client.app["summary_service"],
                                "update_summary",
                                side_effect=Exception("Uncaught"),
                            ):
                                with patch.object(
                                    client.app["summary_service"],
                                    "delete_summary",
                                    side_effect=Exception("Uncaught"),
                                ):
                                    with patch.object(
                                        client.app["summary_service"],
                                        "list_summaries",
                                        side_effect=Exception("Uncaught"),
                                    ):
                                        with patch.object(
                                            client.app["summary_service"],
                                            "add_group",
                                            side_effect=Exception("Uncaught"),
                                        ):
                                            with patch.object(
                                                client.app["summary_service"],
                                                "update_group",
                                                side_effect=Exception("Uncaught"),
                                            ):
                                                with patch.object(
                                                    client.app["summary_service"],
                                                    "delete_group",
                                                    side_effect=Exception("Uncaught"),
                                                ):
                                                    with patch.object(
                                                        client.app["summary_service"],
                                                        "list_groups",
                                                        side_effect=Exception(
                                                            "Uncaught"
                                                        ),
                                                    ):
                                                        with patch.object(
                                                            client.app[
                                                                "summary_service"
                                                            ],
                                                            "get_summary",
                                                            side_effect=Exception(
                                                                "Uncaught"
                                                            ),
                                                        ):
                                                            with patch.object(
                                                                client.app[
                                                                    "summary_service"
                                                                ],
                                                                "list_summary_infos",
                                                                side_effect=Exception(
                                                                    "Uncaught"
                                                                ),
                                                            ):
                                                                with patch.object(
                                                                    client.app[
                                                                        "summary_service"
                                                                    ],
                                                                    "list_summaries_by_id",
                                                                    side_effect=Exception(
                                                                        "Uncaught"
                                                                    ),
                                                                ):
                                                                    resp = await client.post(
                                                                        ep,
                                                                        json=payload,
                                                                        headers=auth_headers,
                                                                    )
                                                                    assert (
                                                                        resp.status
                                                                        == 500
                                                                    )


async def test_upload_apply_summary_error(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    with patch.object(
        client.app["url_signer"],
        "sign",
        side_effect=SupernoteError("Sign error", status_code=400),
    ):
        resp = await client.post(
            "/api/file/upload/apply/summary",
            json={"fileName": "test.txt", "equipmentNo": "eq1"},
            headers=auth_headers,
        )
        assert resp.status == 400

    with patch.object(
        client.app["url_signer"], "sign", side_effect=Exception("Sign fail")
    ):
        resp = await client.post(
            "/api/file/upload/apply/summary",
            json={"fileName": "test.txt", "equipmentNo": "eq1"},
            headers=auth_headers,
        )
        assert resp.status == 500
