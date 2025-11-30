"""Library for accessing backups in Supenote Cloud."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Self

import aiohttp

from .api_model import (
    FileListRequest,
    FileListResponse,
    GetFileDownloadUrlRequest,
    GetFileDownloadUrlResponse,
    QueryUserRequest,
    QueryUserResponse,
)
from .auth import ConstantAuth
from .client import Client
from .login_client import LoginClient


class SupernoteClient:
    """A client library for Supernote Cloud."""

    def __init__(self, client: Client):
        """Initialize the client."""
        self._client = client

    async def query_user(self, account: str) -> QueryUserResponse:
        """Query the user."""
        payload = QueryUserRequest(country_code=1, account=account).to_dict()
        return await self._client.post_json(
            "user/query", QueryUserResponse, json=payload
        )

    async def file_list(self, directory_id: int = 0) -> FileListResponse:
        """Return a list of files."""
        payload = FileListRequest(
            directory_id=directory_id,
            page_no=1,
            page_size=100,
            order="time",
            sequence="desc",
        ).to_dict()
        return await self._client.post_json(
            "file/list/query", FileListResponse, json=payload
        )

    async def file_download(self, file_id: int) -> bytes:
        """Download a file."""
        payload = GetFileDownloadUrlRequest(file_id=file_id, file_type=0).to_dict()
        download_url_response = await self._client.post_json(
            "file/download/url", GetFileDownloadUrlResponse, json=payload
        )
        response = await self._client.get(download_url_response.url)
        return await response.read()

    @classmethod
    @asynccontextmanager
    async def from_credentials(
        cls, email: str, password: str
    ) -> AsyncGenerator[Self, None]:
        """Create a client from credentials."""
        async with aiohttp.ClientSession() as session:
            # Temporary client for login
            temp_client = Client(session)
            login_client = LoginClient(temp_client)
            token = await login_client.login(email, password)

            # Authenticated client
            auth = ConstantAuth(token)
            client = Client(session, auth=auth)
            yield cls(client)
