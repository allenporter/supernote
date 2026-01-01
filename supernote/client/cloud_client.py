"""Library for accessing backups in Supenote Cloud."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Self

import aiohttp

from supernote.models.file import (
    FileDownloadDTO,
    FileDownloadUrlVO,
    FileListQueryDTO,
    FileListQueryVO,
)
from supernote.models.user import UserQueryByIdVO
from .auth import ConstantAuth
from .client import Client
from .login_client import LoginClient


class SupernoteClient:
    """A client library for Supernote Cloud."""

    def __init__(self, client: Client):
        """Initialize the client."""
        self._client = client

    async def query_user(self) -> UserQueryByIdVO:
        """Query the user."""
        return await self._client.post_json("/api/user/query", UserQueryByIdVO)

    async def file_list(self, directory_id: int = 0) -> FileListQueryVO:
        """Return a list of files."""
        payload = FileListQueryDTO(
            directory_id=directory_id,
            page_no=1,
            page_size=100,
            order="time",
            sequence="desc",
        ).to_dict()
        return await self._client.post_json(
            "/api/file/list/query", FileListQueryVO, json=payload
        )

    async def file_download(self, file_id: int) -> bytes:
        """Download a file."""
        payload = FileDownloadDTO(id=file_id, type=DownloadType.DOWNLOAD).to_dict()
        download_url_response = await self._client.post_json(
            "/api/file/download/url", FileDownloadUrlVO, json=payload
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
