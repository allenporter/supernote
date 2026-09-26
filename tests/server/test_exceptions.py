"""Unit tests for supernote.server.exceptions module."""

import json

from supernote.models.base import ErrorCode
from supernote.server.exceptions import (
    AccessDenied,
    DatabaseError,
    FileAlreadyExists,
    FileError,
    FileNotFound,
    HashMismatch,
    InvalidPath,
    InvalidSignature,
    ParentNotFound,
    QuotaExceeded,
    RateLimitExceeded,
    SignerError,
    SummaryError,
    SummaryNotFound,
    SupernoteError,
)


def test_supernote_error_base() -> None:
    """Verify SupernoteError base attributes and to_response conversion."""
    err = SupernoteError(
        "Test error", error_code=ErrorCode.BAD_REQUEST, status_code=400
    )
    assert err.message == "Test error"
    assert err.error_code == ErrorCode.BAD_REQUEST.value
    assert err.status_code == 400

    resp = err.to_response()
    assert resp.status == 400
    assert resp.content_type == "application/json"
    assert resp.text is not None
    body = json.loads(resp.text)
    assert body == {
        "success": False,
        "errorCode": ErrorCode.BAD_REQUEST.value,
        "errorMsg": "Test error",
    }


def test_supernote_error_uncaught() -> None:
    """Verify SupernoteError.uncaught wraps generic exceptions into status 500 error response."""
    original = RuntimeError("Unexpected runtime failure")
    wrapped = SupernoteError.uncaught(original)
    assert wrapped.status_code == 500
    assert wrapped.error_code == ErrorCode.INTERNAL_ERROR.value
    assert "Unexpected runtime failure" in wrapped.message

    resp = wrapped.to_response()
    assert resp.status == 500
    assert resp.text is not None
    body = json.loads(resp.text)
    assert body["success"] is False
    assert body["errorCode"] == ErrorCode.INTERNAL_ERROR.value


def test_parent_not_found() -> None:
    """Verify ParentNotFound default message, status code, error code, and inheritance."""
    err = ParentNotFound()
    assert isinstance(err, FileNotFound)
    assert isinstance(err, FileError)
    assert isinstance(err, SupernoteError)
    assert err.message == "Parent directory is missing"
    assert err.status_code == 404
    assert err.error_code == ErrorCode.PATH_NOT_FOUND.value

    resp = err.to_response()
    assert resp.status == 404
    assert resp.text is not None
    body = json.loads(resp.text)
    assert body == {
        "success": False,
        "errorCode": ErrorCode.PATH_NOT_FOUND.value,
        "errorMsg": "Parent directory is missing",
    }

    custom_err = ParentNotFound("Custom parent missing message")
    assert custom_err.message == "Custom parent missing message"


def test_file_exception_hierarchy() -> None:
    """Verify all file-related exception classes map to their expected status codes and error codes."""
    fnf = FileNotFound("File not found")
    assert fnf.status_code == 404
    assert fnf.error_code == ErrorCode.PATH_NOT_FOUND.value

    fae = FileAlreadyExists("Already exists")
    assert fae.status_code == 409
    assert fae.error_code == ErrorCode.CONFLICT_EXISTS.value

    ip = InvalidPath("Invalid path")
    assert ip.status_code == 400
    assert ip.error_code == ErrorCode.BAD_REQUEST.value

    ad = AccessDenied("Access denied")
    assert ad.status_code == 403
    assert ad.error_code == ErrorCode.ACCESS_DENIED_SYSTEM.value

    hm = HashMismatch("Hash mismatch")
    assert hm.status_code == 400
    assert hm.error_code == ErrorCode.BAD_REQUEST.value

    qe = QuotaExceeded("Quota exceeded")
    assert qe.status_code == 403
    assert qe.error_code == ErrorCode.QUOTA_EXCEEDED.value


def test_system_and_summary_exceptions() -> None:
    """Verify summary, security, database, and rate limiting exception classes."""
    se = SummaryError("Summary error")
    assert isinstance(se, SupernoteError)

    snf = SummaryNotFound("Summary not found")
    assert snf.status_code == 404
    assert snf.error_code == ErrorCode.NOT_FOUND.value

    inv_sig = InvalidSignature("Invalid signature")
    assert inv_sig.status_code == 403
    assert inv_sig.error_code == ErrorCode.ACCESS_DENIED_SYSTEM.value

    signer_err = SignerError("Signer error")
    assert signer_err.status_code == 500
    assert signer_err.error_code == ErrorCode.INTERNAL_ERROR.value

    db_err = DatabaseError("Database failure")
    assert db_err.status_code == 500
    assert db_err.error_code == ErrorCode.INTERNAL_ERROR.value

    rl = RateLimitExceeded("Too many requests")
    assert rl.status_code == 429
    assert rl.error_code == ErrorCode.ACCESS_DENIED_SYSTEM.value
