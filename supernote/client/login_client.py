"""Library for accessing backups in Supenote Cloud."""

import hashlib
import logging
from typing import TypeVar

from mashumaro.mixins.json import DataClassJSONMixin

from .api_model import (
    TokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserLoginResponse,
    UserPreAuthRequest,
    UserPreAuthResponse,
    UserRandomCodeRequest,
    UserRandomCodeResponse,
    UserSendSmsRequest,
    UserSendSmsResponse,
    UserSmsLoginRequest,
    UserSmsLoginResponse,
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


def _extract_real_key(token: str) -> str:
    """Extract real key from token as per JS logic."""
    # var t = e.charAt(e.length - 1)
    # var n = parseInt(t)
    # var a = e.split("-")
    # var o = a[n];
    if not token:
        return ""
    last_char = token[-1]
    try:
        index = int(last_char)
        parts = token.split("-")
        if 0 <= index < len(parts):
            return parts[index]
    except ValueError:
        pass
    return ""


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

    async def request_sms_code(self, telephone: str, country_code: int = 1) -> None:
        """Request an SMS verification code."""
        # 1. Pre-auth to get token
        # Note: The JS code prefixes the account with the country code for pre-auth
        # account: this.tempAccountInfo.countryCode + this.tempAccountInfo.account
        account_with_code = f"{country_code}{telephone}"
        pre_auth_payload = UserPreAuthRequest(account=account_with_code).to_dict()

        # Always get a fresh CSRF token
        await self._client._get_csrf_token()

        pre_auth_response = await self._client.post_json(
            "user/validcode/pre-auth", UserPreAuthResponse, json=pre_auth_payload
        )

        token = pre_auth_response.token

        # 2. Extract real key and calculate sign
        # e.sign = e.hash256(n + a) where n is account_with_code and a is real_key
        real_key = _extract_real_key(token)
        sign = _sha256_s(account_with_code + real_key)

        # 3. Send SMS
        # timestamp is needed here. In the JS it uses e.tempAccountInfo.timestamp
        # We might need to fetch a timestamp first if we don't have one, but let's see.
        # The JS gets timestamp from the initial login failure or a separate query.
        # For now, let's try to get a fresh timestamp/random code first?
        # Actually, the JS flow for "sendVerificationCode" seems to use existing timestamp.
        # But if we are starting fresh, we might need one.
        # Let's assume we can get a fresh random code to get a timestamp.
        random_code_resp = await self._get_random_code(telephone)
        timestamp = random_code_resp.timestamp

        sms_payload = UserSendSmsRequest(
            telephone=telephone,
            timestamp=timestamp,
            token=token,
            sign=sign,
            nationcode=country_code,
        ).to_dict()

        await self._client.post_json(
            "user/sms/validcode/send", UserSendSmsResponse, json=sms_payload
        )

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
