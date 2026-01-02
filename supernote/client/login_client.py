"""Library for authenticating with the Supernote (Private) Cloud Server."""

import logging
from typing import TypeVar

from mashumaro.mixins.json import DataClassJSONMixin

from supernote.models.auth import (
    LoginDTO,
    LoginMethod,
    LoginVO,
    QueryTokenDTO,
    QueryTokenVO,
    RandomCodeDTO,
    RandomCodeVO,
    SendSmsDTO,
    SendSmsVO,
    SmsLoginDTO,
    SmsLoginVO,
    UserPreAuthRequest,
    UserPreAuthResponse,
)

from .client import Client
from .exceptions import ApiException, SmsVerificationRequired
from .hashing import get_token_salt, hash_password, hash_with_salt

_LOGGER = logging.getLogger(__name__)


_T = TypeVar("_T", bound=DataClassJSONMixin)

__all__ = [
    "LoginClient",
]


class LoginClient:
    """A client library for logging in."""

    def __init__(self, client: Client):
        """Initialize the client."""
        self._client = client

    async def login(self, email: str, password: str) -> str:
        """Log in and return an access token."""
        await self._token()
        random_code_response = await self._get_random_code(email)
        encoded_password = hash_password(password, random_code_response.random_code)
        access_token_response = await self._get_access_token(
            email, encoded_password, random_code_response.timestamp
        )
        return access_token_response.token

    async def login_equipment(
        self, email: str, password: str, equipment_no: str
    ) -> LoginVO:
        """Log in via equipment endpoint and return full login response."""
        await self._token()
        random_code_response = await self._get_random_code(email)
        encoded_password = hash_password(password, random_code_response.random_code)

        payload = LoginDTO(
            account=email,
            password=encoded_password,
            login_method=LoginMethod.PHONE if email.isdigit() else LoginMethod.EMAIL,
            timestamp=random_code_response.timestamp,
            equipment_no=equipment_no,
        ).to_dict()

        return await self._client.post_json(
            "/api/official/user/account/login/equipment", LoginVO, json=payload
        )

    async def sms_login(self, telephone: str, code: str, timestamp: str) -> str:
        """Log in via SMS code."""
        # Always get a fresh CSRF token for the SMS login request
        await self._client._get_csrf_token()

        payload = SmsLoginDTO(
            telephone=telephone,
            timestamp=timestamp,
            valid_code=code,
            valid_code_key=f"1-{telephone}_validCode",
        ).to_dict()

        response = await self._client.post_json(
            "/api/official/user/sms/login", SmsLoginVO, json=payload
        )
        return response.token

    async def request_sms_code(self, telephone: str, country_code: int = 1) -> None:
        """Request an SMS verification code."""
        # Pre-authentication step to obtain a token
        account_with_code = f"{country_code}{telephone}"
        pre_auth_payload = UserPreAuthRequest(account=account_with_code).to_dict()

        # Always get a fresh CSRF token
        await self._client._get_csrf_token()

        pre_auth_response = await self._client.post_json(
            "/api/user/validcode/pre-auth", UserPreAuthResponse, json=pre_auth_payload
        )

        # Calculate signature needed to send the random code over SMS
        token_salt = get_token_salt(pre_auth_response.token)
        sign = hash_with_salt(account_with_code, token_salt)

        # Obtain a random code timestamp and send SMS
        random_code_resp = await self._get_random_code(telephone)
        timestamp = random_code_resp.timestamp

        sms_payload = SendSmsDTO(
            telephone=telephone,
            timestamp=timestamp,
            token=pre_auth_response.token,
            sign=sign,
            nationcode=country_code,
        ).to_dict()
        await self._client.post_json(
            "/api/user/sms/validcode/send", SendSmsVO, json=sms_payload
        )

    async def _token(self) -> None:
        """Get a random code."""
        await self._client.post_json(
            "/api/user/query/token", QueryTokenVO, json=QueryTokenDTO().to_dict()
        )

    async def _get_random_code(self, email: str) -> RandomCodeVO:
        """Get a random code."""
        payload = RandomCodeDTO(account=email).to_dict()
        return await self._client.post_json(
            "/api/official/user/query/random/code", RandomCodeVO, json=payload
        )

    async def _get_access_token(
        self, email: str, encoded_password: str, random_code_timestamp: str
    ) -> LoginVO:
        """Get an access token."""
        payload = LoginDTO(
            account=email,
            password=encoded_password,
            login_method=LoginMethod.PHONE if email.isdigit() else LoginMethod.EMAIL,
            timestamp=random_code_timestamp,
        ).to_dict()
        try:
            return await self._client.post_json(
                "/api/official/user/account/login/new", LoginVO, json=payload
            )
        except ApiException as err:
            if "verification code" in str(err):
                raise SmsVerificationRequired(str(err), random_code_timestamp) from err
            raise
