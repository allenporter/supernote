"""Library for authentication."""

import logging
from abc import ABC, abstractmethod

_LOGGER = logging.getLogger(__name__)


class AbstractAuth(ABC):
    """Authentication library."""

    @abstractmethod
    async def async_get_access_token(self) -> str:
        """Return a valid access token."""


class ConstantAuth(AbstractAuth):
    """Authentication library."""

    def __init__(self, access_token: str):
        """Initialize the auth."""
        self._access_token = access_token

    async def async_get_access_token(self) -> str:
        """Return a valid access token."""
        return self._access_token
