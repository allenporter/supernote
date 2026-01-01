"""Tests for System data models."""

from supernote.models.system import (
    DictionaryQueryDTO,
    DictionaryVO,
    EmailServerDTO,
    EmailServerVO,
    FileChunkVO,
    FileUploadApplyLocalVO,
    PageDTO,
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
    from supernote.models.system import ReferenceInfoVO

    info = ReferenceInfoVO(serial="S1", name="N1", value="V1")
    vo = ReferenceRespVO(param_list=[info], random="RND")

    data = vo.to_dict()
    assert data["random"] == "RND"
    assert data["paramList"][0]["serial"] == "S1"

    vo2 = ReferenceRespVO.from_dict(data)
    assert vo2.param_list[0].name == "N1"
