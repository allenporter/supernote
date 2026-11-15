"""Unit tests for supernote.server.exceptions module."""

from supernote.models.base import ErrorCode
from supernote.server.exceptions import (
    CursorExpiredError,
    FileNotFound,
    InvalidInputError,
    ParentNotFound,
)


def test_parent_not_found() -> None:
    """Verify ParentNotFound default message, status code, error code, and inheritance."""
    err = ParentNotFound()
    assert isinstance(err, FileNotFound)
    assert err.message == "Parent directory is missing"
    assert err.status_code == 404
    assert err.error_code == ErrorCode.PATH_NOT_FOUND.value

    custom_err = ParentNotFound("Custom parent missing message")
    assert custom_err.message == "Custom parent missing message"


def test_cursor_expired_and_invalid_input_errors() -> None:
    """Verify CursorExpiredError (410) and InvalidInputError (400) HTTP status mapping."""
    expired = CursorExpiredError("Cursor 5 expired")
    assert expired.status_code == 410
    assert expired.error_code == ErrorCode.BAD_REQUEST.value

    invalid = InvalidInputError("Invalid cursor")
    assert invalid.status_code == 400
    assert invalid.error_code == ErrorCode.BAD_REQUEST.value
