"""Tests for Auth data models."""

from supernote.models.auth import (
    EmailDTO,
    ValidCodeDTO,
)


def test_email_dto() -> None:
    dto = EmailDTO(email="test@example.com", language="en")
    data = dto.to_dict()
    assert data["email"] == "test@example.com"
    assert data["language"] == "en"


def test_valid_code_dto() -> None:
    dto = ValidCodeDTO(valid_code_key="key123", valid_code="123456")
    data = dto.to_dict()
    assert data["validCodeKey"] == "key123"
    assert data["validCode"] == "123456"
