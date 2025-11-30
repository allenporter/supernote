"""Library for accessing backups in Supenote Cloud."""

import logging
from typing import Any, Type, TypeVar

import aiohttp
from aiohttp.client_exceptions import ClientError

from .api_model import BaseResponse
from .auth import AbstractAuth
from .exceptions import ApiException, ForbiddenException, UnauthorizedException

_LOGGER = logging.getLogger(__name__)

API_URL = "https://cloud.supernote.com/api"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
    "Referer": "https://cloud.supernote.com/",
    "Origin": "https://cloud.supernote.com",
}
ACCESS_TOKEN = "x-access-token"
XSRF_COOKIE = "XSRF-TOKEN"
XSRF_HEADER = "X-XSRF-TOKEN"


_T = TypeVar("_T", bound=BaseResponse)


class Client:
    """Library that makes authenticated HTTP requests."""

    def __init__(
        self,
        websession: aiohttp.ClientSession,
        host: str | None = None,
        auth: AbstractAuth | None = None,
    ):
        """Initialize the auth."""
        self._websession = websession
        self._host = host or API_URL
        self._auth = auth
        self._xsrf_token: str | None = None

    async def request(
        self,
        method: str,
        url: str,
        headers: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> aiohttp.ClientResponse:
        """Make a request."""
        if headers is None:
            headers = {
                **HEADERS,
            }
        # Always get a fresh CSRF token
        self._xsrf_token = await self._get_csrf_token()
        headers[XSRF_HEADER] = self._xsrf_token

        if self._auth and ACCESS_TOKEN not in headers:
            access_token = await self._auth.async_get_access_token()
            headers[ACCESS_TOKEN] = access_token
        if not (url.startswith("http://") or url.startswith("https://")):
            url = f"{self._host}/{url}"
        _LOGGER.debug(
            "request[%s]=%s %s %s",
            method,
            url,
            kwargs.get("params"),
            headers,
        )
        if method != "get" and "json" in kwargs:
            _LOGGER.debug("request[post json]=%s", kwargs["json"])
        response = await self._websession.request(
            method, url, **kwargs, headers=headers
        )
        return response

    async def get(self, url: str, **kwargs: Any) -> aiohttp.ClientResponse:
        """Make a get request."""
        try:
            resp = await self.request("get", url, **kwargs)
        except ClientError as err:
            raise ApiException(f"Error connecting to API: {err}") from err
        return await self._raise_for_status(resp)

    async def get_json(
        self,
        url: str,
        data_cls: Type[_T],
        **kwargs: Any,
    ) -> _T:
        """Make a get request and return json response."""
        resp = await self.get(url, **kwargs)
        try:
            result = await resp.text()
        except ClientError as err:
            raise ApiException("Server returned malformed response") from err
        _LOGGER.debug("response=%s", result)
        try:
            data_response = data_cls.from_json(result)
        except (LookupError, ValueError) as err:
            raise ApiException(f"Server return malformed response: {result}") from err
        if not data_response.success:
            raise ApiException(data_response.error_msg)
        return data_response

    async def post(self, url: str, **kwargs: Any) -> aiohttp.ClientResponse:
        """Make a post request."""
        try:
            resp = await self.request("post", url, **kwargs)
        except ClientError as err:
            raise ApiException(f"Error connecting to API: {err}") from err
        return await self._raise_for_status(resp)

    async def post_json(self, url: str, data_cls: Type[_T], **kwargs: Any) -> _T:
        """Make a post request and return a json response."""
        resp = await self.post(url, **kwargs)
        try:
            result = await resp.text()
        except ClientError as err:
            raise ApiException("Server returned malformed response") from err
        try:
            data_response = data_cls.from_json(result)
        except (LookupError, ValueError) as err:
            raise ApiException(f"Server return malformed response: {result}") from err
        if not data_response.success:
            raise ApiException(data_response.error_msg)
        return data_response

    async def _get_csrf_token(self) -> str:
        """Get the CSRF token."""
        url = f"{self._host}/csrf"
        _LOGGER.debug("CSRF request[get]=%s %s", url, HEADERS)
        resp = await self._websession.request("get", url, headers=HEADERS)
        try:
            result = await resp.text()
        except ClientError as err:
            raise ApiException("Server returned malformed response") from err
        _LOGGER.debug("CSRF response=%s", result)
        _LOGGER.debug("CSRF response headers=%s", resp.headers)
        token = resp.headers.get(XSRF_HEADER)
        if token is None:
            raise ApiException("Failed to get CSRF token from header")
        _LOGGER.debug("CSRF token=%s", token)
        _LOGGER.debug("CSRF response cookies=%s", resp.cookies)
        return token

    @classmethod
    async def _raise_for_status(
        cls, resp: aiohttp.ClientResponse
    ) -> aiohttp.ClientResponse:
        """Raise exceptions on failure methods."""
        error_detail = await cls._error_detail(resp)
        try:
            resp.raise_for_status()
        except aiohttp.ClientResponseError as err:
            if err.status == 401:
                error_message = (
                    f"Unauthorized response from API ({err.status}): {error_detail}"
                )
                raise UnauthorizedException(error_message) from err
            if err.status == 403:
                error_message = (
                    f"Forbidden response from API ({err.status}): {error_detail}"
                )
                raise ForbiddenException(error_message) from err
            error_message = f"Error response from API ({err.status}): {error_detail}"
            raise ApiException(error_message) from err
        except aiohttp.ClientError as err:
            raise ApiException(f"Error from API: {err}") from err
        return resp

    @classmethod
    async def _error_detail(cls, resp: aiohttp.ClientResponse) -> str | None:
        """Returns an error message string from the APi response."""
        if resp.status < 400:
            return None
        try:
            result = await resp.text()
        except ClientError:
            return None
        return result
