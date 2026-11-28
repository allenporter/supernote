import math
from pathlib import Path
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.client import Client
from supernote.client.exceptions import (
    ApiException,
    BadRequestException,
    NotFoundException,
)
from supernote.client.extended import ExtendedClient
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
from supernote.server.components.conversion import CONVERSION_SERVICE_KEY
from supernote.server.components.summary import SUMMARY_SERVICE_KEY
from supernote.server.components.summary.service import DEFAULT_SUMMARY_PAGE_SIZE
from supernote.server.components.transcript import TRANSCRIPT_SERVICE_KEY
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.summary import SummaryDO, SummaryTranscriptDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.exceptions import SupernoteError
from supernote.server.keys import (
    BLOB_STORAGE_KEY,
    URL_SIGNER_KEY,
    USER_SERVICE_KEY,
)
from tests.fixtures.server import TEST_USERNAME

DIGEST_MARK = "schaefer-dev/garmin_connect_20260016.pdf.mark"


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


async def test_extended_file_summary_list_invalid_json(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    resp = await client.post(
        "/api/extended/file/summary/list",
        data="invalid json",
        headers=auth_headers,
    )
    assert resp.status == 400


async def test_extended_file_summary_list_invalid_dto(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    resp = await client.post(
        "/api/extended/file/summary/list",
        json={},
        headers=auth_headers,
    )
    assert resp.status == 400


async def test_extended_file_summary_list_success(
    extended_client: ExtendedClient, summary_client: SummaryClient
) -> None:
    add_dto = AddSummaryDTO(
        parent_unique_identifier="group-1",
        unique_identifier="summary-101",
        content="Extended test content",
        file_id=101,
    )
    add_response = await summary_client.add_summary(add_dto)
    assert add_response.success

    res = await extended_client.list_summaries(file_id=101)
    assert len(res.summary_do_list) == 1
    assert res.summary_do_list[0].content == "Extended test content"
    assert res.total_records == 1


async def test_extended_file_summary_list_error(
    client: TestClient, extended_client: ExtendedClient
) -> None:
    with (
        patch.object(
            client.app[SUMMARY_SERVICE_KEY],
            "list_summaries_for_file_internal",
            side_effect=SupernoteError("Custom summary error", status_code=400),
        ),
        pytest.raises(ApiException),
    ):
        await extended_client.list_summaries(file_id=101)

    with (
        patch.object(
            client.app[SUMMARY_SERVICE_KEY],
            "list_summaries_for_file_internal",
            side_effect=ValueError("Uncaught error"),
        ),
        pytest.raises(ApiException),
    ):
        await extended_client.list_summaries(file_id=101)


async def test_summary_group_and_item_wire_ids_serialized_as_strings(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """64-bit Snowflake IDs serialize as strings (and None stays null) across summary CRUD."""
    group_resp = await client.post(
        "/api/file/add/summary/group",
        headers=auth_headers,
        json={
            "uniqueIdentifier": "a" * 32,
            "name": "Reading Highlights",
            "md5Hash": "d41d8cd98f00b204e9800998ecf8427e",
        },
    )
    assert group_resp.status == 200
    group_data = await group_resp.json()
    assert isinstance(group_data["id"], str)

    file_id_str = "750000000000000123"
    add_with_file = await client.post(
        "/api/file/add/summary",
        headers=auth_headers,
        json={
            "uniqueIdentifier": "b" * 32,
            "parentUniqueIdentifier": "a" * 32,
            "fileId": file_id_str,
            "content": "Linked excerpt",
            "sourcePath": "Note/Daily.note",
        },
    )
    assert add_with_file.status == 200
    linked_id = (await add_with_file.json())["id"]
    assert isinstance(linked_id, str)

    add_standalone = await client.post(
        "/api/file/add/summary",
        headers=auth_headers,
        json={
            "uniqueIdentifier": "c" * 32,
            "content": "Standalone digest",
        },
    )
    assert add_standalone.status == 200

    groups_payload = await (
        await client.post(
            "/api/file/query/summary/group",
            headers=auth_headers,
            json={"page": 1, "size": 0},
        )
    ).json()
    assert groups_payload["summaryDOList"][0]["id"] == group_data["id"]
    assert isinstance(groups_payload["summaryDOList"][0]["id"], str)

    items_payload = await (
        await client.post(
            "/api/file/query/summary",
            headers=auth_headers,
            json={"page": 1, "size": 0},
        )
    ).json()
    by_uuid = {row["uniqueIdentifier"]: row for row in items_payload["summaryDOList"]}
    assert by_uuid["b" * 32]["id"] == linked_id
    assert by_uuid["b" * 32]["fileId"] == file_id_str
    assert by_uuid["c" * 32]["fileId"] is None

    update_resp = await client.put(
        "/api/file/update/summary",
        headers=auth_headers,
        json={
            "id": linked_id,
            "content": "Updated excerpt",
            "parentUniqueIdentifier": "",
        },
    )
    assert update_resp.status == 200

    delete_resp = await client.delete(
        "/api/file/delete/summary",
        headers=auth_headers,
        json={"id": linked_id},
    )
    assert delete_resp.status == 200


async def test_summary_hash_and_by_id_wire_ids_serialized_as_strings(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Summary manifest (/hash) and batch lookup (/id) serialize 64-bit IDs as strings."""
    add_data = await (
        await client.post(
            "/api/file/add/summary",
            headers=auth_headers,
            json={"uniqueIdentifier": "d" * 32, "content": "Hash check"},
        )
    ).json()
    summary_id = add_data["id"]
    assert isinstance(summary_id, str)

    hash_payload = await (
        await client.post(
            "/api/file/query/summary/hash",
            headers=auth_headers,
            json={"page": 1, "size": 0},
        )
    ).json()
    assert hash_payload["summaryInfoVOList"][0]["id"] == summary_id
    assert isinstance(hash_payload["summaryInfoVOList"][0]["id"], str)

    by_id_payload = await (
        await client.post(
            "/api/file/query/summary/id",
            headers=auth_headers,
            json={"ids": [summary_id]},
        )
    ).json()
    assert by_id_payload["summaryDOList"][0]["id"] == summary_id
    assert isinstance(by_id_payload["summaryDOList"][0]["id"], str)


async def test_summary_tag_wire_ids_serialized_as_strings(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Summary tag add/query endpoints serialize 64-bit Snowflake IDs as strings."""
    add_tag = await (
        await client.post(
            "/api/file/add/summary/tag",
            headers=auth_headers,
            json={"name": "Important"},
        )
    ).json()
    assert isinstance(add_tag["id"], str)

    query_tags = await (
        await client.get("/api/file/query/summary/tag", headers=auth_headers)
    ).json()
    assert query_tags["summaryTagDOList"][0]["id"] == add_tag["id"]
    assert isinstance(query_tags["summaryTagDOList"][0]["id"], str)


async def _add_handwritten_summary(
    client: TestClient,
    summary_client: SummaryClient,
    test_data_dir: Path,
    handwrite_md5: str = "hwmd5-v1",
) -> int:
    """Store a real `.mark` blob in USER_DATA_BUCKET and create a summary pointing at it."""
    inner_name = "digest_comment.mark"
    await client.app[BLOB_STORAGE_KEY].put(
        USER_DATA_BUCKET, inner_name, (test_data_dir / DIGEST_MARK).read_bytes()
    )
    add_response = await summary_client.add_summary(
        AddSummaryDTO(
            content="Digest with handwritten comment",
            handwrite_inner_name=inner_name,
            handwrite_md5=handwrite_md5,
        )
    )
    assert add_response.id is not None
    return add_response.id


async def test_summary_to_pdf_and_png(
    client: TestClient,
    summary_client: SummaryClient,
    authenticated_client: Client,
    test_data_dir: Path,
) -> None:
    summary_id = await _add_handwritten_summary(client, summary_client, test_data_dir)

    pdf = await summary_client.summary_to_pdf(summary_id)
    assert pdf.url is not None
    assert f"/api/oss/summary/pdf/{summary_id}?" in pdf.url
    assert (await authenticated_client.get_content(pdf.url)).startswith(b"%PDF")

    png = await summary_client.summary_to_png(summary_id)
    assert [page.page_no for page in png.png_page_vo_list] == [0]
    png_bytes = await authenticated_client.get_content(png.png_page_vo_list[0].url)
    assert png_bytes.startswith(b"\x89PNG")


@pytest.mark.parametrize("method", ["summary_to_pdf", "summary_to_png"])
async def test_summary_render_without_handwriting(
    summary_client: SummaryClient,
    method: str,
) -> None:
    add_response = await summary_client.add_summary(
        AddSummaryDTO(content="Text-only digest")
    )
    assert add_response.id is not None

    with pytest.raises(NotFoundException, match="Handwriting data not found"):
        await getattr(summary_client, method)(add_response.id)


@pytest.mark.parametrize("method", ["summary_to_pdf", "summary_to_png"])
async def test_summary_render_other_users_summary(
    client: TestClient,
    summary_client: SummaryClient,
    method: str,
) -> None:
    other_user = "other@example.com"
    await client.app[USER_SERVICE_KEY].register(
        UserRegisterDTO(email=other_user, password="c" * 32)
    )
    other_summary = await client.app[SUMMARY_SERVICE_KEY].add_summary(
        other_user,
        AddSummaryDTO(
            content="Not yours",
            handwrite_inner_name="digest_comment.mark",
            handwrite_md5="hwmd5-v1",
        ),
    )

    with pytest.raises(NotFoundException):
        await getattr(summary_client, method)(other_summary.id)


async def test_summary_render_cache_keyed_by_handwrite_md5(
    client: TestClient,
    summary_client: SummaryClient,
    authenticated_client: Client,
    test_data_dir: Path,
) -> None:
    summary_id = await _add_handwritten_summary(client, summary_client, test_data_dir)
    conversion_service = client.app[CONVERSION_SERVICE_KEY]
    summary_service = client.app[SUMMARY_SERVICE_KEY]

    pdf = await summary_client.summary_to_pdf(summary_id)
    assert pdf.url is not None
    summary_v1 = await summary_service.get_summary(TEST_USERNAME, summary_id)
    stale = await conversion_service.get_summary_pdf(TEST_USERNAME, summary_v1)
    assert stale is not None
    await client.app[BLOB_STORAGE_KEY].put(
        CACHE_BUCKET, stale.storage_key, b"stale render"
    )
    assert await authenticated_client.get_content(pdf.url) == b"stale render"

    await summary_client.update_summary(
        UpdateSummaryDTO(id=summary_id, handwrite_md5="hwmd5-v2")
    )
    summary_v2 = await summary_service.get_summary(TEST_USERNAME, summary_id)
    assert await conversion_service.get_summary_pdf(TEST_USERNAME, summary_v2) is None
    with pytest.raises(ApiException):
        await authenticated_client.get_content(pdf.url)

    fresh = await summary_client.summary_to_pdf(summary_id)
    assert fresh.url is not None
    assert (await authenticated_client.get_content(fresh.url)).startswith(b"%PDF")


async def test_summary_to_pdf_with_static_api_key(
    client: TestClient,
    summary_client: SummaryClient,
    test_data_dir: Path,
) -> None:
    summary_id = await _add_handwritten_summary(client, summary_client, test_data_dir)
    user_service = client.app[USER_SERVICE_KEY]
    user_id = await user_service.get_user_id(TEST_USERNAME)
    raw_api_key, _ = await user_service.create_api_key(user_id, "n8n")
    assert raw_api_key.startswith("sn_")

    resp = await client.post(
        "/api/extended/file/summary/to/pdf",
        json={"id": summary_id},
        headers={"Authorization": f"Bearer {raw_api_key}"},
    )
    assert resp.status == 200
    url = (await resp.json())["url"]

    download = await client.get(url[url.index("/api/oss/") :])
    assert download.status == 200
    assert (await download.read()).startswith(b"%PDF")


async def test_summary_png_out_of_range_page(
    client: TestClient,
    summary_client: SummaryClient,
    authenticated_client: Client,
    test_data_dir: Path,
) -> None:
    summary_id = await _add_handwritten_summary(client, summary_client, test_data_dir)
    await summary_client.summary_to_png(summary_id)

    signed_path = await client.app[URL_SIGNER_KEY].sign(
        f"/api/oss/summary/png/{summary_id}/99", user=TEST_USERNAME, single_use=False
    )
    resp = await client.get(signed_path)
    assert resp.status == 404


@pytest.mark.parametrize("path", ["/api/oss/summary/pdf/1", "/api/oss/summary/png/1/0"])
async def test_summary_render_download_unsigned(client: TestClient, path: str) -> None:
    resp = await client.get(path)
    assert resp.status == 403
    resp = await client.get(f"{path}?signature=bogus")
    assert resp.status == 403


@pytest.mark.parametrize(
    "path", ["/api/extended/file/summary/to/pdf", "/api/extended/file/summary/to/png"]
)
@pytest.mark.parametrize("body", [b"not json", b"{}"])
async def test_summary_render_invalid_request(
    client: TestClient, auth_headers: dict[str, str], path: str, body: bytes
) -> None:
    resp = await client.post(
        path,
        data=body,
        headers={**auth_headers, "Content-Type": "application/json"},
    )
    assert resp.status == 400


@pytest.mark.parametrize("method", ["summary_to_pdf", "summary_to_png"])
async def test_summary_render_unsafe_handwrite_md5(
    client: TestClient,
    summary_client: SummaryClient,
    test_data_dir: Path,
    method: str,
) -> None:
    summary_id = await _add_handwritten_summary(
        client, summary_client, test_data_dir, handwrite_md5="../escape"
    )
    with pytest.raises(BadRequestException):
        await getattr(summary_client, method)(summary_id)


async def test_extended_list_digests_returns_inline_transcripts_and_filters(
    client: TestClient,
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
) -> None:
    user_id = await client.app[USER_SERVICE_KEY].get_user_id(TEST_USERNAME)
    assert user_id is not None

    async with session_manager.session() as session:
        d1 = SummaryDO(
            user_id=user_id,
            file_id=7001,
            parent_unique_identifier="cat-books",
            unique_identifier="http-digest-1",
            name="Chapter 1",
            source_path="/Document/Book.pdf",
            content="Highlighted excerpt",
            comment_str="Typed comment",
            handwrite_inner_name="hw1.mark",
            handwrite_md5="md5_current",
            tags="reading, key",
            is_summary_group=False,
            is_deleted=False,
        )
        d2 = SummaryDO(
            user_id=user_id,
            file_id=7002,
            parent_unique_identifier="cat-ai",
            unique_identifier="http-digest-2",
            name="AI Note Summary",
            content="Generated summary body",
            handwrite_inner_name="hw2.mark",
            handwrite_md5="md5_v2",
            is_summary_group=False,
            is_deleted=False,
        )
        d3 = SummaryDO(
            user_id=user_id,
            file_id=None,
            parent_unique_identifier="cat-books",
            unique_identifier="http-digest-3",
            name="Standalone Digest",
            content="Text only digest",
            is_summary_group=False,
            is_deleted=False,
        )
        session.add_all([d1, d2, d3])
        await session.flush()
        d1_id = int(d1.id)
        d2_id = int(d2.id)
        d3_id = int(d3.id)
        session.add_all(
            [
                SummaryTranscriptDO(
                    user_id=user_id,
                    summary_id=d1_id,
                    handwrite_md5="md5_current",
                    text_content="Transcribed margin note",
                    model_id="ocr-v1",
                ),
                SummaryTranscriptDO(
                    user_id=user_id,
                    summary_id=d2_id,
                    handwrite_md5="md5_stale",
                    text_content="Stale transcript",
                    model_id="ocr-v1",
                ),
            ]
        )
        await session.commit()

    all_resp = await extended_client.list_digests()
    assert all_resp.success
    assert all_resp.total == 3
    by_id = {d.id: d for d in all_resp.digests}
    assert by_id[d1_id].category_id == "cat-books"
    assert by_id[d1_id].tags == ["reading", "key"]
    hw1 = by_id[d1_id].handwriting
    assert hw1 is not None
    assert hw1.md5 == "md5_current"
    assert hw1.transcript == "Transcribed margin note"
    assert hw1.model_id == "ocr-v1"
    hw2 = by_id[d2_id].handwriting
    assert hw2 is not None
    assert hw2.md5 == "md5_v2"
    assert hw2.transcript is None
    assert by_id[d3_id].handwriting is None

    by_file = await extended_client.list_digests(file_id=7001)
    assert by_file.total == 1
    assert [d.id for d in by_file.digests] == [d1_id]

    by_category = await extended_client.list_digests(category_id="cat-books")
    assert by_category.total == 2
    assert {d.id for d in by_category.digests} == {d1_id, d3_id}

    paged = await extended_client.list_digests(limit=1, offset=1)
    assert paged.total == 3
    assert paged.limit == 1
    assert paged.offset == 1
    assert len(paged.digests) == 1


async def test_extended_list_digests_invalid_file_id_returns_400(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    resp = await client.get(
        "/api/extended/digests?fileId=not-a-number",
        headers=auth_headers,
    )
    assert resp.status == 400


async def test_extended_list_digests_resolves_author_and_orders_by_last_modified(
    client: TestClient,
    auth_headers: dict[str, str],
    extended_client: ExtendedClient,
) -> None:
    for payload in [
        {
            "uniqueIdentifier": "meta-author-digest",
            "content": "Metadata author fallback",
            "metadata": '{"author": "Edsger Dijkstra"}',
            "lastModifiedTime": 1700000002000,
        },
        {
            "uniqueIdentifier": "top-author-digest",
            "content": "Top-level author wins",
            "author": "Grace Hopper",
            "metadata": '{"author": "Ignored Author"}',
            "lastModifiedTime": 1700000003000,
        },
        {
            "uniqueIdentifier": "malformed-meta-digest",
            "content": "Malformed metadata ignored",
            "metadata": "not-json",
            "lastModifiedTime": 1700000001000,
        },
    ]:
        resp = await client.post(
            "/api/file/add/summary",
            headers=auth_headers,
            json=payload,
        )
        assert resp.status == 200

    digests = await extended_client.list_digests()
    assert digests.total == 3
    assert [d.unique_identifier for d in digests.digests] == [
        "top-author-digest",
        "meta-author-digest",
        "malformed-meta-digest",
    ]
    assert [d.author for d in digests.digests] == [
        "Grace Hopper",
        "Edsger Dijkstra",
        None,
    ]
    assert [d.update_time for d in digests.digests] == [
        1700000003000,
        1700000002000,
        1700000001000,
    ]


async def test_extended_export_digests_markdown_and_filters(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """GET /api/extended/digests/export renders grouped Markdown and validates format."""
    # Empty export
    empty_resp = await client.get("/api/extended/digests/export", headers=auth_headers)
    assert empty_resp.status == 200
    assert empty_resp.content_type == "text/markdown"
    assert 'filename="digests.md"' in empty_resp.headers["Content-Disposition"]
    assert "_No digests found._" in await empty_resp.text()

    # Unsupported format returns 400
    bad_resp = await client.get(
        "/api/extended/digests/export?format=xml", headers=auth_headers
    )
    assert bad_resp.status == 400

    # Seed two digests (one with handwriting OCR transcript, one in another category)
    cat_a = "a" * 32
    cat_b = "b" * 32
    r1 = await client.post(
        "/api/file/add/summary",
        headers=auth_headers,
        json={
            "uniqueIdentifier": "export-digest-1",
            "parentUniqueIdentifier": cat_a,
            "content": "Simplicity is prerequisite for reliability.",
            "commentStr": "Apply to sync layer",
            "author": "Edsger Dijkstra",
            "sourcePath": "Document/Papers/Reliability.pdf",
            "tags": "classic, systems",
            "handwriteInnerName": "hw-export-1",
            "handwriteMD5": "hw-export-md5-1",
            "lastModifiedTime": 1700000000000,
        },
    )
    assert r1.status == 200
    summary_id = int((await r1.json())["id"])

    r2 = await client.post(
        "/api/file/add/summary",
        headers=auth_headers,
        json={
            "uniqueIdentifier": "export-digest-2",
            "parentUniqueIdentifier": cat_b,
            "content": "Standalone note",
            "lastModifiedTime": 1700000001000,
        },
    )
    assert r2.status == 200

    user_id = await client.app[USER_SERVICE_KEY].get_user_id(TEST_USERNAME)
    assert user_id is not None
    await client.app[TRANSCRIPT_SERVICE_KEY].upsert_summary_transcript(
        user_id=user_id,
        summary_id=summary_id,
        handwrite_md5="hw-export-md5-1",
        text_content="Keep state machines minimal",
        model_id="gemini-2.5-flash",
    )

    resp = await client.get("/api/extended/digests/export", headers=auth_headers)
    assert resp.status == 200
    body = await resp.text()
    assert "## Reliability.pdf" in body
    assert "Source: `Document/Papers/Reliability.pdf`" in body
    assert "Simplicity is prerequisite for reliability." in body
    assert "> Apply to sync layer" in body
    assert "**Handwritten annotation:**\n\nKeep state machines minimal" in body
    assert "Edsger Dijkstra · #classic #systems · 2023-11-14" in body
    assert "## Standalone Digests" in body
    assert "Standalone note" in body

    filtered = await client.get(
        f"/api/extended/digests/export?categoryId={cat_a}", headers=auth_headers
    )
    assert filtered.status == 200
    filtered_body = await filtered.text()
    assert "Simplicity is prerequisite for reliability." in filtered_body
    assert "Standalone note" not in filtered_body

    # Invalid fileId returns 400
    bad_file_resp = await client.get(
        "/api/extended/digests/export?fileId=not-an-int", headers=auth_headers
    )
    assert bad_file_resp.status == 400

    # Other user's export never sees this user's digests
    other_user = "export-other@example.com"
    await client.app[USER_SERVICE_KEY].register(
        UserRegisterDTO(email=other_user, password="c" * 32)
    )
    await client.app[SUMMARY_SERVICE_KEY].add_summary(
        other_user,
        AddSummaryDTO(content="Private other-user digest"),
    )
    resp_again = await client.get("/api/extended/digests/export", headers=auth_headers)
    assert "Private other-user digest" not in await resp_again.text()
