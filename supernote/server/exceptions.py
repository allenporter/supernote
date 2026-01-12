"""Module for centralized exception handling."""

import logging
from typing import Self

from aiohttp import web

from supernote.models.base import BaseResponse, ErrorCode

logger = logging.getLogger(__name__)


class SupernoteError(Exception):
    """Base class for all application exceptions."""

    def __init__(
        self,
        message: str,
        error_code: str | ErrorCode | None = None,
        status_code: int = 400,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = (
            error_code.value if isinstance(error_code, ErrorCode) else error_code
        )
        self.status_code = status_code

    def to_response(self) -> web.Response:
        """Convert the error to an aiohttp web response."""
        return web.json_response(
            BaseResponse(
                success=False,
                error_code=self.error_code,
                error_msg=self.message,
            ).to_dict(),
            status=self.status_code,
        )

    @classmethod
    def uncaught(cls, err: Exception) -> Self:
        """Wrap an uncaught exception in a SupernoteError."""
        logger.exception(f"Uncaught exception: {err}")
        return cls(str(err), error_code=ErrorCode.INTERNAL_ERROR, status_code=500)


class FileError(SupernoteError):
    """Base class for file-related errors."""

    pass


class FileNotFound(FileError):
    """Raised when a file or directory is not found."""

    def __init__(
        self, message: str, error_code: str | ErrorCode = ErrorCode.PATH_NOT_FOUND
    ):
        super().__init__(message, error_code, status_code=404)


class FileAlreadyExists(FileError):
    """Raised when a file or directory already exists."""

    def __init__(
        self, message: str, error_code: str | ErrorCode = ErrorCode.CONFLICT_EXISTS
    ):
        super().__init__(message, error_code, status_code=409)


class InvalidPath(FileError):
    """Raised when a path is invalid or malformed."""

    def __init__(
        self, message: str, error_code: str | ErrorCode = ErrorCode.BAD_REQUEST
    ):
        super().__init__(message, error_code, status_code=400)


class AccessDenied(FileError):
    """Raised when access is denied to a resource."""

    def __init__(
        self, message: str, error_code: str | ErrorCode = ErrorCode.ACCESS_DENIED_SYSTEM
    ):
        super().__init__(message, error_code, status_code=403)


class HashMismatch(FileError):
    """Raised when a hash mismatch is detected."""

    def __init__(
        self, message: str, error_code: str | ErrorCode = ErrorCode.BAD_REQUEST
    ):
        super().__init__(message, error_code, status_code=400)


class QuotaExceeded(FileError):
    """Raised when a user's storage quota is exceeded."""

    def __init__(
        self, message: str, error_code: str | ErrorCode = ErrorCode.QUOTA_EXCEEDED
    ):
        super().__init__(message, error_code, status_code=403)


class SummaryError(SupernoteError):
    """Base class for summary-related errors."""

    pass


class SummaryNotFound(SummaryError):
    """Raised when a summary or tag is not found."""

    def __init__(self, message: str, error_code: str | ErrorCode = ErrorCode.NOT_FOUND):
        super().__init__(message, error_code, status_code=404)


class InvalidSignature(SupernoteError):
    """Raised when a URL signature is invalid or expired."""

    def __init__(
        self, message: str, error_code: str | ErrorCode = ErrorCode.ACCESS_DENIED_SYSTEM
    ):
        super().__init__(message, error_code, status_code=403)


class SignerError(SupernoteError):
    """Raised when an error occurs during URL signing."""

    def __init__(
        self, message: str, error_code: str | ErrorCode = ErrorCode.INTERNAL_ERROR
    ):
        super().__init__(message, error_code, status_code=500)


class DatabaseError(SupernoteError):
    """Raised when a database error occurs."""

    def __init__(
        self, message: str, error_code: str | ErrorCode = ErrorCode.INTERNAL_ERROR
    ):
        super().__init__(message, error_code, status_code=500)


class RateLimitExceeded(SupernoteError):
    """Raised when a rate limit is exceeded."""

    def __init__(
        self, message: str, error_code: str | ErrorCode = ErrorCode.ACCESS_DENIED_SYSTEM
    ):
        super().__init__(message, error_code, status_code=429)
