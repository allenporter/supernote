"""Tests for Summary data models."""

from supernote.models.summary import (
    SummaryItem,
    SummaryTagItem,
    SummaryInfoItem,
    AddSummaryTagDTO,
    AddSummaryTagVO,
    UpdateSummaryTagDTO,
    DeleteSummaryTagDTO,
    QuerySummaryTagVO,
    AddSummaryGroupDTO,
    AddSummaryGroupVO,
    UpdateSummaryGroupDTO,
    DeleteSummaryGroupDTO,
    QuerySummaryGroupDTO,
    QuerySummaryGroupVO,
    AddSummaryDTO,
    AddSummaryVO,
    UpdateSummaryDTO,
    DeleteSummaryDTO,
    QuerySummaryDTO,
    QuerySummaryVO,
    QuerySummaryByIdVO,
    QuerySummaryMD5HashVO,
    DownloadSummaryDTO,
    DownloadSummaryVO,
    UploadSummaryApplyDTO,
    UploadSummaryApplyVO,
)


def test_summary_item() -> None:
    item = SummaryItem(
        id=1,
        file_id=100,
        name="Test Summary",
        user_id=10,
        unique_identifier="uniq123",
        metadata='{"key": "value"}'
    )
    data = item.to_dict()
    assert data["id"] == 1
    assert data["fileId"] == 100
    assert data["name"] == "Test Summary"
    assert data["userId"] == 10
    assert data["uniqueIdentifier"] == "uniq123"


def test_summary_tag_item() -> None:
    item = SummaryTagItem(id=1, name="Tag1", user_id=5)
    data = item.to_dict()
    assert data["id"] == 1
    assert data["name"] == "Tag1"
    assert data["userId"] == 5


def test_add_summary_tag_dto() -> None:
    dto = AddSummaryTagDTO(name="Important")
    data = dto.to_dict()
    assert data["name"] == "Important"


def test_query_summary_tag_vo() -> None:
    tag = SummaryTagItem(id=1, name="Tag1")
    vo = QuerySummaryTagVO(summary_tag_do_list=[tag])
    data = vo.to_dict()
    assert len(data["summaryTagDOList"]) == 1
    assert data["summaryTagDOList"][0]["name"] == "Tag1"


def test_add_summary_group_dto() -> None:
    dto = AddSummaryGroupDTO(
        unique_identifier="group123",
        name="Study Group",
        md5_hash="hash123"
    )
    data = dto.to_dict()
    assert data["uniqueIdentifier"] == "group123"
    assert data["name"] == "Study Group"
    assert data["md5Hash"] == "hash123"


def test_update_summary_group_dto() -> None:
    dto = UpdateSummaryGroupDTO(
        id=5,
        md5_hash="newhash",
        comment_str="Updated comment"
    )
    data = dto.to_dict()
    assert data["id"] == 5
    assert data["md5Hash"] == "newhash"
    assert data["commentStr"] == "Updated comment"


def test_add_summary_dto() -> None:
    dto = AddSummaryDTO(
        unique_identifier="sum1",
        file_id=50,
        content="Summary Content",
        tags="tag1,tag2"
    )
    data = dto.to_dict()
    assert data["uniqueIdentifier"] == "sum1"
    assert data["fileId"] == 50
    assert data["content"] == "Summary Content"
    assert data["tags"] == "tag1,tag2"


def test_query_summary_vo() -> None:
    item = SummaryItem(id=1, name="S1")
    vo = QuerySummaryVO(
        total_records=1,
        total_pages=1,
        summary_do_list=[item]
    )
    data = vo.to_dict()
    assert data["totalRecords"] == 1
    assert data["totalPages"] == 1
    assert data["summaryDOList"][0]["name"] == "S1"


def test_upload_summary_apply_dto() -> None:
    dto = UploadSummaryApplyDTO(
        file_name="summary.pdf",
        equipment_no="dev1"
    )
    data = dto.to_dict()
    assert data["fileName"] == "summary.pdf"
    assert data["equipmentNo"] == "dev1"


def test_upload_summary_apply_vo() -> None:
    vo = UploadSummaryApplyVO(
        full_upload_url="http://upload",
        inner_name="inner.pdf"
    )
    data = vo.to_dict()
    assert data["fullUploadUrl"] == "http://upload"
    assert data["innerName"] == "inner.pdf"
