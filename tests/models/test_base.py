"""Tests for base models."""

import pytest

from supernote.models.auth import LoginMethod
from supernote.models.base import BooleanEnum, create_error_response


def test_create_error_response() -> None:
    """Test create_error_response."""
    error_response = create_error_response("test error")
    assert error_response.error_msg == "test error"
    assert error_response.error_code is None


def test_enum_accepts_a_string_code() -> None:
    """Codes are defined as strings and the device sends them that way."""
    assert LoginMethod("2") is LoginMethod.EMAIL


def test_enum_accepts_a_json_number() -> None:
    """The official Partner apps send {"loginMethod": 2}."""
    assert LoginMethod(1) is LoginMethod.PHONE
    assert LoginMethod(2) is LoginMethod.EMAIL
    assert LoginMethod(3) is LoginMethod.WECHAT


def test_enum_rejects_an_unknown_code() -> None:
    with pytest.raises(ValueError):
        LoginMethod(9)
    with pytest.raises(ValueError):
        LoginMethod("9")


def test_enum_rejects_a_bool() -> None:
    """A bool is not one of the codes."""
    with pytest.raises(ValueError):
        LoginMethod(True)


def test_non_numeric_enum_is_unaffected() -> None:
    assert BooleanEnum("Y") is BooleanEnum.YES
    with pytest.raises(ValueError):
        BooleanEnum(1)
