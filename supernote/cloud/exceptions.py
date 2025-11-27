"""Exceptions for supernote cloud."""


class SupernoteException(Exception):
    """Base exception for supernote cloud."""


class ApiException(SupernoteException):
    """API exception."""


class ForbiddenException(ApiException):
    """API exception."""


class UnauthorizedException(ApiException):
    """Authentication exception."""
