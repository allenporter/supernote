"""Low-level async HTTP/JSON transport and OSS object storage upload helper.

This module provides `supernote.client.client.Client` (re-exported as `supernote.client.Client`),
which wraps `aiohttp.ClientSession` to handle automatic CSRF token acquisition (`X-XSRF-TOKEN`),
authenticated `x-access-token` injection via `supernote.client.auth.AbstractAuth`, typed response
deserialization into `supernote.models.base.BaseResponse` subclasses, and single-part or chunked
multipart binary uploads (`_upload_to_oss`). See `supernote.client` for high-level session usage.
"""

import hashlib
import logging
import re
import uuid
from collections.abc import Mapping
from typing import Any, TypeVar, overload

import aiohttp
from aiohttp import FormData
from aiohttp.client_exceptions import ClientError
from yarl import URL

from supernote.models.base import BaseResponse, ErrorCode
from supernote.models.system import FileChunkParams, FileChunkVO, UploadFileVO

from .auth import AbstractAuth
from .exceptions import (
    ApiException,
    BadRequestException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "Client",
]


_T = TypeVar("_T", bound=BaseResponse)

_REFRESHABLE_AUTH_ERROR_CODES = frozenset(
    {
        ErrorCode.UNAUTHORIZED.value,
        ErrorCode.LOGIN_EXPIRED.value,
        ErrorCode.INVALID_TOKEN.value,
    }
)

_UNAUTHORIZED_ERROR_CODES = _REFRESHABLE_AUTH_ERROR_CODES | frozenset(
    {
        ErrorCode.ACCOUNT_NOT_EXIST.value,
        ErrorCode.PASSWORD_ERROR.value,
        ErrorCode.INVALID_CREDENTIALS.value,
        ErrorCode.USER_DISABLED.value,
        ErrorCode.USER_LOCKED.value,
        ErrorCode.ACCOUNT_LOCKED.value,
    }
)


class _RefreshableUnauthorizedException(UnauthorizedException):
    """Token-invalid `UnauthorizedException` eligible for a single refresh retry."""


CLOUD_API_URL = "https://cloud.supernote.com"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
}
ACCESS_TOKEN = "x-access-token"
AUTHORIZATION_HEADER = "Authorization"
API_KEY_PREFIX = "sn_"
XSRF_COOKIE = "XSRF-TOKEN"
XSRF_HEADER = "X-XSRF-TOKEN"
_REDACTED_LOG_HEADERS = frozenset(
    {ACCESS_TOKEN.lower(), AUTHORIZATION_HEADER.lower(), "cookie", "set-cookie"}
)
_SN_API_KEY_LOG_RE = re.compile(r"\bsn_[0-9a-fA-F]{32}\b")


def _redact_log_headers(headers: Mapping[str, Any]) -> dict[str, Any]:
    """Redact authentication headers before emitting client debug logs."""
    return {
        k: ("***" if k.lower() in _REDACTED_LOG_HEADERS else v)
        for k, v in headers.items()
    }


def _create_headers(host: str | None = None) -> dict[str, Any]:
    headers = {
        **HEADERS,
    }
    if host:
        headers["Referer"] = host
        headers["Origin"] = host
    return headers


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
        self._host = host or CLOUD_API_URL
        self._auth = auth
        self._xsrf_token: str | None = None

    @property
    def host(self) -> str:
        """Return the host URL."""
        return self._host

    def with_auth(self, auth: AbstractAuth) -> "Client":
        """Return a new client with the given authentication credentials."""
        return Client(self._websession, host=self._host, auth=auth)

    def get_auth(self) -> AbstractAuth | None:
        """Return the current authentication credentials."""
        return self._auth

    def _is_same_origin(self, url: str) -> bool:
        """Return True when `url` is relative or shares `(scheme, host, port)` with `self._host`."""
        if not (url.startswith("http://") or url.startswith("https://")):
            return True
        try:
            target = URL(url)
            base = URL(self._host)
        except ValueError:
            return False
        return (target.scheme, target.host, target.port) == (
            base.scheme,
            base.host,
            base.port,
        )

    def _url(self, url: str) -> str:
        if not (url.startswith("http://") or url.startswith("https://")):
            if self._host.endswith("/"):
                url = url.removeprefix("/")
            elif not url.startswith("/"):
                url = f"/{url}"
            url = f"{self._host}{url}"
        return url

    async def _send_request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> tuple[aiohttp.ClientResponse, str | None]:
        """Send a single HTTP request and return `(response, injected_token)`."""
        same_origin = self._is_same_origin(url)
        req_headers = (
            _create_headers(self._host if same_origin else None)
            if headers is None
            else dict(headers)
        )

        used_token: str | None = None
        if same_origin:
            lower_headers = {k.lower() for k in req_headers}
            if (
                self._auth is not None
                and ACCESS_TOKEN.lower() not in lower_headers
                and AUTHORIZATION_HEADER.lower() not in lower_headers
            ):
                access_token = await self._auth.async_get_access_token()
                if access_token:
                    used_token = access_token
                    if access_token.startswith(API_KEY_PREFIX):
                        req_headers[AUTHORIZATION_HEADER] = f"Bearer {access_token}"
                    else:
                        req_headers[ACCESS_TOKEN] = access_token

            # Always get a fresh CSRF token for same-origin API requests
            self._xsrf_token = await self._get_csrf_token()
            req_headers[XSRF_HEADER] = self._xsrf_token

        resolved_url = self._url(url)
        _LOGGER.debug(
            "request[%s]=%s %s %s",
            method,
            resolved_url,
            kwargs.get("params"),
            _redact_log_headers(req_headers),
        )
        if method != "get" and "json" in kwargs:
            _LOGGER.debug("request[post json]=%s", kwargs["json"])
        response = await self._websession.request(
            method, resolved_url, **kwargs, headers=req_headers
        )
        return response, used_token

    @overload
    async def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        data_cls: None = None,
        **kwargs: Any,
    ) -> aiohttp.ClientResponse: ...

    @overload
    async def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        data_cls: type[_T],
        **kwargs: Any,
    ) -> _T: ...

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        data_cls: type[_T] | None = None,
        **kwargs: Any,
    ) -> aiohttp.ClientResponse | _T:
        """Send a request and retry once on token-invalid errors if `self._auth` refreshes."""
        try:
            resp, used_token = await self._send_request(method, url, **kwargs)
        except ClientError as err:
            raise ApiException(f"Error connecting to API: {err}") from err
        try:
            await self._raise_for_status(resp)
            if data_cls is None:
                return resp
            return await self._parse_json_response(method, resp, data_cls)
        except _RefreshableUnauthorizedException:
            if (
                self._auth is None
                or used_token is None
                or not await self._auth.async_refresh_access_token(used_token)
            ):
                raise

        try:
            resp, _ = await self._send_request(method, url, **kwargs)
        except ClientError as err:
            raise ApiException(f"Error connecting to API: {err}") from err
        await self._raise_for_status(resp)
        if data_cls is None:
            return resp
        return await self._parse_json_response(method, resp, data_cls)

    async def _parse_json_response(
        self, method: str, resp: aiohttp.ClientResponse, data_cls: type[_T]
    ) -> _T:
        """Read, deserialize, and validate a JSON `BaseResponse` payload."""
        try:
            result = await resp.text()
        except ClientError as err:
            raise ApiException("Server returned malformed response") from err
        if method == "get":
            _LOGGER.debug("response=%s", _SN_API_KEY_LOG_RE.sub("***", result))
        try:
            data_response = data_cls.from_json(result)
        except (LookupError, ValueError) as err:
            raise ApiException(
                f"Server return malformed response type {data_cls.__name__}: {result}"
            ) from err
        self._raise_for_data_response(data_response)
        return data_response

    async def request(
        self,
        method: str,
        url: str,
        headers: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> aiohttp.ClientResponse:
        """Make a request."""
        resp, _ = await self._send_request(method, url, headers=headers, **kwargs)
        return resp

    async def get(self, url: str, **kwargs: Any) -> aiohttp.ClientResponse:
        """Make a get request."""
        return await self._request_with_retry("get", url, **kwargs)

    async def get_json(
        self,
        url: str,
        data_cls: type[_T],
        **kwargs: Any,
    ) -> _T:
        """Make a get request and return json response."""
        return await self._request_with_retry("get", url, data_cls=data_cls, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> aiohttp.ClientResponse:
        """Make a post request."""
        return await self._request_with_retry("post", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> aiohttp.ClientResponse:
        """Make a put request."""
        return await self._request_with_retry("put", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> aiohttp.ClientResponse:
        """Make a delete request."""
        return await self._request_with_retry("delete", url, **kwargs)

    async def get_content(self, url: str, **kwargs: Any) -> bytes:
        """Make a get request and return bytes."""
        resp = await self.get(url, **kwargs)
        try:
            return await resp.read()
        except ClientError as err:
            raise ApiException(f"Error reading response: {err}") from err

    async def post_json(self, url: str, data_cls: type[_T], **kwargs: Any) -> _T:
        """Make a post request and return a json response."""
        return await self._request_with_retry("post", url, data_cls=data_cls, **kwargs)

    async def put_json(self, url: str, data_cls: type[_T], **kwargs: Any) -> _T:
        """Make a put request and return a json response."""
        return await self._request_with_retry("put", url, data_cls=data_cls, **kwargs)

    async def delete_json(self, url: str, data_cls: type[_T], **kwargs: Any) -> _T:
        """Make a delete request and return a json response."""
        return await self._request_with_retry(
            "delete", url, data_cls=data_cls, **kwargs
        )

    @staticmethod
    def _raise_for_data_response(data_response: BaseResponse) -> None:
        """Raise an appropriate ApiException when a parsed response indicates failure."""
        if data_response.success:
            return
        if data_response.error_code in _REFRESHABLE_AUTH_ERROR_CODES:
            raise _RefreshableUnauthorizedException(data_response.error_msg)
        if data_response.error_code in _UNAUTHORIZED_ERROR_CODES:
            raise UnauthorizedException(data_response.error_msg)
        raise ApiException(data_response.error_msg)

    async def _get_csrf_token(self) -> str:
        """Get the CSRF token."""
        url = self._url("/api/csrf")
        _LOGGER.debug("CSRF request[get]=%s %s", url, HEADERS)
        resp = await self._websession.request("get", url, headers=HEADERS)
        try:
            await resp.text()
        except ClientError as err:
            raise ApiException("Server returned malformed response") from err
        # Can be added back later for debugging
        # _LOGGER.debug("CSRF response headers=%s", resp.headers)
        token = resp.headers.get(XSRF_HEADER)
        if token is None:
            raise ApiException("Failed to get CSRF token from header")
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
                raise _RefreshableUnauthorizedException(
                    f"Unauthorized response from API ({err.status}): {error_detail}"
                ) from err
            if err.status == 403:
                raise ForbiddenException(
                    f"Forbidden response from API ({err.status}): {error_detail}"
                ) from err
            if err.status == 404:
                raise NotFoundException(
                    f"Not found response from API ({err.status}): {error_detail}"
                ) from err
            if err.status == 400:
                raise BadRequestException(
                    f"Bad request response from API ({err.status}): {error_detail}"
                ) from err
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

    async def _upload_to_oss(
        self,
        content: bytes,
        filename: str,
        full_upload_url: str | None,
        part_upload_url: str | None,
        chunk_size: int = 5 * 1024 * 1024,
    ) -> None:
        """Upload content to OSS (support single or multi-part)."""
        size = len(content)

        if size < chunk_size or part_upload_url is None:
            if full_upload_url is None:
                raise ValueError("No upload URL available")

            # Compute MD5 of content for verification
            content_md5 = hashlib.md5(content).hexdigest()

            _LOGGER.debug(
                "Uploading file %s in one chunk (MD5: %s)", filename, content_md5
            )
            data = FormData()
            data.add_field("file", content, filename=filename)
            # Pass empty dict to headers to avoid default application/json Content-Type
            try:
                resp = await self.request(
                    "post",
                    full_upload_url,
                    data=data,
                    headers={},
                )
            except ClientError as err:
                raise ApiException("Failed to upload file") from err
            # Parse the UploadFileVO response
            try:
                result = await resp.text()
            except ClientError:
                raise ApiException("Server returned malformed response")
            _LOGGER.debug("Upload response: %s", result)
            try:
                upload_vo = UploadFileVO.from_json(result)
            except (LookupError, ValueError) as err:
                raise ApiException(
                    f"Server returned malformed upload response: {result}"
                ) from err
            if not upload_vo.success:
                raise ApiException(f"Upload failed: {upload_vo.error_msg}")

            # Verify MD5 matches
            if upload_vo.md5 != content_md5:
                raise ApiException(
                    f"MD5 mismatch: client={content_md5}, server={upload_vo.md5}"
                )
            return

        upload_id = uuid.uuid4().hex
        # Break into chunks
        chunks = [content[i : i + chunk_size] for i in range(0, size, chunk_size)]
        for i, chunk in enumerate(chunks):
            chunk_md5 = hashlib.md5(chunk).hexdigest()
            _LOGGER.debug(f"Uploading chunk {i + 1} of {size} ({len(chunk)} bytes)")
            data = FormData()
            data.add_field("file", chunk, filename=filename)
            params = FileChunkParams(
                upload_id=upload_id,
                part_number=i + 1,
                total_chunks=len(chunks),
            )
            try:
                resp = await self.request(
                    "post",
                    part_upload_url,
                    data=data,
                    params={k: v for k, v in params.to_dict().items() if v is not None},
                    headers={},
                )
            except ApiException as err:
                raise ApiException(f"Chunk upload failed: {err}")
            try:
                result = await resp.text()
            except ClientError as err:
                raise ApiException("Failed to get chunk response") from err
            try:
                _LOGGER.debug("Chunk response: %s", result)
                chunk_vo = FileChunkVO.from_json(result)
            except (LookupError, ValueError) as err:
                raise ApiException(
                    f"Server returned malformed chunk response: {result}"
                ) from err

            if not chunk_vo.success:
                raise ApiException(f"Chunk upload failed: {chunk_vo.error_msg}")

            # Verify MD5 matches
            if chunk_vo.chunk_md5 != chunk_md5:
                raise ApiException(
                    f"Chunk {i + 1} MD5 mismatch: client={chunk_md5}, server={chunk_vo.chunk_md5}"
                )
