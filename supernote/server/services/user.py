import hashlib
import logging
import secrets
import time
from typing import Optional, cast

import jwt

from ..config import AuthConfig, UserEntry
from ..models.auth import LoginResult, UserVO
from .state import StateService

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"


class UserService:
    def __init__(self, config: AuthConfig, state_service: StateService):
        self._config = config
        self._state_service = state_service
        self._random_codes: dict[
            str, tuple[str, str]
        ] = {}  # account -> (code, timestamp)

    @property
    def _users(self) -> list[UserEntry]:
        return self._config.users

    def list_users(self) -> list[UserEntry]:
        return list(self._users)

    def check_user_exists(self, account: str) -> bool:
        return any(u.username == account for u in self._users)

    def generate_random_code(self, account: str) -> tuple[str, str]:
        """Generate a random code for login challenge."""
        random_code = secrets.token_hex(4)  # 8 chars
        timestamp = str(int(time.time() * 1000))
        self._random_codes[account] = (random_code, timestamp)
        return random_code, timestamp

    def _get_user(self, account: str) -> UserEntry | None:
        for user in self._users:
            if user.username == account:
                return user
        return None

    def verify_password(self, account: str, password: str) -> bool:
        user = self._get_user(account)
        if not user or not user.is_active:
            return False
        hash_hex = hashlib.md5(password.encode()).hexdigest()
        return bool(hash_hex == user.password_md5)

    def verify_login_hash(self, account: str, client_hash: str, timestamp: str) -> bool:
        user = self._get_user(account)
        if not user or not user.is_active:
            return False

        code_tuple = self._random_codes.get(account)
        if not code_tuple or code_tuple[1] != timestamp:
            return False

        random_code = code_tuple[0]
        concat = user.password_md5 + random_code
        expected_hash = hashlib.sha256(concat.encode()).hexdigest()

        return expected_hash == client_hash

    def login(
        self,
        account: str,
        password_hash: str,
        timestamp: str,
        equipment_no: Optional[str] = None,
    ) -> LoginResult | None:
        user = self._get_user(account)
        if not user or not user.is_active:
            return None

        if not self.verify_login_hash(account, password_hash, timestamp):
            return None

        # Check binding status from StateService
        user_state = self._state_service.get_user_state(account)
        bound_devices = user_state.devices
        is_bind = "Y" if bound_devices else "N"
        is_bind_equipment = (
            "Y" if equipment_no and equipment_no in bound_devices else "N"
        )

        payload = {
            "sub": account,
            "equipment_no": equipment_no or "",
            "iat": int(time.time()),
            "exp": int(time.time()) + (self._config.expiration_hours * 3600),
        }
        token = jwt.encode(payload, self._config.secret_key, algorithm=JWT_ALGORITHM)

        # Persist session in StateService
        self._state_service.create_session(token, account, equipment_no)

        return LoginResult(
            token=token,
            is_bind=is_bind,
            is_bind_equipment=is_bind_equipment,
        )

    def verify_token(self, token: str) -> str | None:
        """Verify token against persisted sessions and JWT signature."""
        try:
            # 1. Check if session exists in memory/state
            session = self._state_service.get_session(token)
            if not session:
                logger.warning("Session not found in state: %s", token[:10])
                return None

            # 2. Decode and verify JWT
            payload = jwt.decode(
                token, self._config.secret_key, algorithms=[JWT_ALGORITHM]
            )
            return cast(str, payload.get("sub"))
        except jwt.PyJWTError as e:
            logger.warning("Token verification failed: %s", e)
            return None

    def get_user_profile(self, account: str) -> UserVO | None:
        """Get user profile from static config."""
        user = self._get_user(account)
        if not user:
            return None

        return UserVO(
            user_name=user.display_name or account,
            email=user.email or account,
            phone=user.phone or "",
            country_code="1",
            total_capacity=user.total_capacity,
            file_server="0",
            avatars_url=user.avatar or "",
            birthday="",
            sex="",
        )

    def bind_equipment(self, account: str, equipment_no: str) -> bool:
        """Bind a device to the user account using StateService."""
        if not self.check_user_exists(account):
            return False
        self._state_service.add_device(account, equipment_no)
        return True

    def unlink_equipment(self, equipment_no: str) -> bool:
        """Unlink a device from all users using StateService."""
        self._state_service.remove_device(equipment_no)
        return True
