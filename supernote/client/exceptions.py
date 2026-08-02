"""Exceptions for supernote cloud."""


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
