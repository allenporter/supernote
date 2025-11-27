"""Library for accessing backups in Supenote Cloud."""

import hashlib
import logging
from typing import TypeVar

from mashumaro.mixins.json import DataClassJSONMixin

from .api_model import (
    UserLoginRequest,
    UserLoginResponse,
    UserRandomCodeRequest,
    UserRandomCodeResponse,
    UserSmsLoginRequest,
    UserSmsLoginResponse,
    TokenRequest,
    TokenResponse,
)
from .client import Client
from .exceptions import ApiException, SmsVerificationRequired

_LOGGER = logging.getLogger(__name__)


_T = TypeVar("_T", bound=DataClassJSONMixin)


def _sha256_s(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _md5_s(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _encode_password(password: str, rc: str) -> str:
    return _sha256_s(_md5_s(password) + rc)


class LoginClient:
    """A client library for logging in."""

    def __init__(self, client: Client):
        """Initialize the client."""
        self._client = client

    async def login(self, email: str, password: str) -> str:
        """Log in and return an access token."""
        await self._token()
        random_code_response = await self._get_random_code(email)
        encoded_password = _encode_password(password, random_code_response.random_code)
        access_token_response = await self._get_access_token(
            email, encoded_password, random_code_response.timestamp
        )
        return access_token_response.token

    async def sms_login(self, telephone: str, code: str, timestamp: str) -> str:
        """Log in via SMS code."""
        # Always get a fresh CSRF token for the SMS login request
        await self._client._get_csrf_token()

        payload = UserSmsLoginRequest(
            telephone=telephone,
            timestamp=timestamp,
            valid_code=code,
            valid_code_key=f"1-{telephone}_validCode",
        ).to_dict()

        response = await self._client.post_json(
            "official/user/sms/login", UserSmsLoginResponse, json=payload
        )
        return response.token

    async def _token(self) -> None:
        """Get a random code."""
        await self._client.post_json(
            "user/query/token",
            TokenResponse,
            json=TokenRequest().to_dict(),
        )

    async def _get_random_code(self, email: str) -> UserRandomCodeResponse:
        """Get a random code."""
        payload = UserRandomCodeRequest(account=email).to_dict()
        return await self._client.post_json(
            "official/user/query/random/code", UserRandomCodeResponse, json=payload
        )

    async def _get_access_token(
        self, email: str, encoded_password: str, random_code_timestamp: str
    ) -> UserLoginResponse:
        """Get an access token."""
        payload = UserLoginRequest(
            account=email,
            password=encoded_password,
            login_method=1,
            timestamp=random_code_timestamp,
        ).to_dict()
        try:
            return await self._client.post_json(
                "official/user/account/login/new", UserLoginResponse, json=payload
            )
        except ApiException as err:
            if "verification code" in str(err):
                raise SmsVerificationRequired(str(err), random_code_timestamp) from err
            raise
