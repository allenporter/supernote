"""Exception hierarchy for the Supernote client SDK.

This module defines `SupernoteException` and its specialized subclasses raised by
`supernote.client.client.Client`, `supernote.client.login_client.LoginClient`, and
`supernote.client.socket.SupernoteSocketClient`, including HTTP/API error mappings
(`ApiException`, `UnauthorizedException`, `ForbiddenException`, `NotFoundException`,
`BadRequestException`), `SmsVerificationRequired`, and `SupernoteSocketError`.
See `supernote.client` for error-handling examples.
"""


class SupernoteException(Exception):
    """Base exception for supernote cloud."""


class SupernoteSocketError(SupernoteException):
    """Exception raised for Socket.IO connection and status check failures."""


class SmsVerificationRequired(SupernoteException):
    """Exception raised when SMS verification is required."""

    def __init__(self, message: str, timestamp: str):
        super().__init__(message)
        self.timestamp = timestamp


class ApiException(SupernoteException):
    """API exception."""


class ForbiddenException(ApiException):
    """API exception."""


class UnauthorizedException(ApiException):
    """Authentication exception."""


class NotFoundException(ApiException):
    """Resource not found (404)."""


class BadRequestException(ApiException):
    """Bad request (400)."""
