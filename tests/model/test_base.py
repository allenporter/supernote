"""Tests for base models."""

from supernote.models.base import create_error_response


def test_create_error_response() -> None:
    """Test create_error_response."""
    error_response = create_error_response("test error")
    assert error_response.error_msg == "test error"
    assert error_response.error_code is None
