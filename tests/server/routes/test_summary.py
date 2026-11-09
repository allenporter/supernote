import math
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.exceptions import ApiException
from supernote.client.summary import SummaryClient
from supernote.models.summary import (
    AddSummaryDTO,
    AddSummaryGroupDTO,
    QuerySummaryDTO,
    QuerySummaryGroupVO,
    QuerySummaryMD5HashVO,
    QuerySummaryVO,
    UpdateSummaryDTO,
    UpdateSummaryGroupDTO,
)
from supernote.models.user import UserRegisterDTO
from supernote.server.exceptions import SupernoteError
from supernote.server.keys import (
    SUMMARY_SERVICE_KEY,
    URL_SIGNER_KEY,
    USER_SERVICE_KEY,
)
from supernote.server.services.summary import DEFAULT_SUMMARY_PAGE_SIZE


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

    query_response = await summary_client.query_summaries(ids=[summary_id])
    assert query_response.success
    assert len(query_response.summary_do_list) == 1
    summary = query_response.summary_do_list[0]
    assert summary.content == "This is a test summary"
    assert summary.data_source == "TEST"
    assert summary.tags == "test,summary"
    assert summary.metadata == '{"key": "value"}'
    assert summary.creation_time is not None
    assert summary.last_modified_time is not None
    assert summary.md5_hash is not None

    update_dto = UpdateSummaryDTO(
        id=summary_id,
        content="Updated test summary",
        tags="updated",
        source_type=1,
        comment_str="Added a comment",
        comment_handwrite_name="comment_strokes.bin",
        handwrite_inner_name="inner_strokes.bin",
        handwrite_md5="strokes_md5_hash",
        author="Bob",
    )
    update_response = await summary_client.update_summary(update_dto)
    assert update_response.success

    query_response = await summary_client.query_summaries(ids=[summary_id])
    summary = query_response.summary_do_list[0]
    assert summary.content == "Updated test summary"
    assert summary.tags == "updated"
    assert summary.source_type == 1
    assert summary.comment_str == "Added a comment"
    assert summary.comment_handwrite_name == "comment_strokes.bin"
    assert summary.handwrite_inner_name == "inner_strokes.bin"
    assert summary.handwrite_md5 == "strokes_md5_hash"
    assert summary.author == "Bob"

    delete_response = await summary_client.delete_summary(summary_id)
    assert delete_response.success

    query_response = await summary_client.query_summaries(ids=[summary_id])
    assert len(query_response.summary_do_list) == 0


async def test_group_crud(summary_client: SummaryClient) -> None:
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

    query_response = await summary_client.query_groups()
    assert query_response.success
    assert [
        (g.id, g.unique_identifier, g.name) for g in query_response.summary_do_list
    ] == [(group_id, group_uuid, "Test Group")]

    update_dto = UpdateSummaryGroupDTO(
        id=group_id,
        unique_identifier=group_uuid,
        name="Updated Group",
        description="Updated description",
        metadata='{"group": 1}',
        comment_str="Group comment",
        comment_handwrite_name="group_comment_hw.bin",
        handwrite_inner_name="group_inner_hw.bin",
        md5_hash="newhash",
    )
    update_response = await summary_client.update_group(update_dto)
    assert update_response.success

    query_response = await summary_client.query_groups()
    assert [
        (
            g.id,
            g.unique_identifier,
            g.name,
            g.description,
            g.metadata,
            g.comment_str,
            g.comment_handwrite_name,
            g.handwrite_inner_name,
        )
        for g in query_response.summary_do_list
    ] == [
        (
            group_id,
            group_uuid,
            "Updated Group",
            "Updated description",
            '{"group": 1}',
            "Group comment",
            "group_comment_hw.bin",
            "group_inner_hw.bin",
        )
    ]

    delete_response = await summary_client.delete_group(group_id)
    assert delete_response.success

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
    add_dto = AddSummaryDTO(
        content="No handwriting summary",
        data_source="TEST",
    )
    add_response = await summary_client.add_summary(add_dto)
    assert add_response.id
    summary_id = add_response.id

    with pytest.raises(Exception) as exc_info:
        await summary_client.download_summary(summary_id)
    assert "404" in str(exc_info.value) or "Handwriting data not found" in str(
        exc_info.value
    )


async def test_summary_route_error_handling(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    endpoints = [
        ("post", "/api/file/add/summary/tag", {"name": "tag"}),
        ("put", "/api/file/update/summary/tag", {"id": 1, "name": "tag"}),
        ("delete", "/api/file/delete/summary/tag", {"id": 1}),
        ("get", "/api/file/query/summary/tag", None),
        ("post", "/api/file/add/summary", {"content": "c"}),
        ("put", "/api/file/update/summary", {"id": 1, "content": "c"}),
        ("delete", "/api/file/delete/summary", {"id": 1}),
        ("post", "/api/file/query/summary", {}),
        (
            "post",
            "/api/file/add/summary/group",
            {"name": "g", "uniqueIdentifier": "u", "md5Hash": "h"},
        ),
        (
            "put",
            "/api/file/update/summary/group",
            {"id": 1, "name": "g", "uniqueIdentifier": "u", "md5Hash": "h"},
        ),
        ("delete", "/api/file/delete/summary/group", {"id": 1}),
        ("post", "/api/file/query/summary/group", {}),
        ("post", "/api/file/download/summary", {"id": 9999}),
        ("post", "/api/file/query/summary/hash", {}),
        ("post", "/api/file/query/summary/id", {}),
    ]

    endpoint_method_map = {
        "/api/file/add/summary/tag": "add_tag",
        "/api/file/update/summary/tag": "update_tag",
        "/api/file/delete/summary/tag": "delete_tag",
        "/api/file/query/summary/tag": "list_tags",
        "/api/file/add/summary": "add_summary",
        "/api/file/update/summary": "update_summary",
        "/api/file/delete/summary": "delete_summary",
        "/api/file/query/summary": "list_summaries",
        "/api/file/add/summary/group": "add_group",
        "/api/file/update/summary/group": "update_group",
        "/api/file/delete/summary/group": "delete_group",
        "/api/file/query/summary/group": "list_groups",
        "/api/file/download/summary": "get_summary",
        "/api/file/query/summary/hash": "list_summary_infos",
        "/api/file/query/summary/id": "list_summaries_by_id",
    }

    for http_method, ep, payload in endpoints:
        method_name = endpoint_method_map[ep]

        # SupernoteError path -> 400
        with patch.object(
            client.app[SUMMARY_SERVICE_KEY],
            method_name,
            side_effect=SupernoteError("Err", status_code=400),
        ):
            resp = await client.request(
                http_method, ep, json=payload, headers=auth_headers
            )
            assert resp.status == 400

        # Uncaught Exception path -> 500
        with patch.object(
            client.app[SUMMARY_SERVICE_KEY],
            method_name,
            side_effect=Exception("Uncaught"),
        ):
            resp = await client.request(
                http_method, ep, json=payload, headers=auth_headers
            )
            assert resp.status == 500


async def test_upload_apply_summary_error(
    client: TestClient, summary_client: SummaryClient
) -> None:
    with (
        patch.object(
            client.app[URL_SIGNER_KEY],
            "sign",
            side_effect=SupernoteError("Sign error", status_code=400),
        ),
        pytest.raises(ApiException),
    ):
        await summary_client.upload_apply(file_name="test.txt", equipment_no="eq1")

    with (
        patch.object(
            client.app[URL_SIGNER_KEY], "sign", side_effect=Exception("Sign fail")
        ),
        pytest.raises(ApiException),
    ):
        await summary_client.upload_apply(file_name="test.txt", equipment_no="eq1")


async def test_summary_uuid_scoped_per_user(client: TestClient) -> None:
    """Verify two users can create summaries and groups with the same unique_identifier without collision."""
    user_service = client.app[USER_SERVICE_KEY]
    summary_service = client.app[SUMMARY_SERVICE_KEY]

    user_a = "user_a@example.com"
    user_b = "user_b@example.com"
    await user_service.register(UserRegisterDTO(email=user_a, password="a" * 32))
    await user_service.register(UserRegisterDTO(email=user_b, password="b" * 32))

    shared_summary_uuid = "00000000-1111-2222-3333-444444444444"
    shared_group_uuid = "00000000-1111-2222-3333-555555555555"

    item_a = await summary_service.add_summary(
        user_a,
        AddSummaryDTO(unique_identifier=shared_summary_uuid, content="User A summary"),
    )
    item_b = await summary_service.add_summary(
        user_b,
        AddSummaryDTO(unique_identifier=shared_summary_uuid, content="User B summary"),
    )
    assert item_a.unique_identifier == shared_summary_uuid
    assert item_b.unique_identifier == shared_summary_uuid
    assert item_a.content == "User A summary"
    assert item_b.content == "User B summary"

    grp_a = await summary_service.add_group(
        user_a,
        AddSummaryGroupDTO(
            unique_identifier=shared_group_uuid, name="Group A", md5_hash="ha"
        ),
    )
    grp_b = await summary_service.add_group(
        user_b,
        AddSummaryGroupDTO(
            unique_identifier=shared_group_uuid, name="Group B", md5_hash="hb"
        ),
    )
    assert grp_a.unique_identifier == shared_group_uuid
    assert grp_b.unique_identifier == shared_group_uuid
    assert grp_a.name == "Group A"
    assert grp_b.name == "Group B"


async def _seed_summaries(summary_client: SummaryClient, total_items: int) -> list[int]:
    """Create a deterministic sequence of summaries alternating between two parent groups."""
    created_ids: list[int] = []
    for idx in range(total_items):
        resp = await summary_client.add_summary(
            AddSummaryDTO(
                unique_identifier=f"sum-uuid-{total_items}-{idx}",
                parent_unique_identifier="parent-even"
                if idx % 2 == 0
                else "parent-odd",
                content=f"Digest content {idx}",
            )
        )
        assert resp.success and resp.id is not None
        created_ids.append(resp.id)
    return created_ids


@pytest.mark.parametrize("total_items", [0, 1, 5, 20, 25])
async def test_summary_unpaginated_manifest_and_batch_id_queries(
    summary_client: SummaryClient,
    total_items: int,
) -> None:
    """Verify unpaginated hash manifests and batch ID queries return the full item set."""
    created_ids = await _seed_summaries(summary_client, total_items)

    for unpaginated_dto in (QuerySummaryDTO(page=0, size=0), QuerySummaryDTO()):
        hash_resp = await summary_client.query_summary_hash(unpaginated_dto)
        assert hash_resp == QuerySummaryMD5HashVO(
            summary_info_vo_list=hash_resp.summary_info_vo_list,
            total_records=total_items,
            total_pages=1,
            current_page=1,
            page_size=total_items,
        )
        assert [item.id for item in hash_resp.summary_info_vo_list] == created_ids

    batch_resp = await summary_client.query_summary_id(QuerySummaryDTO(ids=created_ids))
    assert [item.id for item in batch_resp.summary_do_list] == created_ids

    ids_query_resp = await summary_client.query_summaries(ids=created_ids)
    assert ids_query_resp == QuerySummaryVO(
        summary_do_list=ids_query_resp.summary_do_list,
        total_records=total_items,
        total_pages=1,
        current_page=1,
        page_size=total_items,
    )
    assert [item.id for item in ids_query_resp.summary_do_list] == created_ids


@pytest.mark.parametrize("total_items", [0, 1, 5, 20, 25])
async def test_summary_paginated_queries_reconstruct_items(
    summary_client: SummaryClient,
    total_items: int,
) -> None:
    """Verify paginating summaries with variable page sizes reconstructs the exact item set."""
    created_ids = await _seed_summaries(summary_client, total_items)

    for requested_size in (None, 1, 4, 10, 20, 50):
        effective_size = (
            DEFAULT_SUMMARY_PAGE_SIZE if requested_size is None else requested_size
        )
        expected_total_pages = max(1, math.ceil(total_items / effective_size))

        collected_summary_ids: list[int] = []
        for page in range(1, expected_total_pages + 1):
            page_resp = await summary_client.query_summaries(
                page=page, size=requested_size
            )
            assert page_resp == QuerySummaryVO(
                summary_do_list=page_resp.summary_do_list,
                total_records=total_items,
                total_pages=expected_total_pages,
                current_page=page,
                page_size=effective_size,
            )
            assert len(page_resp.summary_do_list) <= effective_size
            collected_summary_ids.extend(
                item.id for item in page_resp.summary_do_list if item.id is not None
            )
        assert collected_summary_ids == created_ids

        out_of_range_page = expected_total_pages + 1
        past_end = await summary_client.query_summaries(
            page=out_of_range_page, size=requested_size
        )
        assert past_end == QuerySummaryVO(
            summary_do_list=[],
            total_records=total_items,
            total_pages=expected_total_pages,
            current_page=out_of_range_page,
            page_size=effective_size,
        )


@pytest.mark.parametrize("total_items", [0, 1, 5, 20, 25])
async def test_summary_hash_and_id_paginated_queries(
    summary_client: SummaryClient,
    total_items: int,
) -> None:
    """Verify explicit page sizes on /query/summary/hash and /query/summary/id reconstruct the full item set."""
    created_ids = await _seed_summaries(summary_client, total_items)

    for page_size in (1, 4, 10, 20, 50):
        expected_total_pages = max(1, math.ceil(total_items / page_size))
        collected_hash_ids: list[int] = []
        collected_by_id_ids: list[int] = []

        for page in range(1, expected_total_pages + 1):
            hash_page = await summary_client.query_summary_hash(
                QuerySummaryDTO(page=page, size=page_size)
            )
            assert hash_page == QuerySummaryMD5HashVO(
                summary_info_vo_list=hash_page.summary_info_vo_list,
                total_records=total_items,
                total_pages=expected_total_pages,
                current_page=page,
                page_size=page_size,
            )
            collected_hash_ids.extend(
                item.id
                for item in hash_page.summary_info_vo_list
                if item.id is not None
            )

            by_id_page = await summary_client.query_summary_id(
                QuerySummaryDTO(ids=created_ids, page=page, size=page_size)
            )
            collected_by_id_ids.extend(
                item.id for item in by_id_page.summary_do_list if item.id is not None
            )

        assert collected_hash_ids == created_ids
        assert collected_by_id_ids == created_ids


@pytest.mark.parametrize("total_items", [0, 1, 5, 20, 25])
async def test_summary_filtered_pagination_by_parent_uuid(
    summary_client: SummaryClient,
    total_items: int,
) -> None:
    """Verify parent_uuid-filtered pagination returns accurate filtered counts and items."""
    created_ids = await _seed_summaries(summary_client, total_items)
    expected_even_ids = [created_ids[i] for i in range(0, total_items, 2)]

    for page_size in (2, 7, 25):
        expected_pages = max(1, math.ceil(len(expected_even_ids) / page_size))
        collected_even_ids: list[int] = []
        for page in range(1, expected_pages + 1):
            even_resp = await summary_client.query_summaries(
                parent_uuid="parent-even", page=page, size=page_size
            )
            assert even_resp == QuerySummaryVO(
                summary_do_list=even_resp.summary_do_list,
                total_records=len(expected_even_ids),
                total_pages=expected_pages,
                current_page=page,
                page_size=page_size,
            )
            collected_even_ids.extend(
                item.id for item in even_resp.summary_do_list if item.id is not None
            )
        assert collected_even_ids == expected_even_ids


@pytest.mark.parametrize("total_groups", [0, 1, 5, 20, 23])
async def test_summary_group_pagination_scenarios(
    summary_client: SummaryClient,
    total_groups: int,
) -> None:
    """Verify group queries with variable item counts and page sizes reconstruct the full group list."""
    created_group_ids: list[int] = []
    for idx in range(total_groups):
        resp = await summary_client.add_group(
            AddSummaryGroupDTO(
                unique_identifier=f"group-page-uuid-{total_groups}-{idx}",
                name=f"Group {idx}",
                md5_hash=f"hash-{idx}",
            )
        )
        assert resp.success and resp.id is not None
        created_group_ids.append(resp.id)

    unpaginated = await summary_client.query_groups(page=0, size=0)
    assert unpaginated == QuerySummaryGroupVO(
        summary_do_list=unpaginated.summary_do_list,
        total_records=total_groups,
        total_pages=1,
        current_page=1,
        page_size=total_groups,
    )
    assert [g.id for g in unpaginated.summary_do_list] == created_group_ids

    for requested_size in (None, 1, 2, 6, 20, 30):
        effective_size = (
            DEFAULT_SUMMARY_PAGE_SIZE if requested_size is None else requested_size
        )
        expected_total_pages = max(1, math.ceil(total_groups / effective_size))
        collected_group_ids: list[int] = []
        for page in range(1, expected_total_pages + 1):
            page_resp = await summary_client.query_groups(
                page=page, size=requested_size
            )
            assert page_resp == QuerySummaryGroupVO(
                summary_do_list=page_resp.summary_do_list,
                total_records=total_groups,
                total_pages=expected_total_pages,
                current_page=page,
                page_size=effective_size,
            )
            assert len(page_resp.summary_do_list) <= effective_size
            collected_group_ids.extend(
                g.id for g in page_resp.summary_do_list if g.id is not None
            )
        assert collected_group_ids == created_group_ids

        out_of_range_page = expected_total_pages + 1
        past_end = await summary_client.query_groups(
            page=out_of_range_page, size=requested_size
        )
        assert past_end == QuerySummaryGroupVO(
            summary_do_list=[],
            total_records=total_groups,
            total_pages=expected_total_pages,
            current_page=out_of_range_page,
            page_size=effective_size,
        )
