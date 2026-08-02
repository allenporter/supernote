"""Tests for Auth data models."""

from supernote.models.auth import (
    EmailDTO,
    LoginDTO,
    LoginMethod,
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


def test_login_dto_accepts_a_numeric_login_method() -> None:
    """The Partner apps send loginMethod as a JSON number."""
    dto = LoginDTO.from_dict(
        {
            "account": "user@example.com",
            "password": "deadbeef",
            "timestamp": "1785468843354",
            "loginMethod": 2,
        }
    )
    assert dto.login_method is LoginMethod.EMAIL


def test_login_dto_accepts_a_string_login_method() -> None:
    """The device sends it as a string."""
    dto = LoginDTO.from_dict(
        {
            "account": "user@example.com",
            "password": "deadbeef",
            "timestamp": "1785468843354",
            "loginMethod": "2",
        }
    )
    assert dto.login_method is LoginMethod.EMAIL
