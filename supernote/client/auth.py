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

    @property
    def token(self) -> str:
        """Return the access token."""
        return self._access_token


class FileCacheAuth(AbstractAuth):
    """Authentication library that caches token in a file."""

    def __init__(self, cache_path: str):
        """Initialize the auth."""
        self._cache_path = cache_path
        self._access_token: str | None = None
        self._host: str | None = None
        try:
            self._load_from_cache()
        except ValueError as err:
            _LOGGER.info(f"No cached credentials found at {self._cache_path} ({err})")

    async def async_get_access_token(self) -> str:
        """Return a valid access token."""
        if self._access_token:
            return self._access_token
        raise ValueError(f"No access token found in cache: {self._cache_path}")

    def get_host(self) -> str | None:
        """Return the cached host URL."""
        return self._host

    def _load_from_cache(self) -> None:
        if not os.path.exists(self._cache_path):
            raise ValueError("Cache file does not exist")
        try:
            with open(self._cache_path, "rb") as f:
                data = pickle.load(f)
        except Exception as err:
            raise ValueError(f"Failed to load token from cache: {err}")
        if not isinstance(data, dict):
            raise ValueError("Cache file is not a dictionary")
        self._access_token = data["access_token"]
        if "host" not in data:
            raise ValueError("Cache file is missing host")
        self._host = data["host"]

    def save_credentials(self, token: str, host: str) -> None:
        """Save access token and host to cache."""
        self._access_token = token
        self._host = host

        # Ensure directory exists
        os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)

        with open(self._cache_path, "wb") as f:
            data = {"access_token": token, "host": host}
            pickle.dump(data, f)
