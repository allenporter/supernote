"""Library for authentication."""

import logging
import os
import pickle
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


class FileCacheAuth(AbstractAuth):
    """Authentication library that caches token in a file."""

    def __init__(self, cache_path: str):
        """Initialize the auth."""
        self._cache_path = cache_path
        self._access_token: str | None = None

    async def async_get_access_token(self) -> str:
        """Return a valid access token."""
        if self._access_token:
            return self._access_token

        if os.path.exists(self._cache_path):
            try:
                with open(self._cache_path, "rb") as f:
                    data = pickle.load(f)
                    if isinstance(data, dict) and "access_token" in data:
                        self._access_token = data["access_token"]
                        return self._access_token
            except Exception as err:
                _LOGGER.warning("Failed to load token from cache: %s", err)

        raise ValueError("No access token found in cache")

    def save_access_token(self, token: str) -> None:
        """Save access token to cache."""
        self._access_token = token

        # Ensure directory exists
        os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)

        try:
            with open(self._cache_path, "wb") as f:
                pickle.dump({"access_token": token}, f)
        except Exception as err:
            _LOGGER.warning("Failed to save token to cache: %s", err)
