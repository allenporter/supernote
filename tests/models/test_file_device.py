"""Tests for file device DTO models."""

from supernote.models.file_device import (
    CapacityLocalDTO,
    SynchronousEndLocalDTO,
    SynchronousStartLocalDTO,
)


def test_file_device_dtos_optional_equipment_no() -> None:
    """Verify that equipmentNo is optional in sync and capacity DTOs."""
    dto1 = CapacityLocalDTO.from_dict({})
    assert dto1.equipment_no is None

    dto2 = SynchronousStartLocalDTO.from_dict({})
    assert dto2.equipment_no is None

    dto3 = SynchronousEndLocalDTO.from_dict({"flag": "true"})
    assert dto3.equipment_no is None
    assert dto3.flag == "true"
