"""Tests for System data models."""

import pytest

from supernote.models.system import (
    DictionaryQueryDTO,
    DictionaryVO,
    EmailServerDTO,
    EmailServerVO,
    FileChunkVO,
    FileUploadApplyLocalVO,
    PageDTO,
    RecycleBinCleanupDTO,
    RecycleBinCleanupVO,
    ReferenceInfoVO,
    ReferenceQueryDTO,
    ReferenceRespVO,
)


def test_page_dto() -> None:
    dto = PageDTO(page_no=2, page_size=20)
    data = dto.to_dict()
    assert data["pageNo"] == 2
    assert data["pageSize"] == 20
    assert data["sortField"] is None


def test_email_server_dto() -> None:
    dto = EmailServerDTO(
        smtp_server="smtp.example.com",
        port="587",
        username="user",
        password="password",
        encryption="TLS",
    )
    data = dto.to_dict()
    assert data["smtpServer"] == "smtp.example.com"
    assert data["port"] == "587"


def test_email_server_vo() -> None:
    vo = EmailServerVO(smtp_server="smtp.example.com", flag="Y")
    data = vo.to_dict()
    assert data["smtpServer"] == "smtp.example.com"
    assert data["flag"] == "Y"


def test_file_upload_apply_local_vo() -> None:
    vo = FileUploadApplyLocalVO(
        equipment_no="dev1", bucket_name="supernote", full_upload_url="http://upload"
    )
    data = vo.to_dict()
    assert data["equipmentNo"] == "dev1"
    assert data["bucketName"] == "supernote"
    assert data["fullUploadUrl"] == "http://upload"


def test_file_chunk_vo() -> None:
    vo = FileChunkVO(upload_id="up123", part_number=1, total_chunks=5)
    data = vo.to_dict()
    assert data["uploadId"] == "up123"
    assert data["partNumber"] == 1


def test_dictionary_query_dto() -> None:
    dto = DictionaryQueryDTO(name="STATUS", value="1")
    data = dto.to_dict()
    assert data["name"] == "STATUS"
    assert data["value"] == "1"


def test_dictionary_vo() -> None:
    vo = DictionaryVO(
        id=1, name="STATUS", value="ACTIVE", value_cn="Active", op_user="admin"
    )
    data = vo.to_dict()
    assert data["id"] == 1
    assert data["valueCn"] == "Active"


def test_reference_query_dto() -> None:
    dto = ReferenceQueryDTO(name="REF_CODE")
    data = dto.to_dict()
    assert data["name"] == "REF_CODE"


def test_reference_resp_vo() -> None:
    # Test nested if ReferenceInfoVO works
    info = ReferenceInfoVO(serial="S1", name="N1", value="V1")
    vo = ReferenceRespVO(param_list=[info], random="RND")

    data = vo.to_dict()
    assert data["random"] == "RND"
    assert data["paramList"][0]["serial"] == "S1"

    vo2 = ReferenceRespVO.from_dict(data)
    assert vo2.param_list[0].name == "N1"


def test_recycle_bin_cleanup_dto() -> None:
    """Verify RecycleBinCleanupDTO serialization and deserialization with aliases."""
    default_dto = RecycleBinCleanupDTO()
    assert default_dto.retention_days is None
    assert default_dto.batch_size is None
    assert default_dto.to_dict() == {}

    custom_dto = RecycleBinCleanupDTO(retention_days=15, batch_size=50)
    data = custom_dto.to_dict()
    assert data == {"retentionDays": 15, "batchSize": 50}

    # Deserialization by alias (camelCase)
    from_alias = RecycleBinCleanupDTO.from_dict({"retentionDays": 30, "batchSize": 100})
    assert from_alias.retention_days == 30
    assert from_alias.batch_size == 100

    # Deserialization not by alias (snake_case)
    from_snake = RecycleBinCleanupDTO.from_dict({"retention_days": 7, "batch_size": 25})
    assert from_snake.retention_days == 7
    assert from_snake.batch_size == 25

    # Validation: negative retention_days
    with pytest.raises(ValueError, match="retention_days cannot be negative"):
        RecycleBinCleanupDTO(retention_days=-1)
    with pytest.raises(ValueError, match="retention_days cannot be negative"):
        RecycleBinCleanupDTO.from_dict({"retentionDays": -1})

    # Validation: non-positive batch_size
    with pytest.raises(ValueError, match="batch_size must be positive"):
        RecycleBinCleanupDTO(batch_size=0)
    with pytest.raises(ValueError, match="batch_size must be positive"):
        RecycleBinCleanupDTO.from_dict({"batchSize": -5})


def test_recycle_bin_cleanup_vo() -> None:
    """Verify RecycleBinCleanupVO default attributes and full-structure serialization roundtrip."""
    default_vo = RecycleBinCleanupVO()
    assert default_vo.success is True
    assert default_vo.purged_count == 0
    assert default_vo.bytes_freed == 0
    assert default_vo.to_dict() == {
        "success": True,
        "purged_count": 0,
        "bytes_freed": 0,
    }

    custom_vo = RecycleBinCleanupVO(purged_count=12, bytes_freed=4096)
    data = custom_vo.to_dict()
    assert data == {
        "success": True,
        "purged_count": 12,
        "bytes_freed": 4096,
    }

    deserialized = RecycleBinCleanupVO.from_dict(data)
    assert deserialized.success is True
    assert deserialized.purged_count == 12
    assert deserialized.bytes_freed == 4096
