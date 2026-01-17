"""Library for accessing backups in Supenote Cloud."""

import hashlib
import logging
import uuid
from typing import Any, Type, TypeVar

import aiohttp
from aiohttp import FormData
from aiohttp.client_exceptions import ClientError

from supernote.models.base import BaseResponse
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

CLOUD_API_URL = "https://cloud.supernote.com"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
}
ACCESS_TOKEN = "x-access-token"
XSRF_COOKIE = "XSRF-TOKEN"
XSRF_HEADER = "X-XSRF-TOKEN"


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

    def _url(self, url: str) -> str:
        if not (url.startswith("http://") or url.startswith("https://")):
            if self._host.endswith("/"):
                if url.startswith("/"):
                    url = url[1:]
            elif not url.startswith("/"):
                url = f"/{url}"
            url = f"{self._host}{url}"
        return url

    async def request(
        self,
        method: str,
        url: str,
        headers: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> aiohttp.ClientResponse:
        """Make a request."""
        if headers is None:
            headers = _create_headers(self._host)
        # Always get a fresh CSRF token
        self._xsrf_token = await self._get_csrf_token()
        headers[XSRF_HEADER] = self._xsrf_token

        if self._auth and ACCESS_TOKEN not in headers:
            access_token = await self._auth.async_get_access_token()
            headers[ACCESS_TOKEN] = access_token
        url = self._url(url)
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

    async def put(self, url: str, **kwargs: Any) -> aiohttp.ClientResponse:
        """Make a put request."""
        try:
            resp = await self.request("put", url, **kwargs)
        except ClientError as err:
            raise ApiException(f"Error connecting to API: {err}") from err
        return await self._raise_for_status(resp)

    async def get_content(self, url: str, **kwargs: Any) -> bytes:
        """Make a get request and return bytes."""
        resp = await self.get(url, **kwargs)
        try:
            return await resp.read()
        except ClientError as err:
            raise ApiException(f"Error reading response: {err}") from err

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
            raise ApiException(
                f"Server return malformed response type {data_cls.__name__}: {result}"
            ) from err
        if not data_response.success:
            raise ApiException(data_response.error_msg)
        return data_response

    async def put_json(self, url: str, data_cls: Type[_T], **kwargs: Any) -> _T:
        """Make a put request and return a json response."""
        resp = await self.put(url, **kwargs)
        try:
            result = await resp.text()
        except ClientError as err:
            raise ApiException("Server returned malformed response") from err
        try:
            data_response = data_cls.from_json(result)
        except (LookupError, ValueError) as err:
            raise ApiException(
                f"Server return malformed response type {data_cls.__name__}: {result}"
            ) from err
        if not data_response.success:
            raise ApiException(data_response.error_msg)
        return data_response

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
                raise UnauthorizedException(
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
