"""Supernote session wrapper."""

from typing import Self

import aiohttp

from .auth import AbstractAuth, ConstantAuth
from .client import Client
from .device import DeviceClient
from .login_client import LoginClient
from .web import WebClient


class Supernote:
    """A session-managed entry point for Supernote clients.

    Example:
        async with await Supernote.login("email@example.com", "password", host="http://localhost:8080") as sn:
            # Access Web and Device APIs directly through the session object
            # Example: List root folder using path-based Device API
            result = await sn.device.list_folder("/")

            # sn.token contains the access token for use with `Supernote.from_token`
            print(sn.token)

    Example using an existing token:
        sn = Supernote.from_token("your-token", host="http://localhost:8080")
        # Note: When created this way, you are responsible for closing the session
        # or passing an existing one.
    """

    def __init__(
        self,
        host: str | None = None,
        session: aiohttp.ClientSession | None = None,
        auth: AbstractAuth | None = None,
        close_session: bool | None = None,
    ):
        """Initialize the Supernote session wrapper."""
        if close_session is not None:
            self._close_session = close_session
        else:
            self._close_session = session is None
        self._session = session or aiohttp.ClientSession()
        self._client = Client(self._session, host=host, auth=auth)
        self._web = WebClient(self._client)
        self._device = DeviceClient(self._client)
        self._login_client = LoginClient(self._client)

    @classmethod
    async def login(
        cls,
        email: str,
        password: str,
        host: str | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> "Supernote":
        """Log in and return an authenticated Supernote instance."""
        # Create a temporary unauthenticated instance to perform login
        sn = cls(session=session, host=host)
        login_client = LoginClient(sn.client)
        token = await login_client.login(email, password)
        # Return a new authenticated instance sharing the same session
        return sn.with_auth(ConstantAuth(token))

    @classmethod
    def from_token(
        cls,
        token: str,
        host: str | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> "Supernote":
        """Return an authenticated Supernote instance using an existing token."""
        return cls.from_auth(ConstantAuth(token), host=host, session=session)

    @classmethod
    def from_auth(
        cls,
        auth: AbstractAuth,
        host: str | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> "Supernote":
        """Return an authenticated Supernote instance using existing credentials."""
        return cls(host=host, session=session, auth=auth)

    async def __aenter__(self) -> Self:
        """Enter the async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        """Exit the async context manager."""
        if self._close_session:
            await self._session.close()

    @property
    def web(self) -> WebClient:
        """Return the web client."""
        return self._web

    @property
    def device(self) -> DeviceClient:
        """Return the device client."""
        return self._device

    @property
    def login_client(self) -> LoginClient:
        """Return the login client."""
        return self._login_client

    @property
    def client(self) -> Client:
        """Return the lower level base client."""
        return self._client

    @property
    def token(self) -> str | None:
        """Return the current access token if authenticated with ConstantAuth."""
        auth = self._client.get_auth()
        if isinstance(auth, ConstantAuth):
            return auth.token
        return None

    def with_auth(self, auth: AbstractAuth) -> Self:
        """Return a new Supernote instance with the given authentication credentials."""
        return self.__class__(
            session=self._session,
            host=self._client.host,
            auth=auth,
            close_session=self._close_session,
        )
