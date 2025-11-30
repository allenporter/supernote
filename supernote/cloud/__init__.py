"""Supernote Cloud client library."""

from .client import Client
from .auth import AbstractAuth, ConstantAuth, FileCacheAuth
from .cloud_client import SupernoteCloudClient
from .login_client import LoginClient

# Convenience alias
CloudClient = SupernoteCloudClient

__all__ = [
    "Client",
    "AbstractAuth",
    "ConstantAuth",
    "FileCacheAuth",
    "CloudClient",
    "SupernoteCloudClient",
    "LoginClient",
]
