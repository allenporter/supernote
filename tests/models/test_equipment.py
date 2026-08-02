"""Tests for Equipment data models."""

from supernote.models.equipment import (
    ActivateEquipmentDTO,
    BindEquipmentDTO,
    BindStatusVO,
    EquipmentManualDTO,
    EquipmentManualVO,
    EquipmentVO,
    QueryEquipmentDTO,
    QueryEquipmentVO,
    UnbindEquipmentDTO,
    UserEquipmentDTO,
    UserEquipmentListVO,
    UserEquipmentVO,
)


def test_activate_equipment_dto() -> None:
    dto = ActivateEquipmentDTO(equipment_no="SN123")
    assert dto.equipment_no == "SN123"
    assert dto.to_dict() == {"equipmentNo": "SN123"}
    assert (
        ActivateEquipmentDTO.from_dict({"equipmentNo": "SN456"}).equipment_no == "SN456"
    )


def test_bind_equipment_dto() -> None:
    dto = BindEquipmentDTO(
        equipment_no="SN123",
        account="user@example.com",
        name="MyDevice",
        total_capacity="32GB",
        label=["tag1", "tag2"],
    )
    assert dto.equipment_no == "SN123"
    assert dto.label == ["tag1", "tag2"]

    data = dto.to_dict()
    assert data["equipmentNo"] == "SN123"
    assert data["label"] == ["tag1", "tag2"]

    dto2 = BindEquipmentDTO.from_dict(data)
    assert dto2 == dto


def test_unbind_equipment_dto() -> None:
    dto = UnbindEquipmentDTO(equipment_no="SN123")
    assert dto.to_dict() == {"equipmentNo": "SN123"}


def test_query_equipment_dto() -> None:
    dto = QueryEquipmentDTO(
        page_no="1",
        page_size="20",
        equipment_number="SN123",
    )
    assert dto.page_no == "1"
    assert dto.to_dict()["pageNo"] == "1"


def test_user_equipment_dto() -> None:
    dto = UserEquipmentDTO(equipment_no="SN123")
    assert dto.to_dict()["equipmentNo"] == "SN123"


def test_equipment_manual_dto() -> None:
    dto = EquipmentManualDTO(equipment_no="SN123", language="EN", logic_version="1.0")
    assert dto.language == "EN"
    assert dto.to_dict()["logicVersion"] == "1.0"


def test_bind_status_vo() -> None:
    vo = BindStatusVO(bind_status=True)
    assert vo.bind_status is True
    assert vo.to_dict()["bindStatus"] is True


def test_equipment_manual_vo() -> None:
    vo = EquipmentManualVO(success=True, url="http://example.com/manual.pdf")
    assert vo.url == "http://example.com/manual.pdf"
    assert vo.to_dict()["url"] == "http://example.com/manual.pdf"


def test_equipment_vo() -> None:
    vo = EquipmentVO(equipment_number="SN123", firmware_version="2.0")
    assert vo.equipment_number == "SN123"
    assert vo.firmware_version == "2.0"
    assert vo.to_dict()["equipmentNumber"] == "SN123"


def test_user_equipment_vo() -> None:
    vo = UserEquipmentVO(equipment_number="SN123", user_id=1001)
    assert vo.equipment_number == "SN123"
    assert vo.user_id == 1001
    assert vo.to_dict()["userId"] == 1001


def test_user_equipment_list_vo() -> None:
    item1 = UserEquipmentVO(equipment_number="SN1", user_id=1)
    item2 = UserEquipmentVO(equipment_number="SN2", user_id=2)
    vo = UserEquipmentListVO(equipment_vo_list=[item1, item2])
    assert len(vo.equipment_vo_list) == 2
    assert vo.to_dict()["equipmentVOList"][0]["equipmentNumber"] == "SN1"


def test_query_equipment_vo() -> None:
    vo = QueryEquipmentVO(equipment_number="SN123", user_id="u1")
    assert vo.equipment_number == "SN123"
    assert vo.to_dict()["userId"] == "u1"
